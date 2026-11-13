"""python -m pybatgym.runner --config configs/playground/mock.json"""
import argparse
import json
from pathlib import Path

from .service import run


def main():
    parser = argparse.ArgumentParser(description='Run and verify one PyBatGym benchmark request')
    parser.add_argument('--config', required=True, help='JSON request file')
    parser.add_argument('--output-root', help='Output root; default runs/playground in repository')
    args = parser.parse_args()
    directory = run(Path(args.config), args.output_root)
    status = json.loads((directory / 'status.json').read_text(encoding='utf-8'))
    print(json.dumps({'run_id': directory.name, 'state': status['state'], 'directory': str(directory),
                      'error': status.get('error')}, ensure_ascii=False))
    return {'SUCCEEDED': 0, 'TIMED_OUT': 124, 'CANCELLED': 130}.get(status['state'], 1)


if __name__ == '__main__':
    raise SystemExit(main())
