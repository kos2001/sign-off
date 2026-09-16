"""Real Docker worker + service API checks, using a disposable SQLite database."""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def fixture(filename, name):
    for node in ast.parse((ROOT / 'backend/tests' / filename).read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise RuntimeError(name)


with tempfile.TemporaryDirectory(prefix='signoff-worker-api-') as directory:
    os.environ.update(SIGNOFF_DATABASE_URL=f'sqlite:///{directory}/qa.db', SIGNOFF_AUTH_MODE='local',
                      SIGNOFF_RTL_EXECUTION='container', SIGNOFF_SIMULATION_MODE='trusted_local',
                      SIGNOFF_RTL_SLOT_DIR=f'{directory}/slots')
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.services.rtl import worker_client as worker
    names = []
    command = worker.worker_command
    def capture(name, image):
        names.append(name)
        return command(name, image)
    worker.worker_command = capture
    code, testbench = fixture('test_rtl_signoff.py', 'GOOD_RTL'), fixture('test_rtl_simulation.py', 'TB')
    with TestClient(create_app()) as client:
        project = client.post('/projects', json={'name': 'container API check', 'foundry': 'QA', 'process_node': '5nm'}).json()['id']
        payload = {'code': code, 'testbench': testbench, 'testbench_top': 'tb', 'project_id': project}
        for streaming in [False, True]:
            response = client.post('/analysis/rtl-signoff' + ('/stream' if streaming else ''), json=payload)
            assert response.status_code == 200, response.text
            result = json.loads(response.text.splitlines()[-1])['result'] if streaming else response.json()
            assert result['verdict'] == 'SIGNED_OFF' and result['run_id']
            evidence = client.get(f"/runs/{result['run_id']}/evidence").json()
            assert evidence['result']['execution']['backend'] == 'container'
            assert evidence['result']['execution']['image_id'].startswith('sha256:')
            records = evidence['result']['tool_runs']
            assert set(records) == {'lint', 'width', 'synthesize'}
            assert records == result['tool_runs']
            for name, record in records.items():
                assert record['exit_code'] == 0 and record['error'] is None, (name, record)
                assert len(record['log'].encode()) <= 128 * 1024
                assert record['command'][0] == ('yosys' if name == 'synthesize' else 'verilator')
            artifact = result['netlist']
            assert artifact == evidence['result']['netlist']
            assert hashlib.sha256(artifact['text'].encode()).hexdigest() == artifact['sha256']
            assert len(artifact['text'].encode()) == artifact['byte_length']
            downloaded = client.get(f"/runs/{result['run_id']}/evidence/netlist")
            assert downloaded.status_code == 200 and downloaded.content == artifact['text'].encode()
            assert downloaded.headers['x-artifact-sha256'] == artifact['sha256']
            assert 'Yosys' in records['synthesize']['log']
            synth = next(stage for stage in result['stages'] if stage['name'] == 'synthesize')
            assert 'flops=4' in synth['detail'] and 'latches=0' in synth['detail'], synth
            assert 'cells=0 ' not in synth['detail'], synth
            assert '-Wno-WIDTHTRUNC' not in records['width']['command']
        hierarchy_code = fixture('test_rtl_process.py', 'HIERARCHY_RTL')
        for streaming in [False, True]:
            response = client.post('/analysis/rtl-signoff' + ('/stream' if streaming else ''),
                                   json={'code': hierarchy_code, 'top_module': 'chip', 'project_id': project})
            assert response.status_code == 200, response.text
            result = json.loads(response.text.splitlines()[-1])['result'] if streaming else response.json()
            synth = next(stage for stage in result['stages'] if stage['name'] == 'synthesize')
            assert synth['status'] == 'pass' and 'cells=10 flops=10 latches=0' in synth['detail'], synth
            assert 'scope=selected design hierarchy' in synth['detail']
            evidence = client.get(f"/runs/{result['run_id']}/evidence").json()
            assert evidence['result']['stages'] == result['stages']
            assert evidence['result']['tool_runs'] == result['tool_runs']
            assert '"modules"' in result['tool_runs']['synthesize']['log']
            assert '"design"' in result['tool_runs']['synthesize']['log']
        invalid = fixture('test_rtl_structure.py', 'INVALID_DESIGNS')
        loop = fixture('test_rtl_structure.py', 'CROSS_HIERARCHY_LOOP')
        invalid['cross_hierarchy_loop'] = (loop, 'logic loop')
        invalid['kept_cross_hierarchy_loop'] = (
            loop.replace('module inv', '(* keep_hierarchy *) module inv')
                .replace('module gate', '(* keep_hierarchy *) module gate')
                .replace('inv u', '(* keep_hierarchy *) inv u')
                .replace('gate v', '(* keep_hierarchy *) gate v'), 'logic loop')
        for case, (invalid_code, diagnostic) in invalid.items():
            for streaming in [False, True]:
                response = client.post('/analysis/rtl-signoff' + ('/stream' if streaming else ''),
                                       json={'code': invalid_code, 'top_module': 'top', 'project_id': project})
                assert response.status_code == 200, response.text
                result = json.loads(response.text.splitlines()[-1])['result'] if streaming else response.json()
                synth = next(stage for stage in result['stages'] if stage['name'] == 'synthesize')
                assert result['verdict'] == 'REJECTED' and synth['status'] == 'fail', (case, result)
                assert 'cells=unknown' in synth['detail']
                assert result['netlist'] is None
                assert client.get(f"/runs/{result['run_id']}/evidence/netlist").status_code == 409
                record = result['tool_runs']['synthesize']
                assert record['exit_code'] != 0 and diagnostic in record['log'], (case, record)
                evidence = client.get(f"/runs/{result['run_id']}/evidence").json()
                assert evidence['result']['stages'] == result['stages']
                assert evidence['result']['tool_runs'] == result['tool_runs']
        image = os.environ.get('SIGNOFF_RTL_WORKER_IMAGE')
        os.environ['SIGNOFF_RTL_WORKER_IMAGE'] = 'signoff-missing:' + uuid.uuid4().hex
        try:
            assert client.post('/analysis/rtl-signoff', json=payload).status_code == 503
            rejected = client.post('/analysis/rtl-signoff/stream', json=payload)
            assert json.loads(rejected.text)['event'] == 'error'
        finally:
            if image is None:
                del os.environ['SIGNOFF_RTL_WORKER_IMAGE']
            else:
                os.environ['SIGNOFF_RTL_WORKER_IMAGE'] = image
        assert len(client.get(f'/projects/{project}/runs').json()) == 4 + 2 * len(invalid)
        cancel = threading.Event()
        running = worker.stream_worker(code, testbench, 'tb', cancel=cancel)
        assert next(running)['event'] == 'stage_start'
        cancel.set()
        try:
            list(running)
        except worker.WorkerError:
            pass
        else:
            raise AssertionError('cancelled job released a result')
        worker.TIMEOUT_SECONDS = 2
        try:
            list(worker.stream_worker(code, 'module tb; initial forever #1; endmodule', 'tb'))
        except worker.WorkerError as error:
            assert 'deadline' in str(error)
        else:
            raise AssertionError('hung job completed instead of timing out')
    for name in names:
        inspected = subprocess.run(['docker', 'inspect', name], capture_output=True, text=True, timeout=10)
        absent = any(f'no such {kind}: {name}' in inspected.stderr.lower() for kind in ['object', 'container'])
        assert inspected.returncode != 0 and absent, name
    print(json.dumps({'result': 'PASS', 'checks': ['sync and stream API', 'saved immutable image evidence',
          'missing image fails without saving', 'cancellation removes container', 'deadline removes container'],
          'containers_removed': len(names)}))
