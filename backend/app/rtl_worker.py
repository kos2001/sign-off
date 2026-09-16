"""One RTL job over bounded JSON input and NDJSON output; no DB operations."""
import json
import os
import signal
import subprocess
import sys

from pydantic import ValidationError

from .schemas import RtlSignoffRequest
from .services.report_import import unique_object, reject_constant
from .services.rtl.signoff import stream_signoff

PROTOCOL = 'signoff/rtl-worker/v1'
MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_WALL_SECONDS = 300


def read_request(stream):
    raw = stream.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError('input too large')
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object, parse_constant=reject_constant)
    if not isinstance(value, dict) or set(value) != {'protocol', 'request'} or value['protocol'] != PROTOCOL:
        raise ValueError('invalid protocol')
    request = value['request']
    if not isinstance(request, dict) or set(request) - {'code', 'testbench', 'testbench_top', 'top_module'}:
        raise ValueError('unsupported fields')
    return RtlSignoffRequest.model_validate(request)


def main(input_stream=None, output_stream=None, error_stream=None):
    input_stream = sys.stdin.buffer if input_stream is None else input_stream
    output_stream = sys.stdout if output_stream is None else output_stream
    error_stream = sys.stderr if error_stream is None else error_stream
    try:
        request = read_request(input_stream)
    except (ValueError, UnicodeError, RecursionError, ValidationError):
        print('Invalid RTL worker request.', file=error_stream, flush=True)
        return 2
    emitted = 0
    finished = False
    failure = json.dumps({'protocol': PROTOCOL, 'event': 'error', 'detail': 'RTL worker execution failed.'}) + '\n'
    failure_bytes = len(failure.encode('utf-8'))
    try:
        options = {'top_module': request.top_module} if request.top_module is not None else {}
        for event in stream_signoff(request.code, request.testbench, request.testbench_top, **options):
            if finished:
                raise ValueError('events after final result')
            line = json.dumps({'protocol': PROTOCOL, **event}, ensure_ascii=False, allow_nan=False) + '\n'
            size = len(line.encode('utf-8'))
            if emitted + size + failure_bytes > MAX_OUTPUT_BYTES:
                raise ValueError('output limit')
            emitted += size
            output_stream.write(line)
            output_stream.flush()
            finished = event.get('event') == 'result'
        if not finished:
            raise ValueError('missing final result')
    except BrokenPipeError:
        return 1
    except Exception:
        if emitted + failure_bytes <= MAX_OUTPUT_BYTES:
            output_stream.write(failure)
            output_stream.flush()
        return 1
    return 0


def entrypoint(job_command=None):
    """Arm a worker-local deadline even if its host client disappears."""
    try:
        seconds = int(os.environ.get('SIGNOFF_RTL_WORKER_DEADLINE_SECONDS', str(MAX_WALL_SECONDS)))
        if not 1 <= seconds <= MAX_WALL_SECONDS:
            raise ValueError()
    except ValueError:
        print('Invalid RTL worker deadline configuration.', file=sys.stderr, flush=True)
        return 2
    process = None
    def expire(signum, frame):
        # No Python cleanup can postpone expiry. As container PID 1 exits,
        # the runtime terminates remaining processes in its PID namespace.
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        os._exit(124)
    previous = signal.signal(signal.SIGALRM, expire)
    signal.alarm(seconds)
    try:
        # Keep analysis/native code out of the supervisor. Only this child
        # reads job input and emits protocol events; the supervisor waits.
        command = job_command or [sys.executable, '-c', 'from app.rtl_worker import main; raise SystemExit(main())']
        process = subprocess.Popen(command, start_new_session=True)
        return process.wait()
    except OSError:
        print('RTL worker process could not start.', file=sys.stderr, flush=True)
        return 1
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


if __name__ == '__main__':
    sys.exit(entrypoint())
