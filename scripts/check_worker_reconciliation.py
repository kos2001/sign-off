"""Reconcile only synthetic Docker fixtures using a virtual expiry reference."""
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.worker_maintenance import reconcile
from app.services.rtl.worker_client import remove_container

owner = 'reaper-qa-' + uuid.uuid4().hex
os.environ['SIGNOFF_RTL_WORKER_OWNER'] = owner
image = sys.argv[1] if len(sys.argv) > 1 else 'signoff-rtl-worker:local'
created = []
checkpoint_directory = tempfile.TemporaryDirectory(prefix='signoff-reaper-checkpoint-')
os.environ['SIGNOFF_RTL_REAPER_STATE_DIR'] = checkpoint_directory.name


def fixture(scope, lease=True):
    command = ['docker', 'run', '-d', '--name', 'signoff-rtl-job-' + uuid.uuid4().hex,
               '--network', 'none', '--read-only', '--user', '65534:65534', '--cap-drop', 'ALL',
               '--security-opt', 'no-new-privileges:true', '--memory', '64m', '--pids-limit', '16',
               '--label', 'signoff.rtl-worker=1', '--label', 'signoff.rtl-owner=' + scope]
    if lease:
        command += ['--label', 'signoff.rtl-lease-seconds=360']
    command += ['--entrypoint', 'sleep', image, '3600']
    identifier = subprocess.check_output(command, text=True, timeout=15).strip()
    created.append(identifier)
    return identifier


def inspect(identifier):
    result = subprocess.run(['docker', 'container', 'inspect', identifier], capture_output=True, text=True, timeout=10)
    return json.loads(result.stdout)[0] if result.returncode == 0 else None


try:
    expired = fixture(owner)
    timestamp = datetime.fromisoformat(inspect(expired)['Created'].replace('Z', '+00:00'))
    subprocess.run(['docker', 'pause', expired], check=True, capture_output=True, timeout=10)
    time.sleep(2)  # Separate real creation timestamps without waiting six minutes.
    active, foreign, legacy = fixture(owner), fixture(owner + '-other'), fixture(owner, lease=False)
    extra_legacy = [fixture(owner, lease=False) for _ in range(3)]
    reference = timestamp + timedelta(seconds=361)
    preview = reconcile(now=reference)
    assert [item['id'] for item in preview['items']] == [expired], preview
    assert inspect(expired)['State']['Paused'] is True
    # Use small pages to exercise real Docker inventory continuation without
    # creating hundreds of containers on the developer's machine.
    # Every pass uses a new process, recovering the persisted inventory.
    program = '''
import json, sys
from datetime import datetime
from app import worker_maintenance as maintenance
maintenance.SCAN_LIMIT = 2
print(json.dumps(maintenance.persistent_reconcile(limit=2, now=datetime.fromisoformat(sys.argv[1]))))
'''
    applied_items, passes = [], 0
    while True:
        applied = json.loads(subprocess.check_output([sys.executable, '-c', program, reference.isoformat()],
                                                    cwd=ROOT / 'backend', text=True, timeout=40))
        passes += 1
        applied_items.extend(applied['items'])
        if not applied['remaining']:
            break
        assert passes < 10
    assert passes >= 3
    assert [item['id'] for item in applied_items] == [expired], applied_items
    assert inspect(expired) is None
    assert all(inspect(identifier) is not None for identifier in [active, foreign, legacy, *extra_legacy])
    print(json.dumps({'result': 'PASS', 'checks': ['preview does not mutate', 'expired paused job removed',
          'fresh owned job retained', 'other owner retained', 'legacy metadata retained',
          'old job reached across multiple bounded passes', 'checkpoint resumed in new processes'],
          'passes': passes, 'virtual_reference': reference.isoformat()}))
finally:
    for identifier in created:
        remove_container(identifier)
    checkpoint_directory.cleanup()
