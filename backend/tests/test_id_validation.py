"""Reject invalid identifiers before authorization can query the database."""
import pytest

from app.db import SessionLocal
from app.models import Violation
from test_auth import accounts


INVALID_IDS = ['abc', '0', '-1', str(2**63), '9' * 100, '1.5', 'true', '１２']


@pytest.mark.parametrize('required', [False, True])
def test_path_ids_rejected_in_both_auth_modes(client, accounts, monkeypatch, required):
    _, ids, login = accounts
    caller = login('owner') if required else client
    monkeypatch.setenv('SIGNOFF_AUTH_MODE', 'required' if required else 'local')
    routes = [
        ('GET', '/projects/{}'),
        ('GET', '/runs/{}/evidence'),
        ('GET', '/violations/{}'),
        ('GET', f"/runs/{ids['run']}/agent-reviews/{{}}"),
        ('DELETE', f"/projects/{ids['project']}/members/{{}}"),
    ]
    for method, template in routes:
        for value in INVALID_IDS:
            response = caller.request(method, template.format(value))
            assert response.status_code == 422, (method, template, value, response.text)
    for path in ['/projects/{}', '/runs/{}/evidence', '/violations/{}']:
        assert caller.get(path.format(2**63 - 1)).status_code == 404
    assert caller.get(f"/projects/{ids['project']}").status_code == 200


def test_authentication_and_csrf_still_precede_id_validation(client, accounts):
    assert client.get('/runs/invalid/evidence').status_code == 401
    caller = accounts[2]('editor')
    caller.headers.pop('X-CSRF-Token')
    assert caller.patch('/violations/invalid', json=[]).status_code == 403


@pytest.mark.parametrize('required', [False, True])
def test_invalid_analysis_project_ids_never_execute(client, accounts, monkeypatch, required):
    caller = accounts[2]('editor') if required else client
    monkeypatch.setenv('SIGNOFF_AUTH_MODE', 'required' if required else 'local')
    def forbidden(*args, **kwargs):
        pytest.fail('invalid input reached RTL execution')
    monkeypatch.setattr('app.routers.analysis.acquire_slot', forbidden)
    for endpoint in ['/analysis/rtl-signoff', '/analysis/rtl-signoff/stream']:
        for value in [True, False, 1.5, '1', 0, -1, 2**63, 10**100]:
            response = caller.post(endpoint, json={'project_id': value, 'code': 'module top; endmodule'})
            assert response.status_code == 422, (endpoint, value, response.text)


def test_nonobject_or_malformed_bodies_are_client_errors(accounts):
    _, ids, login = accounts
    caller = login('approver')
    routes = [
        ('PATCH', f"/violations/{ids['violation']}"),
        ('POST', f"/violations/{ids['violation']}/waiver"),
        ('POST', '/analysis/rtl-signoff'),
    ]
    for method, path in routes:
        for content in ['[]', 'null', 'true', '1', '"text"', '{broken', b'\xff']:
            response = caller.request(method, path, content=content, headers={'Content-Type': 'application/json'})
            expected = 400 if isinstance(content, bytes) else 422
            assert response.status_code == expected, (method, path, content, response.text)
    with SessionLocal() as db:
        violation = db.get(Violation, ids['violation'])
        assert violation.status.value == 'open'
        assert violation.waiver is None


def test_query_database_ids_are_bounded(accounts):
    _, ids, login = accounts
    caller = login('admin')
    for field in ['baseline_run_id', 'candidate_run_id']:
        params = {'baseline_run_id': ids['run'], 'candidate_run_id': ids['run'], field: 2**63}
        assert caller.get(f"/projects/{ids['project']}/run-comparison", params=params).status_code == 422
    for path in ['/auth/security-events', '/auth/admin/security-events', f"/projects/{ids['project']}/members/history"]:
        assert caller.get(path, params={'before_id': 2**63}).status_code == 422
        assert caller.get(path, params={'before_id': 2**63 - 1}).status_code == 200
