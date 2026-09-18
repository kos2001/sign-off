import json
import uuid

from sqlalchemy import update

from app.db import SessionLocal
from app.models import RunEvidence
from test_auth import accounts


def new_project(client):
    response = client.post('/projects', json={
        'name': f'target-{uuid.uuid4().hex}', 'process_node': '3nm', 'foundry': 'QA',
    })
    assert response.status_code == 201
    return response.json()['id']


def add_revision_run(client, project_id, revision, tool):
    response = client.post(f'/projects/{project_id}/runs', json={
        'domain': 'sta', 'stage': 'placement', 'tool': tool,
    })
    assert response.status_code == 201
    run = response.json()
    with SessionLocal.begin() as db:
        db.execute(update(RunEvidence).where(RunEvidence.run_id == run['id'])
                   .values(design_revision=revision))
    return run


def test_target_revision_pins_gate_export_and_can_be_cleared(client):
    project_id = new_project(client)
    older = add_revision_run(client, project_id, 'rev-A', 'PrimeTime A')
    newer = add_revision_run(client, project_id, 'rev-B', 'PrimeTime B')
    default_gate = client.get(f'/projects/{project_id}/signoff-status?stage=placement').json()
    assert next(item for item in default_gate['domains'] if item['domain'] == 'sta')['run_id'] == newer['id']
    assert default_gate['target_revision']['version'] == 0

    pinned = client.put(f'/projects/{project_id}/target-revisions/placement', json={
        'expected_version': 0, 'design_revision': 'rev-A', 'reason': 'release candidate A',
    })
    assert pinned.status_code == 200, pinned.text
    assert pinned.json()['version'] == 1 and pinned.json()['updated_by'] == 'local operator'
    gate = client.get(f'/projects/{project_id}/signoff-status?stage=placement').json()
    assert gate['target_revision']['design_revision'] == 'rev-A'
    assert next(item for item in gate['domains'] if item['domain'] == 'sta')['run_id'] == older['id']
    exported = json.loads(client.get(
        f'/projects/{project_id}/signoff-status/export?stage=placement').content)
    assert exported['gate']['target_revision']['design_revision'] == 'rev-A'
    assert [run['id'] for run in exported['runs']] == [older['id']]
    context = client.get(f'/projects/{project_id}/collector-context/placement').json()
    assert context['target_revision']['design_revision'] == 'rev-A'

    assert client.put(f'/projects/{project_id}/target-revisions/placement', json={
        'expected_version': 0, 'design_revision': 'rev-B', 'reason': 'stale',
    }).status_code == 409
    cleared = client.put(f'/projects/{project_id}/target-revisions/placement', json={
        'expected_version': 1, 'design_revision': None, 'reason': 'resume latest',
    })
    assert cleared.status_code == 200 and cleared.json()['version'] == 2
    assert next(item for item in client.get(
        f'/projects/{project_id}/signoff-status?stage=placement').json()['domains']
                if item['domain'] == 'sta')['run_id'] == newer['id']
    history = client.get(f'/projects/{project_id}/target-revisions/history?stage=placement').json()
    assert [(item['version'], item['design_revision']) for item in history['items']] == [
        (2, None), (1, 'rev-A')]


def test_target_revision_requires_approver(accounts):
    _, ids, login = accounts
    editor = login('editor')
    response = editor.put(f"/projects/{ids['project']}/target-revisions/final", json={
        'expected_version': 0, 'design_revision': 'candidate', 'reason': 'editor cannot pin',
    })
    assert response.status_code == 403
    approver = login('approver')
    response = approver.put(f"/projects/{ids['project']}/target-revisions/final", json={
        'expected_version': 0, 'design_revision': 'candidate', 'reason': 'release scope',
    })
    assert response.status_code == 200
    assert response.json()['updated_by_user_id'] is not None
