"""Named host-local capacity pools shared by API worker processes."""
import fcntl
import os
from pathlib import Path
import tempfile

from fastapi import HTTPException


def pool_capacity(name):
    variable = f'SIGNOFF_{name}_MAX_CONCURRENT'
    try:
        limit = int(os.environ.get(variable, '2'))
    except ValueError:
        raise RuntimeError(f'{variable} must be an integer from 1 to 16') from None
    if not 1 <= limit <= 16:
        raise RuntimeError(f'{variable} must be an integer from 1 to 16')
    return limit


class Slot:
    def __init__(self, fd):
        self.fd = fd

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def acquire_pool_slot(name):
    limit = pool_capacity(name)
    variable = f'SIGNOFF_{name}_SLOT_DIR'
    default = Path(tempfile.gettempdir()) / f'signoff-{name.lower()}-{os.getuid()}'
    directory = Path(os.environ.get(variable, str(default)))
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.lstat()
    if directory.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError(f'{name} slot directory must be owned by this user with mode 0700')
    for index in range(limit):
        fd = os.open(directory / f'{index}.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            continue
        except BaseException:
            os.close(fd)
            raise
        return Slot(fd)
    raise HTTPException(429, f'{name} analysis capacity is full; retry shortly',
                        headers={'Retry-After': '5'})
