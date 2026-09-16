"""Bounded Unix tool execution; process-group cleanup is not an OS sandbox."""
import os
import math
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time


def run_command(command, cwd, *, timeout_seconds=30, max_output_bytes=128 * 1024,
                max_file_bytes=64 * 1024 * 1024, max_memory_bytes=1024 * 1024 * 1024,
                max_open_files=256, cpu_seconds=None):
    """Drain a bounded pipe, with a wall deadline and process-group cleanup."""
    chunks = bytearray()
    reason = None
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError('tool limits must be positive finite values')
    cpu = math.ceil(timeout_seconds) + 1 if cpu_seconds is None else cpu_seconds
    if any(
        type(value) is not int or value <= 0 for value in
        [max_output_bytes, max_file_bytes, max_memory_bytes, max_open_files, cpu]
    ):
        raise ValueError('tool limits must be positive finite values')
    launcher = [sys.executable, '-I', str(Path(__file__).with_name('launcher.py')),
                str(cpu), str(max_file_bytes), str(max_memory_bytes), str(max_open_files), *command]
    try:
        process = subprocess.Popen(launcher, cwd=cwd, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                   start_new_session=True)
    except OSError as error:
        log = str(error).encode('utf-8', errors='replace')[:max_output_bytes].decode('utf-8', errors='ignore')
        return {'exit_code': None, 'log': log, 'error': 'tool could not execute'}
    try:
        deadline = time.monotonic() + timeout_seconds
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    reason = f'tool timed out after {timeout_seconds}s'
                    break
                if not selector.select(min(remaining, 0.1)):
                    continue
                data = os.read(process.stdout.fileno(), 8192)
                if not data:
                    selector.unregister(process.stdout)
                    break
                room = max_output_bytes - len(chunks)
                chunks.extend(data[:room])
                if len(data) > room:
                    reason = f'tool output exceeded {max_output_bytes} bytes'
                    break
        if reason is None:
            try:
                process.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                reason = f'tool timed out after {timeout_seconds}s'
    finally:
        # Also clean up descendants when the parent exits before its children.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        process.stdout.close()
    # Replacement characters can expand invalid input bytes; bound the returned UTF-8 too.
    log = chunks.decode('utf-8', errors='replace').encode('utf-8')[:max_output_bytes].decode('utf-8', errors='ignore')
    if reason is None:
        if process.returncode == 125:
            reason = 'tool resource limits could not be applied'
        elif process.returncode == 127:
            reason = 'tool could not execute'
        elif process.returncode == -signal.SIGXFSZ:
            reason = 'tool exceeded its per-file size limit'
        elif process.returncode == -signal.SIGXCPU:
            reason = 'tool exceeded its CPU time limit'
    return {'exit_code': process.returncode, 'log': log, 'error': reason}
