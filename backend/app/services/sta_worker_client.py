"""Bounded host transport for the isolated OpenSTA worker."""
import json
import os
import re
import subprocess
import uuid

from ..sta_worker import MAX_INPUT_BYTES, OPENSTA_COMMIT, PROTOCOL
from .report_import import parse_opensta, unique_object, reject_constant, finite_json_float


class StaWorkerError(RuntimeError):
    pass


def configured_image():
    image = os.environ.get('SIGNOFF_STA_WORKER_IMAGE', 'signoff-sta-worker:d97587f')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/:@-]{0,255}', image):
        raise StaWorkerError('Invalid STA worker image configuration.')
    return image


def run_sta(netlist, liberty, sdc, top_module):
    request = {'protocol': PROTOCOL, 'request': {'netlist': netlist, 'liberty': liberty, 'sdc': sdc, 'top_module': top_module}}
    payload = json.dumps(request, ensure_ascii=False).encode()
    if len(payload) > MAX_INPUT_BYTES:
        raise StaWorkerError('STA worker input limit exceeded.')
    image = configured_image()
    inspected = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', image], capture_output=True, timeout=10)
    image_id = inspected.stdout.decode(errors='replace').strip()
    if inspected.returncode or not re.fullmatch(r'sha256:[0-9a-f]{64}', image_id):
        raise StaWorkerError('STA worker image is unavailable.')
    name = 'signoff-sta-job-' + uuid.uuid4().hex
    command = ['docker', 'run', '--pull', 'never', '--rm', '--name', name, '--label', 'signoff.sta-worker=1',
               '--network', 'none', '--read-only', '--user', '65534:65534', '--cap-drop', 'ALL',
               '--security-opt', 'no-new-privileges:true', '--memory', '2g', '--memory-swap', '2g',
               '--cpus', '2', '--pids-limit', '64', '--tmpfs', '/tmp:rw,nosuid,nodev,noexec,size=128m',
               '--log-driver', 'none', '-i', image_id]
    try:
        completed = subprocess.run(command, input=payload, capture_output=True, timeout=250)
    except (OSError, subprocess.TimeoutExpired) as error:
        subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        raise StaWorkerError('STA worker deadline exceeded or could not start.') from error
    if completed.returncode:
        raise StaWorkerError((completed.stderr.decode(errors='replace')[-2000:] or 'STA worker failed.').strip())
    try:
        result = json.loads(completed.stdout.decode(), object_pairs_hook=unique_object,
                            parse_constant=reject_constant, parse_float=finite_json_float)
        if result['protocol'] != PROTOCOL or result['opensta_commit'] != OPENSTA_COMMIT:
            raise ValueError()
        parsed = parse_opensta(result['report'])
    except (ValueError, KeyError, UnicodeError, RecursionError, json.JSONDecodeError) as error:
        raise StaWorkerError('Invalid STA worker response.') from error
    return result, parsed, image_id
