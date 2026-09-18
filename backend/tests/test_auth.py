import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update

from app.auth import COOKIE, password_hash, token_hash, verify_password
from app.db import SessionLocal
from app.models import AuthSession, LoginBucket, Project, ProjectMember, SignoffRun, User, Violation, ViolationEvent, Waiver

PASSWORD = 'test-only-long-passphrase-123'
HASH = password_hash(PASSWORD)


@pytest.fixture
def accounts(client, monkeypatch):
    monkeypatch.setenv('SIGNOFF_AUTH_MODE', 'required')
    monkeypatch.setenv('SIGNOFF_COOKIE_SECURE', 'false')
    prefix = uuid.uuid4().hex[:10]
    with SessionLocal() as db:
        db.execute(delete(LoginBucket))
        users = {role: User(username=f'{prefix}-{role}', password_hash=HASH, is_admin=role == 'admin') for role in ['admin', 'owner', 'approver', 'editor', 'viewer', 'outsider']}
        db.add_all(users.values())
        p = Project(name=f'auth-{prefix}', foundry='test', process_node='5nm')
        db.add(p)
        db.flush()
        for role in ['owner', 'approver', 'editor', 'viewer']:
            db.add(ProjectMember(project_id=p.id, user_id=users[role].id, role=role))
        run = SignoffRun(project_id=p.id, domain='sta', stage='final', tool='auth-test')
        db.add(run)
        db.flush()
        violation = Violation(run_id=run.id, check_name='setup', severity='error')
        db.add(violation)
        db.commit()
        ids = {'project': p.id, 'run': run.id, 'violation': violation.id}
    clients = []
    def login(role):
        c = TestClient(client.app, headers={"X-Signoff-Client": "1"})
        clients.append(c)
        response = c.post('/auth/login', json={'username': users[role].username, 'password': PASSWORD}, headers={'X-Signoff-Client': '1'})
        assert response.status_code == 200, response.text
        c.headers['X-CSRF-Token'] = response.json()['csrf_token']
        return c
    yield users, ids, login
    for c in clients:
        c.close()


def test_all_business_routes_require_login(client, accounts):
    for route in client.app.routes:
        if not getattr(route, 'path', '').startswith(('/projects', '/runs', '/violations', '/analysis', '/agents')):
            continue
        path = route.path.replace('{project_id}', '1').replace('{run_id}', '1').replace('{violation_id}', '1').replace('{release_id}', '1').replace('{user_id}', '1')
        for method in route.methods:
            response = client.request(method, path, json={})
            assert response.status_code == 401, (method, path, response.text)
    assert client.get('/health').status_code == 200
    assert client.get('/auth/session').json()['user'] is None


def test_hidden_projects_and_direct_ids(accounts):
    users, ids, login = accounts
    outsider = login('outsider')
    assert outsider.get('/projects').json() == []
    for path in [f"/projects/{ids['project']}", f"/projects/{ids['project']}/runs", f"/projects/{ids['project']}/violations", f"/projects/{ids['project']}/signoff-status?stage=final", f"/projects/{ids['project']}/run-comparison?baseline_run_id={ids['run']}&candidate_run_id=99", f"/runs/{ids['run']}/evidence", f"/runs/{ids['run']}/violations", f"/violations/{ids['violation']}", f"/violations/{ids['violation']}/history"]:
        assert outsider.get(path).status_code == 404, path
    assert outsider.post('/analysis/rtl-signoff', json={'project_id': ids['project'], 'code': 'module top; endmodule'}).status_code == 404
    visible = login('viewer').get('/projects').json()
    assert [p['id'] for p in visible] == [ids['project']]


def test_role_matrix_and_identity_cannot_be_spoofed(accounts):
    users, ids, login = accounts
    viewer, editor, approver = [login(role) for role in ['viewer', 'editor', 'approver']]
    path = f"/violations/{ids['violation']}"
    fixed = {'expected_status': 'open', 'expected_version': 1, 'status': 'fixed', 'actor': 'spoofed-admin', 'reason': 'verified test'}
    assert viewer.patch(path, json=fixed).status_code == 403
    assert viewer.patch(f"/runs/{ids['run']}", json={'status': 'passed'}).status_code == 403
    scenario_path = f"/projects/{ids['project']}/sta-scenario-plan/routing"
    scenario_plan = {'scenarios': [{'name': 'slow'}], 'expected_version': 0, 'reason': 'signoff scope'}
    assert viewer.put(scenario_path, json=scenario_plan).status_code == 403
    assert editor.put(scenario_path, json=scenario_plan).status_code == 403
    assert approver.put(scenario_path, json=scenario_plan).status_code == 200
    assert editor.post(path + '/waiver', json={'expected_version': 1, 'approved_by': 'spoofed-admin', 'reason': 'waive'}).status_code == 403
    assert editor.patch(path, json={**fixed, 'status': 'waived'}).status_code == 403
    assert editor.patch(path, json=fixed).status_code == 200
    event = viewer.get(path + '/history').json()[-1]
    assert event['actor'] == users['editor'].username
    assert event['actor_user_id'] == users['editor'].id
    assert editor.patch(path, json={**fixed, 'expected_status': 'fixed', 'expected_version': 2, 'status': 'open'}).status_code == 200
    waived = approver.post(path + '/waiver', json={'expected_version': 3, 'approved_by': 'spoofed-admin', 'reason': 'reviewed'}).json()
    assert waived['waiver']['approved_by'] == users['approver'].username
    assert waived['waiver']['approved_user_id'] == users['approver'].id
    reopen = {**fixed, 'expected_status': 'waived', 'expected_version': 4, 'status': 'open'}
    assert editor.patch(path, json=reopen).status_code == 403
    assert approver.patch(path, json=reopen).status_code == 200


def test_csrf_rotation_logout_expiry_and_disable(accounts):
    users, ids, login = accounts
    c = login('editor')
    old = c.cookies.get(COOKIE)
    c.headers.pop('X-CSRF-Token')
    assert c.patch(f"/runs/{ids['run']}", json={'status': 'passed'}).status_code == 403
    session = c.get('/auth/session')
    assert session.headers['cache-control'] == 'no-store'
    c.headers['X-CSRF-Token'] = session.json()['csrf_token']
    assert c.post('/auth/logout').status_code == 200
    c.cookies.set(COOKIE, old)
    assert c.get('/projects').status_code == 401
    c = login('editor')
    with SessionLocal() as db:
        db.execute(update(AuthSession).where(AuthSession.token_hash == token_hash(c.cookies.get(COOKIE))).values(expires_at=int(time.time()) - 1))
        db.commit()
    assert c.get('/projects').status_code == 401
    c = login('editor')
    with SessionLocal() as db:
        db.execute(update(User).where(User.id == users['editor'].id).values(disabled=True))
        db.commit()
    assert c.get('/projects').status_code == 401


def test_membership_changes_apply_to_existing_session(accounts):
    users, ids, login = accounts
    owner, editor = login('owner'), login('editor')
    path = f"/projects/{ids['project']}/members"
    assert editor.get(path).status_code == 403
    assert owner.put(path, json={'username': users['owner'].username, 'role': 'viewer'}).status_code == 409
    assert owner.delete(path + f"/{users['owner'].id}").status_code == 409
    assert owner.put(path, json={'username': users['editor'].username, 'role': 'viewer'}).status_code == 200
    assert editor.patch(f"/runs/{ids['run']}", json={'status': 'passed'}).status_code == 403
    assert owner.delete(path + f"/{users['editor'].id}").status_code == 200
    assert editor.get(f"/runs/{ids['run']}/violations").status_code == 404
    assert editor.get('/projects').json() == []


def test_creator_is_owner_and_admin_can_recover_existing_projects(accounts):
    users, ids, login = accounts
    outsider = login('outsider')
    created = outsider.post('/projects', json={'name': uuid.uuid4().hex, 'process_node': '5nm', 'foundry': 'test'}).json()
    members = outsider.get(f"/projects/{created['id']}/members").json()
    assert members == [{'username': users['outsider'].username, 'user_id': users['outsider'].id, 'role': 'owner', 'disabled': False}]
    assert login('admin').get(f"/projects/{ids['project']}/members").status_code == 200


def test_login_protection_and_secure_cookie(client, accounts, monkeypatch):
    users, ids, login = accounts
    payload = {'username': users['viewer'].username, 'password': PASSWORD}
    assert client.post('/auth/login', json=payload).status_code == 403
    monkeypatch.setenv('SIGNOFF_COOKIE_SECURE', 'true')
    response = client.post('/auth/login', json=payload, headers={'X-Signoff-Client': '1'})
    cookie = response.headers['set-cookie'].lower()
    assert all(flag in cookie for flag in ['secure', 'httponly', 'samesite=strict', 'max-age=43200'])
    client.cookies.clear()
    bad = {**payload, 'password': 'wrong-password'}
    for _ in range(7):
        assert client.post('/auth/login', json=bad, headers={'X-Signoff-Client': '1'}).status_code == 401
    assert client.post('/auth/login', json=bad, headers={'X-Signoff-Client': '1'}).status_code == 429


def test_password_hash_and_session_storage(accounts):
    users, ids, login = accounts
    c = login('viewer')
    assert verify_password(PASSWORD, HASH)
    assert not verify_password('incorrect', HASH)
    assert password_hash(PASSWORD) != HASH
    with SessionLocal() as db:
        session = db.scalar(select(AuthSession).where(AuthSession.user_id == users['viewer'].id))
        assert session.token_hash == token_hash(c.cookies.get(COOKIE))
        assert session.token_hash != c.cookies.get(COOKIE)


def test_relogin_rotates_cookie_and_csrf(accounts):
    users, ids, login = accounts
    c = login('editor')
    old_token = c.cookies.get(COOKIE)
    response = c.post('/auth/login', json={'username': users['editor'].username, 'password': PASSWORD})
    assert response.status_code == 200
    assert c.cookies.get(COOKIE) != old_token
    assert c.patch(f"/runs/{ids['run']}", json={'status': 'passed'}).status_code == 403
    c.headers['X-CSRF-Token'] = response.json()['csrf_token']
    assert c.patch(f"/runs/{ids['run']}", json={'status': 'passed'}).status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(AuthSession.id).where(AuthSession.token_hash == token_hash(old_token))) is None
    assert c.get('/projects').headers['cache-control'] == 'no-store'


def test_cli_reset_and_disable_revoke_sessions(accounts, monkeypatch):
    from app.accounts import main
    users, ids, login = accounts
    c = login('editor')
    username = users['editor'].username
    monkeypatch.setattr('app.accounts.read_password', lambda: 'replacement-long-passphrase')
    main(['reset-password', username])
    assert c.get('/projects').status_code == 401
    response = c.post('/auth/login', json={'username': username, 'password': 'replacement-long-passphrase'})
    assert response.status_code == 200
    main(['disable-user', username])
    assert c.get('/projects').status_code == 401
    main(['enable-user', username])
    assert c.get('/projects').status_code == 401  # Enabling does not revive old sessions.
    assert c.post('/auth/login', json={'username': username, 'password': 'replacement-long-passphrase'}).status_code == 200
    main(['revoke-sessions'])
    assert c.get('/projects').status_code == 401


def test_legacy_waiver_keeps_unverified_attribution(accounts):
    users, ids, login = accounts
    with SessionLocal() as db:
        violation = db.get(Violation, ids['violation'])
        violation.status = 'waived'
        violation.waiver = Waiver(reason='legacy evidence', approved_by=users['owner'].username)
        db.commit()
    c = login('approver')
    response = c.patch(f"/violations/{ids['violation']}", json={'expected_status': 'waived', 'expected_version': 1, 'status': 'open', 'actor': 'spoof', 'reason': 'new review'})
    assert response.status_code == 200
    history = c.get(f"/violations/{ids['violation']}/history").json()
    assert history[0]['actor_user_id'] is None
    assert history[0]['actor'] == users['owner'].username
    assert history[1]['actor_user_id'] == users['approver'].id


def test_agent_conversations_are_scoped_to_account(accounts, monkeypatch):
    users, ids, login = accounts
    sessions = []
    async def chat(self, role, text, *, session_id):
        sessions.append(session_id)
        return 'test'
    monkeypatch.setattr('app.hermes.HermesClient.chat', chat)
    monkeypatch.setattr('app.hermes.a1_should_review', lambda result: True)
    for role in ['viewer', 'editor']:
        response = login(role).post('/agents/review/rtl', json={'rtl_signoff_result': {'run_id': ids['run']}})
        assert response.status_code == 200
        assert response.json()['available']
    assert sessions[0].startswith(str(users['viewer'].id) + ':')
    assert sessions[1].startswith(str(users['editor'].id) + ':')
    assert sessions[0] != sessions[1]


NEW_PASSWORD = 'replacement-self-service-passphrase'


def test_password_change_rotates_current_and_revokes_other_sessions(accounts):
    users, ids, login = accounts
    current, other, unrelated = login('editor'), login('editor'), login('viewer')
    old_cookie = current.cookies.get(COOKIE)
    old_csrf = current.headers['X-CSRF-Token']
    response = current.post('/auth/password', json={'current_password': PASSWORD, 'new_password': NEW_PASSWORD})
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    assert current.cookies.get(COOKIE) != old_cookie
    assert response.json()['csrf_token'] != old_csrf
    assert current.get('/projects').status_code == 200
    assert other.get('/projects').status_code == 401
    assert unrelated.get('/projects').status_code == 200
    assert current.patch(f"/runs/{ids['run']}", json={'status': 'passed'}).status_code == 403
    current.headers['X-CSRF-Token'] = response.json()['csrf_token']
    assert current.patch(f"/runs/{ids['run']}", json={'status': 'passed'}).status_code == 200
    assert other.post('/auth/login', json={'username': users['editor'].username, 'password': PASSWORD}).status_code == 401
    assert other.post('/auth/login', json={'username': users['editor'].username, 'password': NEW_PASSWORD}).status_code == 200


def test_password_change_rejects_invalid_inputs_without_revocation(accounts):
    users, ids, login = accounts
    current, other = login('editor'), login('editor')
    old_cookie = current.cookies.get(COOKIE)
    for payload, status in [
        ({'current_password': 'wrong-secret-value', 'new_password': NEW_PASSWORD}, 400),
        ({'current_password': PASSWORD, 'new_password': PASSWORD}, 400),
        ({'current_password': PASSWORD, 'new_password': 'short-secret'}, 422),
        ({'current_password': PASSWORD, 'new_password': NEW_PASSWORD * 20}, 422),
    ]:
        response = current.post('/auth/password', json=payload)
        assert response.status_code == status
        assert all(secret not in response.text for secret in payload.values())
        assert current.cookies.get(COOKIE) == old_cookie
        assert other.get('/projects').status_code == 200
    with SessionLocal() as db:
        assert verify_password(PASSWORD, db.get(User, users['editor'].id).password_hash)


def test_password_change_requires_session_csrf_and_is_throttled(client, accounts, monkeypatch):
    _, _, login = accounts
    payload = {'current_password': 'wrong-password', 'new_password': NEW_PASSWORD}
    client.cookies.clear()
    assert client.post('/auth/password', json=payload).status_code == 401
    c = login('editor')
    csrf = c.headers.pop('X-CSRF-Token')
    assert c.post('/auth/password', json=payload).status_code == 403
    c.headers['X-CSRF-Token'] = csrf
    for _ in range(8):
        assert c.post('/auth/password', json=payload).status_code == 400
    response = c.post('/auth/password', json=payload)
    assert response.status_code == 429
    assert response.headers['retry-after'] == '300'
    monkeypatch.setenv('SIGNOFF_AUTH_MODE', 'local')
    assert c.post('/auth/password', json=payload).status_code == 409


def test_auth_validation_never_echoes_passwords(client, accounts):
    for path, payload in [
        ('/auth/login', {'username': 'invalid username', 'password': {'secret': PASSWORD}}),
        ('/auth/password', {'current_password': {'secret': PASSWORD}, 'new_password': 'short-secret'}),
    ]:
        response = client.post(path, json=payload)
        assert response.status_code == 422
        assert PASSWORD not in response.text
        assert 'short-secret' not in response.text
        assert all(set(error) == {'loc', 'msg', 'type'} for error in response.json()['detail'])


@pytest.mark.parametrize('operation', ['login', 'password'])
@pytest.mark.parametrize('intervening', ['reset-password', 'disable-user'])
def test_stale_credentials_cannot_create_session_after_operator_change(accounts, monkeypatch, operation, intervening):
    from app.accounts import main
    users, _, login = accounts
    c = login('editor')
    username = users['editor'].username
    monkeypatch.setattr('app.accounts.read_password', lambda: 'operator-replacement-passphrase')
    original_verify = verify_password
    def intervening_change(password, encoded):
        result = original_verify(password, encoded)
        main([intervening, username])
        return result
    monkeypatch.setattr('app.routers.auth.verify_password', intervening_change)
    payload = {'username': username, 'password': PASSWORD} if operation == 'login' else {'current_password': PASSWORD, 'new_password': NEW_PASSWORD}
    response = c.post('/auth/' + operation, json=payload)
    assert response.status_code == (401 if operation == 'login' else 409), response.text
    with SessionLocal() as db:
        assert db.scalar(select(AuthSession.id).where(AuthSession.user_id == users['editor'].id)) is None
        user = db.get(User, users['editor'].id)
        assert user.disabled if intervening == 'disable-user' else original_verify('operator-replacement-passphrase', user.password_hash)


def test_password_change_commit_failure_rolls_back_credentials_and_sessions(accounts, monkeypatch):
    from sqlalchemy.orm import Session
    _, _, login = accounts
    current, other = login('editor'), login('editor')
    old_cookie = current.cookies.get(COOKIE)
    original_commit = Session.commit
    def failing_commit(db):
        if any(isinstance(item, AuthSession) for item in db.new):
            raise RuntimeError('simulated storage failure')
        return original_commit(db)
    monkeypatch.setattr(Session, 'commit', failing_commit)
    assert current.post('/auth/password', json={'current_password': PASSWORD, 'new_password': NEW_PASSWORD}).status_code == 500
    monkeypatch.setattr(Session, 'commit', original_commit)
    assert current.cookies.get(COOKIE) == old_cookie
    assert current.get('/projects').status_code == 200
    assert other.get('/projects').status_code == 200
    assert login('editor').get('/projects').status_code == 200
