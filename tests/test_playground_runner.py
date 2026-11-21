"""Acceptance tests for orchestration, not just benchmark calculations."""
import json
import os
from pathlib import Path

import pytest


@pytest.mark.parametrize('count', [1000, 10000])
@pytest.mark.parametrize('backend', ['mock', 'real'])
def test_large_demo_configuration_resolves(count, backend):
    from pybatgym.runner.config import REPO, Request, resolve
    request = Request.model_validate_json(
        (REPO / f'configs/playground/{backend}_{count}.json').read_text()
    )
    cfg, hashes = resolve(request)
    workload = json.loads((REPO / f'data/workloads/{request.workload}.json').read_text())
    serial_bound = max(j['subtime'] for j in workload['jobs']) + sum(
        workload['profiles'][j['profile']]['delay'] for j in workload['jobs']
    )
    assert cfg['workload']['num_jobs'] == count
    assert cfg['episode']['max_simulation_time'] > serial_bound
    assert cfg['episode']['max_steps'] == count * 20
    if backend == 'real':
        assert cfg['platform']['platform_path'].endswith('medium_platform.xml')
        assert 'data/platforms/medium_platform.xml' in hashes
from pydantic import ValidationError

from pybatgym.runner import run
from pybatgym.runner.config import Request, resolve
from pybatgym.runner.storage import RealLock
from pybatgym.runner.docker_runtime import owned, host_path
from pybatgym.runner.verify import verify


def read(path, name='status.json'):
    return json.loads((path / name).read_text(encoding='utf-8'))


@pytest.mark.parametrize('change', [
    {'backend': 'unknown'}, {'workload': '../gen_c32_s0'}, {'preset': '../../default'},
    {'policies': ['fcfs', 'fcfs']}, {'policies': ['ppo_maskable']}, {'seed': True},
    {'timeout_seconds': 0.0}, {'random_seeds': 0}, {'container': 'unrelated'},
])
def test_request_rejects_unsafe_or_unimplemented_options(change):
    with pytest.raises(ValidationError):
        Request.model_validate(change)


def test_missing_workload_fails_before_any_worker(tmp_path):
    directory = run({'workload': 'not_an_existing_workload'}, tmp_path)
    status = read(directory)
    assert status['state'] == 'FAILED' and status['error_code'] == 'VALIDATION_ERROR'
    assert 'worker_pid' not in status
    assert (directory / 'stderr.log').stat().st_size > 0


def test_two_runs_are_independent_and_seed_is_applied(tmp_path):
    request = {'policies': ['random'], 'seed': 11, 'random_seeds': 2}
    a, b = run(request, tmp_path), run(request, tmp_path)
    assert a != b
    for directory in (a, b):
        status = read(directory)
        assert status['state'] == 'SUCCEEDED', status
        assert [s['state'] for s in status['history']] == ['CREATED', 'VALIDATING', 'RUNNING', 'VERIFYING', 'SUCCEEDED']
        check = read(directory, 'verification.json')
        assert {e['seed'] for e in check['episodes']} == {11, 12}
        assert check['job_rows'] == 200
        assert read(directory, 'config_resolved.json')['workload']['seed'] == 11
    # Exclude timestamps/run IDs: scheduling decisions must reproduce.
    import csv
    def decisions(directory):
        with (directory / 'results/steps.csv').open() as f:
            return [(r['seed'], r['action'], r['reward']) for r in csv.DictReader(f)]
    assert decisions(a) == decisions(b)


def test_incomplete_episode_is_failed_even_when_worker_exits_zero(tmp_path):
    directory = run({'policies': ['fcfs'], 'max_steps': 1}, tmp_path)
    status = read(directory)
    assert status['state'] == 'FAILED' and status['error_code'] == 'RESULT_INVALID'
    assert status['worker_exit_code'] == 0
    assert 'INCOMPLETE_EPISODE' in status['error']


def test_timeout_stops_child_and_records_failure(tmp_path):
    directory = run({'policies': ['fcfs'], 'timeout_seconds': 0.1}, tmp_path)
    status = read(directory)
    assert status['state'] == 'TIMED_OUT' and status['error_code'] == 'TIMEOUT'
    assert read(directory, 'metadata.json')['worker_exit_code'] != 0
    if os.name == 'posix':
        with pytest.raises(ProcessLookupError):
            os.kill(status['worker_pid'], 0)


def test_worker_failure_records_exit_code_and_stderr(tmp_path, monkeypatch):
    from pybatgym.runner import service
    import sys
    original = service.subprocess.Popen
    def failing_worker(command, **kwargs):
        return original([sys.executable, '-c', 'import sys; print("dependency unavailable", file=sys.stderr); sys.exit(7)'], **kwargs)
    monkeypatch.setattr(service.subprocess, 'Popen', failing_worker)
    directory = run({'policies': ['fcfs']}, tmp_path)
    status = read(directory)
    assert status['state'] == 'FAILED' and status['error_code'] == 'RUNTIME_ERROR'
    assert read(directory, 'metadata.json')['worker_exit_code'] == 7
    assert 'dependency unavailable' in (directory / 'stderr.log').read_text()


@pytest.mark.skipif(os.name != 'posix', reason='Real Docker execution is Linux-only')
def test_real_lock_refuses_second_run_without_docker_changes(tmp_path):
    with RealLock():
        directory = run({'backend': 'real'}, tmp_path)
    status = read(directory)
    assert status['state'] == 'FAILED' and status['error_code'] == 'REAL_BUSY'
    assert 'worker_pid' not in status
    # OS lock is reusable after release, without deleting lock files.
    with RealLock():
        pass


def test_docker_ownership_guard_refuses_unrelated_resources():
    with pytest.raises(RuntimeError, match='not owned'):
        owned({'Config': {'Labels': {'com.docker.compose.project': 'other'}}}, 'test-run')
    assert host_path('F:\\DACN\\PyBatGym', Path('runs') / 'one') == 'F:\\DACN\\PyBatGym\\runs\\one'


def test_missing_artifact_cannot_be_success(tmp_path):
    directory = run({'policies': ['fcfs']}, tmp_path)
    assert read(directory)['state'] == 'SUCCEEDED'
    (directory / 'results/jobs.csv').unlink()  # disposable pytest fixture only
    req = Request(policies=['fcfs'])
    cfg, _ = resolve(req)
    with pytest.raises(ValueError, match='Missing or empty artifact'):
        verify(directory, req, cfg)


def test_malformed_json_is_a_durable_validation_failure(tmp_path):
    config = tmp_path / 'broken.json'
    config.write_text('{not-json', encoding='utf-8')
    directory = run(config, tmp_path / 'runs')
    status = read(directory)
    assert status['state'] == 'FAILED' and status['error_code'] == 'VALIDATION_ERROR'
    assert (directory / 'request.original.json').read_text() == '{not-json'


@pytest.mark.skipif(os.name != 'posix', reason='POSIX signal supervision')
def test_sigterm_records_cancelled_and_stops_worker(tmp_path):
    import signal
    import subprocess
    import sys
    import time
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'policies': ['fcfs']}))
    output = tmp_path / 'runs'
    parent = subprocess.Popen([sys.executable, '-m', 'pybatgym.runner', '--config', str(config),
                               '--output-root', str(output)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            files = list(output.glob('*/status.json')) if output.exists() else []
            if files:
                status = json.loads(files[0].read_text())
                if status['state'] == 'RUNNING':
                    break
            time.sleep(0.01)
        else:
            pytest.fail('Parent did not reach RUNNING')
        parent.send_signal(signal.SIGTERM)
        parent.communicate(timeout=15)
        assert parent.returncode == 130
        status = json.loads(files[0].read_text())
        assert status['state'] == 'CANCELLED'
        with pytest.raises(ProcessLookupError):
            os.kill(status['worker_pid'], 0)
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.communicate()
