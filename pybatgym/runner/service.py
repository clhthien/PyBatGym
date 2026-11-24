"""Run orchestration, process supervision, and durable status API."""
from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import uuid

from .config import REPO, Request, resolve
from .storage import RealLock, Status, now, write_json
from .verify import verify
from pybatgym.time_units import TIME_UNITS


def git(*args):
    try:
        return subprocess.check_output(['git', *args], cwd=REPO, text=True, stderr=subprocess.DEVNULL, timeout=5).strip()
    except (OSError, subprocess.SubprocessError):
        return 'unavailable'


def stop_process(child):
    if child is None or child.poll() is not None:
        return
    try:
        if os.name == 'posix':
            os.killpg(child.pid, signal.SIGTERM)
        else:
            child.terminate()
    except ProcessLookupError:
        child.wait()
        return
    try:
        child.wait(timeout=3)
    except subprocess.TimeoutExpired:
        if os.name == 'posix':
            os.killpg(child.pid, signal.SIGKILL)
        else:
            child.kill()
        child.wait(timeout=5)


def allocate(output_root=None):
    output_root = Path(output_root or REPO / 'runs/playground').resolve()
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:12]
    directory = output_root / run_id
    directory.mkdir(parents=True, exist_ok=False)
    Status(directory)
    (directory / 'stdout.log').touch()
    (directory / 'stderr.log').touch()
    return directory


def run(config, output_root=None, *, _prepared=None) -> Path:
    """Synchronously run a JSON request/dict. Inspect status.json for the outcome.

    Validation/runtime errors produce a FAILED run with an error code. Output
    directory creation errors are raised because no durable record can be made.
    """
    output_root = Path(output_root or REPO / 'runs/playground').resolve()
    if _prepared is None:
        run_dir = allocate(output_root)
        status = Status(run_dir, resume=True)
    else:
        run_dir = Path(_prepared).resolve(strict=True)
        if run_dir.parent != output_root:
            raise ValueError('Prepared run must be directly inside the output root')
        status = Status(run_dir, resume=True)
        if status.value['state'] != 'QUEUED':
            raise ValueError('Prepared run is not queued')
    run_id = run_dir.name
    write_json(run_dir / 'units.json', TIME_UNITS)
    request = None
    runtime = None
    child = None
    error_code = 'VALIDATION_ERROR'
    terminal_state = 'FAILED'
    metadata = {'run_id': run_id, 'created_at': now(), 'python': sys.version,
                'git_commit': git('rev-parse', 'HEAD'), 'git_status': git('status', '--short'),
                'runner_pid': os.getpid(), 'versions': {}}
    for name in ('pybatgym', 'numpy', 'gymnasium', 'pydantic', 'pybatsim'):
        try:
            metadata['versions'][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    # Dirty code must be identifiable even if it has not been committed yet.
    metadata['source_sha256'] = {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in (REPO / 'pybatgym').rglob('*.py')}
    write_json(run_dir / 'metadata.json', metadata)
    old_sigterm = None
    if os.name == 'posix' and threading.current_thread() is threading.main_thread():
        old_sigterm = signal.getsignal(signal.SIGTERM)
        def interrupt(signum, frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, interrupt)
    try:
        status.set('VALIDATING')
        if isinstance(config, (str, Path)):
            raw = Path(config).read_text(encoding='utf-8-sig')
            (run_dir / 'request.original.json').write_text(raw, encoding='utf-8')
            config = json.loads(raw)
        write_json(run_dir / 'request.original.json', config)
        request = Request.model_validate(config)
        cfg, hashes = resolve(request)
        write_json(run_dir / 'request.json', request.model_dump(mode='json'))
        write_json(run_dir / 'config_resolved.json', cfg)
        metadata['input_sha256'] = hashes
        write_json(run_dir / 'metadata.json', metadata)
        error_code = 'RUNTIME_ERROR'
        with RealLock() if request.backend == 'real' else nullcontext():
            if request.backend == 'real':
                from .runtime import backend
                runtime = backend().prepare(REPO, run_dir)
                write_json(run_dir / 'runtime.json', runtime)
            command = [sys.executable, '-u', '-m', 'pybatgym.runner.worker', str(run_dir)]
            env = os.environ.copy()
            env.update(PYTHONUTF8='1', PYTHONUNBUFFERED='1', PYTHONDONTWRITEBYTECODE='1')
            env['PYTHONPATH'] = str(REPO) + os.pathsep + env.get('PYTHONPATH', '')
            metadata['command'] = command
            write_json(run_dir / 'metadata.json', metadata)
            try:
                with (run_dir / 'stdout.log').open('w', encoding='utf-8') as stdout, (run_dir / 'stderr.log').open('w', encoding='utf-8') as stderr:
                    child = subprocess.Popen(command, cwd=REPO, env=env, stdout=stdout, stderr=stderr,
                                             start_new_session=(os.name == 'posix'))
                    status.set('RUNNING', started_at=now(), worker_pid=child.pid)
                    try:
                        return_code = child.wait(timeout=request.timeout_seconds)
                    except subprocess.TimeoutExpired:
                        terminal_state = 'TIMED_OUT'
                        error_code = 'TIMEOUT'
                        raise RuntimeError(f'Exceeded {request.timeout_seconds} wall-clock seconds (s_wall)') from None
                metadata['worker_exit_code'] = return_code
                write_json(run_dir / 'metadata.json', metadata)
                if return_code != 0:
                    raise RuntimeError(f'Worker exited with code {return_code}; see stderr.log and simulator logs')
                status.set('VERIFYING', worker_exit_code=return_code)
                error_code = 'RESULT_INVALID'
                verify(run_dir, request, cfg)
            finally:
                stop_process(child)
                if child is not None:
                    metadata['worker_exit_code'] = child.returncode
                    write_json(run_dir / 'metadata.json', metadata)
                if runtime:
                    from .runtime import backend
                    cleanup = backend(runtime.get('kind', 'docker')).cleanup
                    pending_exception = sys.exc_info()[0] is not None
                    try:
                        cleanup(runtime, run_dir)
                    except Exception as cleanup_error:
                        metadata['cleanup_error'] = str(cleanup_error)
                        write_json(run_dir / 'metadata.json', metadata)
                        if not pending_exception:
                            error_code = 'CLEANUP_ERROR'
                            raise
            status.set('SUCCEEDED', finished_at=now(), worker_exit_code=return_code)
    except KeyboardInterrupt:
        stop_process(child)
        status.set('CANCELLED', finished_at=now(), error_code='CANCELLED', error='Interrupted by user')
    except Exception as exc:
        message = str(exc)
        if message.startswith('REAL_BUSY:'):
            error_code = 'REAL_BUSY'
        status.set(terminal_state, finished_at=now(), error_code=error_code, error=message)
        with (run_dir / 'stderr.log').open('a', encoding='utf-8') as log:
            log.write(f'\n{error_code}: {message}\n')
    finally:
        if old_sigterm is not None:
            signal.signal(signal.SIGTERM, old_sigterm)
    return run_dir
