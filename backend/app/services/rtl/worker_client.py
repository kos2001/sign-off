"""Host-side, bounded Docker worker transport; results are withheld until exit."""
import json
import logging
import os
import re
import selectors
import signal
import subprocess
import threading
import time
import uuid

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from ...rtl_worker import PROTOCOL, MAX_INPUT_BYTES, MAX_OUTPUT_BYTES
from ..report_import import unique_object, reject_constant, finite_json_float
from ..evidence import rtl_result_status
from .lifecycle import lifecycle_labels

TIMEOUT_SECONDS = 240
STAGES = ['lint', 'design', 'synthesize', 'simulate']


class WorkerError(RuntimeError):
    pass


class WorkerStage(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    name: str
    status: Literal['pass', 'fail', 'skip']
    gating: Literal[True]
    detail: str


class WorkerRule(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    code: str
    name: str
    severity: Literal['error', 'warn', 'info']
    status: Literal['pass', 'violation']
    detail: str


class WorkerResult(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    verdict: Literal['SIGNED_OFF', 'CONDITIONAL', 'REJECTED']
    score: int = Field(ge=0, le=100)
    grade: str
    module: str | None
    stages: list[WorkerStage]
    rules: list[WorkerRule]
    suggestions: list[str]
    simulation: dict


def container_mode():
    mode = os.environ.get('SIGNOFF_RTL_EXECUTION', 'local')
    if mode not in {'local', 'container'}:
        raise WorkerError('Invalid RTL execution mode.')
    return mode == 'container'


def configured_image():
    image = os.environ.get('SIGNOFF_RTL_WORKER_IMAGE', 'signoff-rtl-worker:local')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/:@-]{0,255}', image):
        raise WorkerError('Invalid RTL worker image configuration.')
    return image


def worker_command(name, image):
    command = ['docker', 'run', '--pull', 'never', '--rm', '--name', name, '--label', 'signoff.rtl-worker=1',
               '--network', 'none', '--read-only', '--user', '65534:65534', '--cap-drop', 'ALL',
               '--security-opt', 'no-new-privileges:true', '--memory', '1g', '--memory-swap', '1g',
               '--cpus', '1', '--pids-limit', '64', '--tmpfs', '/tmp:rw,nosuid,nodev,noexec,size=128m',
               '--log-driver', 'none', '-e', 'SIGNOFF_RTL_WORKER_DEADLINE_SECONDS=300', '-i']
    if os.environ.get('SIGNOFF_SIMULATION_MODE') == 'trusted_local':
        command += ['-e', 'SIGNOFF_SIMULATION_MODE=trusted_local']
    for key, value in lifecycle_labels().items():
        command += ['--label', f'{key}={value}']
    return command + [image]


def remove_container(name):
    try:
        deadline = time.monotonic() + 10
        subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=5)
        # --rm and explicit removal can race. Confirm absence, including when
        # the daemon reports that removal is already in progress.
        while time.monotonic() < deadline:
            inspected = subprocess.run(['docker', 'container', 'inspect', name], capture_output=True,
                                       timeout=max(0.1, deadline - time.monotonic()))
            if inspected.returncode:
                absent = rb'no such (?:object|container):\s*' + re.escape(name.encode('ascii')) + rb'(?:\s|$)'
                if re.search(absent, inspected.stderr.lower()):
                    return
                raise WorkerError('RTL worker cleanup could not be confirmed.')
            time.sleep(0.05)
        raise WorkerError('RTL worker cleanup could not be confirmed.')
    except (OSError, subprocess.TimeoutExpired) as error:
        raise WorkerError('RTL worker cleanup could not be confirmed.') from error


class EventSequence:
    def __init__(self):
        self.position = 0
        self.done = []
        self.result = None

    def accept(self, raw):
        try:
            event = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object, parse_constant=reject_constant,
                               parse_float=finite_json_float)
            if not isinstance(event, dict) or event.pop('protocol', None) != PROTOCOL or self.result is not None:
                raise ValueError()
            if self.position < 8:
                kind = 'stage_start' if self.position % 2 == 0 else 'stage_done'
                if event.get('event') != kind or event.get('stage') != STAGES[self.position // 2]:
                    raise ValueError()
                if kind == 'stage_start' and set(event) != {'event', 'stage'}:
                    raise ValueError()
                if kind == 'stage_done':
                    if set(event) != {'event', 'stage', 'status', 'detail'} or event['status'] not in {'pass', 'fail', 'skip'} or not isinstance(event['detail'], str):
                        raise ValueError()
                    self.done.append(event)
                self.position += 1
                return event
            if set(event) != {'event', 'result'} or event['event'] != 'result':
                raise ValueError()
            result = WorkerResult.model_validate(event['result']).model_dump()
            if [stage['name'] for stage in result['stages']] != STAGES:
                raise ValueError()
            if any(stage['status'] != done['status'] or stage['detail'] != done['detail']
                   for stage, done in zip(result['stages'], self.done)):
                raise ValueError()
            verdict = {'passed': 'SIGNED_OFF', 'incomplete': 'CONDITIONAL', 'failed': 'REJECTED'}[rtl_result_status(result).value]
            if result['verdict'] != verdict:
                raise ValueError()
            self.result = result
            return None
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as error:
            raise WorkerError('Invalid or incomplete RTL worker response.') from error


def stream_worker(code, testbench=None, testbench_top=None, *, cancel=None):
    cancel = cancel if cancel is not None else threading.Event()
    payload = json.dumps({'protocol': PROTOCOL, 'request': {'code': code, 'testbench': testbench,
                         'testbench_top': testbench_top}}, ensure_ascii=False).encode('utf-8')
    if len(payload) > MAX_INPUT_BYTES:
        raise WorkerError('RTL worker input limit exceeded.')
    image = configured_image()
    deadline = time.monotonic() + TIMEOUT_SECONDS
    try:
        inspected = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', image],
                                   capture_output=True, timeout=min(10, TIMEOUT_SECONDS))
    except (OSError, subprocess.TimeoutExpired) as error:
        raise WorkerError('RTL worker image is unavailable.') from error
    image_id = inspected.stdout.decode('ascii', errors='replace').strip()
    if inspected.returncode or re.fullmatch(r'sha256:[0-9a-f]{64}', image_id) is None:
        raise WorkerError('RTL worker image is unavailable.')
    if cancel.is_set():
        raise WorkerError('RTL worker cancelled.')
    name = 'signoff-rtl-job-' + uuid.uuid4().hex
    try:
        process = subprocess.Popen(worker_command(name, image_id), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
    except OSError as error:
        raise WorkerError('RTL worker could not start.') from error
    sequence, buffer, total, stderr_total, written = EventSequence(), bytearray(), 0, 0, 0
    try:
        with selectors.DefaultSelector() as selector:
            for pipe, events in [(process.stdin, selectors.EVENT_WRITE), (process.stdout, selectors.EVENT_READ),
                                 (process.stderr, selectors.EVENT_READ)]:
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, events)
            while selector.get_map():
                if cancel.is_set():
                    raise WorkerError('RTL worker cancelled.')
                if time.monotonic() >= deadline:
                    raise WorkerError('RTL worker deadline exceeded.')
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
                    if pipe is process.stderr:
                        stderr_total += len(data)
                        if stderr_total > 128 * 1024:
                            raise WorkerError('RTL worker diagnostic limit exceeded.')
                        continue
                    total += len(data)
                    if total > MAX_OUTPUT_BYTES:
                        raise WorkerError('RTL worker output limit exceeded.')
                    buffer.extend(data)
                    while b'\n' in buffer:
                        line, _, remaining = buffer.partition(b'\n')
                        buffer = bytearray(remaining)
                        event = sequence.accept(line)
                        if event is not None:
                            yield event
            while process.poll() is None:
                if cancel.is_set() or time.monotonic() >= deadline:
                    raise WorkerError('RTL worker cancelled or deadline exceeded.')
                cancel.wait(0.05)
            if process.returncode or buffer or sequence.result is None:
                raise WorkerError('RTL worker did not complete successfully.')
    finally:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait()
        for pipe in [process.stdin, process.stdout, process.stderr]:
            pipe.close()
        try:
            remove_container(name)
        except WorkerError:
            logging.getLogger('uvicorn.error.signoff').error('RTL worker cleanup unconfirmed: %s', name)
            raise
    if cancel.is_set():
        raise WorkerError('RTL worker cancelled.')
    sequence.result['execution'] = {'backend': 'container', 'image_id': image_id}
    yield {'event': 'result', 'result': sequence.result}
