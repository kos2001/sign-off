import asyncio
import os
import subprocess
import sys
import uuid

import pytest

from app.review_capacity import acquire, capacity, ReviewCapacityFull
from test_source_export import imported


@pytest.fixture(autouse=True)
def pool(tmp_path, monkeypatch):
    monkeypatch.setenv('SIGNOFF_REVIEW_SLOT_DIR', str(tmp_path/'slots'))
    monkeypatch.setenv('SIGNOFF_REVIEW_MAX_CONCURRENT', '1')


def test_shared_across_processes_and_released_after_crash():
    child = subprocess.Popen([sys.executable, '-c', "from app.review_capacity import acquire; import sys; slot=acquire(); print('locked',flush=True); sys.stdin.read()"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == 'locked'
        with pytest.raises(ReviewCapacityFull):
            acquire()
    finally:
        child.kill()
        child.wait(timeout=5)
        child.stdin.close()
        child.stdout.close()
    slot = acquire()
    slot.close()
    slot.close()


@pytest.mark.parametrize('value', ['0', '-1', '17', 'abc', '1.5'])
def test_invalid_capacity_fails_configuration(monkeypatch, value):
    monkeypatch.setenv('SIGNOFF_REVIEW_MAX_CONCURRENT', value)
    with pytest.raises(RuntimeError):
        capacity()


def test_no_slot_replacement_through_symlink_or_public_file(tmp_path):
    directory = tmp_path/'slots'
    directory.mkdir(mode=0o700)
    target = tmp_path/'target'
    target.write_text('preserve')
    (directory/'0.lock').symlink_to(target)
    with pytest.raises(OSError):
        acquire()
    assert target.read_text() == 'preserve'
    (directory/'0.lock').unlink()
    (directory/'0.lock').write_text('')
    (directory/'0.lock').chmod(0o644)
    with pytest.raises(RuntimeError):
        acquire()


def test_automatic_and_saved_reviews_share_capacity_without_model_calls(client, monkeypatch):
    calls = []
    async def chat(*args, **kwargs):
        calls.append(True)
        return 'reviewed'
    monkeypatch.setattr('app.hermes.HermesClient.chat', chat)
    rid, _ = imported(client)
    key = str(uuid.uuid4())
    slot = acquire()
    try:
        response = client.post('/agents/review/gate', json={'gate_status': {'ready': False}}).json()
        assert response['a5']['error'] == 'review_capacity' and response['v'] is None
        clean = client.post('/agents/review/gate', json={'gate_status': {'ready': True}}).json()
        assert not clean['a5']['triggered']
        saved = client.post(f'/runs/{rid}/agent-reviews', json={'request_key': key}).json()
        assert saved['status'] == 'failed' and saved['outcome']['error'] == 'review_capacity'
        assert not calls
    finally:
        slot.close()
    again = client.post(f'/runs/{rid}/agent-reviews', json={'request_key': key})
    assert again.json() == saved and not calls
    fresh = client.post(f'/runs/{rid}/agent-reviews', json={'request_key': str(uuid.uuid4())}).json()
    assert fresh['status'] == 'completed' and len(calls) == 1
    slot = acquire()
    slot.close()


def test_cancellation_releases_capacity(monkeypatch):
    from app.hermes import ROLES
    from app.routers.agents import _run_role
    closed = []
    async def chat(*args, **kwargs):
        raise asyncio.CancelledError()
    async def close(*args):
        closed.append(True)
    monkeypatch.setattr('app.hermes.HermesClient.chat', chat)
    monkeypatch.setattr('app.hermes.HermesClient.aclose', close)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_run_role(ROLES['a1_rtl'], {}, session_id='test'))
    assert closed == [True]
    slot = acquire()
    slot.close()
