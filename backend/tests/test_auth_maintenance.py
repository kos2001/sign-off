import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, event, inspect, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import Delete

from app.auth_maintenance import cleanup_expired, main
from app.db import Base
from app.models import AuthSession, LoginBucket, User, AccountSecurityEvent
from app.migrations import initialize_schema


@pytest.fixture
def state(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path}/maintenance.db')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(username='maintenance', password_hash='fixture')
        db.add(user)
        db.flush()
        for i, expires in enumerate([98, 99, 100, 101]):
            db.add(AuthSession(user_id=user.id, token_hash=f'token-{i}', csrf_token=f'csrf-{i}', expires_at=expires))
            db.add(LoginBucket(key=f'bucket-{i}', attempts=8, expires_at=expires))
        db.add(AccountSecurityEvent(subject_user_id=user.id, actor='fixture', source='api', action='login'))
        db.commit()
    yield engine
    engine.dispose()


def test_preview_bounded_cleanup_and_expiry_boundary(state):
    with Session(state) as db:
        preview = cleanup_expired(db, cutoff=100, limit=2)
        assert all(value == {'count': 2, 'more_at_selection': True} for value in preview.values())
        assert len(list(db.scalars(select(AuthSession)))) == 4
        assert cleanup_expired(db, cutoff=100, limit=2, apply=True) == preview
        db.commit()
        second = cleanup_expired(db, cutoff=100, limit=2, apply=True)
        assert all(value == {'count': 1, 'more_at_selection': False} for value in second.values())
        db.commit()
        assert list(db.scalars(select(AuthSession.expires_at))) == [101]
        assert list(db.scalars(select(LoginBucket.expires_at))) == [101]
        assert db.scalar(select(LoginBucket.attempts)) == 8
        assert len(list(db.scalars(select(AccountSecurityEvent)))) == 1


def test_failure_rolls_back_both_tables(state, monkeypatch):
    with Session(state) as db:
        execute = db.execute
        def fail_buckets(statement, *args, **kwargs):
            if isinstance(statement, Delete) and statement.table.name == 'login_buckets':
                raise RuntimeError('injected storage failure')
            return execute(statement, *args, **kwargs)
        monkeypatch.setattr(db, 'execute', fail_buckets)
        with pytest.raises(RuntimeError):
            cleanup_expired(db, cutoff=100, apply=True)
        db.rollback()
    with Session(state) as db:
        assert len(list(db.scalars(select(AuthSession)))) == 4
        assert len(list(db.scalars(select(LoginBucket)))) == 4


def test_bucket_renewed_after_selection_is_preserved(state, monkeypatch):
    with Session(state) as db:
        execute = db.execute
        def renew_before_delete(statement, *args, **kwargs):
            if isinstance(statement, Delete) and statement.table.name == 'login_buckets':
                execute(update(LoginBucket).where(LoginBucket.key == 'bucket-0').values(expires_at=400, attempts=1))
            return execute(statement, *args, **kwargs)
        monkeypatch.setattr(db, 'execute', renew_before_delete)
        result = cleanup_expired(db, cutoff=100, apply=True)
        db.commit()
        assert result['login_buckets']['count'] == 2
        bucket = db.scalar(select(LoginBucket).where(LoginBucket.key == 'bucket-0'))
        assert bucket.expires_at == 400 and bucket.attempts == 1


def test_cli_defaults_to_preview_and_commits_only_with_apply(state, monkeypatch, capsys):
    monkeypatch.setattr('app.auth_maintenance.SessionLocal', lambda: Session(state))
    monkeypatch.setattr('app.auth_maintenance.time.time', lambda: 100)
    main(['--limit', '2'])
    output = capsys.readouterr().out
    assert json.loads(output)['mode'] == 'preview'
    assert 'token-' not in output and 'csrf-' not in output and 'bucket-' not in output
    with Session(state) as db:
        assert len(list(db.scalars(select(AuthSession)))) == 4
    main(['--limit', '2', '--apply'])
    assert json.loads(capsys.readouterr().out)['mode'] == 'apply'
    with Session(state) as db:
        assert len(list(db.scalars(select(AuthSession)))) == 2


@pytest.mark.parametrize('limit', [0, -1, 1001, True])
def test_invalid_limit_never_mutates(state, limit):
    with Session(state) as db:
        with pytest.raises(ValueError):
            cleanup_expired(db, cutoff=100, limit=limit, apply=True)
        assert len(list(db.scalars(select(AuthSession)))) == 4


def test_expiry_indexes_upgrade_existing_db_concurrently_and_preserve_rows(state):
    with state.begin() as connection:
        connection.exec_driver_sql('DROP INDEX ix_auth_sessions_expiry_id')
        connection.exec_driver_sql('DROP INDEX ix_login_buckets_expiry_id')
        before = {table: connection.exec_driver_sql(f'SELECT * FROM {table} ORDER BY id').fetchall()
                  for table in ['auth_sessions', 'login_buckets', 'account_security_events']}
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(initialize_schema, [state] * 3))
    initialize_schema(state)
    with state.connect() as connection:
        for table, expected in before.items():
            assert connection.exec_driver_sql(f'SELECT * FROM {table} ORDER BY id').fetchall() == expected
        for table in ['auth_sessions', 'login_buckets']:
            indexes = inspect(connection).get_indexes(table)
            assert any(index['column_names'] == ['expires_at', 'id'] for index in indexes)


def test_cleanup_uses_index_range_without_sort_and_oldest_expiry_first(state):
    # Most rows are still valid; old expiration times have newer IDs.
    with Session(state) as db:
        user_id = db.scalar(select(User.id))
        db.add_all([AuthSession(user_id=user_id, token_hash=f'bulk-{i}', csrf_token='fixture', expires_at=500)
                    for i in range(2000)])
        db.add_all([LoginBucket(key=f'bulk-{i}', attempts=1, expires_at=500) for i in range(2000)])
        for model in [AuthSession, LoginBucket]:
            db.execute(update(model).where(model.id == 3).values(expires_at=1))
        db.commit()
    captured = []
    def observe(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith('SELECT') and 'expires_at' in statement:
            captured.append((statement, parameters))
    event.listen(state, 'before_cursor_execute', observe)
    try:
        with Session(state) as db:
            cleanup_expired(db, cutoff=100, limit=1, apply=True)
            db.commit()
    finally:
        event.remove(state, 'before_cursor_execute', observe)
    assert len(captured) == 2
    with state.connect() as connection:
        for statement, parameters in captured:
            plan = ' '.join(str(row) for row in connection.exec_driver_sql('EXPLAIN QUERY PLAN ' + statement, parameters))
            assert 'SEARCH' in plan and 'COVERING INDEX' in plan and 'expires_at<?' in plan
            assert 'TEMP B-TREE' not in plan and 'SCAN ' not in plan
    with Session(state) as db:
        for model in [AuthSession, LoginBucket]:
            assert db.get(model, 3) is None
            assert db.get(model, 1) is not None
