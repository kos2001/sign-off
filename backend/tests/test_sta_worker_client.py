import json
import sys
import threading
import time

import pytest

from app.services import sta_worker_client as worker


def result():
    return {'protocol': worker.PROTOCOL, 'report': json.dumps({'checks': []}), 'log': 'done',
            'opensta_commit': worker.OPENSTA_COMMIT,
            'inputs': {kind: {'sha256': character * 64, 'byte_length': 1}
                       for kind, character in [('netlist', '1'), ('liberty', '2'), ('sdc', '3')]}}


@pytest.fixture
def docker(tmp_path, monkeypatch):
    marker = tmp_path / 'operations'
    binary = tmp_path / 'docker'
    binary.write_text(f'''#!{sys.executable}
import json,os,sys,time
args=sys.argv[1:]
scenario=os.environ.get('STA_WORKER_TEST_SCENARIO','valid')
if args[0]=='image':
 print('sha256:'+'a'*64)
elif args[0]=='container':
 print('error: no such container: '+args[-1],file=sys.stderr); sys.exit(1)
elif args[0]=='rm':
 with open({str(marker)!r},'a') as f: f.write('removed '+args[-1]+'\\n')
else:
 name=args[args.index('--name')+1]
 with open({str(marker)!r},'a') as f: f.write('started '+name+'\\n')
 sys.stdin.buffer.read()
 if scenario=='stdout_flood':
  sys.stdout.write('x'*65536); sys.stdout.flush(); time.sleep(30)
 elif scenario=='stderr_flood':
  sys.stderr.write('x'*65536); sys.stderr.flush(); time.sleep(30)
 elif scenario=='hang':
  time.sleep(30)
 elif scenario=='exit_error':
  print('bounded diagnostic',file=sys.stderr); sys.exit(3)
 else:
  print(json.dumps({result()!r}))
''')
    binary.chmod(0o700)
    monkeypatch.setenv('PATH', str(tmp_path))
    return marker


def assert_removed(marker):
    rows = marker.read_text().splitlines()
    assert rows[0].replace('started ', '') == rows[-1].replace('removed ', '')


def test_success_is_bounded_and_records_image(docker):
    raw, parsed, image = worker.run_sta('n', 'l', 's', 'top')
    assert parsed['metrics']['reported_paths'] == 0
    assert raw['opensta_commit'] == worker.OPENSTA_COMMIT
    assert image == 'sha256:' + 'a' * 64
    assert_removed(docker)


@pytest.mark.parametrize('scenario,limit,message', [
    ('stdout_flood', 'MAX_OUTPUT_BYTES', 'output limit'),
    ('stderr_flood', 'MAX_DIAGNOSTIC_BYTES', 'diagnostic limit'),
])
def test_output_flood_is_stopped_and_cleaned(docker, monkeypatch, scenario, limit, message):
    monkeypatch.setenv('STA_WORKER_TEST_SCENARIO', scenario)
    monkeypatch.setattr(worker, limit, 1024)
    started = time.monotonic()
    with pytest.raises(worker.StaWorkerError, match=message):
        worker.run_sta('n', 'l', 's', 'top')
    assert time.monotonic() - started < 3
    assert_removed(docker)


def test_deadline_stops_process_group_and_cleans_container(docker, monkeypatch):
    monkeypatch.setenv('STA_WORKER_TEST_SCENARIO', 'hang')
    monkeypatch.setattr(worker, 'TIMEOUT_SECONDS', 0.2)
    started = time.monotonic()
    with pytest.raises(worker.StaWorkerError, match='deadline'):
        worker.run_sta('n', 'l', 's', 'top')
    assert time.monotonic() - started < 2
    assert_removed(docker)


def test_cancellation_stops_process_group_and_cleans_container(docker, monkeypatch):
    monkeypatch.setenv('STA_WORKER_TEST_SCENARIO', 'hang')
    cancel = threading.Event()
    def cancel_after_start():
        deadline = time.monotonic() + 2
        while not docker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        cancel.set()
    thread = threading.Thread(target=cancel_after_start)
    thread.start()
    try:
        with pytest.raises(worker.StaWorkerError, match='cancelled'):
            worker.run_sta('n', 'l', 's', 'top', cancel=cancel)
    finally:
        thread.join(timeout=2)
    assert_removed(docker)


def test_nonzero_worker_exit_never_returns_result(docker, monkeypatch):
    monkeypatch.setenv('STA_WORKER_TEST_SCENARIO', 'exit_error')
    with pytest.raises(worker.StaWorkerError, match='bounded diagnostic'):
        worker.run_sta('n', 'l', 's', 'top')
    assert_removed(docker)


def test_worker_command_has_ownership_and_resource_boundaries(monkeypatch):
    monkeypatch.setenv('SIGNOFF_RTL_WORKER_OWNER', 'sta-test-owner')
    command = worker.worker_command('signoff-sta-job-' + 'a' * 32, 'sha256:' + 'b' * 64)
    joined = ' '.join(command)
    for value in ['--network none', '--read-only', '--cap-drop ALL', '--memory 2g', '--pids-limit 64',
                  'signoff.sta-worker=1', 'signoff.rtl-owner=sta-test-owner', 'signoff.rtl-lease-seconds=360']:
        assert value in joined
