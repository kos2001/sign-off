import copy
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services.commercial_emir import parse_commercial_emir
from app.services.coverage_attestation import REQUIRED_EMIR_CLAIMS, canonical_payload
from app.routers.imports import CoverageAttestationPayload
from test_auth import accounts


def report(tool='Ansys RedHawk-SC'):
    return {'format': 'signoff/commercial-power-integrity/v1', 'tool': tool,
            'tool_version': '2025 R1', 'coordinate_unit': 'nm', 'top_cell': 'CHIP', 'findings': [
        {'analysis': 'static_ir', 'metric': 'voltage_drop', 'check': 'VDD max drop',
         'severity': 'critical', 'value': 0.085, 'limit': 0.075, 'unit': 'V',
         'x': 1500, 'y': 2000, 'instance': 'u_core/u_cpu', 'net': 'VDD', 'layer': 'M8',
         'message': 'Static rail drop exceeds the submitted limit'},
        {'analysis': 'em', 'metric': 'current_density', 'check': 'M4 signal EM',
         'severity': 'warning', 'value': 0.8, 'limit': 1.0, 'unit': 'mA/um2',
         'x': 500, 'y': 600, 'net': 'n42', 'layer': 'M4'},
    ]}


def payload(document=None):
    document = report() if document is None else document
    return {'import_id': str(uuid.uuid4()), 'stage': 'routing', 'filename': 'redhawk-findings.json',
            'tool_version': document.get('tool_version', '2025 R1'), 'design_revision': 'rev-emir',
            'scenario': 'func-ss-0p72v-125c', 'source_text': json.dumps(document, indent=2) + '\n'}


def attest(body, project_id, secret='emir-collector-secret-with-at-least-32-bytes'):
    now = datetime.now(timezone.utc)
    document = json.loads(body['source_text'])
    value = {
        'format': 'signoff/coverage-attestation/v1', 'attestation_id': body['import_id'],
        'key_id': 'qa-emir-collector', 'issued_at': now.isoformat(),
        'expires_at': (now + timedelta(hours=1)).isoformat(), 'project_id': project_id,
        'stage': body['stage'], 'domain': 'emir', 'design_revision': body['design_revision'],
        'source_sha256': hashlib.sha256(body['source_text'].encode()).hexdigest(),
        'tool': document['tool'], 'tool_version': body['tool_version'], 'scenario': body['scenario'],
        'claims': {claim: True for claim in REQUIRED_EMIR_CLAIMS}, 'signature': '0' * 64,
    }
    parsed = CoverageAttestationPayload.model_validate(value)
    value['signature'] = hmac.new(secret.encode(), canonical_payload(parsed), hashlib.sha256).hexdigest()
    return value


def test_parser_normalizes_metrics_coordinates_and_identity():
    result = parse_commercial_emir(json.dumps(report()))
    assert result['status'] == 'failed'
    assert result['metrics'] == {'reported_findings': 2, 'violated_findings': 1,
        'static_ir_findings': 1, 'dynamic_ir_findings': 0, 'em_findings': 1}
    first, second = result['items']
    assert first['value'] == 85 and first['limit'] == 75 and first['unit'] == 'mV' and first['violated']
    assert first['x_um'] == '1.500' and first['y_um'] == '2.000'
    assert second['value'] == pytest.approx(.0008) and not second['violated']
    changed = report()
    changed['findings'][0]['value'] = .05
    assert parse_commercial_emir(json.dumps(changed))['items'][0]['fingerprint'] == first['fingerprint']
    empty = report('Cadence Voltus'); empty['findings'] = []
    assert parse_commercial_emir(json.dumps(empty))['status'] == 'incomplete'


@pytest.mark.parametrize('field,value', [
    ('format', 'wrong'), ('tool', 'unknown'), ('tool_version', ' '), ('coordinate_unit', 'mm'),
    ('findings', [{}]),
    ('findings', [{**report()['findings'][0], 'analysis': 'em'}]),
    ('findings', [{**report()['findings'][0], 'unit': 'A'}]),
    ('findings', [{**report()['findings'][0], 'value': -1}]),
    ('findings', [{**report()['findings'][0], 'x': float('nan')}]),
    ('findings', [{**report()['findings'][0], 'x': 10**400}]),
])
def test_invalid_reports_are_rejected(field, value):
    document = copy.deepcopy(report()); document[field] = value
    with pytest.raises(ValueError):
        parse_commercial_emir(json.dumps(document))


def test_import_explorer_evidence_violations_retry_and_auth(accounts):
    _, ids, login = accounts
    path = f"/projects/{ids['project']}/imports/commercial-emir"
    body = payload(); viewer, editor, outsider = login('viewer'), login('editor'), login('outsider')
    assert viewer.post(path + '/preview', json=body).status_code == 403
    assert outsider.post(path, json=body).status_code == 404
    preview = editor.post(path + '/preview', json=body)
    assert preview.status_code == 200 and preview.json()['metrics']['violated_findings'] == 1
    response = editor.post(path, json=body)
    assert response.status_code == 201, response.text
    run = response.json()
    assert run['tool'] == 'Ansys RedHawk-SC' and run['domain'] == 'emir'
    assert run['evidence_source'] == 'commercial_emir_report' and run['result_locked']
    assert editor.post(path, json=body).json()['id'] == run['id']
    assert editor.post(path, json={**body, 'scenario': 'changed'}).status_code == 409
    assert editor.post(path + '/preview', json={**body, 'tool_version': 'wrong'}).status_code == 422
    evidence = viewer.get(f"/runs/{run['id']}/evidence").json()
    assert evidence['source_sha256'] == hashlib.sha256(body['source_text'].encode()).hexdigest()
    assert evidence['result']['metadata']['report_format'] == 'commercial-power-integrity-json/v1'
    violations = viewer.get(f"/runs/{run['id']}/violations").json()
    assert len(violations) == 1 and violations[0]['check_name'].startswith('redhawk/')
    findings = viewer.get(f"/runs/{run['id']}/power-integrity-findings").json()
    assert findings['reported_total'] == 2 and findings['violated_total'] == 1
    assert findings['bounds_um'] == {'xmin': .5, 'xmax': 1.5, 'ymin': .6, 'ymax': 2.0}
    assert viewer.get(f"/runs/{run['id']}/power-integrity-findings?analysis=em").json()['total'] == 1
    detail = viewer.get(f"/runs/{run['id']}/power-integrity-findings/1").json()
    assert detail['violation_match']['status'] == 'unique'
    assert viewer.get(f"/runs/{run['id']}/power-integrity-findings/2").json()['violation_match']['status'] == 'not_applicable'
    assert outsider.get(f"/runs/{run['id']}/power-integrity-findings").status_code == 404
    source = viewer.get(f"/runs/{run['id']}/evidence/source")
    assert source.content == body['source_text'].encode() and '.json' in source.headers['content-disposition']
    assert editor.patch(f"/runs/{run['id']}", json={'status': 'passed'}).status_code == 409
    gate = viewer.get(f"/projects/{ids['project']}/signoff-status?stage=routing").json()
    emir = next(domain for domain in gate['domains'] if domain['domain'] == 'emir')
    assert not emir['ready'] and 'full EM/IR coverage' in emir['reason']


def test_trusted_emir_attestation_can_establish_gate_coverage(accounts, monkeypatch):
    secret = 'emir-collector-secret-with-at-least-32-bytes'
    monkeypatch.setenv('SIGNOFF_COVERAGE_HMAC_KEYS', json.dumps({'qa-emir-collector': {'secret': secret, 'domains': ['emir']}}))
    _, ids, login = accounts
    body = payload({**report(), 'findings': []})
    body['coverage_attestation'] = attest(body, ids['project'], secret)
    path = f"/projects/{ids['project']}/imports/commercial-emir"
    editor = login('editor')
    preview = editor.post(path + '/preview', json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()['status'] == 'passed'
    assert preview.json()['coverage'] == 'collector_attested_complete'
    run = editor.post(path, json=body).json()
    assert run['status'] == 'passed'
    evidence = editor.get(f"/runs/{run['id']}/evidence").json()
    assert evidence['result']['coverage_attestation']['signature'] == body['coverage_attestation']['signature']
    emir = next(item for item in editor.get(
        f"/projects/{ids['project']}/signoff-status?stage=routing").json()['domains'] if item['domain'] == 'emir')
    assert emir['ready'] is True and emir['run_id'] == run['id']
    candidate_body = payload({**report(), 'findings': []})
    candidate_body['coverage_attestation'] = attest(candidate_body, ids['project'], secret)
    candidate = editor.post(path, json=candidate_body).json()
    comparison = editor.get(f"/projects/{ids['project']}/run-comparison", params={
        'baseline_run_id': run['id'], 'candidate_run_id': candidate['id'],
    }).json()
    assert comparison['partial'] is False
    monkeypatch.delenv('SIGNOFF_COVERAGE_HMAC_KEYS')
    assert editor.post(path, json=body).json()['id'] == run['id']


def test_invalid_or_failing_emir_attestation_never_opens_gate(accounts, monkeypatch):
    secret = 'emir-collector-secret-with-at-least-32-bytes'
    monkeypatch.setenv('SIGNOFF_COVERAGE_HMAC_KEYS', json.dumps({'qa-emir-collector': {'secret': secret, 'domains': ['emir']}}))
    _, ids, login = accounts
    path = f"/projects/{ids['project']}/imports/commercial-emir"
    editor = login('editor')
    bad = payload({**report(), 'findings': []})
    bad['coverage_attestation'] = attest(bad, ids['project'], secret)
    bad['coverage_attestation']['claims'].pop('extraction_complete')
    assert editor.post(path + '/preview', json=bad).status_code == 422
    wrong_scope = payload({**report(), 'findings': []})
    wrong_scope['coverage_attestation'] = attest(wrong_scope, ids['project'], secret)
    monkeypatch.setenv('SIGNOFF_COVERAGE_HMAC_KEYS', json.dumps({
        'qa-emir-collector': {'secret': secret, 'domains': ['sta']},
    }))
    scope_response = editor.post(path + '/preview', json=wrong_scope)
    assert scope_response.status_code == 422 and 'this domain' in scope_response.json()['detail']
    monkeypatch.setenv('SIGNOFF_COVERAGE_HMAC_KEYS', json.dumps({
        'qa-emir-collector': {'secret': secret, 'domains': ['emir']},
    }))
    failing = payload()
    failing['coverage_attestation'] = attest(failing, ids['project'], secret)
    preview = editor.post(path + '/preview', json=failing)
    assert preview.status_code == 200 and preview.json()['status'] == 'failed'
    run = editor.post(path, json=failing).json()
    emir = next(item for item in editor.get(
        f"/projects/{ids['project']}/signoff-status?stage=routing").json()['domains'] if item['domain'] == 'emir')
    assert emir['run_id'] == run['id'] and emir['ready'] is False
    assert emir['reason'] == "latest run status is 'failed'"
