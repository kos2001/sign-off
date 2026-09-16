import json
from pathlib import Path
import sys
import threading
import time
import uuid

import pytest

from app.services.rtl import worker_client as worker


def events():
    result = dict(verdict='SIGNED_OFF', score=100, grade='A', module='top',
                  stages=[dict(name=name, status='pass', gating=True, detail='ok') for name in worker.STAGES],
                  rules=[], suggestions=[], simulation={})
    output = []
    for name in worker.STAGES:
        output += [dict(event='stage_start', stage=name), dict(event='stage_done', stage=name, status='pass', detail='ok')]
    return [{**event, 'protocol': worker.PROTOCOL} for event in output + [dict(event='result', result=result)]]


@pytest.fixture
def docker(tmp_path, monkeypatch):
    marker = tmp_path / 'operations'
    binary = tmp_path / 'docker'
    binary.write_text(f'''#!{sys.executable}
import os,sys,json,time
args=sys.argv[1:]
scenario=os.environ.get('WORKER_TEST_SCENARIO','valid')
if args[0]=='image':
 print('sha256:'+'a'*64)
elif args[0]=='container':
 print('daemon unavailable' if scenario=='cleanup_error' else 'error: no such container: '+args[-1],file=sys.stderr)
 sys.exit(1)
elif args[0]=='rm':
 with open({str(marker)!r},'a') as f: f.write('removed '+args[-1]+'\\n')
 if scenario=='cleanup_error':
  print('daemon unavailable',file=sys.stderr); sys.exit(1)
else:
 with open({str(marker)!r},'a') as f: f.write('started '+args[args.index('--name')+1]+'\\n')
 sys.stdin.buffer.read()
 rows={events()!r}
 if scenario=='flood':
  print('x'*4096,flush=True); time.sleep(30)
 elif scenario=='bad':
  print('{{"protocol":"wrong"}}',flush=True)
 elif scenario=='hang':
  print(json.dumps(rows[0]),flush=True); time.sleep(30)
 else:
  for row in rows: print(json.dumps(row),flush=True)
  if scenario=='exit_error': sys.exit(3)
''')
    binary.chmod(0o700)
    monkeypatch.setenv('PATH', str(tmp_path))
    monkeypatch.setenv('SIGNOFF_RTL_EXECUTION', 'container')
    return marker


def assert_removed(marker):
    rows = marker.read_text().splitlines()
    assert rows[0].replace('started ', '') == rows[-1].replace('removed ', '')


def test_daemon_dns_failure_is_not_treated_as_container_absence(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(worker.subprocess, 'run', lambda *args, **kwargs:
                        SimpleNamespace(returncode=1, stderr=b'cannot connect: lookup daemon: no such host'))
    with pytest.raises(worker.WorkerError, match='cleanup'):
        worker.remove_container('signoff-rtl-job-test')


def test_success_waits_for_exit_and_records_image(docker):
    output = list(worker.stream_worker('module top; endmodule'))
    assert len(output) == 9 and output[-1]['event'] == 'result'
    assert output[-1]['result']['execution'] == {'backend': 'container', 'image_id': 'sha256:' + 'a' * 64}
    assert_removed(docker)


@pytest.mark.parametrize('scenario', ['exit_error', 'bad', 'flood', 'cleanup_error'])
def test_failure_never_releases_result_and_removes_own_container(docker, monkeypatch, scenario):
    monkeypatch.setenv('WORKER_TEST_SCENARIO', scenario)
    if scenario == 'flood':
        monkeypatch.setattr(worker, 'MAX_OUTPUT_BYTES', 1024)
    received = []
    with pytest.raises(worker.WorkerError):
        for event in worker.stream_worker('module top; endmodule'):
            received.append(event)
    assert all(event['event'] != 'result' for event in received)
    assert_removed(docker)


@pytest.mark.parametrize('cancelled', [False, True])
def test_hung_worker_deadline_and_cancellation(docker, monkeypatch, cancelled):
    monkeypatch.setenv('WORKER_TEST_SCENARIO', 'hang')
    monkeypatch.setattr(worker, 'TIMEOUT_SECONDS', 3 if cancelled else 1)
    cancel = threading.Event()
    stream = worker.stream_worker('module top; endmodule', cancel=cancel)
    assert next(stream)['event'] == 'stage_start'
    if cancelled:
        cancel.set()
    started = time.monotonic()
    with pytest.raises(worker.WorkerError):
        list(stream)
    assert time.monotonic() - started < 2
    assert_removed(docker)


def test_generator_close_removes_running_container(docker, monkeypatch):
    monkeypatch.setenv('WORKER_TEST_SCENARIO', 'hang')
    stream = worker.stream_worker('module top; endmodule')
    assert next(stream)['event'] == 'stage_start'
    stream.close()
    assert_removed(docker)


@pytest.mark.parametrize('change', ['order', 'duplicate', 'mismatch', 'nonfinite', 'fields'])
def test_protocol_rejects_untrustworthy_results(change):
    rows = events()
    if change == 'order':
        rows[0]['stage'] = 'simulate'
    elif change == 'duplicate':
        rows.append(rows[-1])
    elif change == 'mismatch':
        rows[-1]['result']['stages'][0]['status'] = 'fail'
    elif change == 'nonfinite':
        rows[-1]['result']['simulation'] = {'value': float('inf')}
    else:
        del rows[-1]['result']['rules']
    sequence = worker.EventSequence()
    with pytest.raises(worker.WorkerError):
        for row in rows:
            sequence.accept(json.dumps(row).encode())


@pytest.mark.parametrize('streaming', [False, True])
def test_api_worker_failure_does_not_save_run(client, docker, monkeypatch, streaming):
    monkeypatch.setenv('WORKER_TEST_SCENARIO', 'exit_error')
    project = client.post('/projects', json={'name': 'worker failure ' + uuid.uuid4().hex, 'foundry': 'QA', 'process_node': '5nm'}).json()['id']
    response = client.post('/analysis/rtl-signoff' + ('/stream' if streaming else ''),
                           json={'code': 'module top; endmodule', 'project_id': project})
    if streaming:
        output = [json.loads(line) for line in response.text.splitlines()]
        assert output[-1]['event'] == 'error' and not any(row['event'] == 'result' for row in output)
    else:
        assert response.status_code == 503
    assert client.get(f'/projects/{project}/runs').json() == []
    assert_removed(docker)


@pytest.mark.parametrize('streaming', [False, True])
def test_api_saves_verified_worker_evidence(client, docker, streaming):
    project = client.post('/projects', json={'name': 'worker success ' + uuid.uuid4().hex, 'foundry': 'QA', 'process_node': '5nm'}).json()['id']
    response = client.post('/analysis/rtl-signoff' + ('/stream' if streaming else ''),
                           json={'code': 'module top; endmodule', 'project_id': project})
    result = json.loads(response.text.splitlines()[-1])['result'] if streaming else response.json()
    assert response.status_code == 200 and result['run_id']
    evidence = client.get(f"/runs/{result['run_id']}/evidence").json()
    assert evidence['result']['execution']['image_id'] == 'sha256:' + 'a' * 64
    assert_removed(docker)


@pytest.mark.parametrize('transcripts', [
    {'lint': {'command': ['verilator'], 'exit_code': 0, 'error': None, 'log': 'x' * (128 * 1024 + 1)}},
    {'lint': {'command': 'verilator', 'exit_code': 0, 'error': None, 'log': ''}},
    {'lint': {'command': ['verilator'], 'exit_code': True, 'error': None, 'log': ''}},
    {'other': None},
])
def test_worker_rejects_invalid_transcripts(transcripts):
    rows = events()
    rows[-1]['result']['tool_runs'] = transcripts
    sequence = worker.EventSequence()
    for row in rows[:-1]:
        sequence.accept(json.dumps(row).encode())
    with pytest.raises(worker.WorkerError):
        sequence.accept(json.dumps(rows[-1]).encode())


def test_worker_accepts_bounded_transcripts_and_legacy_missing_records():
    for records in [{}, {'lint': None, 'width': None, 'synthesize': {
        'command': ['yosys', '-p', 'stat'], 'exit_code': 0, 'error': None, 'log': 'reported output'}}]:
        rows = events()
        rows[-1]['result']['tool_runs'] = records
        sequence = worker.EventSequence()
        for row in rows:
            sequence.accept(json.dumps(row).encode())
        assert sequence.result['tool_runs'] == records
