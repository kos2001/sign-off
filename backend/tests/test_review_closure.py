import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from threading import Event

import pytest

from app.db import SessionLocal
from app.models import RunAgentReview
from test_auth import accounts
from test_source_export import imported


def receipt(rid, *, status='running', age=180):
    with SessionLocal() as db:
        row = RunAgentReview(run_id=rid, request_key=str(uuid.uuid4()), requester='local', role='a2_timing',
                             input_snapshot={'kept': True}, review_policy='kept', model_alias='test',
                             status=status, outcome={}, created_at=datetime.now(timezone.utc)-timedelta(seconds=age))
        db.add(row)
        db.commit()
        return row.id


def test_owner_closure_is_scoped_attributed_and_exported(accounts):
    _, ids, login = accounts
    rid = ids['run']
    review_id = receipt(rid)
    path = f'/runs/{rid}/agent-reviews/{review_id}'
    for role in ['viewer', 'editor', 'approver']:
        assert login(role).post(path+'/close', json={'reason': 'resolve'}).status_code == 403
    assert login('outsider').post(path+'/close', json={'reason': 'resolve'}).status_code == 404
    owner = login('owner')
    assert owner.post(path+'/close', json={'reason': ' ', 'actor': 'forged'}).status_code == 422
    response = owner.post(path+'/close', json={'reason': ' 서버 재시작 후 미완료 정리 '})
    assert response.status_code == 200
    row = response.json()
    assert row['status'] == 'failed' and not row['completion_overdue']
    assert row['outcome']['closure']['actor'] == accounts[0]['owner'].username
    assert row['outcome']['closure']['actor_user_id'] == accounts[0]['owner'].id
    assert row['outcome']['closure']['reason'] == '서버 재시작 후 미완료 정리'
    assert row['input_snapshot'] == {'kept': True} and row['review_policy'] == 'kept'
    assert owner.post(path+'/close', json={'reason': 'overwrite'}).status_code == 409
    assert owner.get(path).json() == row
    assert login('viewer').get(path+'/export').json()['review'] == row
    assert owner.post(f'/runs/{rid}/agent-reviews', json={'request_key': row['request_key']}).json() == row
    other, _ = imported(owner, ids['project'])
    assert owner.post(f'/runs/{other}/agent-reviews/{review_id}/close', json={'reason': 'wrong run'}).status_code == 404


@pytest.mark.parametrize('status,age', [('running', 0), ('completed', 180), ('failed', 180)])
def test_only_overdue_running_records_can_close(client, status, age):
    rid, _ = imported(client)
    review_id = receipt(rid, status=status, age=age)
    path = f'/runs/{rid}/agent-reviews/{review_id}'
    before = client.get(path).json()
    assert client.post(path+'/close', json={'reason': 'resolve'}).status_code == 409
    assert client.get(path).json() == before


def test_late_provider_response_cannot_overwrite_closure(client, monkeypatch):
    started, release = Event(), Event()
    async def chat(*args, **kwargs):
        started.set()
        while not release.is_set():
            await asyncio.sleep(.01)
        return 'late provider result'
    monkeypatch.setattr('app.hermes.HermesClient.chat', chat)
    rid, _ = imported(client)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, f'/runs/{rid}/agent-reviews', json={'request_key': str(uuid.uuid4())})
        try:
            assert started.wait(5)
            review_id = client.get(f'/runs/{rid}/agent-reviews').json()['items'][0]['id']
            with SessionLocal() as db:
                db.get(RunAgentReview, review_id).created_at = datetime.now(timezone.utc)-timedelta(minutes=3)
                db.commit()
            closed = client.post(f'/runs/{rid}/agent-reviews/{review_id}/close', json={'reason': 'operator resolution'})
            assert closed.status_code == 200
        finally:
            release.set()
        completed = future.result(timeout=5)
    assert completed.json() == closed.json()
    assert completed.json()['outcome']['review'] is None


def test_concurrent_closures_preserve_one_operator_decision(client):
    from threading import Barrier
    rid, _ = imported(client)
    review_id = receipt(rid)
    path = f'/runs/{rid}/agent-reviews/{review_id}'
    barrier = Barrier(2)
    def close(reason):
        barrier.wait(timeout=5)
        return client.post(path+'/close', json={'reason': reason})
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(close, 'first'), pool.submit(close, 'second')
        responses = [first.result(timeout=5), second.result(timeout=5)]
    assert sorted(r.status_code for r in responses) == [200, 409]
    winner = next(r.json() for r in responses if r.status_code == 200)
    assert client.get(path).json() == winner
