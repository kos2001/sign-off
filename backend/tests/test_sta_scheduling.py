from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.db import SessionLocal
from app.models import StaBatchExecution, Stage
from app.services.rtl.admission import acquire_slot as acquire_rtl_slot
from app.services.sta_admission import acquire_slot as acquire_sta_slot, capacity
from app.services.sta_batch_queue import _claim_candidates


@pytest.fixture
def separate_pools(tmp_path, monkeypatch):
    monkeypatch.setenv('SIGNOFF_RTL_SLOT_DIR', str(tmp_path / 'rtl'))
    monkeypatch.setenv('SIGNOFF_STA_SLOT_DIR', str(tmp_path / 'sta'))
    monkeypatch.setenv('SIGNOFF_RTL_MAX_CONCURRENT', '1')
    monkeypatch.setenv('SIGNOFF_STA_MAX_CONCURRENT', '1')


def test_sta_and_rtl_capacity_pools_are_independent(separate_pools):
    with acquire_rtl_slot():
        with acquire_sta_slot():
            with pytest.raises(HTTPException) as full:
                acquire_sta_slot()
            assert full.value.status_code == 429
            assert full.value.detail == 'STA analysis capacity is full; retry shortly'
            assert full.value.headers['Retry-After'] == '5'


@pytest.mark.parametrize('path,batch', [
    ('/analysis/sta-signoff', False),
    ('/analysis/sta-signoff/stream', False),
    ('/analysis/sta-signoff/batch/stream', True),
])
def test_interactive_sta_endpoints_use_the_sta_pool(client, separate_pools, path, batch):
    pid = client.post('/projects', json={'name': f'capacity-{path.rsplit("/", 1)[-1]}-{batch}',
        'process_node': '5nm', 'foundry': 'QA'}).json()['id']
    single = {'project_id': pid, 'stage': 'routing', 'top_module': 'top',
              'design_revision': 'capacity', 'scenario': 'slow',
              'netlist': 'module top; endmodule', 'liberty': 'library(x) {}', 'sdc': 'clock'}
    body = ({key: value for key, value in single.items() if key not in {'scenario', 'liberty', 'sdc'}} |
            {'scenarios': [{'scenario': 'slow', 'liberty': 'library(x) {}', 'sdc': 'clock'}]}
            if batch else single)
    with acquire_sta_slot():
        response = client.post(path, json=body)
    assert response.status_code == 429
    assert response.headers['retry-after'] == '5'
    assert client.get(f'/projects/{pid}/runs').json() == []
    assert client.get(f'/projects/{pid}/sta-batches').json()['items'] == []


@pytest.mark.parametrize('value', ['0', '-1', '17', 'invalid'])
def test_invalid_sta_capacity_is_rejected(value, monkeypatch):
    monkeypatch.setenv('SIGNOFF_STA_MAX_CONCURRENT', value)
    with pytest.raises(RuntimeError, match='SIGNOFF_STA_MAX_CONCURRENT'):
        capacity()


def test_scheduler_prefers_an_idle_project_then_the_least_recently_started(client):
    first = client.post('/projects', json={'name': 'fair-first', 'process_node': '5nm', 'foundry': 'QA'}).json()['id']
    second = client.post('/projects', json={'name': 'fair-second', 'process_node': '5nm', 'foundry': 'QA'}).json()['id']
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        active = StaBatchExecution(project_id=first, stage=Stage.routing, top_module='top',
            design_revision='active', submitted_by='local', status='running', started_at=now)
        first_oldest = StaBatchExecution(project_id=first, stage=Stage.routing, top_module='top',
            design_revision='first-1', submitted_by='local', status='queued')
        first_later = StaBatchExecution(project_id=first, stage=Stage.routing, top_module='top',
            design_revision='first-2', submitted_by='local', status='queued')
        second_only = StaBatchExecution(project_id=second, stage=Stage.routing, top_module='top',
            design_revision='second-1', submitted_by='local', status='queued')
        db.add_all([active, first_oldest, first_later, second_only])
        db.flush()
        assert _claim_candidates(db) == [second_only.id, first_oldest.id]

        active.status = 'completed'
        active.finished_at = now
        second_history = StaBatchExecution(project_id=second, stage=Stage.routing, top_module='top',
            design_revision='second-done', submitted_by='local', status='completed',
            started_at=now + timedelta(seconds=1), finished_at=now + timedelta(seconds=2))
        db.add(second_history)
        db.flush()
        assert _claim_candidates(db) == [first_oldest.id, second_only.id]
        db.rollback()


def test_dispatcher_recovers_after_a_database_poll_failure(monkeypatch):
    import threading
    from app.services import sta_batch_queue as queue

    stop = threading.Event()
    calls = []
    monkeypatch.setattr(queue, 'reconcile_stale_batches', lambda: None)

    def claim(_token):
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError('transient database failure')
        stop.set()
        return None

    monkeypatch.setattr(queue, 'claim_next', claim)
    thread = threading.Thread(target=queue.dispatcher_loop, args=(stop,))
    thread.start()
    thread.join(timeout=3)
    assert not thread.is_alive() and len(calls) == 2
