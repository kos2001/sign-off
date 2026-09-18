"""Bounded host transport for the isolated OpenSTA worker."""
import json
import os
import re
import selectors
import signal
import subprocess
import threading
import time
import uuid

from ..sta_worker import MAX_INPUT_BYTES, MAX_OUTPUT_BYTES, OPENSTA_COMMIT, PROTOCOL
from .report_import import parse_opensta, unique_object, reject_constant, finite_json_float
from .rtl.lifecycle import lifecycle_labels

TIMEOUT_SECONDS = 250
MAX_DIAGNOSTIC_BYTES = 128 * 1024


class StaWorkerError(RuntimeError):
    pass


def configured_image():
    image = os.environ.get('SIGNOFF_STA_WORKER_IMAGE', 'signoff-sta-worker:d97587f')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/:@-]{0,255}', image):
        raise StaWorkerError('Invalid STA worker image configuration.')
    return image


def worker_command(name, image_id):
    command = ['docker', 'run', '--pull', 'never', '--rm', '--name', name, '--label', 'signoff.sta-worker=1',
               '--network', 'none', '--read-only', '--user', '65534:65534', '--cap-drop', 'ALL',
               '--security-opt', 'no-new-privileges:true', '--memory', '2g', '--memory-swap', '2g',
               '--cpus', '2', '--pids-limit', '64', '--tmpfs', '/tmp:rw,nosuid,nodev,noexec,size=128m',
               '--log-driver', 'none', '-i']
    for key, value in lifecycle_labels().items():
        command += ['--label', f'{key}={value}']
    return command + [image_id]


def remove_container(name):
    try:
        subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=5)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            inspected = subprocess.run(['docker', 'container', 'inspect', name], capture_output=True,
                                       timeout=max(0.1, deadline - time.monotonic()))
            if inspected.returncode:
                absent = rb'no such (?:object|container):\s*' + re.escape(name.encode()) + rb'(?:\s|$)'
                if re.search(absent, inspected.stderr.lower()):
                    return
                raise StaWorkerError('STA worker cleanup could not be confirmed.')
            time.sleep(0.05)
        raise StaWorkerError('STA worker cleanup could not be confirmed.')
    except (OSError, subprocess.TimeoutExpired) as error:
        raise StaWorkerError('STA worker cleanup could not be confirmed.') from error


def bounded_worker(command, payload, name, cancel=None):
    cancel = cancel if cancel is not None else threading.Event()
    if cancel.is_set():
        raise StaWorkerError('STA worker cancelled.')
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True)
    except OSError as error:
        raise StaWorkerError('STA worker could not start.') from error
    stdout, stderr, written = bytearray(), bytearray(), 0
    deadline = time.monotonic() + TIMEOUT_SECONDS
    try:
        with selectors.DefaultSelector() as selector:
            for pipe, events in [(process.stdin, selectors.EVENT_WRITE), (process.stdout, selectors.EVENT_READ),
                                 (process.stderr, selectors.EVENT_READ)]:
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, events)
            while selector.get_map():
                if cancel.is_set():
                    raise StaWorkerError('STA worker cancelled.')
                if time.monotonic() >= deadline:
                    raise StaWorkerError('STA worker deadline exceeded.')
                for key, _ in selector.select(0.1):
                    pipe = key.fileobj
                    if pipe is process.stdin:
                        try:
                            written += os.write(pipe.fileno(), payload[written:written + 65536])
                        except BrokenPipeError:
                            written = len(payload)
                        if written == len(payload):
                            selector.unregister(pipe)
                            pipe.close()
                        continue
                    data = os.read(pipe.fileno(), 65536)
                    if not data:
                        selector.unregister(pipe)
                        continue
                    target, limit, message = ((stderr, MAX_DIAGNOSTIC_BYTES, 'STA worker diagnostic limit exceeded.')
                                              if pipe is process.stderr else
                                              (stdout, MAX_OUTPUT_BYTES, 'STA worker output limit exceeded.'))
                    target.extend(data)
                    if len(target) > limit:
                        raise StaWorkerError(message)
            while process.poll() is None:
                if cancel.is_set():
                    raise StaWorkerError('STA worker cancelled.')
                if time.monotonic() >= deadline:
                    raise StaWorkerError('STA worker deadline exceeded.')
                time.sleep(0.05)
            return process.returncode, bytes(stdout), bytes(stderr)
    finally:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait()
        for pipe in (process.stdin, process.stdout, process.stderr):
            if not pipe.closed:
                pipe.close()
        remove_container(name)


def run_sta(netlist, liberty, sdc, top_module, *, cancel=None):
    cancel = cancel if cancel is not None else threading.Event()
    request = {'protocol': PROTOCOL, 'request': {'netlist': netlist, 'liberty': liberty, 'sdc': sdc, 'top_module': top_module}}
    payload = json.dumps(request, ensure_ascii=False).encode()
    if len(payload) > MAX_INPUT_BYTES:
        raise StaWorkerError('STA worker input limit exceeded.')
    if cancel.is_set():
        raise StaWorkerError('STA worker cancelled.')
    image = configured_image()
    try:
        inspected = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', image], capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise StaWorkerError('STA worker image is unavailable.') from error
    image_id = inspected.stdout.decode(errors='replace').strip()
    if inspected.returncode or not re.fullmatch(r'sha256:[0-9a-f]{64}', image_id):
        raise StaWorkerError('STA worker image is unavailable.')
    name = 'signoff-sta-job-' + uuid.uuid4().hex
    returncode, stdout, stderr = bounded_worker(worker_command(name, image_id), payload, name, cancel)
    if returncode:
        raise StaWorkerError((stderr.decode(errors='replace')[-2000:] or 'STA worker failed.').strip())
    try:
        result = json.loads(stdout.decode(), object_pairs_hook=unique_object,
                            parse_constant=reject_constant, parse_float=finite_json_float)
        if result['protocol'] != PROTOCOL or result['opensta_commit'] != OPENSTA_COMMIT:
            raise ValueError()
        parsed = parse_opensta(result['report'])
    except (ValueError, KeyError, UnicodeError, RecursionError, json.JSONDecodeError) as error:
        raise StaWorkerError('Invalid STA worker response.') from error
    return result, parsed, image_id
