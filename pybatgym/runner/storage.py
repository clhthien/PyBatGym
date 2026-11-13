"""Atomic status files and an OS-owned advisory lock for serial Real runs."""
import json
import os
import tempfile
from pathlib import Path
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Status:
    def __init__(self, directory, *, resume=False):
        self.path = directory / 'status.json'
        if resume:
            self.value = json.loads(self.path.read_text(encoding='utf-8'))
            if self.value['run_id'] != directory.name:
                raise ValueError('Run ID does not match status record')
            return
        self.value = {'run_id': directory.name, 'state': 'CREATED', 'created_at': now(), 'history': []}
        self.set('CREATED')

    def set(self, state, **fields):
        timestamp = now()
        self.value.update(state=state, updated_at=timestamp, **fields)
        self.value['history'].append({'state': state, 'at': timestamp})
        write_json(self.path, self.value)


class RealLock:
    def __init__(self, path=None):
        self.path = Path(path or (Path(tempfile.gettempdir()) / f'pybatgym-real-{getattr(os, "getuid", lambda: 0)()}.lock'))
        self.file = None

    def __enter__(self):
        if os.name != 'posix':
            raise RuntimeError('Real backend requires the PyBatGym Linux Docker shell')
        import fcntl
        self.file = self.path.open('a+')
        try:
            fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.file.close()
            self.file = None
            raise RuntimeError('REAL_BUSY: another runner owns the Real backend') from None
        return self

    def __exit__(self, *exc):
        if self.file:
            import fcntl
            fcntl.flock(self.file, fcntl.LOCK_UN)
            self.file.close()
