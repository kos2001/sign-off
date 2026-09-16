import io
import json
import os
import subprocess
import sys

import pytest

from app import rtl_worker as worker


def invoke(value):
    output, error = io.StringIO(), io.StringIO()
    status = worker.main(io.BytesIO(value), output, error)
    return status, output.getvalue(), error.getvalue()


def request(**fields):
    return json.dumps({'protocol': worker.PROTOCOL, 'request': {'code': 'module top; endmodule', **fields}}).encode()


@pytest.mark.parametrize('raw', [b'bad', b'\xff', b'[]', b'{"protocol":"wrong","request":{}}',
    request(project_id=1), request(testbench='module tb; endmodule'), request(code=''),
    b'{"protocol":"signoff/rtl-worker/v1","request":{"code":"a","code":"b"}}'])
def test_invalid_input_never_runs_or_exposes_source(monkeypatch, raw):
    def unexpected(*args):
        pytest.fail('invalid input must not execute')
    monkeypatch.setattr(worker, 'stream_signoff', unexpected)
    assert invoke(raw) == (2, '', 'Invalid RTL worker request.\n')


def test_one_job_emits_ordered_versioned_events(monkeypatch):
    events = [{'event': 'stage_start', 'stage': 'lint'}, {'event': 'result', 'result': {'verdict': 'CONDITIONAL'}}]
    received = []
    def run(*args):
        received.append(args)
        yield from events
    monkeypatch.setattr(worker, 'stream_signoff', run)
    status, output, error = invoke(request())
    assert status == 0 and error == ''
    assert [json.loads(line) for line in output.splitlines()] == [{'protocol': worker.PROTOCOL, **event} for event in events]
    assert received == [('module top; endmodule', None, None)]


def test_failed_execution_has_no_success_result_or_private_error(monkeypatch):
    def run(*args):
        yield {'event': 'stage_start', 'stage': 'lint'}
        raise RuntimeError('private source or credential')
    monkeypatch.setattr(worker, 'stream_signoff', run)
    status, output, error = invoke(request())
    assert status == 1 and 'private' not in output + error
    assert [json.loads(line)['event'] for line in output.splitlines()] == ['stage_start', 'error']


def test_input_and_output_budgets_fail_closed(monkeypatch):
    monkeypatch.setattr(worker, 'MAX_INPUT_BYTES', 8)
    assert invoke(request())[0] == 2
    monkeypatch.setattr(worker, 'MAX_INPUT_BYTES', 1024)
    monkeypatch.setattr(worker, 'MAX_OUTPUT_BYTES', 256)
    monkeypatch.setattr(worker, 'stream_signoff', lambda *args: iter([{'event': 'result', 'result': 'x' * 512}]))
    status, output, _ = invoke(request())
    assert status == 1 and json.loads(output)['event'] == 'error'
    assert len(output.encode()) <= 256


def test_missing_final_result_is_a_worker_failure(monkeypatch):
    monkeypatch.setattr(worker, 'stream_signoff', lambda *args: iter([{'event': 'stage_start', 'stage': 'lint'}]))
    status, output, _ = invoke(request())
    assert status == 1 and json.loads(output.splitlines()[-1])['event'] == 'error'


@pytest.mark.parametrize('value', ['0', '-1', '301', 'invalid', '1.5'])
def test_invalid_deadline_fails_before_job_input(value):
    result = subprocess.run([sys.executable, '-m', 'app.rtl_worker'], input=b'', capture_output=True,
                            env={**os.environ, 'SIGNOFF_RTL_WORKER_DEADLINE_SECONDS': value}, timeout=5)
    assert result.returncode == 2 and result.stdout == b''
    assert result.stderr == b'Invalid RTL worker deadline configuration.\n'


def test_worker_deadline_interrupts_stalled_input():
    process = subprocess.Popen([sys.executable, '-m', 'app.rtl_worker'], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env={**os.environ, 'SIGNOFF_RTL_WORKER_DEADLINE_SECONDS': '1'})
    try:
        assert process.wait(timeout=5) == 124  # Keep stdin open and send no EOF.
        output, error = process.communicate()
        assert output == error == b''
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


def test_worker_deadline_interrupts_running_job():
    script = 'import sys; from app import rtl_worker as w; sys.exit(w.entrypoint([sys.executable,"-c","import time; time.sleep(20)"]))'
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, timeout=5,
                            env={**os.environ, 'SIGNOFF_RTL_WORKER_DEADLINE_SECONDS': '1'})
    assert result.returncode == 124 and result.stdout == b''


def test_completed_worker_disarms_deadline():
    script = 'import time,sys; from app import rtl_worker as w; assert w.entrypoint([sys.executable,"-c","pass"])==0; time.sleep(1.2); print("done")'
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, timeout=5,
                            env={**os.environ, 'SIGNOFF_RTL_WORKER_DEADLINE_SECONDS': '1'})
    assert result.returncode == 0 and result.stdout == b'done\n'


def test_supervisor_preserves_failed_job_exit_status():
    script = 'import sys; from app import rtl_worker as w; sys.exit(w.entrypoint([sys.executable,"-c","raise SystemExit(7)"]))'
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, timeout=5)
    assert result.returncode == 7 and result.stdout == b''
