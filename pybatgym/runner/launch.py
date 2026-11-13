"""Detached entrypoint. Only a queued run created by submit() can execute."""
import json
from pathlib import Path
import sys

from .service import run
from .storage import Status, now


def main():
    directory = Path(sys.argv[1]).resolve(strict=True)
    try:
        request = json.loads((directory / 'submission.json').read_text(encoding='utf-8'))
        run(request, directory.parent, _prepared=directory)
    except Exception as exc:
        status = Status(directory, resume=True)
        if status.value['state'] in ('CREATED', 'QUEUED', 'VALIDATING', 'RUNNING', 'VERIFYING'):
            status.set('FAILED', finished_at=now(), error_code='LAUNCH_ERROR', error=str(exc))
        raise


if __name__ == '__main__':
    main()
