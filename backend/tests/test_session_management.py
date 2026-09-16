import time
import uuid

from sqlalchemy.orm import Session

from app.auth import COOKIE, token_hash
from app.db import SessionLocal
from app.models import AuthSession
from test_auth import accounts


def test_session_listing_is_self_scoped_paginated_and_secret_free(accounts):
    users, _, login = accounts
    current, remote, outsider = login('editor'), login('editor'), login('outsider')
    with SessionLocal() as db:
        db.add(AuthSession(user_id=users['editor'].id, token_hash=uuid.uuid4().hex,
                           csrf_token='expired-secret', expires_at=int(time.time()) - 1))
        db.commit()
    response = current.get('/auth/sessions?limit=1')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    result = response.json()
    assert result['total'] == 2
    assert result['items'][0]['current'] is True
    assert set(result['items'][0]) == {'id', 'current', 'expires_at'}
    second = current.get('/auth/sessions?offset=1&limit=1').json()
    assert second['items'][0]['current'] is False
    assert second['items'][0]['id'] != result['items'][0]['id']
    assert outsider.get('/auth/sessions').json()['total'] == 1
    assert remote.get('/auth/sessions').json()['items'][0]['current'] is True
    for secret in [current.cookies.get(COOKIE), token_hash(current.cookies.get(COOKIE)), current.headers['X-CSRF-Token']]:
        assert secret not in response.text
    for query in ['limit=0', 'limit=101', 'offset=-1']:
        assert current.get('/auth/sessions?' + query).status_code == 422


def test_revoke_others_keeps_current_and_other_accounts_and_allows_new_login(accounts):
    users, _, login = accounts
    current, remote, outsider = login('editor'), login('editor'), login('outsider')
    cookie = current.cookies.get(COOKIE)
    csrf = current.get('/auth/session').json()['csrf_token']
    result = current.post('/auth/sessions/revoke-others', json={'user_id': users['outsider'].id})
    assert result.status_code == 200 and result.json() == {'revoked': 1}
    assert result.headers['cache-control'] == 'no-store'
    assert current.cookies.get(COOKIE) == cookie
    assert current.get('/auth/session').json()['csrf_token'] == csrf
    assert current.get('/projects').status_code == 200
    assert remote.get('/projects').status_code == 401
    assert outsider.get('/projects').status_code == 200
    assert current.post('/auth/sessions/revoke-others').json() == {'revoked': 0}
    assert login('editor').get('/projects').status_code == 200


def test_session_management_requires_login_mode_and_csrf(client, accounts, monkeypatch):
    _, _, login = accounts
    assert client.get('/auth/sessions').status_code == 401
    assert client.post('/auth/sessions/revoke-others').status_code == 401
    current = login('editor')
    current.headers.pop('X-CSRF-Token')
    assert current.post('/auth/sessions/revoke-others').status_code == 403
    monkeypatch.setenv('SIGNOFF_AUTH_MODE', 'local')
    assert current.get('/auth/sessions').status_code == 409
    assert current.post('/auth/sessions/revoke-others').status_code == 409


def test_revoked_caller_cannot_revoke_survivor_after_identity_check(accounts, monkeypatch):
    from app.routers import auth
    _, _, login = accounts
    losing, surviving = login('editor'), login('editor')
    original = auth.get_identity
    def interleave(request, db):
        identity = original(request, db)
        if request.headers.get('X-Test-Interleave'):
            response = surviving.post('/auth/sessions/revoke-others')
            assert response.status_code == 200 and response.json()['revoked'] == 1
        return identity
    monkeypatch.setattr(auth, 'get_identity', interleave)
    response = losing.post('/auth/sessions/revoke-others', headers={'X-Test-Interleave': '1'})
    assert response.status_code == 401
    assert surviving.get('/projects').status_code == 200
    assert losing.get('/projects').status_code == 401


def test_revoke_commit_failure_keeps_all_sessions(accounts, monkeypatch):
    _, _, login = accounts
    current, remote = login('editor'), login('editor')
    def fail(_):
        raise RuntimeError('simulated session storage failure')
    monkeypatch.setattr(Session, 'commit', fail)
    assert current.post('/auth/sessions/revoke-others').status_code == 500
    assert current.get('/projects').status_code == 200
    assert remote.get('/projects').status_code == 200
