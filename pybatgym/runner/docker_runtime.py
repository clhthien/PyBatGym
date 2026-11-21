"""Docker Unix API restricted to this runner's labelled episode containers.

No global prune/restart, image build, container removal, or Docker Desktop control.
"""
import http.client
import json
import os
import socket
import struct
import time
from pathlib import Path, PureWindowsPath, PurePosixPath
from urllib.parse import quote, urlencode

from .storage import write_json

OWNER = 'org.pybatgym.runner'
IMAGE = 'oarteam/batsim:3.1.0'


class UnixConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect('/var/run/docker.sock')


def api(method, path, body=None, raw=False):
    connection = UnixConnection('localhost', timeout=10)
    try:
        data = json.dumps(body).encode() if body is not None else None
        connection.request(method, '/v1.41' + path, body=data, headers={'Content-Type': 'application/json'})
        response = connection.getresponse()
        payload = response.read()
        if response.status >= 300:
            raise RuntimeError(f'Docker {method} {path}: {response.status}: {payload.decode(errors="replace")[:400]}')
        return payload if raw else (json.loads(payload) if payload else None)
    finally:
        connection.close()


def host_path(source, relative):
    cls = PureWindowsPath if PureWindowsPath(source).drive else PurePosixPath
    return str(cls(source).joinpath(*relative.parts))


def prepare(repo: Path, run_dir: Path):
    if not Path('/var/run/docker.sock').exists():
        raise RuntimeError('Real requires /var/run/docker.sock in the existing PyBatGym shell')
    shell = api('GET', '/containers/' + quote(os.environ.get('HOSTNAME', ''), safe='') + '/json')
    if shell['Config'].get('Labels', {}).get('com.docker.compose.project') != 'pybatgym':
        raise RuntimeError('Real must run inside the verified pybatgym Compose project')
    mount = next((m for m in shell['Mounts'] if m['Destination'] == str(repo) and m['Type'] == 'bind'), None)
    if not mount or not run_dir.is_relative_to(repo):
        raise RuntimeError('Real output must be inside the repository bind mount (use runs/playground)')
    networks = shell['NetworkSettings']['Networks']
    if 'pybatgym_default' not in networks:
        raise RuntimeError('Expected pybatgym_default network is unavailable')
    image = api('GET', '/images/' + quote(IMAGE, safe='') + '/json')
    return {'repo_source': mount['Source'], 'run_source': host_path(mount['Source'], run_dir.relative_to(repo)),
            'shell_name': shell['Name'].lstrip('/'), 'network': 'pybatgym_default',
            'image_id': image['Id'], 'image_digests': image.get('RepoDigests', []), 'run_id': run_dir.name}


def owned(container, run_id):
    labels = container['Config'].get('Labels', {})
    if labels.get(OWNER) != 'true' or labels.get(OWNER + '.run_id') != run_id:
        raise RuntimeError('Refusing to control a container not owned by this run')


def log_text(payload):
    chunks = []
    offset = 0
    # Walk Docker frames without copying the entire remaining log each time.
    # Large experiments have many small frames, making repeated slicing O(n²).
    while len(payload) - offset >= 8 and payload[offset] in (0, 1, 2) and payload[offset + 1:offset + 4] == b'\x00\x00\x00':
        length = struct.unpack_from('>I', payload, offset + 4)[0]
        chunks.append(payload[offset + 8:offset + 8 + length])
        offset += 8 + length
    chunks.append(payload[offset:])
    return b''.join(chunks).decode('utf-8', errors='replace')


def collect(container_id, run_id, directory: Path, *, stop=False):
    data = api('GET', '/containers/' + container_id + '/json')
    owned(data, run_id)
    if stop and data['State']['Running']:
        api('POST', '/containers/' + container_id + '/stop?t=2')
        data = api('GET', '/containers/' + container_id + '/json')
    directory.mkdir(parents=True, exist_ok=True)
    payload = api('GET', '/containers/' + container_id + '/logs?stdout=1&stderr=1', raw=True)
    (directory / 'batsim.log').write_text(log_text(payload), encoding='utf-8')
    write_json(directory / 'container.json', {'id': container_id, 'name': data['Name'],
               'image': data['Image'], 'state': data['State']})
    return data['State']


def cleanup(runtime, run_dir):
    filters = json.dumps({'label': [OWNER + '=true', OWNER + '.run_id=' + runtime['run_id']]})
    containers = api('GET', '/containers/json?' + urlencode({'all': 'true', 'filters': filters}))
    for item in containers:
        data = api('GET', '/containers/' + item['Id'] + '/json')
        owned(data, runtime['run_id'])
        episode = data['Config']['Labels'][OWNER + '.episode']
        if not episode.isdigit():
            raise RuntimeError('Invalid owned episode label')
        collect(item['Id'], runtime['run_id'], run_dir / 'simulator' / episode, stop=True)


class EpisodeContainer:
    def __init__(self, runtime, run_dir, episode, config, port):
        self.runtime = runtime
        self.run_dir = run_dir
        self.directory = run_dir / 'simulator' / str(episode)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.id = None
        self.finished = False
        source = host_path(runtime['run_source'], Path('simulator') / str(episode))
        command = ('for f in /nix/store/*-batsim-*/bin/batsim; do '
                   'if [ -x "$f" ]; then exec "$f" -p "$1" -w "$2" '
                   '-e /simulator/batsim -s "$3"; fi; done; exit 127')
        payload = {
            'Image': runtime['image_id'], 'Entrypoint': ['/bin/sh'],
            'Cmd': ['-c', command, 'stage2', config.platform.platform_path, config.workload.trace_path,
                    f'tcp://{runtime["shell_name"]}:{port}'],
            'Labels': {OWNER: 'true', OWNER + '.run_id': runtime['run_id'], OWNER + '.episode': str(episode),
                       'com.docker.compose.project': 'pybatgym'},
            'HostConfig': {'NetworkMode': runtime['network'],
                'Mounts': [{'Type': 'bind', 'Source': runtime['repo_source'], 'Target': '/workspace', 'ReadOnly': True},
                           {'Type': 'bind', 'Source': source, 'Target': '/simulator'}],
                'Tmpfs': {'/tmp': 'rw,size=16m', '/data': 'rw,size=1m'}, 'Memory': 512 * 1024 * 1024,
                'NanoCpus': 1000000000, 'PidsLimit': 128},
        }
        name = f'pybatgym-runner-{runtime["run_id"]}-{episode}'
        self.id = api('POST', '/containers/create?' + urlencode({'name': name}), payload)['Id']
        write_json(self.directory / 'resource.json', {'container_id': self.id, 'episode': episode})

    def start(self):
        data = api('GET', '/containers/' + self.id + '/json')
        owned(data, self.runtime['run_id'])
        api('POST', '/containers/' + self.id + '/start')

    def finish(self):
        if self.finished:
            return
        self.finished = True
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            data = api('GET', '/containers/' + self.id + '/json')
            owned(data, self.runtime['run_id'])
            if not data['State']['Running']:
                break
            time.sleep(0.1)
        state = collect(self.id, self.runtime['run_id'], self.directory, stop=True)
        if state['ExitCode'] != 0:
            raise RuntimeError(f'BatSim did not exit cleanly: {state["ExitCode"]}; see simulator log')
