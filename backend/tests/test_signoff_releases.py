import hashlib
import io
import json
import zipfile

from fastapi import Response

from app.db import SessionLocal
from app.models import RunEvidence, SignoffReleaseDecision, SignoffRun
from test_auth import accounts


def attach_source(run_id: int):
    source = 'stored commercial evidence\n'
    with SessionLocal() as db:
        run = db.get(SignoffRun, run_id)
        run.evidence = RunEvidence(
            source='commercial_sta_report', source_text=source,
            source_sha256=hashlib.sha256(source.encode()).hexdigest(),
            design_revision='release-r1', result={'parser': 'test'},
        )
        db.commit()


def test_release_decision_requires_approver_and_preserves_exact_package(accounts):
    users, ids, login = accounts
    attach_source(ids['run'])
    url = f"/projects/{ids['project']}/signoff-releases"
    payload = {'stage': 'final', 'decision': 'rejected', 'reason': 'coverage is incomplete'}
    assert login('editor').post(url, json=payload).status_code == 403
    response = login('approver').post(url, json=payload)
    assert response.status_code == 201, response.text
    item = response.json()
    assert item['decision'] == 'rejected'
    assert item['decided_by'] == users['approver'].username
    assert item['decided_by_user_id'] == users['approver'].id
    assert item['gate']['ready'] is False
    assert item['design_revision'] is None

    viewer = login('viewer')
    page = viewer.get(url).json()
    assert page['items'] == [item] and page['next_before_id'] is None
    assert viewer.get(f"{url}/{item['id']}").json() == item
    package = viewer.get(f"{url}/{item['id']}/package")
    assert package.status_code == 200
    assert hashlib.sha256(package.content).hexdigest() == item['package_sha256']
    assert package.headers['x-signoff-manifest-sha256'] == item['manifest_sha256']
    assert package.headers['x-signoff-decision-sha256'] == item['decision_sha256']
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        assert json.loads(archive.read('manifest.json'))['gate'] == item['gate']
    assert login('outsider').get(url).status_code == 404


def test_blocked_gate_cannot_be_approved(accounts):
    _, ids, login = accounts
    attach_source(ids['run'])
    response = login('approver').post(
        f"/projects/{ids['project']}/signoff-releases",
        json={'stage': 'final', 'decision': 'approved', 'reason': 'attempted approval'},
    )
    assert response.status_code == 409
    assert '차단된 게이트' in response.json()['detail']
    with SessionLocal() as db:
        assert db.query(SignoffReleaseDecision).filter_by(project_id=ids['project']).count() == 0


def test_ready_gate_approval_records_server_identity(accounts, monkeypatch):
    users, ids, login = accounts
    manifest = {'format': 'signoff/evidence-package/v1', 'gate': {
        'ready': True, 'revision_check': {'common_revision': 'release-ready'}, 'domains': [], 'stage': 'final',
    }}
    manifest_bytes = json.dumps(manifest, separators=(',', ':')).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('manifest.json', manifest_bytes)
    monkeypatch.setattr(
        'app.routers.releases.export_signoff_package',
        lambda project_id, stage, db: Response(output.getvalue(), media_type='application/zip'),
    )
    response = login('approver').post(
        f"/projects/{ids['project']}/signoff-releases",
        json={'stage': 'final', 'decision': 'approved', 'reason': 'all required evidence reviewed'},
    )
    assert response.status_code == 201
    assert response.json()['decision'] == 'approved'
    assert response.json()['design_revision'] == 'release-ready'
    assert response.json()['decided_by'] == users['approver'].username


def test_archived_package_tampering_is_rejected(accounts):
    _, ids, login = accounts
    attach_source(ids['run'])
    url = f"/projects/{ids['project']}/signoff-releases"
    item = login('approver').post(
        url, json={'stage': 'final', 'decision': 'rejected', 'reason': 'blocked'},
    ).json()
    with SessionLocal() as db:
        record = db.get(SignoffReleaseDecision, item['id'])
        record.package_bytes = b'tampered'
        db.commit()
    response = login('viewer').get(f"{url}/{item['id']}/package")
    assert response.status_code == 409
    assert '무결성' in response.json()['detail']


def test_archived_decision_tampering_is_rejected(accounts):
    _, ids, login = accounts
    attach_source(ids['run'])
    url = f"/projects/{ids['project']}/signoff-releases"
    item = login('approver').post(
        url, json={'stage': 'final', 'decision': 'rejected', 'reason': 'original reason'},
    ).json()
    with SessionLocal() as db:
        record = db.get(SignoffReleaseDecision, item['id'])
        record.reason = 'changed after decision'
        db.commit()
    response = login('viewer').get(f"{url}/{item['id']}")
    assert response.status_code == 409
    assert '결정 무결성' in response.json()['detail']
