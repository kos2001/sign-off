import json

from sqlalchemy import select

from app.db import SessionLocal
from app.models import ProjectSignoffPlanRevision
from test_auth import accounts


def test_default_plan_and_approver_versioned_update(accounts):
    users, ids, login = accounts
    viewer, editor, approver = login('viewer'), login('editor'), login('approver')
    path = f"/projects/{ids['project']}/signoff-plan"
    default = viewer.get(path)
    assert default.status_code == 200
    placement = next(item for item in default.json()['stages'] if item['stage'] == 'placement')
    assert placement == {
        'stage': 'placement', 'version': 0, 'source': 'default',
        'required_domains': ['sta', 'emir', 'pv'], 'reason': None,
        'updated_by': None, 'updated_by_user_id': None, 'created_at': None,
    }
    body = {'expected_version': 0, 'required_domains': ['sta', 'low_power'],
            'reason': 'UPF 기반 저전력 블록의 placement 승인 계획'}
    assert viewer.put(path + '/placement', json=body).status_code == 403
    assert editor.put(path + '/placement', json=body).status_code == 403
    changed = approver.put(path + '/placement', json=body)
    assert changed.status_code == 200, changed.text
    assert changed.json()['version'] == 1
    assert changed.json()['required_domains'] == ['sta', 'low_power']
    assert changed.json()['updated_by'] == users['approver'].username

    gate = viewer.get(f"/projects/{ids['project']}/signoff-status?stage=placement").json()
    assert gate['plan']['version'] == 1 and gate['plan']['source'] == 'custom'
    assert [item['domain'] for item in gate['domains']] == ['sta', 'low_power']

    conflict = approver.put(path + '/placement', json=body)
    assert conflict.status_code == 409
    assert conflict.json()['detail']['current']['version'] == 1
    history = viewer.get(path + '/history?stage=placement&limit=1').json()
    assert len(history['items']) == 1
    assert history['items'][0]['version'] == 1
    assert history['items'][0]['required_domains'] == ['sta', 'low_power']
    assert history['next_before_id'] is None
    with SessionLocal() as db:
        revisions = db.scalars(select(ProjectSignoffPlanRevision).where(
            ProjectSignoffPlanRevision.project_id == ids['project'],
            ProjectSignoffPlanRevision.stage == 'placement')).all()
        assert len(revisions) == 1


def test_plan_validation_and_gate_export_binding(accounts):
    _, ids, login = accounts
    approver = login('approver')
    path = f"/projects/{ids['project']}/signoff-plan/final"
    duplicate = {'expected_version': 0, 'required_domains': ['sta', 'sta'], 'reason': 'duplicate'}
    assert approver.put(path, json=duplicate).status_code == 422
    assert approver.put(path, json={'expected_version': 0, 'required_domains': [], 'reason': 'empty'}).status_code == 422
    update = {'expected_version': 0, 'required_domains': ['sta'], 'reason': 'STA-only characterization project'}
    assert approver.put(path, json=update).status_code == 200
    exported = approver.get(f"/projects/{ids['project']}/signoff-status/export?stage=final")
    assert exported.status_code == 200
    bundle = json.loads(exported.content)
    assert bundle['gate']['plan']['version'] == 1
    assert bundle['gate']['plan']['required_domains'] == ['sta']
