"""Rootless Podman on allocated compute nodes; all storage/containers run-owned."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from .storage import write_json

IMAGE = 'docker.io/oarteam/batsim:3.1.0'
OWNER = 'org.pybatgym.runner'


def command(runtime, *args, timeout=30):
    operation = args[0] if args else 'operation'
    scratch = Path(runtime['scratch'])
    if not scratch.is_dir() or scratch.is_symlink():
        raise RuntimeError('Owned Podman scratch is unavailable on this node')
    marker = json.loads((scratch / 'owner.json').read_text())
    if marker != {'run_id': runtime['run_id'], 'uid': os.getuid()}:
        raise RuntimeError('Refusing Podman command for unowned scratch')
    env = os.environ.copy()
    env.pop('DBUS_SESSION_BUS_ADDRESS', None)
    env.update(CONTAINERS_CONF=str(scratch / 'containers.conf'), XDG_RUNTIME_DIR=str(scratch / 'runtime'))
    args = ['podman', '--cgroup-manager=cgroupfs', '--events-backend=file',
            '--root', str(scratch / 'storage'), '--runroot', str(scratch / 'run'),
            '--storage-opt', 'overlay.ignore_chown_errors=true', *args]
    try:
        result = subprocess.run(args, env=env, text=True, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('Podman operation timed out') from exc
    if result.returncode:
        raise RuntimeError(f'Podman {operation}: {result.stderr[-3000:]}')
    # Podman forwards the container's stderr separately; retain it in logs.
    return result.stdout + result.stderr if operation in ('logs', 'pull') else result.stdout


def prepare(repo, run_dir):
    if not os.environ.get('SLURM_JOB_ID'):
        raise RuntimeError('Podman benchmark must execute inside a Slurm allocation')
    if not shutil.which('podman'):
        raise RuntimeError('Podman is unavailable on the compute node')
    scratch = Path(tempfile.mkdtemp(prefix=f'pbg-{run_dir.name}-', dir='/tmp'))
    (scratch / 'runtime').mkdir(mode=0o700)
    write_json(scratch / 'owner.json', {'run_id': run_dir.name, 'uid': os.getuid()})
    (scratch / 'containers.conf').write_text('[engine]\ncgroup_manager="cgroupfs"\nevents_logger="file"\n')
    runtime = dict(kind='podman', run_id=run_dir.name, scratch=str(scratch), repo=str(repo.resolve()),
                   slurm_job_id=os.environ['SLURM_JOB_ID'])
    # Persist even if pull fails so storage usage and diagnostics are traceable.
    write_json(run_dir / 'runtime.json', runtime)
    output = command(runtime, 'pull', IMAGE, timeout=300)
    (run_dir / 'podman-pull.log').write_text(output)
    image = json.loads(command(runtime, 'image', 'inspect', IMAGE))[0]
    runtime.update(image_id=image['Id'], image_digests=image.get('RepoDigests', []))
    return runtime


def inspect(runtime, identifier):
    value = json.loads(command(runtime, 'inspect', identifier))[0]
    labels = value.get('Config', {}).get('Labels') or {}
    if labels.get(OWNER) != 'true' or labels.get(OWNER + '.run_id') != runtime['run_id']:
        raise RuntimeError('Refusing to control an unowned Podman container')
    return value


def collect(runtime, run_dir, identifier, episode, *, stop=False):
    value = inspect(runtime, identifier)
    if stop and value['State']['Running']:
        command(runtime, 'stop', '-t', '2', identifier)
        value = inspect(runtime, identifier)
    directory = run_dir / 'simulator' / str(episode)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'batsim.log').write_text(command(runtime, 'logs', identifier), encoding='utf-8')
    write_json(directory / 'container.json', {'id': value['Id'], 'state': value['State'], 'image': value.get('Image')})
    source = Path(runtime['scratch']) / 'episodes' / str(episode)
    if source.is_dir() and not source.is_symlink():
        for path in source.iterdir():
            if path.is_file() and not path.is_symlink() and path.name.startswith('batsim'):
                shutil.copyfile(path, directory / path.name)
    return value['State']


def cleanup(runtime, run_dir):
    manifest_path = run_dir / 'simulator/manifest.json'
    if not manifest_path.exists():
        return
    for entry in json.loads(manifest_path.read_text()):
        episode = entry['episode']
        if type(episode) is not int or episode < 0:
            raise RuntimeError('Invalid episode manifest')
        collect(runtime, run_dir, entry['container_id'], episode, stop=True)


class EpisodeContainer:
    def __init__(self, runtime, run_dir, episode, config, port):
        self.runtime, self.run_dir, self.episode = runtime, run_dir, episode
        self.finished = False
        self.directory = run_dir / 'simulator' / str(episode)
        self.directory.mkdir(parents=True, exist_ok=False)
        scratch_output = Path(runtime['scratch']) / 'episodes' / str(episode)
        scratch_output.mkdir(parents=True, exist_ok=False)
        repo = Path(runtime['repo'])
        platform = Path(config.platform.platform_path).resolve().relative_to(repo)
        workload = Path(config.workload.trace_path).resolve().relative_to(repo)
        # A private /tmp output with a read-only source bind was verified on HPCC.
        self.id = command(runtime, 'create', '--name', f'pbg-{runtime["run_id"]}-{episode}',
                          '--label', OWNER + '=true', '--label', OWNER + '.run_id=' + runtime['run_id'],
                          '--network', 'host', '--mount', f'type=bind,src={repo},dst=/workspace,ro',
                          '--mount', f'type=bind,src={scratch_output},dst=/simulator',
                          '--tmpfs', '/tmp:rw,mode=1777', '--entrypoint', '/bin/batsim', runtime['image_id'],
                          '-p', '/workspace/' + platform.as_posix(), '-w', '/workspace/' + workload.as_posix(),
                          '-e', '/simulator/batsim', '-s', f'tcp://127.0.0.1:{port}').strip()
        write_json(self.directory / 'resource.json', {'container_id': self.id, 'episode': episode})

    def start(self):
        inspect(self.runtime, self.id)
        command(self.runtime, 'start', self.id)

    def finish(self):
        if self.finished:
            return
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if not inspect(self.runtime, self.id)['State']['Running']:
                break
            time.sleep(.1)
        state = collect(self.runtime, self.run_dir, self.id, self.episode, stop=True)
        self.finished = True
        if state['ExitCode'] != 0:
            raise RuntimeError(f'BatSim exited {state["ExitCode"]}; see native log')
