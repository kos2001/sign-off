import pytest


@pytest.fixture
def issue(client):
    import uuid
    pid = client.post('/projects', json={
        'name': f'lifecycle-{uuid.uuid4()}', 'process_node': '130nm', 'foundry': 'SkyWater',
    }).json()['id']
    for domain in ['sta', 'emir', 'pv']:
        rid = client.post(f'/projects/{pid}/runs', json={
            'domain': domain, 'stage': 'placement', 'tool': 'test',
        }).json()['id']
        client.patch(f'/runs/{rid}', json={'status': 'passed'})
    vid = client.post(f'/runs/{rid}/violations', json=[{
        'check_name': 'spacing', 'severity': 'critical',
    }]).json()[0]['id']
    return pid, rid, vid


def test_fix_reopen_waive_revoke_history_and_gate(client, issue):
    pid, rid, vid = issue
    def ready():
        return client.get(f'/projects/{pid}/signoff-status?stage=placement').json()['ready']
    assert not ready()
    for version, (before, after) in enumerate([('open', 'fixed'), ('fixed', 'open'), ('open', 'waived'), ('waived', 'open'), ('open', 'waived')], start=1):
        response = client.patch(f'/violations/{vid}', json={
            'expected_version': version, 'expected_status': before, 'status': after,
            'actor': ' Reviewer ', 'reason': f' Evidence for {after} ',
        })
        assert response.status_code == 200, response.text
        assert response.json()['status'] == after
        assert (response.json()['waiver'] is not None) == (after == 'waived')
        assert not ready()  # Manual passed states cannot establish coverage.
        gate = client.get(f'/projects/{pid}/signoff-status?stage=placement').json()
        pv = next(d for d in gate['domains'] if d['domain'] == 'pv')
        assert pv['open_blocking_violations'] == (1 if after == 'open' else 0)
    events = client.get(f'/violations/{vid}/history').json()
    assert len(events) == 5
    assert events[0]['from_status'] == 'open'
    assert events[0]['to_status'] == 'fixed'
    assert events[0]['actor'] == 'Reviewer'
    assert events[0]['reason'] == 'Evidence for fixed'
    assert all(e['created_at'] for e in events)
    assert client.get(f'/runs/{rid}/violations?status=waived').json()[0]['id'] == vid


def test_stale_review_and_invalid_transitions_leave_no_history(client, issue):
    _, _, vid = issue
    data = {'expected_version': 1, 'expected_status': 'open', 'status': 'fixed', 'actor': 'A', 'reason': 'Verified'}
    assert client.patch(f'/violations/{vid}', json=data).status_code == 200
    assert client.patch(f'/violations/{vid}', json={**data, 'status': 'waived'}).status_code == 409
    assert client.patch(f'/violations/{vid}', json={**data, 'expected_version': 1, 'expected_status': 'fixed', 'status': 'waived'}).status_code == 409
    assert client.post(f'/violations/{vid}/waiver', json={'expected_version': 1, 'approved_by': 'A', 'reason': 'Exception'}).status_code == 409
    assert len(client.get(f'/violations/{vid}/history').json()) == 1


@pytest.mark.parametrize('field,value', [('actor', '   '), ('reason', '\n\t'), ('actor', 'a' * 81), ('reason', 'a' * 4001)])
def test_invalid_evidence_rejected(client, issue, field, value):
    _, _, vid = issue
    data = {'expected_version': 1, 'expected_status': 'open', 'status': 'fixed', 'actor': 'A', 'reason': 'Verified', field: value}
    assert client.patch(f'/violations/{vid}', json=data).status_code == 422
    assert client.get(f'/violations/{vid}/history').json() == []


def test_legacy_waiver_validates_and_records_history(client, issue):
    _, _, vid = issue
    assert client.post(f'/violations/{vid}/waiver', json={'expected_version': 1, 'reason': ' ', 'approved_by': 'A'}).status_code == 422
    assert client.post(f'/violations/{vid}/waiver', json={'expected_version': 1, 'reason': 'Exception', 'approved_by': 'A'}).status_code == 201
    events = client.get(f'/violations/{vid}/history').json()
    assert len(events) == 1
    assert events[0]['to_status'] == 'waived'


def test_missing_violation(client):
    assert client.get('/violations/999999/history').status_code == 404
    assert client.patch('/violations/999999', json={
        'expected_version': 1, 'expected_status': 'open', 'status': 'fixed', 'actor': 'A', 'reason': 'Verified',
    }).status_code == 404


def test_revoke_legacy_waiver_preserves_original_evidence(client, issue):
    from app.db import SessionLocal
    from app.models import Violation, ViolationStatus, Waiver
    _, _, vid = issue
    with SessionLocal() as db:
        violation = db.get(Violation, vid)
        violation.status = ViolationStatus.waived
        violation.waiver = Waiver(reason='Original approval evidence', approved_by='Original reviewer')
        db.commit()
    response = client.patch(f'/violations/{vid}', json={
        'expected_version': 1, 'expected_status': 'waived', 'status': 'open', 'actor': 'New reviewer', 'reason': 'Exception no longer valid',
    })
    assert response.status_code == 200
    assert response.json()['waiver'] is None
    events = client.get(f'/violations/{vid}/history').json()
    assert [(e['actor'], e['reason']) for e in events] == [
        ('Original reviewer', 'Original approval evidence'),
        ('New reviewer', 'Exception no longer valid'),
    ]
