"""Child process: benchmark with an injected, run-owned Docker adapter."""
import json
import os
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from pybatgym.experiments import run_benchmark as benchmark
from .storage import write_json


def main():
    run_dir = Path(sys.argv[1]).resolve()
    request = json.loads((run_dir / 'request.json').read_text())
    runtime = json.loads((run_dir / 'runtime.json').read_text()) if request['backend'] == 'real' else None
    manifest = []
    factory = None
    last_sample = 0.0
    last_cpu = 0.0

    def progress(env, policy, seed, done):
        nonlocal last_sample, last_cpu
        now = time.monotonic()
        if not done and now - last_sample < 1.0:
            return
        cpu = sum(os.times()[:2])
        cpu_percent = (cpu-last_cpu)/(now-last_sample)*100 if last_sample else None
        last_sample, last_cpu = now, cpu
        try:
            resource = env._state['resource']
            sample = dict(policy=policy, seed=seed, sim_time=env._adapter.get_current_time(),
                          at=datetime.now(timezone.utc).isoformat(),
                          total=env._config.workload.num_jobs,
                          completed=len(env._adapter.get_completed_jobs()),
                          queued=len(env._state.get('pending_jobs', [])),
                          running=len(getattr(env._adapter, '_running_jobs', [])),
                          busy=resource.used_cores, cores=resource.total_cores, done=bool(done))
            sample['worker_cpu_percent'] = cpu_percent
            running = getattr(env._adapter, '_running_jobs', [])
            sample['core_map'] = [dict(id=str(job.job_id), cores=sorted(job.allocated_core_set), start=job.start_time)
                                  for job in (running if isinstance(running, list) else [])
                                  if getattr(job, 'allocated_core_set', None)]
            try:
                rss_line = next(line for line in Path('/proc/self/status').read_text().splitlines() if line.startswith('VmRSS:'))
                sample['worker_rss_mib'] = int(rss_line.split()[1])/1024
            except (OSError, StopIteration, ValueError):
                sample['worker_rss_mib'] = None
            with (run_dir / 'progress.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(sample, allow_nan=False) + '\n')
            write_json(run_dir / 'progress.json', sample)
        except (OSError, ValueError, TypeError):
            # Observability must not change scheduling or experiment success.
            pass
    if runtime:
        from .runtime import backend
        EpisodeContainer = backend(runtime.get('kind', 'docker')).EpisodeContainer
        from pybatgym.adapters.batsim_adapter import RealBatsimAdapter

        class ManagedAdapter(RealBatsimAdapter):
            def __init__(self, cfg):
                # Select the endpoint BEFORE the pybatsim thread binds it.
                with socket.socket() as sock:
                    sock.bind(('', 0))
                    port = sock.getsockname()[1]
                os.environ['BATSIM_SOCKET'] = f'tcp://*:{port}'
                super().__init__(cfg)
                self.episode_container = EpisodeContainer(runtime, run_dir, len(manifest), cfg, port)
                manifest.append({'episode': len(manifest), 'container_id': self.episode_container.id})
                write_json(run_dir / 'simulator' / 'manifest.json', manifest)

            def _start_batsim_subprocess(self):
                self.episode_container.start()

            def close(self):
                try:
                    super().close()
                finally:
                    self.episode_container.finish()

        factory = ManagedAdapter
    benchmark.main([
        '--config', str(run_dir / 'config_resolved.json'),
        '--workloads', json.loads((run_dir / 'config_resolved.json').read_text())['workload']['trace_path'],
        '--policies', *request['policies'], '--backend', request['backend'],
        '--seed', str(request['seed']), '--random-seeds', str(request['random_seeds']),
        '--out', str(run_dir / 'results'),
    ], adapter_factory=factory, progress=progress)


if __name__ == '__main__':
    main()
