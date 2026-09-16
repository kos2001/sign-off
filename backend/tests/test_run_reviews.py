import copy
import uuid

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import RunAgentReview, SignoffRun
from test_auth import accounts
from test_source_export import imported


@pytest.fixture(autouse=True)
def provider(monkeypatch):
    calls = []
    async def chat(self, role, text, *, session_id):
        calls.append((role.id, text))
        with SessionLocal() as db:
            assert db.scalar(select(RunAgentReview).where(RunAgentReview.status == 'running').order_by(RunAgentReview.id.desc())) is not None
        return '제공된 경로만 검토한 참고 의견'
    monkeypatch.setattr('app.hermes.HermesClient.chat', chat)
    return calls


def request(client, rid, key=None):
    return client.post(f'/runs/{rid}/agent-reviews', json={'request_key': key or str(uuid.uuid4())})


def test_review_uses_captured_evidence_and_persists_snapshot(client, provider):
    rid, _ = imported(client)
    key = str(uuid.uuid4())
    response = request(client, rid, key)
    assert response.status_code == 201
    row = response.json()
    assert row['status'] == 'completed'
    assert row['input_snapshot']['run_id'] == rid
    assert row['input_snapshot']['analysis']['coverage'] == 'reported_paths_only'
    assert row['outcome']['review'] == '제공된 경로만 검토한 참고 의견'
    assert row['requester'] == 'local' and 'Sign-off Hub' in row['review_policy']
    assert row['input_snapshot']['source_sha256'] == client.get(f'/runs/{rid}/evidence').json()['source_sha256']
    assert request(client, rid, key).json() == row
    assert len(provider) == 1
    with SessionLocal() as db:
        db.get(SignoffRun, rid).evidence.design_revision = 'changed later'
        db.commit()
    assert client.get(f"/runs/{rid}/agent-reviews/{row['id']}").json() == row
    items = client.get(f'/runs/{rid}/agent-reviews').json()['items']
    assert items[0]['id'] == row['id'] and 'input_snapshot' not in items[0] and 'outcome' not in items[0]


def test_review_access_attribution_and_cross_run_lookup(accounts):
    _, ids, login = accounts
    editor, viewer, outsider = login('editor'), login('viewer'), login('outsider')
    rid, _ = imported(editor, ids['project'])
    assert request(viewer, rid).status_code == 403
    assert request(outsider, rid).status_code == 404
    row = request(editor, rid).json()
    assert row['requester'] == accounts[0]['editor'].username and row['requester_user_id'] is not None
    assert viewer.get(f"/runs/{rid}/agent-reviews/{row['id']}").status_code == 200
    assert outsider.get(f'/runs/{rid}/agent-reviews').status_code == 404
    assert viewer.get(f"/runs/{ids['run']}/agent-reviews/{row['id']}").status_code == 404
    assert request(editor, ids['run']).status_code == 409
    assert editor.post(f'/runs/{rid}/agent-reviews', json={'request_key': str(uuid.uuid4()), 'review': 'forged'}).status_code == 422


def test_failed_review_is_saved_without_provider_secrets(client, monkeypatch):
    async def fail(*args, **kwargs):
        raise RuntimeError('private-provider-secret')
    monkeypatch.setattr('app.hermes.HermesClient.chat', fail)
    rid, _ = imported(client)
    row = request(client, rid).json()
    assert row['status'] == 'failed' and row['outcome']['available'] is False and row['outcome']['review'] is None
    assert 'private-provider-secret' not in str(row)
    assert client.get(f"/runs/{rid}/agent-reviews/{row['id']}").json() == row


def test_hash_mismatch_prevents_call_and_receipt(client, provider):
    rid, _ = imported(client)
    with SessionLocal() as db:
        db.get(SignoffRun, rid).evidence.source_sha256 = '0' * 64
        db.commit()
    assert request(client, rid).status_code == 409
    assert not provider
    assert client.get(f'/runs/{rid}/agent-reviews').json()['items'] == []


def test_incomplete_receipt_is_not_silently_reexecuted(client, provider):
    rid, _ = imported(client)
    row = request(client, rid).json()
    with SessionLocal() as db:
        stored = db.get(RunAgentReview, row['id'])
        stored.status, stored.outcome = 'running', {}
        db.commit()
    again = request(client, rid, row['request_key'])
    assert again.status_code == 200 and again.json()['status'] == 'running'
    assert len(provider) == 1


def test_history_cursor_traverses_once_without_payloads(client):
    rid, _ = imported(client)
    row = request(client, rid).json()
    with SessionLocal() as db:
        original = db.get(RunAgentReview, row['id'])
        for _ in range(22):
            db.add(RunAgentReview(run_id=rid, request_key=str(uuid.uuid4()), requester='local', role=original.role,
                                  input_snapshot=copy.deepcopy(original.input_snapshot), review_policy=original.review_policy,
                                  model_alias=original.model_alias, status='completed', outcome={}))
        db.commit()
    first = client.get(f'/runs/{rid}/agent-reviews').json()
    second = client.get(f'/runs/{rid}/agent-reviews', params={'before_id': first['next_before_id']}).json()
    ids = [item['id'] for item in first['items'] + second['items']]
    assert len(first['items']) == 20 and len(ids) == len(set(ids)) == 23
    assert ids == sorted(ids, reverse=True) and second['next_before_id'] is None


def test_same_request_while_provider_runs_does_not_execute_twice(client, monkeypatch):
    import asyncio
    from threading import Event
    from concurrent.futures import ThreadPoolExecutor
    started, release = Event(), Event()
    calls = []
    async def chat(*args, **kwargs):
        calls.append(True)
        started.set()
        while not release.is_set():
            await asyncio.sleep(0.01)
        return 'completed once'
    monkeypatch.setattr('app.hermes.HermesClient.chat', chat)
    rid, _ = imported(client)
    key = str(uuid.uuid4())
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(request, client, rid, key)
        try:
            assert started.wait(5)
            duplicate = request(client, rid, key)
            assert duplicate.status_code == 200 and duplicate.json()['status'] == 'running'
        finally:
            release.set()
        done = future.result(timeout=5)
    assert done.json()['status'] == 'completed' and len(calls) == 1
    assert request(client, rid, key).json()['id'] == done.json()['id']


def test_input_limit_rejects_without_creating_record(client, provider):
    rid, _ = imported(client)
    with SessionLocal() as db:
        evidence = db.get(SignoffRun, rid).evidence
        evidence.source = 'rtl_ladder'
        evidence.result = {'notes': '한' * 100000}
        db.commit()
    assert request(client, rid).status_code == 413
    assert not provider
    assert client.get(f'/runs/{rid}/agent-reviews').json()['items'] == []


@pytest.mark.parametrize('status', ['running', 'completed', 'failed'])
@pytest.mark.parametrize('seconds', [119.999, 120, 121])
@pytest.mark.parametrize('naive', [True, False])
def test_completion_notice_uses_server_age_without_changing_status(status, seconds, naive):
    from datetime import datetime, timezone, timedelta
    from app.routers.run_reviews import summary
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    row = RunAgentReview(id=1, run_id=1, request_key='test', requester='local', role='a2_timing', status=status,
                         created_at=created.replace(tzinfo=None) if naive else created)
    result = summary(row, now=created + timedelta(seconds=seconds))
    assert result['completion_overdue'] == (status == 'running' and seconds >= 120)
    assert result['status'] == row.status == status
    assert result['created_at'].tzinfo is not None


def test_history_query_does_not_load_large_payload_columns(client):
    from sqlalchemy import event
    from app.db import engine
    rid, _ = imported(client)
    request(client, rid)
    statements = []
    def capture(connection, cursor, statement, parameters, context, many):
        if 'FROM run_agent_reviews' in statement:
            statements.append(statement)
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        response = client.get(f'/runs/{rid}/agent-reviews')
        assert response.status_code == 200 and len(response.json()['items']) == 1
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    assert len(statements) == 1
    for column in ['input_snapshot', 'outcome', 'review_policy', 'model_alias']:
        assert f'run_agent_reviews.{column}' not in statements[0]


@pytest.mark.parametrize('status', ['running', 'completed', 'failed'])
def test_review_export_preserves_snapshot_status_and_unicode(client, status):
    rid, _ = imported(client)
    row = request(client, rid).json()
    with SessionLocal() as db:
        stored = db.get(RunAgentReview, row['id'])
        stored.status = status
        stored.outcome = {'available': status == 'completed', 'review': '한글 검토\nµW' if status == 'completed' else None}
        db.commit()
    before = client.get(f"/runs/{rid}/agent-reviews/{row['id']}").json()
    response = client.get(f"/runs/{rid}/agent-reviews/{row['id']}/export")
    assert response.status_code == 200
    bundle = response.json()
    assert bundle['format'] == 'signoff/run-agent-review-export/v1'
    assert bundle['review'] == before
    assert bundle['exported_at'].endswith('+00:00')
    assert 'Not a sign-off approval' in bundle['scope_note']
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['content-disposition'] == f'attachment; filename="run-{rid}-review-{row["id"]}.json"'
    assert client.get(f"/runs/{rid}/agent-reviews/{row['id']}").json() == before


def test_review_export_byte_boundary_and_no_partial_attachment(client, monkeypatch):
    rid, _ = imported(client)
    row = request(client, rid).json()
    url = f"/runs/{rid}/agent-reviews/{row['id']}/export"
    size = len(client.get(url).content)
    monkeypatch.setattr('app.routers.run_reviews.MAX_EXPORT_BYTES', size)
    assert client.get(url).status_code == 200
    monkeypatch.setattr('app.routers.run_reviews.MAX_EXPORT_BYTES', size - 1)
    response = client.get(url)
    assert response.status_code == 413
    assert 'content-disposition' not in response.headers


def test_review_export_permissions_and_cross_run(accounts):
    _, ids, login = accounts
    editor, viewer, outsider = login('editor'), login('viewer'), login('outsider')
    rid, _ = imported(editor, ids['project'])
    row = request(editor, rid).json()
    url = f"/runs/{rid}/agent-reviews/{row['id']}/export"
    assert viewer.get(url).status_code == 200
    assert outsider.get(url).status_code == 404
    assert viewer.get(f"/runs/{ids['run']}/agent-reviews/{row['id']}/export").status_code == 404
    assert viewer.get(f'/runs/{rid}/agent-reviews/99999999/export').status_code == 404
