"""Host-local RTL capacity shared by API workers using kernel file locks."""
import fcntl
import os
from pathlib import Path
import tempfile
import threading
import anyio

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from starlette.requests import ClientDisconnect


def capacity():
    try:
        limit = int(os.environ.get('SIGNOFF_RTL_MAX_CONCURRENT', '2'))
    except ValueError:
        raise RuntimeError('SIGNOFF_RTL_MAX_CONCURRENT must be an integer from 1 to 16') from None
    if not 1 <= limit <= 16:
        raise RuntimeError('SIGNOFF_RTL_MAX_CONCURRENT must be an integer from 1 to 16')
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


def acquire_slot():
    limit = capacity()
    directory = Path(os.environ.get('SIGNOFF_RTL_SLOT_DIR', str(Path(tempfile.gettempdir()) / f'signoff-rtl-{os.getuid()}')))
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.lstat()
    if directory.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError('RTL slot directory must be owned by this user with mode 0700')
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
    raise HTTPException(429, 'RTL analysis capacity is full; retry shortly', headers={'Retry-After': '5'})


class AdmittedIterator:
    """Retain admission until an in-flight synchronous next() actually finishes.

    A disconnected HTTP response may close the iterator while a tool is still
    executing in a worker thread. Closing requests cleanup; that worker performs
    it after the current stage yields. No subsequent stage is then started.
    """
    def __init__(self, iterator, slot, on_close=None):
        self.iterator = iter(iterator)
        self.slot = slot
        self.guard = threading.Lock()
        self.active = False
        self.closed = False
        self.on_close = on_close

    def __iter__(self):
        return self

    def __next__(self):
        with self.guard:
            if self.closed:
                raise StopIteration
            self.active = True
        ended = False
        try:
            return next(self.iterator)
        except BaseException:
            ended = True
            raise
        finally:
            with self.guard:
                self.active = False
                cleanup = ended or self.closed
                if cleanup:
                    self.closed = True
            if cleanup:
                self._cleanup()

    def _cleanup(self):
        try:
            close = getattr(self.iterator, 'close', None)
            if close:
                close()
        finally:
            self.slot.close()

    def close(self):
        if self.on_close is not None:
            self.on_close()
        with self.guard:
            if self.closed:
                return
            self.closed = True
            cleanup = not self.active
        if cleanup:
            self._cleanup()


class AdmittedStreamingResponse(StreamingResponse):
    def __init__(self, iterator, slot, on_close=None):
        self.admitted = AdmittedIterator(iterator, slot, on_close)
        try:
            super().__init__(self.admitted, media_type='application/x-ndjson')
        except BaseException:
            self.admitted.close()
            raise

    async def __call__(self, scope, receive, send):
        try:
            # ASGI 2.4's send-error-only disconnect detection cannot interrupt
            # a long synchronous next(). Listen concurrently so the worker's
            # cancellation event is set before waiting for that thread to end.
            async with anyio.create_task_group() as group:
                async def stream():
                    try:
                        await self.stream_response(send)
                    finally:
                        self.admitted.close()
                        group.cancel_scope.cancel()
                group.start_soon(stream)
                await self.listen_for_disconnect(receive)
                self.admitted.close()
                group.cancel_scope.cancel()
            if self.background is not None:
                await self.background()
        except BaseExceptionGroup as errors:
            error = errors
            while isinstance(error, BaseExceptionGroup) and len(error.exceptions) == 1:
                error = error.exceptions[0]
            if isinstance(error, OSError):
                raise ClientDisconnect() from None
            raise error
        finally:
            self.admitted.close()
