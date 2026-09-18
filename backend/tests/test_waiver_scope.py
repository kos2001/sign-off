from datetime import datetime, timedelta, timezone

from app.db import SessionLocal
from app.models import RunEvidence, RunStatus, SignoffRun, Violation, ViolationStatus, Waiver, Domain, Severity, Stage
from app.services.stages import evaluate_gate
from test_auth import accounts


def test_api_waiver_binds_revision_expiry_and_history(accounts):
    _, ids, login = accounts
    approver = login('approver')
    with SessionLocal() as db:
        run = db.get(SignoffRun, ids['run'])
        run.evidence = RunEvidence(source='manual', design_revision='rev-waiver', result={})
        db.commit()
    expiry = datetime.now(timezone.utc) + timedelta(days=30)
    response = approver.post(f"/violations/{ids['violation']}/waiver", json={
        'expected_version': 1, 'approved_by': 'forged', 'reason': 'bounded exception',
        'expires_at': expiry.isoformat(),
    })
    assert response.status_code == 201, response.text
    waiver = response.json()['waiver']
    assert waiver['design_revision'] == 'rev-waiver'
    assert waiver['expires_at'].endswith('Z') or '+00:00' in waiver['expires_at']
    assert waiver['active'] is True and waiver['inactive_reason'] is None
    history = approver.get(f"/violations/{ids['violation']}/history").json()
    assert history[-1]['waiver_design_revision'] == 'rev-waiver'
    assert history[-1]['waiver_expires_at'] is not None


def test_waiver_expiry_validation_and_default(accounts):
    _, ids, login = accounts
    approver = login('approver')
    path = f"/violations/{ids['violation']}/waiver"
    base = {'expected_version': 1, 'approved_by': 'reviewer', 'reason': 'temporary'}
    assert approver.post(path, json={**base, 'expires_at': (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}).status_code == 422
    assert approver.post(path, json={**base, 'expires_at': (datetime.now(timezone.utc) + timedelta(days=366)).isoformat()}).status_code == 422
    assert approver.post(path, json={**base, 'expires_at': '2030-01-01T00:00:00'}).status_code == 422
    accepted = approver.post(path, json=base)
    assert accepted.status_code == 201
    expiry = datetime.fromisoformat(accepted.json()['waiver']['expires_at'].replace('Z', '+00:00'))
    remaining = expiry - datetime.now(timezone.utc)
    assert timedelta(days=89) < remaining <= timedelta(days=90)


def test_expired_or_revision_mismatched_waiver_blocks_gate():
    now = datetime.now(timezone.utc)
    evidence = RunEvidence(source='manual', design_revision='rev-new', result={})
    run = SignoffRun(id=1, project_id=1, domain=Domain.sta, stage=Stage.final,
                     tool='test', status=RunStatus.passed, created_at=now,
                     evidence=evidence, violations=[])
    violation = Violation(id=1, run=run, run_id=1, check_name='setup', severity=Severity.error,
                          status=ViolationStatus.waived, version=2)
    waiver = Waiver(violation=violation, reason='expired', approved_by='reviewer',
                    design_revision='rev-new', expires_at=now - timedelta(seconds=1), created_at=now)
    violation.waiver = waiver
    run.violations = [violation]
    plan = {'stage': 'final', 'version': 1, 'source': 'custom', 'required_domains': ['sta'],
            'reason': 'test', 'updated_by': 'test', 'updated_by_user_id': None, 'created_at': now}
    gate = evaluate_gate([run], Stage.final, plan)
    assert gate['domains'][0]['inactive_waivers'] == 1
    assert gate['domains'][0]['open_blocking_violations'] == 1
    assert not gate['domains'][0]['ready']
    waiver.expires_at = now + timedelta(days=1)
    waiver.design_revision = 'rev-old'
    gate = evaluate_gate([run], Stage.final, plan)
    assert gate['domains'][0]['inactive_waivers'] == 1
