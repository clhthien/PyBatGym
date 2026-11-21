"""Fingerprint the release source; fail when a mounted checkout differs."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path('/workspace')
MANIFEST = Path('/opt/pybatgym-release/source.json')


def hashes():
    result = {}
    for folder in ('pybatgym', 'pybatgym_viz', 'configs', 'data/platforms', 'data/workloads'):
        for path in sorted((ROOT / folder).rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                result[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


if __name__ == '__main__':
    if sys.argv[1:] == ['write']:
        MANIFEST.write_text(json.dumps(hashes(), indent=2))
    else:
        if hashes() != json.loads(MANIFEST.read_text()):
            raise SystemExit('Release source mismatch: use the exported release workspace, not the development checkout.')
        print('Release source verified')
