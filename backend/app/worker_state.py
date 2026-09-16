"""Private, atomic host-local checkpoints for worker reconciliation."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import stat
import tempfile

from .services.rtl.worker_client import WorkerError

logger = logging.getLogger('uvicorn.error.signoff')
MAX_STATE_BYTES = 1024 * 1024


class SweepBusy(WorkerError):
    pass


def private_file(fd):
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
        raise WorkerError('Worker checkpoint files must be private regular files owned by this user.')


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


class SweepCheckpoint:
    def __init__(self, directory, owner, daemon_id, max_ids):
        self.directory = Path(directory)
        self.owner, self.daemon_id, self.max_ids = owner, daemon_id, max_ids
        key = hashlib.sha256(f'{owner}:{daemon_id}'.encode()).hexdigest()
        self.path = self.directory / f'{key}.json'
        self.lock_path = self.directory / f'{key}.lock'

    def load(self):
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return []
        with os.fdopen(fd, 'rb') as stream:
            private_file(stream.fileno())
            raw = stream.read(MAX_STATE_BYTES + 1)
        try:
            if len(raw) > MAX_STATE_BYTES:
                raise ValueError('oversized')
            value = json.loads(raw, object_pairs_hook=strict_object)
            if (not isinstance(value, dict) or set(value) != {'version', 'owner', 'daemon_id', 'pending'}
                    or type(value['version']) is not int or value['version'] != 1
                    or value['owner'] != self.owner or value['daemon_id'] != self.daemon_id):
                raise ValueError('invalid scope or version')
            pending = value['pending']
            if (not isinstance(pending, list) or len(pending) > self.max_ids
                    or any(not isinstance(item, str) or re.fullmatch(r'[0-9a-f]{64}', item) is None for item in pending)
                    or len(set(pending)) != len(pending)):
                raise ValueError('invalid inventory')
            return pending
        except (ValueError, UnicodeError, RecursionError):
            logger.warning('Invalid RTL worker checkpoint; inventory will be refreshed.')
            return []

    def save(self, pending):
        payload = json.dumps({'version': 1, 'owner': self.owner, 'daemon_id': self.daemon_id,
                              'pending': list(pending)}, separators=(',', ':')).encode()
        if len(payload) > MAX_STATE_BYTES:
            raise WorkerError('Worker checkpoint exceeds its size limit.')
        fd, temporary = tempfile.mkstemp(prefix='.checkpoint-', dir=self.directory)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    @contextmanager
    def locked(self):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise WorkerError('Worker checkpoint directory must be owned by this user with mode 0700.')
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            private_file(fd)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SweepBusy('Another process is reconciling this deployment.') from None
            yield self
        finally:
            os.close(fd)
