import asyncio
import logging

import httpx
import pytest

from app.hermes import HermesClient, ROLES, Settings


@pytest.fixture
def anyio_backend():
    return 'asyncio'


def test_unavailable_gate_skips_verifier_and_never_returns_exception_details(client, monkeypatch, caplog):
    calls, closed = [], []
    secret = 'Bearer-private-token /private/internal/design.sv'
    async def chat(self, role, text, *, session_id):
        calls.append(role.id)
        raise RuntimeError(secret)
    async def close(self):
        closed.append(True)
    monkeypatch.setattr(HermesClient, 'chat', chat)
    monkeypatch.setattr(HermesClient, 'aclose', close)
    with caplog.at_level(logging.WARNING):
        response = client.post('/agents/review/gate', json={'gate_status': {'ready': False}, 'findings': {}})
    assert response.status_code == 200
    result = response.json()
    assert result['a5']['available'] is False
    assert result['a5']['review'] is None
    assert result['a5']['error'] == 'review_unavailable'
    assert len(result['a5']['error_id']) == 32
    assert result['v'] is None
    assert calls == ['a5_synth'] and closed == [True]
    assert result['a5']['review_id'] == result['a5']['error_id']
    assert result['a5']['duration_ms'] >= 0
    assert result['a5']['completed_at']
    assert secret not in response.text and secret not in caplog.text
    assert result['a5']['error_id'] in caplog.text


def test_success_chains_verifier_and_closes_both_clients(client, monkeypatch):
    calls, closed = [], []
    async def chat(self, role, text, *, session_id):
        calls.append((role.id, text))
        return 'reviewed evidence'
    async def close(self):
        closed.append(True)
    monkeypatch.setattr(HermesClient, 'chat', chat)
    monkeypatch.setattr(HermesClient, 'aclose', close)
    response = client.post('/agents/review/gate', json={'gate_status': {'ready': False}, 'findings': {}})
    result = response.json()
    assert result['a5']['available'] and result['v']['available']
    assert [role for role, _ in calls] == ['a5_synth', 'v_verify']
    assert 'reviewed evidence' in calls[1][1]
    assert len(closed) == 2
    from datetime import datetime
    assert result['a5']['review_id'] != result['v']['review_id']
    for role in ('a5', 'v'):
        assert len(result[role]['review_id']) == 32
        assert result[role]['duration_ms'] >= 0
        assert datetime.fromisoformat(result[role]['completed_at']).tzinfo is not None
    assert result['a5']['completed_at'] <= result['v']['completed_at']


@pytest.mark.parametrize('content', ['', '   ', None, {'invalid': 'content'}])
def test_empty_review_never_claims_available(client, monkeypatch, content):
    async def chat(self, *args, **kwargs):
        return content
    monkeypatch.setattr(HermesClient, 'chat', chat)
    result = client.post('/agents/review/rtl', json={'rtl_signoff_result': {'rules': [{'status': 'violation'}]}}).json()
    assert result['available'] is False and result['review'] is None


def test_review_timeout_cancels_work_and_closes_client(client, monkeypatch):
    stopped, closed = [], []
    async def chat(self, *args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            stopped.append(True)
    async def close(self):
        closed.append(True)
    monkeypatch.setattr(HermesClient, 'chat', chat)
    monkeypatch.setattr(HermesClient, 'aclose', close)
    monkeypatch.setattr('app.routers.agents.REVIEW_TIMEOUT_SECONDS', 0.01)
    result = client.post('/agents/review/rtl', json={'rtl_signoff_result': {'rules': [{'status': 'violation'}]}}).json()
    assert result['available'] is False
    assert stopped == [True] and closed == [True]


@pytest.mark.anyio
async def test_unconfigured_key_does_not_send_malformed_authorization():
    seen = []
    def handler(request):
        seen.append(request.headers)
        return httpx.Response(200, json={'choices': [{'message': {'content': 'review'}}]})
    client = HermesClient(Settings('http://test/v1', '', 'test'), transport=httpx.MockTransport(handler))
    try:
        assert await client.chat(ROLES['a1_rtl'], 'test', session_id='local:test') == 'review'
        assert 'authorization' not in seen[0]
    finally:
        await client.aclose()
    assert client._http.is_closed
