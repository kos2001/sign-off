"""Non-queued, host-local admission shared by all AI review roles and API workers."""
import fcntl
import os
from pathlib import Path
import stat
import tempfile


class ReviewCapacityFull(Exception):
    pass


def capacity():
    try:
        value = int(os.environ.get('SIGNOFF_REVIEW_MAX_CONCURRENT', '2'))
    except ValueError:
        value = 0
    if not 1 <= value <= 16:
        raise RuntimeError('SIGNOFF_REVIEW_MAX_CONCURRENT must be an integer from 1 to 16')
    return value


class Slot:
    def __init__(self, fd):
        self.fd = fd

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def acquire():
    limit = capacity()
    directory = Path(os.environ.get('SIGNOFF_REVIEW_SLOT_DIR', str(Path(tempfile.gettempdir()) / f'signoff-reviews-{os.getuid()}')))
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(directory_fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise RuntimeError('Review slot directory must be private and owned by this user')
        for index in range(limit):
            fd = os.open(f'{index}.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory_fd)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
                    raise RuntimeError('Review slot file must be private, regular and owned by this user')
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                continue
            except BaseException:
                os.close(fd)
                raise
            return Slot(fd)
    finally:
        os.close(directory_fd)
    raise ReviewCapacityFull()
