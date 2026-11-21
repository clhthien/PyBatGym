"""Submit a validated playground request without running work on the login node."""
import argparse
import json
from pathlib import Path

from .slurm import submit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--output-root', type=Path)
    args = parser.parse_args()
    directory = submit(json.loads(args.config.read_text(encoding='utf-8-sig')), args.output_root)
    print(json.dumps({'run_id': directory.name, 'directory': str(directory),
                      'slurm': json.loads((directory / 'slurm.json').read_text())}))


if __name__ == '__main__':
    main()
