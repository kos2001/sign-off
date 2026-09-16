import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import COOKIE, token_hash, verify_password
from app.db import SessionLocal
from app.models import AccountSecurityEvent, AuthSession, User
from app.services.account_security import record_security_event
from test_auth import accounts, PASSWORD, NEW_PASSWORD


def test_security_history_successes_ownership_and_secrets(accounts):
    users, _, login = accounts
    current, remote, other = login('editor'), login('editor'), login('viewer')
    initial = current.get('/auth/security-events')
    assert initial.status_code == 200 and initial.headers['cache-control'] == 'no-store'
    assert [item['action'] for item in initial.json()['items']] == ['login', 'login']
    assert current.post('/auth/password', json={'current_password': 'wrong', 'new_password': NEW_PASSWORD}).status_code == 400
    assert current.get('/auth/security-events').json() == initial.json()
    assert current.post('/auth/sessions/revoke-others').status_code == 200
    event = current.get('/auth/security-events').json()['items'][0]
    assert event['action'] == 'other_sessions_revoked' and event['revoked_sessions'] == 1
    assert event['actor'] == users['editor'].username and event['actor_user_id'] == users['editor'].id
    assert event['source'] == 'api'
    assert len(other.get('/auth/security-events').json()['items']) == 1
    assert remote.get('/auth/security-events').status_code == 401
    text = current.get('/auth/security-events').text
    for secret in [PASSWORD, NEW_PASSWORD, current.cookies.get(COOKIE), token_hash(current.cookies.get(COOKIE)), current.headers['X-CSRF-Token']]:
        assert secret not in text
    assert current.post('/auth/password', json={'current_password': PASSWORD, 'new_password': NEW_PASSWORD}).status_code == 200
    assert current.get('/auth/security-events').json()['items'][0]['action'] == 'password_changed'


def test_logout_and_cursor_history_excludes_newer_events(accounts):
    users, _, login = accounts
    current = login('editor')
    assert current.post('/auth/logout').status_code == 200
    current = login('editor')
    assert [item['action'] for item in current.get('/auth/security-events').json()['items']] == ['login', 'logout', 'login']
    with SessionLocal() as db:
        for _ in range(30):
            record_security_event(db, 'other_sessions_revoked', subject=users['editor'], actor=users['editor'], revoked_sessions=0)
        db.commit()
    first = current.get('/auth/security-events?limit=25').json()
    assert len(first['items']) == 25
    assert first['next_before_id'] == first['items'][-1]['id']
    login('editor')
    second = current.get(f"/auth/security-events?limit=25&before_id={first['next_before_id']}").json()
    assert len(second['items']) == 8 and second['next_before_id'] is None
    assert not {item['id'] for item in first['items']} & {item['id'] for item in second['items']}


@pytest.mark.parametrize('operation', ['login', 'password', 'revoke', 'logout'])
def test_audit_write_failure_rolls_back_actual_operation(accounts, monkeypatch, operation):
    users, _, login = accounts
    current, remote = login('editor'), login('editor')
    with SessionLocal() as db:
        previous = db.scalar(select(func.count()).select_from(AccountSecurityEvent).where(AccountSecurityEvent.subject_user_id == users['editor'].id))
    original = Session.flush
    def fail_event(db, *args, **kwargs):
        if any(isinstance(item, AccountSecurityEvent) for item in db.new):
            raise RuntimeError('simulated security event storage failure')
        return original(db, *args, **kwargs)
    monkeypatch.setattr(Session, 'flush', fail_event)
    if operation == 'login':
        with TestClient(current.app, headers={'X-Signoff-Client': '1'}) as fresh:
            response = fresh.post('/auth/login', json={'username': users['editor'].username, 'password': PASSWORD})
    else:
        path, body = {'password': ('/auth/password', {'current_password': PASSWORD, 'new_password': NEW_PASSWORD}),
                      'revoke': ('/auth/sessions/revoke-others', {}), 'logout': ('/auth/logout', {})}[operation]
        response = current.post(path, json=body)
    assert response.status_code == 500
    assert current.get('/projects').status_code == remote.get('/projects').status_code == 200
    with SessionLocal() as db:
        assert verify_password(PASSWORD, db.get(User, users['editor'].id).password_hash)
        assert db.scalar(select(func.count()).select_from(AuthSession).where(AuthSession.user_id == users['editor'].id)) == 2
        assert db.scalar(select(func.count()).select_from(AccountSecurityEvent).where(AccountSecurityEvent.subject_user_id == users['editor'].id)) == previous


def test_operator_account_actions_and_global_revoke_are_recorded(accounts, monkeypatch):
    from app.accounts import main
    monkeypatch.setattr('app.accounts.read_password', lambda: PASSWORD)
    username = 'audit-' + uuid.uuid4().hex[:12]
    for command in ['create-user', 'reset-password', 'disable-user', 'enable-user']:
        main([command, username])
    main(['create-user', username + '-admin', '--admin'])
    main(['revoke-sessions'])
    with SessionLocal() as db:
        events = db.scalars(select(AccountSecurityEvent).where(AccountSecurityEvent.subject_username == username).order_by(AccountSecurityEvent.id)).all()
        assert [event.action for event in events] == ['account_created', 'password_reset', 'account_disabled', 'account_enabled']
        assert all(event.source == 'operator' and event.actor_user_id is None and event.actor == 'local operator' for event in events)
        assert db.scalar(select(AccountSecurityEvent.action).where(AccountSecurityEvent.subject_username == username + '-admin')) == 'admin_account_created'
        latest = db.scalar(select(AccountSecurityEvent).order_by(AccountSecurityEvent.id.desc()).limit(1))
        assert latest.action == 'all_sessions_revoked' and latest.subject_user_id is None


def test_operator_audit_failure_rolls_back_password_reset(accounts, monkeypatch):
    from app.accounts import main
    users, _, login = accounts
    current = login('editor')
    monkeypatch.setattr('app.accounts.read_password', lambda: NEW_PASSWORD)
    original = Session.flush
    def fail_event(db, *args, **kwargs):
        if any(isinstance(item, AccountSecurityEvent) for item in db.new):
            raise RuntimeError('simulated operator audit failure')
        return original(db, *args, **kwargs)
    monkeypatch.setattr(Session, 'flush', fail_event)
    with pytest.raises(RuntimeError, match='operator audit failure'):
        main(['reset-password', users['editor'].username])
    assert current.get('/projects').status_code == 200
    with SessionLocal() as db:
        assert verify_password(PASSWORD, db.get(User, users['editor'].id).password_hash)
        assert db.scalar(select(AccountSecurityEvent).where(AccountSecurityEvent.subject_user_id == users['editor'].id, AccountSecurityEvent.action == 'password_reset')) is None


def test_security_history_requires_authenticated_mode_and_valid_cursor(client, accounts, monkeypatch):
    _, _, login = accounts
    assert client.get('/auth/security-events').status_code == 401
    current = login('viewer')
    for query in ['limit=0', 'limit=101', 'before_id=0']:
        assert current.get('/auth/security-events?' + query).status_code == 422
    monkeypatch.setenv('SIGNOFF_AUTH_MODE', 'local')
    assert current.get('/auth/security-events').status_code == 409


def test_admin_history_requires_global_admin_and_includes_global_events(client, accounts, monkeypatch):
    users, _, login = accounts
    route = '/auth/admin/security-events'
    assert client.get(route).status_code == 401
    for role in ['owner', 'approver', 'editor', 'viewer', 'outsider']:
        assert login(role).get(route).status_code == 403
    admin = login('admin')
    with SessionLocal() as db:
        record_security_event(db, 'all_sessions_revoked', source='operator', revoked_sessions=7)
        db.commit()
    response = admin.get(route + '?action=all_sessions_revoked&source=operator')
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    event = response.json()['items'][0]
    assert event['subject_user_id'] is None and event['subject_username'] is None
    assert event['revoked_sessions'] == 7 and event['actor_user_id'] is None
    assert login('editor').get('/auth/security-events').json()['items'][0]['action'] != 'all_sessions_revoked'
    with SessionLocal() as db:
        db.get(User, users['admin'].id).is_admin = False
        db.commit()
    assert admin.get(route).status_code == 403
    monkeypatch.setenv('SIGNOFF_AUTH_MODE', 'local')
    assert admin.get(route).status_code == 409


def test_admin_history_exact_filters_cursor_and_read_only(accounts):
    users, _, login = accounts
    admin, editor = login('admin'), login('editor')
    with SessionLocal() as db:
        for _ in range(3):
            record_security_event(db, 'password_reset', subject=users['editor'], source='operator', revoked_sessions=0)
        db.commit()
        count = db.scalar(select(func.count()).select_from(AccountSecurityEvent))
    route = '/auth/admin/security-events'
    filters = {'subject_username': users['editor'].username, 'action': 'password_reset', 'source': 'operator', 'limit': 2}
    first = admin.get(route, params=filters).json()
    assert len(first['items']) == 2 and first['next_before_id'] is not None
    assert all(event['subject_user_id'] == users['editor'].id for event in first['items'])
    second = admin.get(route, params={**filters, 'before_id': first['next_before_id']}).json()
    assert len(second['items']) == 1 and second['next_before_id'] is None
    assert second['items'][0]['id'] < first['items'][-1]['id']
    for subject in ['%', users['editor'].username.upper(), users['editor'].username[:-1]]:
        assert admin.get(route, params={**filters, 'subject_username': subject}).json()['items'] == []
    assert admin.get(route, params={**filters, 'source': 'api'}).json()['items'] == []
    for query in ['action=unknown', 'source=bad', 'limit=101', 'before_id=0']:
        assert admin.get(route + '?' + query).status_code == 422
    assert editor.get('/projects').status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AccountSecurityEvent)) == count


def test_failed_login_records_target_without_claiming_actor_or_exposing_credentials(accounts):
    users, _, login = accounts
    admin, current = login('admin'), login('editor')
    unknown = 'missing-' + uuid.uuid4().hex[:12]
    secret = 'invalid-private-password-for-audit'
    with TestClient(current.app, headers={'X-Signoff-Client': '1'}) as anonymous:
        for name in [users['editor'].username, unknown]:
            response = anonymous.post('/auth/login', json={'username': name, 'password': secret})
            assert response.status_code == 401 and response.json()['detail'] == 'invalid username or password'
            assert response.headers['cache-control'] == 'no-store'
            events = admin.get('/auth/admin/security-events', params={'subject_username': name, 'action': 'login_failed'}).json()['items']
            assert len(events) == 1
            assert events[0]['subject_user_id'] == (users['editor'].id if name != unknown else None)
            assert events[0]['subject_username'] == name
            assert events[0]['actor_user_id'] is None and events[0]['actor'] == 'unverified client'
            assert events[0]['revoked_sessions'] is None
            assert secret not in str(events)
    personal = current.get('/auth/security-events').json()['items']
    assert personal[0]['action'] == 'login_failed'
    assert current.get('/projects').status_code == 200


def test_throttled_login_does_not_grow_failure_history(accounts):
    users, _, login = accounts
    current = login('editor')
    with TestClient(current.app, headers={'X-Signoff-Client': '1'}) as anonymous:
        for _ in range(7):
            assert anonymous.post('/auth/login', json={'username': users['editor'].username, 'password': 'wrong'}).status_code == 401
        assert anonymous.post('/auth/login', json={'username': users['editor'].username, 'password': 'wrong'}).status_code == 429
    events = current.get('/auth/security-events').json()['items']
    assert sum(item['action'] == 'login_failed' for item in events) == 7


def test_failed_login_audit_failure_never_creates_session(accounts, monkeypatch):
    users, _, login = accounts
    current = login('editor')
    original = Session.flush
    def fail(db, *args, **kwargs):
        if any(isinstance(item, AccountSecurityEvent) and item.action == 'login_failed' for item in db.new):
            raise RuntimeError('simulated failure audit write error')
        return original(db, *args, **kwargs)
    monkeypatch.setattr(Session, 'flush', fail)
    with TestClient(current.app, headers={'X-Signoff-Client': '1'}) as anonymous:
        assert anonymous.post('/auth/login', json={'username': users['editor'].username, 'password': 'wrong'}).status_code == 500
        assert anonymous.get('/auth/session').json()['user'] is None
    assert current.get('/projects').status_code == 200
    assert [item['action'] for item in current.get('/auth/security-events').json()['items']] == ['login']


def test_admin_period_normalizes_timezones_and_has_inclusive_start_exclusive_end(accounts):
    users, _, login = accounts
    admin = login('admin')
    with SessionLocal() as db:
        for hour in [0, 1, 2]:
            db.add(AccountSecurityEvent(subject_user_id=users['editor'].id, subject_username=users['editor'].username,
                actor='local operator', source='operator', action='password_reset',
                created_at=datetime(2026, 1, 1, hour, tzinfo=timezone.utc)))
        db.commit()
    route = '/auth/admin/security-events'
    base = {'subject_username': users['editor'].username, 'action': 'password_reset'}
    interval = {**base, 'created_from': '2026-01-01T09:00:00+09:00', 'created_before': '2026-01-01T11:00:00+09:00'}
    result = admin.get(route, params=interval)
    assert result.status_code == 200, result.text
    assert len(result.json()['items']) == 2
    utc = admin.get(route, params={**base, 'created_from': '2026-01-01T00:00:00Z', 'created_before': '2026-01-01T02:00:00Z'}).json()
    assert result.json() == utc
    first = admin.get(route, params={**interval, 'limit': 1}).json()
    second = admin.get(route, params={**interval, 'limit': 1, 'before_id': first['next_before_id']}).json()
    assert second['items'][0]['id'] != first['items'][0]['id'] and second['next_before_id'] is None
    assert len(admin.get(route, params={**base, 'created_before': '2026-01-01T00:00:00Z'}).json()['items']) == 0
    assert len(admin.get(route, params={**base, 'created_from': '2026-01-01T02:00:00Z'}).json()['items']) == 1


@pytest.mark.parametrize('period', [
    {'created_from': 'bad'}, {'created_from': '2026-01-01T00:00:00'},
    {'created_before': '2026-01-01T00:00:00'},
    {'created_from': '2026-01-02T00:00:00Z', 'created_before': '2026-01-01T00:00:00Z'},
    {'created_from': '2026-01-01T00:00:00Z', 'created_before': '2026-01-01T00:00:00Z'},
])
def test_admin_period_rejects_ambiguous_or_reversed_ranges(accounts, period):
    _, _, login = accounts
    assert login('admin').get('/auth/admin/security-events', params=period).status_code == 422
