import hashlib
import json
import threading
import time
import uuid

from app.db import SessionLocal
from app.models import StaBatchExecution, StaBatchExecutionItem, StaBatchInputArtifact, Stage
from app.services.report_import import parse_opensta
from app.services.sta_worker_client import StaWorkerError


def project(client):
    return client.post('/projects', json={'name': f'detached-{uuid.uuid4()}',
        'process_node': '5nm', 'foundry': 'QA'}).json()['id']


def worker_result():
    report = json.dumps({'checks': [{'type': 'check', 'path_type': 'max', 'path_group': 'clk',
        'startpoint': 'u1/Q', 'endpoint': 'u2/D', 'source_path': [{'pin': 'u1/Q'}, {'pin': 'u2/D'}],
        'slack': 2e-11}]})
    values = {'netlist': 'module top; endmodule', 'liberty': 'library(x) {}', 'sdc': 'create_clock -period 1 clk'}
    inputs = {name: {'sha256': hashlib.sha256(value.encode()).hexdigest(),
                     'byte_length': len(value.encode())} for name, value in values.items()}
    return {'protocol': 'signoff/sta-worker/v1', 'report': report, 'log': 'OpenSTA complete',
            'opensta_commit': 'd97587f669b4f169be7132346df70e7d634500c3',
            'inputs': inputs}, parse_opensta(report), 'sha256:' + 'a' * 64


def payload(pid, scenarios=2):
    return {'project_id': pid, 'stage': 'routing', 'top_module': 'top',
            'design_revision': 'detached-rev', 'netlist': 'module top; endmodule',
            'scenarios': [{'scenario': f'corner-{index}', 'liberty': 'library(x) {}',
                           'sdc': 'create_clock -period 1 clk'} for index in range(scenarios)]}


def wait_terminal(client, pid, batch_id, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = client.get(f'/projects/{pid}/sta-batches/{batch_id}').json()
        if row['status'] not in {'queued', 'running'}:
            return row
        time.sleep(0.02)
    raise AssertionError('detached batch did not reach a terminal state')


def test_detached_batch_survives_request_and_records_artifacts(client, monkeypatch):
    pid = project(client)
    monkeypatch.setattr('app.services.sta_batch_queue.run_sta', lambda *args, **kwargs: worker_result())
    response = client.post('/analysis/sta-signoff/batch', json=payload(pid))
    assert response.status_code == 202, response.text
    receipt = response.json()
    assert receipt['status'] in {'queued', 'running', 'completed'}
    assert 'netlist' not in response.text and 'library(x)' not in response.text
    result = wait_terminal(client, pid, receipt['id'])
    assert result['status'] == 'completed' and result['started_at'] and result['finished_at']
    assert all(item['status'] == 'completed' and item['run_id'] for item in result['items'])
    assert all(item['started_at'] and item['finished_at'] for item in result['items'])
    assert [event['kind'] for event in result['events']] == [
        'submitted', 'started', 'scenario_started', 'scenario_completed',
        'scenario_started', 'scenario_completed', 'finalized',
    ]
    assert all(event['actor'] for event in result['events'])
    with SessionLocal() as db:
        artifacts = db.query(StaBatchInputArtifact).filter_by(batch_id=receipt['id']).all()
        assert len(artifacts) == 5
        assert all(item.sha256 == hashlib.sha256(item.content_text.encode()).hexdigest() for item in artifacts)


def test_terminal_batch_retry_is_idempotent_and_preserves_lineage(client, monkeypatch):
    pid = project(client)
    monkeypatch.setattr('app.services.sta_batch_queue.run_sta', lambda *args, **kwargs: worker_result())
    source = client.post('/analysis/sta-signoff/batch', json=payload(pid, 1)).json()
    wait_terminal(client, pid, source['id'])
    key = str(uuid.uuid4())
    first = client.post(f"/projects/{pid}/sta-batches/{source['id']}/retry",
                        json={'request_key': key})
    second = client.post(f"/projects/{pid}/sta-batches/{source['id']}/retry",
                         json={'request_key': key})
    assert first.status_code == second.status_code == 202
    assert first.json()['id'] == second.json()['id']
    retried = wait_terminal(client, pid, first.json()['id'])
    assert retried['status'] == 'completed'
    assert retried['retry_of_batch_id'] == source['id'] and retried['attempt'] == 2
    with SessionLocal() as db:
        assert db.query(StaBatchExecution).filter_by(retry_request_key=key).count() == 1
        source_inputs = db.query(StaBatchInputArtifact).filter_by(batch_id=source['id']).all()
        retry_inputs = db.query(StaBatchInputArtifact).filter_by(batch_id=retried['id']).all()
        assert [(x.position, x.kind, x.sha256) for x in retry_inputs] == [
            (x.position, x.kind, x.sha256) for x in source_inputs]


def test_active_batch_cannot_be_retried(client):
    pid = project(client)
    with SessionLocal() as db:
        batch = StaBatchExecution(project_id=pid, stage=Stage.routing, top_module='top',
            design_revision='active', submitted_by='local', status='running',
            items=[StaBatchExecutionItem(position=0, scenario='busy', status='running')])
        db.add(batch)
        db.commit()
        batch_id = batch.id
    response = client.post(f'/projects/{pid}/sta-batches/{batch_id}/retry',
                           json={'request_key': str(uuid.uuid4())})
    assert response.status_code == 409


def test_retry_rejects_tampered_source_inputs_without_creating_attempt(client):
    pid = project(client)
    with SessionLocal() as db:
        batch = StaBatchExecution(project_id=pid, stage=Stage.routing, top_module='top',
            design_revision='bad-source', submitted_by='local', status='failed',
            items=[StaBatchExecutionItem(position=0, scenario='bad', status='failed')])
        db.add(batch)
        db.flush()
        db.add_all([
            StaBatchInputArtifact(batch_id=batch.id, position=-1, kind='netlist',
                content_text='module top; endmodule', sha256='0' * 64, byte_length=21),
            StaBatchInputArtifact(batch_id=batch.id, position=0, kind='liberty',
                content_text='lib', sha256=hashlib.sha256(b'lib').hexdigest(), byte_length=3),
            StaBatchInputArtifact(batch_id=batch.id, position=0, kind='sdc',
                content_text='sdc', sha256=hashlib.sha256(b'sdc').hexdigest(), byte_length=3),
        ])
        db.commit()
        batch_id = batch.id
    response = client.post(f'/projects/{pid}/sta-batches/{batch_id}/retry',
                           json={'request_key': str(uuid.uuid4())})
    assert response.status_code == 409
    with SessionLocal() as db:
        assert db.query(StaBatchExecution).filter_by(retry_of_batch_id=batch_id).count() == 0


def test_running_detached_batch_can_be_cancelled(client, monkeypatch):
    pid = project(client)
    started = threading.Event()

    def blocked(*args, cancel, **kwargs):
        started.set()
        if not cancel.wait(3):
            raise AssertionError('cancel signal was not delivered')
        raise StaWorkerError('STA worker cancelled.')

    monkeypatch.setattr('app.services.sta_batch_queue.run_sta', blocked)
    receipt = client.post('/analysis/sta-signoff/batch', json=payload(pid, 1)).json()
    assert started.wait(3)
    cancel = client.post(f"/projects/{pid}/sta-batches/{receipt['id']}/cancel")
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()['cancel_requested'] is True
    result = wait_terminal(client, pid, receipt['id'])
    assert result['status'] == 'cancelled'
    assert result['items'][0]['status'] == 'cancelled' and result['items'][0]['run_id'] is None
    assert [event['kind'] for event in result['events']] == [
        'submitted', 'started', 'scenario_started', 'cancel_requested',
        'scenario_cancelled', 'finalized',
    ]
    assert client.post(f"/projects/{pid}/sta-batches/{receipt['id']}/cancel").status_code == 409


def test_queued_detached_batch_can_be_cancelled(client):
    pid = project(client)
    with SessionLocal() as db:
        batch = StaBatchExecution(project_id=pid, stage=Stage.routing, top_module='top',
            design_revision='queued', submitted_by='local', status='queued',
            items=[StaBatchExecutionItem(position=0, scenario='waiting', status='pending')])
        db.add(batch)
        db.commit()
        batch_id = batch.id
    response = client.post(f'/projects/{pid}/sta-batches/{batch_id}/cancel')
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['status'] == 'cancelled' and result['cancel_requested'] is True
    assert result['items'][0]['status'] == 'cancelled' and result['finished_at']
    assert [event['kind'] for event in result['events']] == ['scenario_cancelled', 'finalized']


def test_detached_batch_rejects_tampered_stored_input(client, monkeypatch):
    from app.services.sta_batch_queue import execute_claimed
    pid = project(client)
    with SessionLocal() as db:
        batch = StaBatchExecution(project_id=pid, stage=Stage.routing, top_module='top',
            design_revision='tampered', submitted_by='local', status='running',
            items=[StaBatchExecutionItem(position=0, scenario='slow', status='pending')])
        db.add(batch)
        db.flush()
        db.add_all([
            StaBatchInputArtifact(batch_id=batch.id, position=-1, kind='netlist',
                content_text='module top; endmodule', sha256='0' * 64, byte_length=21),
            StaBatchInputArtifact(batch_id=batch.id, position=0, kind='liberty',
                content_text='lib', sha256=hashlib.sha256(b'lib').hexdigest(), byte_length=3),
            StaBatchInputArtifact(batch_id=batch.id, position=0, kind='sdc',
                content_text='sdc', sha256=hashlib.sha256(b'sdc').hexdigest(), byte_length=3),
        ])
        db.commit()
        batch_id = batch.id
    monkeypatch.setattr('app.services.sta_batch_queue.run_sta', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    execute_claimed(batch_id, threading.Event())
    result = client.get(f'/projects/{pid}/sta-batches/{batch_id}').json()
    assert result['status'] == 'failed' and result['items'][0]['status'] == 'failed'


def test_stale_worker_lease_is_finalized_without_reexecution(client, monkeypatch):
    from app.services.sta_batch_queue import reconcile_stale_batches
    from app.services.sta_execution import update_batch_item
    pid = project(client)
    with SessionLocal() as db:
        batch = StaBatchExecution(project_id=pid, stage=Stage.routing, top_module='top',
            design_revision='stale', submitted_by='local', status='running', worker_token='a' * 32,
            lease_expires_at=10, items=[
                StaBatchExecutionItem(position=0, scenario='done', status='completed'),
                StaBatchExecutionItem(position=1, scenario='lost', status='running'),
            ])
        db.add(batch)
        db.commit()
        batch_id = batch.id
    monkeypatch.setattr('app.services.sta_batch_queue.run_sta', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    reconcile_stale_batches(now=11)
    result = client.get(f'/projects/{pid}/sta-batches/{batch_id}').json()
    assert result['status'] == 'partial' and result['finished_at']
    assert result['items'][1]['status'] == 'failed'
    assert result['items'][1]['detail'] == 'Batch execution was interrupted.'
    assert [event['kind'] for event in result['events']] == ['scenario_failed', 'finalized']
    reconcile_stale_batches(now=11)
    assert len(client.get(f'/projects/{pid}/sta-batches/{batch_id}').json()['events']) == 2
    assert update_batch_item(batch_id, 1, 'completed', run_id=999) is False
    unchanged = client.get(f'/projects/{pid}/sta-batches/{batch_id}').json()
    assert unchanged['items'][1]['status'] == 'failed' and unchanged['items'][1]['run_id'] is None
    assert len(unchanged['events']) == 2
