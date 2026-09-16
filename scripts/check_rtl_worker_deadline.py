"""Verify worker-local expiry, including loss of its host Docker client."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.services.rtl.worker_client import worker_command, remove_container
from app.rtl_worker import PROTOCOL

IMAGE = sys.argv[1] if len(sys.argv) > 1 else 'signoff-rtl-worker:local'
os.environ['SIGNOFF_SIMULATION_MODE'] = 'trusted_local'
payload = json.dumps({'protocol': PROTOCOL, 'request': {'code': 'module top; endmodule',
                     'testbench': 'module tb; initial forever #1; endmodule', 'testbench_top': 'tb'}}).encode()


def command(name, seconds=3):
    return [arg.replace('SIGNOFF_RTL_WORKER_DEADLINE_SECONDS=300', f'SIGNOFF_RTL_WORKER_DEADLINE_SECONDS={seconds}')
            for arg in worker_command(name, IMAGE)]


name = 'signoff-rtl-deadline-' + uuid.uuid4().hex
try:
    completed = subprocess.run(command(name), input=payload, capture_output=True, timeout=10)
    assert completed.returncode == 124, (completed.returncode, completed.stderr)
    events = [json.loads(line) for line in completed.stdout.splitlines()]
    assert any(event.get('stage') == 'simulate' for event in events)
    assert not any(event['event'] == 'result' for event in events)
finally:
    remove_container(name)

name = 'signoff-rtl-deadline-' + uuid.uuid4().hex
process = subprocess.Popen(command(name, 8), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    process.stdin.write(payload)
    process.stdin.close()
    ready_deadline = time.monotonic() + 5
    while True:
        top = subprocess.run(['docker', 'top', name, '-eo', 'pid,comm'], capture_output=True, timeout=2)
        if top.returncode == 0 and b'vvp' in top.stdout:
            break
        if time.monotonic() > ready_deadline:
            raise AssertionError(f'simulation did not start: {top.stdout!r} {top.stderr!r}')
        time.sleep(0.05)
    process.kill()  # No client finally block or container cleanup runs here.
    process.wait(timeout=2)
    running = subprocess.run(['docker', 'inspect', '--format', '{{.State.Running}}', name], capture_output=True, timeout=2)
    assert running.returncode == 0 and running.stdout.strip() == b'true'
    expires = time.monotonic() + 12
    while True:
        inspected = subprocess.run(['docker', 'container', 'inspect', name], capture_output=True, timeout=2)
        if inspected.returncode and any(f'no such {kind}: {name}'.encode() in inspected.stderr.lower() for kind in ['object', 'container']):
            break
        if time.monotonic() > expires:
            raise AssertionError('worker survived its independent deadline')
        time.sleep(0.1)
finally:
    if process.poll() is None:
        process.kill()
    process.wait()
    process.stdin.close()
    remove_container(name)

print(json.dumps({'result': 'PASS', 'checks': ['worker exits 124 without final result',
      'actual vvp running after host client SIGKILL', 'container expires without host cleanup'], 'image': IMAGE}))
