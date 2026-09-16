import json

import pytest

from test_auth import accounts
from test_violation_lifecycle import issue


def transition(client, vid, version, before, after, reason='Reviewed evidence'):
    response = client.patch(f'/violations/{vid}', json={'expected_version': version,
        'expected_status': before, 'status': after, 'actor': 'Reviewer', 'reason': reason})
    assert response.status_code == 200, response.text


def test_history_export_preserves_revoked_waiver_and_current_state(client, issue):
    pid, rid, vid = issue
    for version, (before, after) in enumerate([('open', 'fixed'), ('fixed', 'open'),
                                              ('open', 'waived'), ('waived', 'open')], 1):
        transition(client, vid, version, before, after, f'근거 {version}: {after}')
    before = client.get(f'/violations/{vid}').json()
    history = client.get(f'/violations/{vid}/history').json()
    response = client.get(f'/violations/{vid}/history/export')
    assert response.status_code == 200, response.text
    bundle = response.json()
    assert bundle['format'] == 'signoff/violation-history-export/v1'
    assert bundle['exported_at'].endswith('+00:00')
    assert bundle['events'] == history and bundle['total'] == 4
    assert bundle['violation']['id'] == vid and bundle['violation']['run']['project_id'] == pid
    assert bundle['violation']['status'] == 'open' and bundle['violation']['version'] == 5
    assert bundle['violation']['waiver'] is None
    assert bundle['events'][2]['to_status'] == 'waived'
    assert bundle['events'][2]['reason'] == '근거 3: waived'
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['content-disposition'] == f'attachment; filename="violation-{vid}-history.json"'
    assert client.get(f'/violations/{vid}').json() == before
    assert client.get(f'/violations/{vid}/history').json() == history


def test_history_export_empty_and_missing(client, issue):
    _, _, vid = issue
    bundle = client.get(f'/violations/{vid}/history/export').json()
    assert bundle['events'] == [] and bundle['total'] == 0
    assert bundle['violation']['version'] == 1 and 'legacy' in bundle['coverage_note']
    assert client.get('/violations/99999999/history/export').status_code == 404


def test_history_export_refreshes_preloaded_authorization_identity(client, issue):
    from app.db import SessionLocal
    from app.models import Violation
    from app.services.violation_history_export import export_history
    _, _, vid = issue
    with SessionLocal() as db:
        old = db.get(Violation, vid)
        assert old.version == 1
        transition(client, vid, 1, 'open', 'fixed')
        assert old.version == 1
        bundle = json.loads(export_history(db, vid).body)
        assert bundle['violation']['version'] == 2
        assert bundle['violation']['status'] == bundle['events'][-1]['to_status'] == 'fixed'


@pytest.mark.parametrize('cap', ['MAX_EVENTS', 'MAX_BYTES'])
def test_history_export_refuses_partial_files(client, issue, monkeypatch, cap):
    from app.services import violation_history_export as exporter
    _, _, vid = issue
    transition(client, vid, 1, 'open', 'fixed')
    transition(client, vid, 2, 'fixed', 'open')
    monkeypatch.setattr(exporter, cap, 1)
    response = client.get(f'/violations/{vid}/history/export')
    assert response.status_code == 413
    assert 'content-disposition' not in response.headers and 'events' not in response.json()
    assert len(client.get(f'/violations/{vid}/history').json()) == 2


def test_history_export_byte_boundary(client, issue, monkeypatch):
    from datetime import datetime, timezone
    from app.services import violation_history_export as exporter
    class FixedTime:
        @staticmethod
        def now(*args):
            return datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(exporter, 'datetime', FixedTime)
    _, _, vid = issue
    transition(client, vid, 1, 'open', 'fixed', '한글\n근거')
    route = f'/violations/{vid}/history/export'
    expected = client.get(route)
    monkeypatch.setattr(exporter, 'MAX_BYTES', len(expected.content))
    assert client.get(route).content == expected.content
    monkeypatch.setattr(exporter, 'MAX_BYTES', len(expected.content) - 1)
    assert client.get(route).status_code == 413


def test_history_export_project_scope_and_authenticated_actor(accounts):
    users, ids, login = accounts
    editor, viewer, outsider = login('editor'), login('viewer'), login('outsider')
    created = editor.post(f"/runs/{ids['run']}/violations", json=[{'check_name': 'history export', 'severity': 'error'}]).json()[0]
    vid = created['id']
    transition(editor, vid, 1, 'open', 'fixed')
    route = f'/violations/{vid}/history/export'
    response = viewer.get(route)
    assert response.status_code == 200
    assert response.json()['events'][0]['actor'] == users['editor'].username
    assert response.json()['events'][0]['actor_user_id'] is not None
    assert outsider.get(route).status_code == 404
