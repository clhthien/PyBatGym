"""Acceptance checks: exit code alone is not a successful experiment."""
import csv
import json
import math
from pathlib import Path
from statistics import fmean

from .storage import write_json


def table(path):
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f'Missing or empty artifact: {path.name}')
    with path.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(run_dir: Path, request, cfg):
    results = run_dir / 'results'
    for name in ('config_resolved.json', 'env_info.json'):
        json.loads((results / name).read_text())
    eps = table(results / 'per_episode_metrics.csv')
    jobs = table(results / 'jobs.csv')
    steps = table(results / 'steps.csv')
    table(results / 'comparison_table.csv')
    table(results / 'benchmark_summary.csv')
    labels = {'fcfs': 'FCFS', 'sjf': 'SJF', 'easy': 'EASY', 'random': 'Random'}
    expected_keys = {(labels[p], str(seed)) for p in request.policies
                     for seed in (range(request.seed, request.seed + request.random_seeds) if p == 'random' else [request.seed])}
    require(len(eps) == len(expected_keys), 'Missing or duplicate episode records')
    require({(e['policy'], e['seed']) for e in eps} == expected_keys, 'Policy/seed mapping differs from request')
    workload = json.loads(Path(cfg['workload']['trace_path']).read_text())
    specs = {str(j['id']): j for j in workload['jobs']}
    n = len(specs)
    for ep in eps:
        require(int(ep['completed_jobs']) == n and ep['terminated'] == '1' and ep['truncated'] == '0',
                f'INCOMPLETE_EPISODE: {ep["policy"]} completed {ep["completed_jobs"]}/{n}')
    require(len(jobs) == n * len(eps), 'Unexpected total completed job records')
    native_manifest = json.loads((run_dir / 'simulator/manifest.json').read_text()) if request.backend == 'real' else []
    if request.backend == 'real':
        require(len(native_manifest) == len(eps), 'Missing native episode exports')
    checks = []
    for i, ep in enumerate(eps):
        require(int(ep['completed_jobs']) == n and ep['terminated'] == '1' and ep['truncated'] == '0',
                f'INCOMPLETE_EPISODE: {ep["policy"]} completed {ep["completed_jobs"]}/{n}')
        require(int(ep['invalid_actions']) == 0, 'Invalid scheduling actions occurred')
        for metric in ('avg_waiting_time', 'avg_bounded_slowdown', 'utilization', 'makespan', 'throughput', 'total_reward'):
            require(math.isfinite(float(ep[metric])), f'Non-finite metric: {metric}')
        require(float(ep['makespan']) > 0 and 0 <= float(ep['utilization']) <= 1, 'Invalid makespan/utilization')
        subset = [j for j in jobs if j['policy'] == ep['policy'] and j['seed'] == ep['seed']]
        require(len(subset) == n and {j['job_id'] for j in subset} == set(specs), 'Missing/duplicate job IDs')
        for j in subset:
            submit, start, finish, actual, wait = (float(j[k]) for k in ('submit_time', 'start_time', 'finish_time', 'actual_runtime', 'waiting_time'))
            require(all(math.isfinite(x) for x in (submit, start, finish, actual, wait)), 'Non-finite timestamp')
            require(submit <= start <= finish and actual >= 0, 'Invalid job timestamps')
            require(abs(finish - start - actual) < 1e-4 and abs(start - submit - wait) < 1e-4, 'Inconsistent runtime/waiting time')
            spec = specs[j['job_id']]
            require(abs(submit - float(spec['subtime'])) < 1e-4 and int(j['requested_resources']) == int(spec['res']), 'Job differs from workload')
            profile = workload['profiles'][spec['profile']]
            if profile['type'] == 'delay':
                # Mock currently executes the full profile; Real obeys walltime.
                target = float(profile['delay'])
                if request.backend == 'real':
                    target = min(target, float(spec['walltime']))
                require(abs(actual - target) < 0.01, f'Runtime differs from profile: job {j["job_id"]}')
        require(abs(fmean(float(j['waiting_time']) for j in subset) - float(ep['avg_waiting_time'])) < 1e-4, 'Incorrect average waiting time')
        require(abs(fmean(float(j['bounded_slowdown']) for j in subset) - float(ep['avg_bounded_slowdown'])) < 1e-4, 'Incorrect average slowdown')
        total_cores = cfg['platform']['total_nodes'] * cfg['platform']['cores_per_node']
        util = sum(float(j['actual_runtime']) * int(j['requested_resources']) for j in subset) / (float(ep['makespan']) * total_cores)
        require(abs(min(1., util) - float(ep['utilization'])) < 1e-4, 'Incorrect utilization')
        require(abs(n / float(ep['makespan']) - float(ep['throughput'])) < 1e-5, 'Incorrect throughput')
        episode_steps = [s for s in steps if s['policy'] == ep['policy'] and s['seed'] == ep['seed']]
        require(len(episode_steps) == int(ep['num_steps']), 'Missing decision steps')
        native_error = None
        if request.backend == 'real':
            native_dir = run_dir / 'simulator' / str(i)
            state = json.loads((native_dir / 'container.json').read_text())['state']
            require(not state['Running'] and state['ExitCode'] == 0, 'BatSim did not exit normally')
            native = table(native_dir / 'batsim_jobs.csv')
            require(len(native) == n and {j['job_id'] for j in native} == set(specs), 'Incomplete native BatSim job export')
            indexed = {j['job_id']: j for j in native}
            native_error = 0.
            for j in subset:
                reference = indexed[j['job_id']]
                require(reference['success'] == '1', 'BatSim reports an unsuccessful job')
                for key, native_key in [('start_time', 'starting_time'), ('finish_time', 'finish_time'),
                                         ('actual_runtime', 'execution_time'), ('waiting_time', 'waiting_time')]:
                    error = abs(float(j[key]) - float(reference[native_key]))
                    native_error = max(native_error, error)
                    require(error < 0.001, f'Native timestamp mismatch: {key}')
            table(native_dir / 'batsim_schedule.csv')
        checks.append({'policy': ep['policy'], 'seed': int(ep['seed']), 'completed_jobs': n,
                       'native_max_error_seconds': native_error})
    log = (run_dir / 'stdout.log').read_text(encoding='utf-8')
    require('[BatSim thread] Exception' not in log, 'BatSim thread reported an exception')
    if request.backend == 'real':
        require(log.count('Simulation ENDS') == len(eps), 'Missing clean simulation end events')
    result = {'status': 'PASS', 'episodes': checks, 'job_rows': len(jobs), 'backend': request.backend}
    write_json(run_dir / 'verification.json', result)
    return result
