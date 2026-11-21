"""Fast, non-blocking submission for the per-user Passenger application."""
import os
from pathlib import Path
import subprocess
import sys

from .config import REPO, Request, resolve
from .service import allocate
from .storage import Status, now, write_json

_children = []


def reap():
    _children[:] = [child for child in _children if child.poll() is None]


def submit(config, output_root=None) -> Path:
    if os.environ.get('PYBATGYM_EXECUTION_MODE') == 'slurm':
        from .slurm import submit as submit_slurm
        return submit_slurm(config, output_root)
    request = Request.model_validate(config)
    resolve(request)  # Invalid forms do not spawn processes or create a run.
    directory = allocate(output_root)
    write_json(directory / 'submission.json', request.model_dump(mode='json'))
    status = Status(directory, resume=True)
    status.set('QUEUED', submitted_at=now())
    command = [sys.executable, '-u', '-m', 'pybatgym.runner.launch', str(directory)]
    env = os.environ.copy()
    env.update(PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1')
    env['PYTHONPATH'] = str(REPO) + os.pathsep + env.get('PYTHONPATH', '')
    reap()
    try:
        with (directory / 'launcher.log').open('w', encoding='utf-8') as log:
            child = subprocess.Popen(command, cwd=REPO, env=env, stdin=subprocess.DEVNULL,
                                     stdout=log, stderr=subprocess.STDOUT,
                                     start_new_session=(os.name == 'posix'), close_fds=True)
        _children.append(child)
        # Separate metadata: do not overwrite a status already updated by child.
        write_json(directory / 'submission.meta.json', {'pid': child.pid, 'submitted_at': now()})
    except Exception as exc:
        status.set('FAILED', finished_at=now(), error_code='LAUNCH_ERROR', error=str(exc))
        raise
    return directory
