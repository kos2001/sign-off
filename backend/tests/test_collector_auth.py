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
    editor = login('editor')
    assert editor.post(path, json={}, headers={'Authorization': f'Bearer {valid}'}).status_code == 401
    client.close()


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
