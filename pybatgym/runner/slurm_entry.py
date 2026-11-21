"""Compute-node entrypoint; propagate runner result to the Slurm exit code."""
import json
import os
from pathlib import Path
import sys

from .service import run


def main():
    if not os.environ.get('SLURM_JOB_ID'):
        raise RuntimeError('This entrypoint requires a Slurm allocation')
    directory = Path(sys.argv[1]).resolve(strict=True)
    request = json.loads((directory / 'submission.json').read_text())
    run(request, directory.parent, _prepared=directory)
    state = json.loads((directory / 'status.json').read_text())['state']
    return {'SUCCEEDED': 0, 'TIMED_OUT':124, 'CANCELLED':130}.get(state,1)


if __name__ == '__main__':
    sys.exit(main())
