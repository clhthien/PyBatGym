"""Child process: benchmark with an injected, run-owned Docker adapter."""
import json
import os
import socket
import sys
from pathlib import Path

from pybatgym.experiments import run_benchmark as benchmark
from .docker_runtime import EpisodeContainer
from .storage import write_json


def main():
    run_dir = Path(sys.argv[1]).resolve()
    request = json.loads((run_dir / 'request.json').read_text())
    runtime = json.loads((run_dir / 'runtime.json').read_text()) if request['backend'] == 'real' else None
    manifest = []
    factory = None
    if runtime:
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
    ], adapter_factory=factory)


if __name__ == '__main__':
    main()
