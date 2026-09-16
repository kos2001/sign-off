"""Integration check for the one-job RTL worker; requires a locally built image."""
import ast
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
IMAGE = sys.argv[1] if len(sys.argv) > 1 else 'signoff-rtl-worker:local'
PROTOCOL = 'signoff/rtl-worker/v1'


def fixture(filename, name):
    for node in ast.parse((ROOT / 'backend/tests' / filename).read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise RuntimeError(f'Missing fixture: {name}')


def container(payload=None, *, simulation=False, probe=None):
    name = 'signoff-worker-check-' + uuid.uuid4().hex
    command = ['docker', 'run', '--rm', '--name', name, '--network', 'none', '--read-only',
               '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
               '--memory', '1g', '--memory-swap', '1g', '--cpus', '1', '--pids-limit', '64',
               '--tmpfs', '/tmp:rw,nosuid,nodev,noexec,size=128m', '-i']
    if simulation:
        command += ['-e', 'SIGNOFF_SIMULATION_MODE=trusted_local']
    if probe:
        command += ['--entrypoint', 'python', IMAGE, '-c', probe]
    else:
        command += [IMAGE]
    try:
        return subprocess.run(command, input=json.dumps(payload) if payload is not None else '',
                              capture_output=True, text=True, timeout=240)
    finally:
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=15)


code, testbench = fixture('test_rtl_signoff.py', 'GOOD_RTL'), fixture('test_rtl_simulation.py', 'TB')
for mode, expected in [('disabled', 'CONDITIONAL'), ('enabled', 'SIGNED_OFF'), ('failing', 'REJECTED')]:
    request = {'code': code, 'testbench': testbench if mode != 'failing' else testbench.replace('SIGNOFF_TEST_PASS', 'NOT_PASS'), 'testbench_top': 'tb'}
    completed = container({'protocol': PROTOCOL, 'request': request}, simulation=mode != 'disabled')
    assert completed.returncode == 0, completed.stderr
    events = [json.loads(line) for line in completed.stdout.splitlines()]
    assert all(event['protocol'] == PROTOCOL for event in events)
    assert [event['stage'] for event in events if event['event'] == 'stage_start'] == ['lint', 'design', 'synthesize', 'simulate']
    assert events[-1]['event'] == 'result' and events[-1]['result']['verdict'] == expected, events[-1]
    assert len([event for event in events if event['event'] == 'result']) == 1
invalid = container({'protocol': PROTOCOL, 'request': {'code': code, 'project_id': 1}})
assert invalid.returncode == 2 and invalid.stdout == ''
probe = container(probe='''import os,socket,pathlib,errno
assert os.getuid() != 0
status=pathlib.Path('/proc/self/status').read_text()
assert 'NoNewPrivs:\\t1' in status and 'CapEff:\\t0000000000000000' in status
try:
 open('/workspace/should-not-write','w')
except OSError as e:
 assert e.errno in (errno.EROFS,errno.EACCES)
else:
 raise AssertionError('root filesystem was writable')
assert not pathlib.Path('/workspace/backend/signoff.db').exists()
s=socket.socket(); s.settimeout(1)
try:
 s.connect(('198.51.100.1',80))
except OSError:
 pass
else:
 raise AssertionError('external network was reachable')
finally:
 s.close()
print('isolation checks passed')
''')
assert probe.returncode == 0, probe.stderr
print(json.dumps({'result': 'PASS', 'checks': ['disabled simulation', 'signed-off fixture', 'failed testbench',
      'ordered events', 'invalid job rejected', 'nonroot', 'no capabilities or privilege gain',
      'readonly root', 'no application database', 'no external network'], 'image': IMAGE}))
