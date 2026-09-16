import pytest
from sqlalchemy import select

from app.db import SessionLocal, get_db
from app.models import ProjectAccessEvent, ProjectMember
from test_auth import accounts  # noqa: F401 — shared isolated account fixture


def test_membership_lifecycle_audits_actor_and_keeps_removed_subject(accounts):
    users, ids, login = accounts
    owner = login('owner')
    path = f"/projects/{ids['project']}/members"
    body = {'username': users['outsider'].username, 'role': 'viewer', 'actor': 'spoofed', 'actor_user_id': users['admin'].id}
    assert owner.put(path, json=body).status_code == 200
    assert owner.put(path, json=body).status_code == 200  # No-op is not a role change.
    assert owner.put(path, json={**body, 'role': 'editor'}).status_code == 200
    assert owner.delete(path + f"/{users['outsider'].id}").status_code == 200
    assert owner.delete(path + f"/{users['outsider'].id}").status_code == 200
    events = owner.get(path + '/history').json()['items']
    assert [(e['before_role'], e['after_role']) for e in events] == [('editor', None), ('viewer', 'editor'), (None, 'viewer')]
    assert all(e['actor_user_id'] == users['owner'].id and e['actor'] == users['owner'].username for e in events)
    assert all(e['subject_user_id'] == users['outsider'].id and e['subject_username'] == users['outsider'].username for e in events)
    assert all(e['source'] == 'api' and e['created_at'] for e in events)
    assert not any(m['user_id'] == users['outsider'].id for m in owner.get(path).json())
    assert owner.patch(path + '/history', json={'actor': 'rewrite'}).status_code == 405
    assert owner.delete(path + '/history').status_code in [405, 422]
    assert owner.get(path + '/history').json()['items'] == events


def test_history_owner_only_and_cursor_stable_with_new_events(accounts):
    users, ids, login = accounts
    owner = login('owner')
    path = f"/projects/{ids['project']}/members"
    for index in range(7):
        assert owner.put(path, json={'username': users['editor'].username, 'role': 'viewer' if index % 2 == 0 else 'editor'}).status_code == 200
    first = owner.get(path + '/history?limit=3').json()
    assert len(first['items']) == 3
    assert first['next_before_id'] == first['items'][-1]['id']
    assert owner.put(path, json={'username': users['editor'].username, 'role': 'approver'}).status_code == 200
    second = owner.get(path + f"/history?before_id={first['next_before_id']}&limit=100").json()
    assert second['next_before_id'] is None
    ids_seen = [e['id'] for e in first['items'] + second['items']]
    assert len(ids_seen) == len(set(ids_seen)) == 7
    assert all(a > b for a, b in zip(ids_seen, ids_seen[1:]))
    assert login('viewer').get(path + '/history').status_code == 403
    assert login('outsider').get(path + '/history').status_code == 404
    assert owner.get(path + '/history?limit=101').status_code == 422
    assert owner.get(path + '/history?before_id=0').status_code == 422


def test_commit_failure_rolls_back_membership_and_event(accounts):
    users, ids, login = accounts
    owner = login('owner')
    def failing_db():
        with SessionLocal() as db:
            def fail():
                db.flush()
                raise RuntimeError('audit commit failed')
            db.commit = fail
            yield db
    owner.app.dependency_overrides[get_db] = failing_db
    try:
        assert owner.put(f"/projects/{ids['project']}/members", json={'username': users['editor'].username, 'role': 'viewer'}).status_code == 500
    finally:
        owner.app.dependency_overrides.pop(get_db)
    with SessionLocal() as db:
        assert db.scalar(select(ProjectMember.role).where(ProjectMember.project_id == ids['project'], ProjectMember.user_id == users['editor'].id)) == 'editor'
        assert db.scalar(select(ProjectAccessEvent.id).where(ProjectAccessEvent.project_id == ids['project'])) is None


def test_cli_grant_and_project_creation_are_recorded(accounts):
    from app.accounts import main
    users, ids, login = accounts
    main(['grant', users['editor'].username, str(ids['project']), 'approver'])
    owner = login('owner')
    event = owner.get(f"/projects/{ids['project']}/members/history").json()['items'][0]
    assert event['source'] == 'operator'
    assert event['actor_user_id'] is None
    assert (event['before_role'], event['after_role']) == ('editor', 'approver')
    created = owner.post('/projects', json={'name': users['owner'].username + '-created', 'foundry': 'test', 'process_node': '5nm'}).json()
    event = owner.get(f"/projects/{created['id']}/members/history").json()['items'][0]
    assert event['actor_user_id'] == users['owner'].id == event['subject_user_id']
    assert event['before_role'] is None and event['after_role'] == 'owner'


def test_concurrent_changes_do_not_lose_audit_order(accounts):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.services.access import MembershipConflict, change_membership
    users, ids, _ = accounts
    barrier = Barrier(2)
    def change(role):
        with SessionLocal() as db:
            original = db.scalar
            def synchronized(*args, **kwargs):
                value = original(*args, **kwargs)
                if isinstance(value, ProjectMember):
                    barrier.wait(timeout=5)
                return value
            db.scalar = synchronized
            try:
                change_membership(db, ids['project'], users['editor'], role, actor=users['owner'])
                db.commit()
                return role
            except MembershipConflict:
                db.rollback()
                return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(change, ['viewer', 'approver']))
    assert results.count('conflict') == 1
    winner = next(role for role in results if role != 'conflict')
    with SessionLocal() as db:
        events = db.scalars(select(ProjectAccessEvent).where(ProjectAccessEvent.project_id == ids['project'])).all()
        assert len(events) == 1
        assert (events[0].before_role, events[0].after_role) == ('editor', winner)
        assert db.scalar(select(ProjectMember.role).where(ProjectMember.project_id == ids['project'], ProjectMember.user_id == users['editor'].id)) == winner
