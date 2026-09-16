import copy
import hashlib
import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import ReportImport, RunEvidence, SignoffRun, Violation
from app.services.report_import import parse_opensta
from test_auth import accounts  # Reuse authenticated project fixture.


def report(slack=-2.5e-11):
    path = {'type': 'check', 'path_type': 'max', 'path_group': 'clk',
            'startpoint': 'launch/Q', 'endpoint': 'capture/D',
            'source_path': [{'pin': 'launch/Q'}, {'pin': 'capture/D'}], 'slack': slack}
    return {'checks': [path]}


def payload(document=None):
    return {'import_id': str(uuid.uuid4()), 'stage': 'placement', 'filename': 'timing.json',
            'tool_version': 'QA fixture', 'design_revision': 'rev-abc', 'scenario': 'slow',
            'source_text': json.dumps(report() if document is None else document, indent=2) + '\n'}


def project(client):
    return client.post('/projects', json={'name': uuid.uuid4().hex, 'foundry': 'QA', 'process_node': '5nm'}).json()['id']


def test_parser_units_identity_duplicates_and_empty_coverage():
    doc = report()
    doc['checks'].append(copy.deepcopy(doc['checks'][0]))
    result = parse_opensta(json.dumps(doc))
    assert result['metrics'] == {'reported_paths': 2, 'violating_paths': 2, 'unconstrained_paths': 0, 'worst_reported_slack_ps': -25.0}
    assert result['status'] == 'failed'
    assert result['paths'][0]['fingerprint'] == result['paths'][1]['fingerprint']
    doc['checks'][0]['slack'] = 1e-11
    assert parse_opensta(json.dumps(doc))['paths'][0]['fingerprint'] == result['paths'][0]['fingerprint']
    for source in [json.dumps(report(1e-11)), '{"checks": []}']:
        parsed = parse_opensta(source)
        assert parsed['status'] == 'incomplete'
        assert parsed['coverage'] == 'reported_paths_only'
    doc = report()
    doc['checks'][0].update(type='unconstrained')
    del doc['checks'][0]['slack']
    assert parse_opensta(json.dumps(doc))['metrics']['unconstrained_paths'] == 1


@pytest.mark.parametrize('source', [
    '{}', '{"checks": null}', '{"checks":[false]}', '{"checks":[],"checks":[]}',
    json.dumps(report(float('nan'))), json.dumps(report(float('inf'))), json.dumps(report(True)),
    json.dumps(report(10**400)), json.dumps(report())[:-2],
    json.dumps({'checks': [{k: v for k, v in report()['checks'][0].items() if k != 'slack'}]}),
    json.dumps({'checks': [{**report()['checks'][0], 'endpoint': 'wrong/D'}]}),
    json.dumps({'checks': [{**report()['checks'][0], 'path_type': 'unknown'}]}),
    json.dumps({'checks': report()['checks'] * 1001}), ' ' * 2_000_001,
])
def test_bad_report_never_silently_skips_paths(source):
    with pytest.raises(ValueError):
        parse_opensta(source)


def test_preview_import_immutable_evidence_and_review(client):
    pid = project(client)
    path = f'/projects/{pid}/imports/opensta'
    body = payload()
    assert client.post(path + '/preview', json=body).json()['metrics']['violating_paths'] == 1
    assert client.get(f'/projects/{pid}/runs').json() == []
    response = client.post(path, json=body)
    assert response.status_code == 201, response.text
    run = response.json()
    assert run['status'] == 'failed' and run['result_locked']
    evidence = client.get(f"/runs/{run['id']}/evidence").json()
    assert evidence['source_text'] == body['source_text']
    assert evidence['source_sha256'] == hashlib.sha256(body['source_text'].encode()).hexdigest()
    assert evidence['design_revision'] == body['design_revision']
    assert evidence['result']['submitted_by'] is None
    assert client.patch(f"/runs/{run['id']}", json={'status': 'passed'}).status_code == 409
    assert client.post(f"/runs/{run['id']}/violations", json=[]).status_code == 409
    violation = client.get(f"/runs/{run['id']}/violations").json()[0]
    assert violation['location'] == 'capture/D'
    assert '-25 ps' in violation['description']
    assert client.patch(f"/violations/{violation['id']}", json={'expected_status': 'open', 'expected_version': 1, 'status': 'waived', 'reason': 'test approval', 'actor': 'reviewer'}).status_code == 200
    domain = next(d for d in client.get(f'/projects/{pid}/signoff-status?stage=placement').json()['domains'] if d['domain'] == 'sta')
    assert not domain['ready'] and 'coverage' in domain['reason']
    assert client.get(f"/runs/{run['id']}/evidence").json() == evidence


def test_same_request_retry_and_concurrent_requests_create_one_run(client):
    pid = project(client)
    path, body = f'/projects/{pid}/imports/opensta', payload()
    def send(_):
        with TestClient(client.app) as c:
            return c.post(path, json=body)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(send, range(2)))
    assert [response.status_code for response in responses] == [201, 201]
    assert responses[0].json()['id'] == responses[1].json()['id']
    assert client.post(path, json=body).json()['id'] == responses[0].json()['id']
    assert len(client.get(f'/projects/{pid}/runs').json()) == 1
    assert client.post(path, json={**body, 'scenario': 'fast'}).status_code == 409
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ReportImport).where(ReportImport.project_id == pid)) == 1


def test_import_validation_and_commit_failure_leave_no_partial_run(client, monkeypatch):
    pid = project(client)
    path, body = f'/projects/{pid}/imports/opensta', payload()
    assert client.post(path, json={**body, 'source_text': '{broken'}).status_code == 422
    assert client.post(path, json={**body, 'scenario': ' '}).status_code == 422
    original = Session.commit
    def fail(db):
        if any(isinstance(item, ReportImport) for item in db.new):
            raise RuntimeError('simulated import storage failure')
        return original(db)
    monkeypatch.setattr(Session, 'commit', fail)
    assert client.post(path, json=body).status_code == 500
    monkeypatch.setattr(Session, 'commit', original)
    assert client.get(f'/projects/{pid}/runs').json() == []
    assert client.post(path, json=body).status_code == 201


def test_import_project_roles_and_verified_uploader(accounts):
    users, ids, login = accounts
    body = payload()
    for role, status in [('viewer', 403), ('outsider', 404)]:
        c = login(role)
        for suffix in ['', '/preview']:
            assert c.post(f"/projects/{ids['project']}/imports/opensta{suffix}", json=body).status_code == status
    editor = login('editor')
    response = editor.post(f"/projects/{ids['project']}/imports/opensta", json=body)
    assert response.status_code == 201
    evidence = editor.get(f"/runs/{response.json()['id']}/evidence").json()
    assert evidence['result']['submitted_by'] == {'user_id': users['editor'].id, 'username': users['editor'].username}
    assert login('outsider').get(f"/runs/{response.json()['id']}/evidence").status_code == 404


def test_import_comparison_stable_when_report_order_changes(client):
    pid = project(client)
    doc = report()
    second = copy.deepcopy(doc['checks'][0])
    second['path_type'] = 'min'
    doc['checks'].append(second)
    before = client.post(f'/projects/{pid}/imports/opensta', json=payload(doc)).json()
    doc['checks'].reverse()
    after = client.post(f'/projects/{pid}/imports/opensta', json=payload(doc)).json()
    comparison = client.get(f"/projects/{pid}/run-comparison?baseline_run_id={before['id']}&candidate_run_id={after['id']}").json()
    assert comparison['partial']
    assert comparison['summary'] == {'new': 0, 'changed': 0, 'removed': 0, 'unchanged': 2}


def test_report_bom_and_line_endings_preserved_in_hash():
    source = '\ufeff' + json.dumps(report(), indent=2).replace('\n', '\r\n') + '\r\n'
    result = parse_opensta(source)
    assert result['source_sha256'] == hashlib.sha256(source.encode('utf-8')).hexdigest()
    assert result['metrics']['worst_reported_slack_ps'] == -25


@pytest.mark.parametrize('slack', [-1e-17, -1.234567890123456e-12])
def test_precision_survives_preview_storage_paths_and_evidence(client, slack):
    pid = project(client)
    body = payload(report(slack))
    path = f'/projects/{pid}/imports/opensta'
    expected = slack * 1e12
    preview = client.post(path + '/preview', json=body)
    assert preview.status_code == 200
    assert preview.json()['metrics']['worst_reported_slack_ps'] == expected
    saved = client.post(path, json=body)
    assert saved.status_code == 201
    run = saved.json()
    assert run['status'] == 'failed'
    assert run['metrics']['worst_reported_slack_ps'] == expected
    evidence = client.get(f"/runs/{run['id']}/evidence").json()
    assert evidence['source_text'] == body['source_text']
    assert evidence['result']['paths'][0]['slack_ps'] == expected
    listed = client.get(f"/runs/{run['id']}/timing-paths?status=violated").json()
    assert listed['total'] == 1
    assert listed['items'][0]['slack_ps'] == expected
    detail = client.get(f"/runs/{run['id']}/timing-paths/1").json()
    assert detail['path']['slack_ps'] == expected
    violation = client.get(f"/runs/{run['id']}/violations").json()[0]
    captured_text = violation['description'].split('Reported slack: ')[1].removesuffix(' ps')
    assert float(captured_text) == expected


def test_comparison_detects_slack_changes_beyond_twelve_significant_digits(client):
    pid = project(client)
    runs = []
    for slack in [-1.2345678901234e-12, -1.2345678901235e-12]:
        response = client.post(f'/projects/{pid}/imports/opensta', json=payload(report(slack)))
        assert response.status_code == 201
        runs.append(response.json())
    comparison = client.get(f"/projects/{pid}/run-comparison?baseline_run_id={runs[0]['id']}&candidate_run_id={runs[1]['id']}").json()
    assert comparison['summary'] == {'new': 0, 'changed': 1, 'removed': 0, 'unchanged': 0}
    assert comparison['items'][0]['changed_fields'] == ['description']
    metric = next(item for item in comparison['metrics'] if item['name'] == 'worst_reported_slack_ps')
    assert metric['changed'] and metric['delta'] < 0


@pytest.mark.parametrize('literal', ['-1e-400', '1e-400', '-1E-9999', '1e309', '-1E999', '0.00001e-999'])
def test_unrepresentable_json_slack_is_rejected_before_preview_or_storage(client, literal):
    pid = project(client)
    body = payload(report(0))
    body['source_text'] = body['source_text'].replace('"slack": 0', '"slack": ' + literal)
    for suffix in ['/preview', '']:
        response = client.post(f'/projects/{pid}/imports/opensta' + suffix, json=body)
        assert response.status_code == 422, response.text
        assert 'supported floating-point range' in response.json()['detail']
    assert client.get(f'/projects/{pid}/runs').json() == []


@pytest.mark.parametrize('literal', ['0e-400', '-0.0E-9999', '0.000E999', '-5e-324', '-1e-17'])
def test_exact_zero_and_representable_tiny_slack_remain_supported(literal):
    source = json.dumps(report(0)).replace('"slack": 0', '"slack": ' + literal)
    result = parse_opensta(source)
    expected = float(literal) * 1e12
    assert result['paths'][0]['slack_ps'] == expected
    assert result['metrics']['violating_paths'] == int(expected < 0)
    assert result['status'] == ('failed' if expected < 0 else 'incomplete')


def test_pin_time_underflow_is_not_silently_converted_to_zero(client):
    pid = project(client)
    document = report()
    document['checks'][0]['source_path'][0]['arrival'] = 'tiny-placeholder'
    body = payload(document)
    body['source_text'] = body['source_text'].replace('"tiny-placeholder"', '1e-400')
    response = client.post(f'/projects/{pid}/imports/opensta', json=body)
    assert response.status_code == 422
    assert client.get(f'/projects/{pid}/runs').json() == []
