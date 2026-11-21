"""Submit the same durable runner to Slurm; settings belong to the deployer."""
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

from .config import REPO, Request, resolve
from .service import allocate
from .storage import Status, now, write_json

_last_checked = {}
TERMINAL = {'SUCCEEDED', 'FAILED', 'TIMED_OUT', 'CANCELLED'}


def submit(config, output_root=None):
    request = Request.model_validate(config)
    resolve(request)
    python = Path(os.environ.get('PYBATGYM_PYTHON', sys.executable))
    if not python.is_absolute() or not python.is_file():
        raise ValueError('PYBATGYM_PYTHON must be an absolute shared interpreter path')
    settings = {key: os.environ.get('PYBATGYM_SLURM_' + key.upper(), default) for key, default in
                [('account','general'), ('partition','compute'), ('qos','normal'), ('memory','4G'), ('time','00:15:00')]}
    if any(not re.fullmatch(r'[A-Za-z0-9_:.+-]+', value) for value in settings.values()):
        raise ValueError('Invalid deployment Slurm setting')
    node = os.environ.get('PYBATGYM_SLURM_NODE')
    if node and not re.fullmatch(r'[A-Za-z0-9_.-]+', node):
        raise ValueError('Invalid deployment node')
    directory = allocate(output_root)
    write_json(directory / 'submission.json', request.model_dump(mode='json'))
    status = Status(directory, resume=True)
    status.set('QUEUED', submitted_at=now())
    script = '#!/bin/bash\nset -euo pipefail\n'
    script += 'export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=1\n'
    script += 'export PYTHONPATH=' + shlex.quote(str(REPO)) + '\n'
    script += 'export PYBATGYM_RUNTIME=podman\n'
    script += 'cd ' + shlex.quote(str(REPO)) + '\n'
    script += 'exec ' + shlex.join([str(python), '-u', '-m', 'pybatgym.runner.slurm_entry', str(directory)]) + '\n'
    script_path = directory / 'job.sbatch'
    script_path.write_text(script)
    command = ['sbatch', '--parsable', '--job-name=pbg-' + directory.name[-12:], '--nodes=1', '--ntasks=1',
               '--cpus-per-task=1', '--account=' + settings['account'], '--partition=' + settings['partition'],
               '--qos=' + settings['qos'], '--mem=' + settings['memory'], '--time=' + settings['time'],
               '--output=' + str(directory / 'slurm_%j.out'), '--error=' + str(directory / 'slurm_%j.err')]
    if node:
        command.append('--nodelist=' + node)
    command.append(str(script_path))
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=30)
        (directory / 'sbatch.log').write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError('Slurm refused submission: ' + result.stderr[-2000:])
        match = re.fullmatch(r'(\d+)(?:;[\w.-]+)?', result.stdout.strip())
        if not match:
            # Submission might already exist: do not auto-retry.
            raise RuntimeError('Unrecognized sbatch reply; inspect sbatch.log before retrying')
        write_json(directory / 'slurm.json', {'job_id': match[1], 'submitted_at': now(), 'settings': settings})
    except Exception as exc:
        status = Status(directory, resume=True)
        if status.value['state'] == 'QUEUED':
            status.set('FAILED', error_code='SLURM_SUBMIT_ERROR', error=str(exc), finished_at=now())
        raise
    return directory


def reconcile(directory):
    """Scheduler is authoritative for killed jobs, never sufficient for PASS."""
    record = directory / 'slurm.json'
    if not record.is_file():
        return None
    value = json.loads(record.read_text())
    job_id = str(value.get('job_id',''))
    if not job_id.isdigit():
        raise ValueError('Invalid persisted Slurm ID')
    if time.monotonic() - _last_checked.get(str(directory), -100) < 10:
        return value
    _last_checked[str(directory)] = time.monotonic()
    try:
        result = subprocess.run(['sacct','-X','-j',job_id,'--noheader','--parsable2','--format=JobIDRaw,State,ExitCode'],
                                text=True,capture_output=True,timeout=5)
        if result.returncode:
            return value
        for line in result.stdout.splitlines():
            fields = line.strip().split('|')
            if len(fields) < 3 or fields[0] != job_id:
                continue
            state = fields[1].split()[0].rstrip('+')
            value.update(scheduler_state=state, exit_code=fields[2], checked_at=now())
            write_json(record, value)
            # Worker owns active statuses. Allow final file writes to settle.
            status = Status(directory, resume=True)
            if status.value['state'] not in TERMINAL and time.time() - status.path.stat().st_mtime > 30:
                failure = {'CANCELLED':'CANCELLED', 'TIMEOUT':'TIMED_OUT', 'FAILED':'FAILED',
                           'OUT_OF_MEMORY':'FAILED', 'NODE_FAIL':'FAILED', 'PREEMPTED':'FAILED', 'BOOT_FAIL':'FAILED',
                           'COMPLETED':'FAILED'}.get(state)
                if failure:
                    status.set(failure, error_code='SLURM_' + state,
                               error='Job ended without a verified runner result: ' + state, finished_at=now())
    except (OSError, subprocess.TimeoutExpired):
        pass
    return value
