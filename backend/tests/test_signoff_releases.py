import hashlib
import io
import json
import subprocess
import sys
import zipfile

import pytest
from fastapi import Response

from app.db import SessionLocal
from app.models import RunEvidence, SignoffReleaseDecision, SignoffRun
from app.routers.releases import evidence_digest
from app.release_ledger import verify_ledger
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
    assert login('editor').get(f'{url}/review?stage=final').status_code == 403
    review = login('approver').get(f'{url}/review?stage=final')
    assert review.status_code == 200
    assert review.json()['gate']['ready'] is False
    assert len(review.json()['evidence_snapshot_sha256']) == 64
    response = login('approver').post(url, json=payload)
    assert response.status_code == 201, response.text
    item = response.json()
    assert item['decision'] == 'rejected'
    assert item['lifecycle_status'] == 'current'
    assert len(item['gate_snapshot_sha256']) == 64
    assert len(item['evidence_snapshot_sha256']) == 64
    assert item['decided_by'] == users['approver'].username
    assert item['decided_by_user_id'] == users['approver'].id
    assert item['gate']['ready'] is False
    assert item['design_revision'] is None
    assert item['chain_version'] == 1
    assert item['previous_decision_sha256'] is None

    viewer = login('viewer')
    page = viewer.get(url).json()
    assert page['items'] == [item] and page['next_before_id'] is None
    assert viewer.get(f"{url}/{item['id']}").json() == item
    audit = viewer.get(f'{url}/audit')
    assert audit.status_code == 200
    assert audit.json()['decision_count'] == 1
    assert audit.json()['chained_decision_count'] == 1
    assert audit.json()['chain_head_sha256'] == item['decision_sha256']
    ledger_response = viewer.get(f'{url}/audit/export')
    assert ledger_response.status_code == 200
    assert ledger_response.headers['x-signoff-decision-chain-head'] == item['decision_sha256']
    assert verify_ledger(ledger_response.json(), item['decision_sha256'])['decision_count'] == 1
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
        'target_revision': {'design_revision': 'release-ready', 'version': 1},
    }, 'runs': []}
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
        json={'stage': 'final', 'decision': 'approved', 'reason': 'all required evidence reviewed',
              'expected_evidence_sha256': evidence_digest(manifest)},
    )
    assert response.status_code == 201
    assert response.json()['decision'] == 'approved'
    assert response.json()['design_revision'] == 'release-ready'
    assert response.json()['decided_by'] == users['approver'].username


def test_ready_gate_approval_requires_pinned_target_revision(accounts, monkeypatch):
    _, ids, login = accounts

    def package_for(target_revision):
        manifest = {'format': 'signoff/evidence-package/v1', 'gate': {
            'ready': True,
            'revision_check': {'common_revision': 'release-ready'},
            'domains': [],
            'stage': 'final',
            'target_revision': {'design_revision': target_revision, 'version': 1},
        }, 'runs': []}
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('manifest.json', json.dumps(manifest, separators=(',', ':')).encode())
        return Response(output.getvalue(), media_type='application/zip')

    monkeypatch.setattr(
        'app.routers.releases.export_signoff_package',
        lambda project_id, stage, db: package_for(None),
    )
    url = f"/projects/{ids['project']}/signoff-releases"
    payload = {'stage': 'final', 'decision': 'approved', 'reason': 'approve release candidate'}
    response = login('approver').post(url, json=payload)
    assert response.status_code == 409
    assert '릴리스 후보 리비전' in response.json()['detail']

    monkeypatch.setattr(
        'app.routers.releases.export_signoff_package',
        lambda project_id, stage, db: package_for('different-revision'),
    )
    response = login('approver').post(url, json=payload)
    assert response.status_code == 409
    assert '일치하지 않습니다' in response.json()['detail']


def test_ready_gate_approval_requires_current_review_snapshot(accounts, monkeypatch):
    _, ids, login = accounts
    manifest = {'format': 'signoff/evidence-package/v1', 'gate': {
        'ready': True,
        'revision_check': {'common_revision': 'release-ready'},
        'domains': [],
        'stage': 'final',
        'target_revision': {'design_revision': 'release-ready', 'version': 1},
    }, 'runs': []}
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('manifest.json', json.dumps(manifest, separators=(',', ':')).encode())
    monkeypatch.setattr(
        'app.routers.releases.export_signoff_package',
        lambda project_id, stage, db: Response(output.getvalue(), media_type='application/zip'),
    )
    url = f"/projects/{ids['project']}/signoff-releases"
    base = {'stage': 'final', 'decision': 'approved', 'reason': 'approve reviewed evidence'}

    response = login('approver').post(url, json=base)
    assert response.status_code == 409
    assert '스냅샷을 검토' in response.json()['detail']

    response = login('approver').post(url, json={**base, 'expected_evidence_sha256': '0' * 64})
    assert response.status_code == 409
    assert '근거가 변경' in response.json()['detail']


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


def test_release_lifecycle_tracks_evidence_changes_and_newer_decisions(accounts):
    _, ids, login = accounts
    attach_source(ids['run'])
    url = f"/projects/{ids['project']}/signoff-releases"
    approver = login('approver')
    first = approver.post(url, json={
        'stage': 'final', 'decision': 'rejected', 'reason': 'initial review',
    }).json()
    assert first['lifecycle_status'] == 'current'

    with SessionLocal() as db:
        run = db.get(SignoffRun, ids['run'])
        run.metrics = {'changed_after_decision': True}
        db.commit()
    changed = approver.get(f"{url}/{first['id']}").json()
    assert changed['lifecycle_status'] == 'evidence_changed'

    second = approver.post(url, json={
        'stage': 'final', 'decision': 'rejected', 'reason': 'reviewed changed evidence',
    }).json()
    assert second['lifecycle_status'] == 'current'
    page = approver.get(url).json()['items']
    assert [item['lifecycle_status'] for item in page] == ['current', 'superseded_by_decision']


def test_gate_snapshot_tampering_is_rejected(accounts):
    _, ids, login = accounts
    attach_source(ids['run'])
    url = f"/projects/{ids['project']}/signoff-releases"
    item = login('approver').post(
        url, json={'stage': 'final', 'decision': 'rejected', 'reason': 'original snapshot'},
    ).json()
    with SessionLocal() as db:
        record = db.get(SignoffReleaseDecision, item['id'])
        record.gate_snapshot = {**record.gate_snapshot, 'ready': True}
        db.commit()
    response = login('viewer').get(f"{url}/{item['id']}")
    assert response.status_code == 409
    assert '게이트 스냅샷 무결성' in response.json()['detail']
    assert login('viewer').get(f"{url}/{item['id']}/package").status_code == 409


def test_evidence_snapshot_tampering_is_rejected(accounts):
    _, ids, login = accounts
    attach_source(ids['run'])
    url = f"/projects/{ids['project']}/signoff-releases"
    item = login('approver').post(
        url, json={'stage': 'final', 'decision': 'rejected', 'reason': 'frozen evidence'},
    ).json()
    with SessionLocal() as db:
        record = db.get(SignoffReleaseDecision, item['id'])
        manifest = dict(record.manifest)
        manifest['runs'] = [{**run, 'metrics': {'tampered': True}} for run in manifest['runs']]
        record.manifest = manifest
        db.commit()
    response = login('viewer').get(f"{url}/{item['id']}")
    assert response.status_code == 409
    assert '근거 스냅샷 무결성' in response.json()['detail']


def test_release_audit_detects_deleted_middle_decision(accounts):
    _, ids, login = accounts
    attach_source(ids['run'])
    url = f"/projects/{ids['project']}/signoff-releases"
    approver = login('approver')
    first = approver.post(url, json={
        'stage': 'final', 'decision': 'rejected', 'reason': 'first review',
    }).json()
    second = approver.post(url, json={
        'stage': 'final', 'decision': 'rejected', 'reason': 'second review',
    }).json()
    assert second['previous_decision_sha256'] == first['decision_sha256']
    with SessionLocal() as db:
        db.delete(db.get(SignoffReleaseDecision, first['id']))
        db.commit()
    response = login('viewer').get(f'{url}/audit')
    assert response.status_code == 409
    assert '이전 결정 연결' in response.json()['detail']


def test_release_audit_detects_deleted_chain_tail(accounts):
    _, ids, login = accounts
    attach_source(ids['run'])
    url = f"/projects/{ids['project']}/signoff-releases"
    item = login('approver').post(url, json={
        'stage': 'final', 'decision': 'rejected', 'reason': 'record chain head',
    }).json()
    with SessionLocal() as db:
        db.delete(db.get(SignoffReleaseDecision, item['id']))
        db.commit()
    response = login('viewer').get(f'{url}/audit')
    assert response.status_code == 409
    assert '저장된 헤드' in response.json()['detail']


def test_portable_release_ledger_cli_and_tamper_detection(accounts, tmp_path):
    _, ids, login = accounts
    attach_source(ids['run'])
    url = f"/projects/{ids['project']}/signoff-releases"
    item = login('approver').post(url, json={
        'stage': 'final', 'decision': 'rejected', 'reason': 'portable audit evidence',
    }).json()
    ledger = login('viewer').get(f'{url}/audit/export').json()
    path = tmp_path / 'decision-ledger.json'
    path.write_text(json.dumps(ledger, ensure_ascii=False), encoding='utf-8')
    verified = subprocess.run([
        sys.executable, '-m', 'app.release_ledger', 'verify', '--ledger', str(path),
        '--expected-head', item['decision_sha256'],
    ], capture_output=True, text=True, timeout=10)
    assert verified.returncode == 0, verified.stderr
    assert json.loads(verified.stdout)['status'] == 'verified'

    ledger['decisions'][0]['reason'] = 'rewritten outside the service'
    with pytest.raises(ValueError, match='digest mismatch'):
        verify_ledger(ledger, item['decision_sha256'])
    wrong_head = subprocess.run([
        sys.executable, '-m', 'app.release_ledger', 'verify', '--ledger', str(path),
        '--expected-head', '0' * 64,
    ], capture_output=True, text=True, timeout=10)
    assert wrong_head.returncode == 1
    assert 'externally retained head' in wrong_head.stderr
