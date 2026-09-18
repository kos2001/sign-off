import copy
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import ReportImport, RunEvidence, SignoffRun, Violation
from app.services.report_import import parse_commercial_sta, parse_opensta
from app.services.coverage_attestation import REQUIRED_STA_CLAIMS, canonical_payload
from app.routers.imports import CoverageAttestationPayload
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


def commercial_report(tool='Synopsys PrimeTime', slack=-0.025):
    return {'format': 'signoff/commercial-sta-paths/v1', 'tool': tool,
            'tool_version': 'T-2025.06', 'time_unit': 'ns', 'paths': [{
                'check_type': 'setup', 'path_type': 'max', 'path_group': 'core_clk',
                'startpoint': 'launch/Q', 'endpoint': 'capture/D', 'slack': slack,
                'source_clock': 'core_clk', 'target_clock': 'core_clk',
                'data_arrival_time': 0.8, 'required_time': 0.775,
                'points': [
                    {'pin': 'launch/Q', 'instance': 'launch', 'cell': 'DFF', 'arrival': 0.1, 'slew': 0.02},
                    {'pin': 'u1/Y', 'instance': 'u1', 'cell': 'BUF', 'net': 'n1', 'arrival': 0.4},
                    {'pin': 'capture/D', 'instance': 'capture', 'cell': 'DFF', 'arrival': 0.8},
                ],
            }]}


def commercial_payload(document=None):
    document = commercial_report() if document is None else document
    return {'import_id': str(uuid.uuid4()), 'stage': 'routing', 'filename': 'primetime-paths.json',
            'tool_version': document.get('tool_version', 'T-2025.06'), 'design_revision': 'rev-commercial',
            'scenario': 'ss-setup', 'source_text': json.dumps(document, ensure_ascii=False, indent=2) + '\n'}


def attest_sta(body, project_id, secret='collector-secret-that-is-at-least-32-bytes', plan_version=None):
    now = datetime.now(timezone.utc)
    value = {
        'format': 'signoff/coverage-attestation/v1', 'attestation_id': body['import_id'],
        'key_id': 'qa-collector-1', 'issued_at': now.isoformat(),
        'expires_at': (now + timedelta(hours=1)).isoformat(), 'project_id': project_id,
        'stage': body['stage'], 'domain': 'sta', 'design_revision': body['design_revision'],
        'source_sha256': hashlib.sha256(body['source_text'].encode()).hexdigest(),
        'tool': json.loads(body['source_text'])['tool'], 'tool_version': body['tool_version'],
        'scenario': body['scenario'], 'claims': {claim: True for claim in REQUIRED_STA_CLAIMS},
        'signature': '0' * 64,
    }
    if plan_version is not None:
        value['scenario_plan_version'] = plan_version
    parsed = CoverageAttestationPayload.model_validate(value)
    value['signature'] = hmac.new(secret.encode(), canonical_payload(parsed), hashlib.sha256).hexdigest()
    return value


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


def test_commercial_sta_parser_units_identity_and_points():
    source = json.dumps(commercial_report())
    result = parse_commercial_sta(source)
    assert result['tool'] == 'Synopsys PrimeTime' and result['tool_version'] == 'T-2025.06'
    assert result['parser'] == 'commercial-sta-path-json/v1'
    assert result['metrics'] == {'reported_paths': 1, 'violating_paths': 1,
        'unconstrained_paths': 0, 'worst_reported_slack_ps': -25.0}
    changed = commercial_report(slack=0.1)
    assert parse_commercial_sta(json.dumps(changed))['paths'][0]['fingerprint'] == result['paths'][0]['fingerprint']
    tempus = commercial_report(tool='Cadence Tempus', slack=None)
    parsed = parse_commercial_sta(json.dumps(tempus))
    assert parsed['status'] == 'incomplete' and parsed['metrics']['unconstrained_paths'] == 1


@pytest.mark.parametrize('patch', [
    {'format': 'wrong'}, {'tool': 'Unknown STA'}, {'tool_version': ' '}, {'time_unit': 'cycles'},
    {'paths': [{}]}, {'paths': [{**commercial_report()['paths'][0], 'slack': float('nan')}]},
    {'paths': [{k: v for k, v in commercial_report()['paths'][0].items() if k != 'slack'}]},
    {'paths': [{**commercial_report()['paths'][0], 'points': []}]},
    {'paths': [{**commercial_report()['paths'][0], 'endpoint': 'wrong/D'}]},
])
def test_bad_commercial_sta_report_is_rejected(patch):
    document = {**commercial_report(), **patch}
    with pytest.raises(ValueError):
        parse_commercial_sta(json.dumps(document))


def test_commercial_sta_preview_import_paths_and_evidence(client):
    pid = project(client)
    path = f'/projects/{pid}/imports/commercial-sta'
    body = commercial_payload()
    preview = client.post(path + '/preview', json=body)
    assert preview.status_code == 200 and preview.json()['metrics']['violating_paths'] == 1
    response = client.post(path, json=body)
    assert response.status_code == 201, response.text
    run = response.json()
    assert run['tool'] == 'Synopsys PrimeTime' and run['evidence_source'] == 'commercial_sta_report'
    assert run['result_locked'] and run['status'] == 'failed'
    evidence = client.get(f"/runs/{run['id']}/evidence").json()
    assert evidence['source_text'] == body['source_text']
    assert evidence['result']['metadata']['report_format'] == 'commercial-sta-path-json/v1'
    violations = client.get(f"/runs/{run['id']}/violations").json()
    assert violations[0]['check_name'].startswith('primetime/max/')
    paths = client.get(f"/runs/{run['id']}/timing-paths").json()
    assert paths['items'][0]['slack_ps'] == pytest.approx(-25)
    detail = client.get(f"/runs/{run['id']}/timing-paths/1").json()
    assert detail['point_total'] == 3 and detail['points'][1]['arrival_ps'] == pytest.approx(400)
    assert detail['arrival_delta_summary']['reported_pairs'] == 2
    download = client.get(f"/runs/{run['id']}/evidence/source")
    assert download.status_code == 200 and download.content == body['source_text'].encode()
    assert client.post(path, json=body).json()['id'] == run['id']
    assert client.post(path, json={**body, 'scenario': 'ff-hold'}).status_code == 409
    assert client.post(path + '/preview', json={**body, 'tool_version': 'mismatch'}).status_code == 422


def test_trusted_sta_attestation_can_establish_gate_coverage(client, monkeypatch):
    secret = 'collector-secret-that-is-at-least-32-bytes'
    monkeypatch.setenv('SIGNOFF_COVERAGE_HMAC_KEYS', json.dumps({'qa-collector-1': {'secret': secret, 'domains': ['sta']}}))
    pid = project(client)
    body = commercial_payload({**commercial_report(slack=0.1), 'paths': []})
    body['coverage_attestation'] = attest_sta(body, pid, secret)
    path = f'/projects/{pid}/imports/commercial-sta'
    preview = client.post(path + '/preview', json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()['status'] == 'passed'
    assert preview.json()['coverage'] == 'collector_attested_complete'
    assert preview.json()['coverage_attestation']['verified'] is True
    response = client.post(path, json=body)
    assert response.status_code == 201, response.text
    run = response.json()
    assert run['status'] == 'passed'
    evidence = client.get(f"/runs/{run['id']}/evidence").json()
    assert evidence['result']['coverage_attestation']['signature'] == body['coverage_attestation']['signature']
    candidate_body = commercial_payload({**commercial_report(slack=0.1), 'paths': []})
    candidate_body['coverage_attestation'] = attest_sta(candidate_body, pid, secret)
    candidate = client.post(path, json=candidate_body).json()
    comparison = client.get(f"/projects/{pid}/run-comparison", params={
        'baseline_run_id': run['id'], 'candidate_run_id': candidate['id'],
    }).json()
    assert comparison['partial'] is False
    monkeypatch.delenv('SIGNOFF_COVERAGE_HMAC_KEYS')
    assert client.post(path, json=body).json()['id'] == run['id']  # Durable idempotent retry after key rotation.
    domain = next(item for item in client.get(
        f'/projects/{pid}/signoff-status?stage=routing').json()['domains'] if item['domain'] == 'sta')
    assert domain['ready'] is True and domain['run_id'] == candidate['id']


def test_trusted_sta_attestation_is_bound_to_current_scenario_plan(client, monkeypatch):
    secret = 'collector-secret-that-is-at-least-32-bytes'
    monkeypatch.setenv('SIGNOFF_COVERAGE_HMAC_KEYS', json.dumps({
        'qa-collector-1': {'secret': secret, 'domains': ['sta']},
    }))
    pid = project(client)
    plan_path = f'/projects/{pid}/sta-scenario-plan/routing'
    assert client.put(plan_path, json={'scenarios': [{'name': 'ss-setup', 'require_spef': True}],
        'expected_version': 0, 'reason': 'initial routing MMMC plan'}).status_code == 200
    body = commercial_payload({**commercial_report(slack=0.1), 'paths': []})
    body['coverage_attestation'] = attest_sta(body, pid, secret)
    import_path = f'/projects/{pid}/imports/commercial-sta'
    rejected = client.post(import_path + '/preview', json=body)
    assert rejected.status_code == 422 and 'scenario_plan_version' in rejected.json()['detail']

    body['coverage_attestation'] = attest_sta(body, pid, secret, plan_version=1)
    saved = client.post(import_path, json=body)
    assert saved.status_code == 201, saved.text
    gate = client.get(f'/projects/{pid}/signoff-status?stage=routing').json()
    sta = next(item for item in gate['domains'] if item['domain'] == 'sta')
    assert sta['scenario_plan_version'] == sta['required_scenario_plan_version'] == 1

    changed = client.put(plan_path, json={'scenarios': [
        {'name': 'ss-setup', 'require_spef': True}, {'name': 'ff-hold', 'require_spef': True}],
        'expected_version': 1, 'reason': 'add fast hold corner'})
    assert changed.status_code == 200 and changed.json()['version'] == 2
    gate = client.get(f'/projects/{pid}/signoff-status?stage=routing').json()
    sta = next(item for item in gate['domains'] if item['domain'] == 'sta')
    assert not sta['ready'] and sta['reason'] == 'Trusted STA evidence targets an outdated scenario plan'
    assert sta['scenario_plan_version'] == 1 and sta['required_scenario_plan_version'] == 2


@pytest.mark.parametrize('mutation', ['signature', 'source_sha256', 'claims', 'claim_type', 'expired', 'unknown_key'])
def test_invalid_sta_attestation_never_promotes_coverage(client, monkeypatch, mutation):
    secret = 'collector-secret-that-is-at-least-32-bytes'
    monkeypatch.setenv('SIGNOFF_COVERAGE_HMAC_KEYS', json.dumps({'qa-collector-1': {'secret': secret, 'domains': ['sta']}}))
    pid = project(client)
    body = commercial_payload({**commercial_report(slack=0.1), 'paths': []})
    attestation = attest_sta(body, pid, secret)
    if mutation == 'signature':
        attestation['signature'] = 'f' * 64
    elif mutation == 'source_sha256':
        attestation['source_sha256'] = '0' * 64
    elif mutation == 'claims':
        attestation['claims'].pop('findings_complete')
    elif mutation == 'claim_type':
        attestation['claims']['findings_complete'] = 1
    elif mutation == 'expired':
        attestation['issued_at'] = '2020-01-01T00:00:00Z'
        attestation['expires_at'] = '2020-01-01T01:00:00Z'
    else:
        attestation['key_id'] = 'unknown'
    body['coverage_attestation'] = attestation
    response = client.post(f'/projects/{pid}/imports/commercial-sta/preview', json=body)
    assert response.status_code == 422
    assert client.get(f'/projects/{pid}/runs').json() == []


def test_attestation_requires_server_key_configuration(client):
    pid = project(client)
    body = commercial_payload({**commercial_report(slack=0.1), 'paths': []})
    body['coverage_attestation'] = attest_sta(body, pid)
    response = client.post(f'/projects/{pid}/imports/commercial-sta/preview', json=body)
    assert response.status_code == 503


def test_attested_sta_findings_still_fail(client, monkeypatch):
    secret = 'collector-secret-that-is-at-least-32-bytes'
    monkeypatch.setenv('SIGNOFF_COVERAGE_HMAC_KEYS', json.dumps({'qa-collector-1': {'secret': secret, 'domains': ['sta']}}))
    pid = project(client)
    body = commercial_payload(commercial_report(slack=-0.025))
    body['coverage_attestation'] = attest_sta(body, pid, secret)
    preview = client.post(f'/projects/{pid}/imports/commercial-sta/preview', json=body)
    assert preview.status_code == 200
    assert preview.json()['status'] == 'failed'
    run = client.post(f'/projects/{pid}/imports/commercial-sta', json=body).json()
    domain = next(item for item in client.get(
        f'/projects/{pid}/signoff-status?stage=routing').json()['domains'] if item['domain'] == 'sta')
    assert domain['run_id'] == run['id'] and domain['ready'] is False
    assert domain['reason'] == "latest run status is 'failed'"


def test_invalid_configured_attestation_keys_stop_app_startup(monkeypatch):
    from app.main import create_app
    from app.services.coverage_attestation import AttestationConfigurationError
    monkeypatch.setenv('SIGNOFF_COVERAGE_HMAC_KEYS', '{"duplicate":"a", "duplicate":"b"}')
    with pytest.raises(AttestationConfigurationError):
        create_app()


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
