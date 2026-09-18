import json
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth import token_hash
from app.collectors import issue_credential, main as collector_admin
from app.db import SessionLocal
from app.models import CollectorCredential, Project
from app.services.coverage_attestation import REQUIRED_CLAIMS
from app.services.collector_request import build_import_request
from test_auth import accounts
from test_report_import import commercial_report


HMAC_SECRET = 'collector-auth-hmac-secret-with-at-least-32-bytes'


def credential(project_id, *, name='primetime-prod', expires=None, revoked=False):
    token = 'soct_test_' + name + '_credential_value_1234567890'
    with SessionLocal() as db:
        item = CollectorCredential(project_id=project_id, name=name, token_hash=token_hash(token),
            expires_at=expires or int(time.time()) + 3600,
            revoked_at=datetime.now(timezone.utc) if revoked else None)
        db.add(item); db.commit(); db.refresh(item)
        return token, item.id


def request_body(project_id):
    report = {**commercial_report(slack=0.1), 'paths': []}
    return build_import_request(domain='sta', source_text=json.dumps(report) + '\n',
        filename='primetime.json', project_id=project_id, stage='routing', design_revision='release-r1',
        scenario='all-signoff-views', tool_version=report['tool_version'], key_id='collector-hmac',
        secret=HMAC_SECRET, claims={key: True for key in REQUIRED_CLAIMS['sta']})


def test_project_collector_can_only_submit_and_identity_is_preserved(accounts, monkeypatch):
    _, ids, login = accounts
    monkeypatch.setenv('SIGNOFF_COVERAGE_HMAC_KEYS', json.dumps({
        'collector-hmac': {'secret': HMAC_SECRET, 'domains': ['sta']},
    }))
    token, collector_id = credential(ids['project'])
    headers = {'Authorization': f'Bearer {token}'}
    machine = TestClient(login('outsider').app, headers=headers)
    context = machine.get(f"/projects/{ids['project']}/collector-context/routing")
    assert context.status_code == 200, context.text
    contract = context.json()
    assert contract['format'] == 'signoff/collector-context/v1'
    assert contract['signoff_plan']['required_domains'] == ['sta', 'emir', 'pv', 'lvs']
    assert contract['sta_scenario_plan']['version'] == 0
    sta = next(item for item in contract['domains'] if item['domain'] == 'sta')
    assert sta['import_path'].endswith('/imports/commercial-sta')
    assert sta['required_claims'] == sorted(REQUIRED_CLAIMS['sta'])
    response = machine.post(f"/projects/{ids['project']}/imports/commercial-sta",
        json=request_body(ids['project']))
    assert response.status_code == 201, response.text
    assert response.json()['status'] == 'passed'
    evidence = login('viewer').get(f"/runs/{response.json()['id']}/evidence").json()
    assert evidence['result']['submitted_by'] == {'collector_id': collector_id, 'name': 'primetime-prod'}
    assert token not in json.dumps(evidence)
    assert machine.post(f"/projects/{ids['project']}/imports/commercial-sta/preview",
        json=request_body(ids['project'])).status_code == 401
    assert machine.get(f"/projects/{ids['project']}").status_code == 401
    unsigned = request_body(ids['project']); unsigned.pop('coverage_attestation')
    rejected = machine.post(f"/projects/{ids['project']}/imports/commercial-sta", json=unsigned)
    assert rejected.status_code == 422 and 'coverage attestation' in rejected.json()['detail']
    machine.close()


def test_collector_rejects_cross_project_expired_revoked_unknown_and_cookie_mix(accounts):
    _, ids, login = accounts
    with SessionLocal() as db:
        other = Project(name='collector-other-project', foundry='QA', process_node='5nm')
        db.add(other); db.commit(); db.refresh(other)
    tokens = [
        credential(ids['project'], name='expired', expires=int(time.time()) - 1)[0],
        credential(ids['project'], name='revoked', revoked=True)[0],
        'soct_unknown_credential_value_12345678901234567890',
    ]
    client = TestClient(login('outsider').app)
    path = f"/projects/{ids['project']}/imports/commercial-sta"
    for token in tokens:
        response = client.post(path, json={}, headers={'Authorization': f'Bearer {token}'})
        assert response.status_code == 401 and token not in response.text
    valid, _ = credential(ids['project'], name='cross-project')
    assert client.post(f"/projects/{other.id}/imports/commercial-sta", json={},
        headers={'Authorization': f'Bearer {valid}'}).status_code == 401
    assert client.get(f"/projects/{other.id}/collector-context/routing",
        headers={'Authorization': f'Bearer {valid}'}).status_code == 401
    editor = login('editor')
    assert editor.post(path, json={}, headers={'Authorization': f'Bearer {valid}'}).status_code == 401
    client.close()


def test_project_user_can_read_collector_context(accounts):
    _, ids, login = accounts
    approver = login('approver')
    assert approver.put(f"/projects/{ids['project']}/signoff-plan/final", json={
        'expected_version': 0, 'required_domains': ['sta', 'low_power'],
        'reason': 'UPF design final contract',
    }).status_code == 200
    assert approver.put(f"/projects/{ids['project']}/sta-scenario-plan/final", json={
        'expected_version': 0,
        'scenarios': [{'name': 'ss-functional', 'require_spef': True}],
        'reason': 'final extracted timing contract',
    }).status_code == 200
    response = login('viewer').get(f"/projects/{ids['project']}/collector-context/final")
    assert response.status_code == 200
    contract = response.json()
    assert contract['stage'] == 'final' and contract['signoff_plan']['version'] == 1
    assert [item['domain'] for item in contract['domains']] == ['sta', 'low_power']
    assert contract['sta_scenario_plan']['version'] == 1
    assert contract['sta_scenario_plan']['scenarios'] == [
        {'name': 'ss-functional', 'require_spef': True}]
    assert login('outsider').get(
        f"/projects/{ids['project']}/collector-context/final").status_code == 404


def test_issue_credential_stores_only_hash_and_enforces_scope(accounts):
    _, ids, _ = accounts
    with SessionLocal() as db:
        item, token = issue_credential(db, ids['project'], 'voltus-prod', 30)
        db.commit()
        assert item.token_hash == token_hash(token) and token not in item.token_hash
        assert item.project_id == ids['project'] and item.expires_at > int(time.time())
    with SessionLocal() as db:
        with pytest.raises(ValueError, match='already exists'):
            issue_credential(db, ids['project'], 'voltus-prod', 30)
        db.rollback()
        with pytest.raises(ValueError, match='valid-days'):
            issue_credential(db, ids['project'], 'new-name', 0)


def test_operator_can_issue_list_and_revoke_without_revealing_token_again(accounts, capsys):
    _, ids, _ = accounts
    collector_admin(['create', str(ids['project']), 'calibre-prod', '--valid-days', '30'])
    created = json.loads(capsys.readouterr().out)
    assert created['token'].startswith('soct_') and created['name'] == 'calibre-prod'
    collector_admin(['list', str(ids['project'])])
    listed = json.loads(capsys.readouterr().out)
    item = next(row for row in listed if row['name'] == 'calibre-prod')
    assert 'token' not in item and item['revoked_at'] is None
    collector_admin(['revoke', str(ids['project']), 'calibre-prod'])
    assert capsys.readouterr().out == 'Collector credential revoked.\n'
    with SessionLocal() as db:
        stored = db.get(CollectorCredential, created['id'])
        assert stored.revoked_at is not None and stored.token_hash == token_hash(created['token'])
