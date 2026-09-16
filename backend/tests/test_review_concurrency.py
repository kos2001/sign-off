from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine, event, inspect

from app.db import engine
from app.migrations import initialize_schema
from test_violation_lifecycle import issue


def transition(client, vid, version, before, after, actor='Reviewer'):
    return client.patch(f'/violations/{vid}', json={
        'expected_version': version, 'expected_status': before, 'status': after,
        'actor': actor, 'reason': f'{actor} evidence',
    })


def test_status_roundtrip_rejects_old_review_even_when_status_matches(client, issue):
    _, rid, vid = issue
    original = client.get(f'/runs/{rid}/violations').json()[0]
    assert original['version'] == 1
    assert transition(client, vid, 1, 'open', 'fixed').json()['version'] == 2
    assert transition(client, vid, 2, 'fixed', 'open').json()['version'] == 3
    assert transition(client, vid, 1, 'open', 'waived', 'Stale reviewer').status_code == 409
    assert client.post(f'/violations/{vid}/waiver', json={
        'expected_version': 1, 'approved_by': 'Stale reviewer', 'reason': 'Old evidence',
    }).status_code == 409
    current = client.get(f'/runs/{rid}/violations').json()[0]
    assert current['status'] == 'open' and current['version'] == 3 and current['waiver'] is None
    assert len(client.get(f'/violations/{vid}/history').json()) == 2
    assert transition(client, vid, 3, 'open', 'waived').json()['version'] == 4


def test_two_simultaneous_reviews_commit_exactly_one_event(client, issue):
    _, rid, vid = issue
    barrier = Barrier(2)
    def synchronize(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith('UPDATE violations SET'):
            barrier.wait(timeout=10)
    event.listen(engine, 'before_cursor_execute', synchronize)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(transition, client, vid, 1, 'open', status, actor) for status, actor in [('fixed', 'A'), ('waived', 'B')]]
            responses = [future.result(timeout=15) for future in futures]
    finally:
        event.remove(engine, 'before_cursor_execute', synchronize)
    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = next(response.json() for response in responses if response.status_code == 200)
    current = client.get(f'/runs/{rid}/violations').json()[0]
    assert current['version'] == 2
    assert current['status'] == winner['status']
    assert (current['waiver'] is not None) == (winner['status'] == 'waived')
    assert len(client.get(f'/violations/{vid}/history').json()) == 1


@pytest.mark.parametrize('version', [None, 0, -1, True, '1', 1.5, 2**100])
def test_both_write_apis_require_valid_version(client, issue, version):
    _, _, vid = issue
    expected = {} if version is None else {'expected_version': version}
    patch = {'expected_status': 'open', 'status': 'fixed', 'actor': 'A', 'reason': 'Evidence', **expected}
    waiver = {'approved_by': 'A', 'reason': 'Evidence', **expected}
    assert client.patch(f'/violations/{vid}', json=patch).status_code == 422
    assert client.post(f'/violations/{vid}/waiver', json=waiver).status_code == 422
    assert client.get(f'/violations/{vid}/history').json() == []


def test_additive_migration_preserves_legacy_review_and_is_concurrently_repeatable(tmp_path):
    import sqlite3
    from sqlalchemy.orm import Session
    from app.models import Violation
    path = tmp_path / 'legacy-review.db'
    with sqlite3.connect(path) as db:
        db.executescript('''
            CREATE TABLE violations (id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, check_name VARCHAR(120) NOT NULL,
                severity VARCHAR(8) NOT NULL, location VARCHAR(200), description TEXT, status VARCHAR(6) NOT NULL);
            INSERT INTO violations VALUES (1, 1, 'Original check', 'critical', 'u_core', 'Original evidence', 'open');
        ''')
    engines = [create_engine(f'sqlite:///{path}', connect_args={'timeout': 15}) for _ in range(2)]
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(initialize_schema, engines))
        initialize_schema(engines[0])
        assert sum(col['name'] == 'version' for col in inspect(engines[0]).get_columns('violations')) == 1
        with Session(engines[0]) as db:
            row = db.get(Violation, 1)
            assert row.version == 1
            assert row.check_name == 'Original check' and row.description == 'Original evidence'
    finally:
        for db_engine in engines:
            db_engine.dispose()


def test_failed_commit_rolls_back_version_waiver_and_history(client, issue, monkeypatch):
    from sqlalchemy.orm import Session
    _, _, vid = issue
    before = client.get(f'/violations/{vid}').json()
    def fail_commit(session):
        raise RuntimeError('simulated commit failure')
    with monkeypatch.context() as patch:
        patch.setattr(Session, 'commit', fail_commit)
        assert transition(client, vid, 1, 'open', 'waived').status_code == 500
    assert client.get(f'/violations/{vid}').json() == before
    assert client.get(f'/violations/{vid}/history').json() == []
    assert transition(client, vid, 1, 'open', 'fixed').status_code == 200
    assert client.get(f'/violations/{vid}').json()['version'] == 2
    assert client.get('/violations/99999999').status_code == 404
