import copy
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.routers.imports import CoverageAttestationPayload
from app.services.commercial_lvs import parse_commercial_lvs
from app.services.coverage_attestation import REQUIRED_LVS_CLAIMS, canonical_payload
from test_auth import accounts


def report(tool='Siemens Calibre nmLVS'):
    return {'format': 'signoff/commercial-lvs/v1', 'tool': tool, 'tool_version': '2025.2',
        'layout_top': 'CHIP', 'schematic_top': 'CHIP', 'status': 'mismatched',
        'summary': {'layout_devices': 1002, 'schematic_devices': 1001,
                    'layout_nets': 804, 'schematic_nets': 803},
        'mismatches': [
            {'kind': 'short', 'name': 'VDD_to_VSS', 'severity': 'critical',
             'layout_object': 'net:VDD', 'schematic_object': 'net:VSS',
             'message': 'Layout short joins distinct schematic nets.'},
            {'kind': 'missing_device', 'name': 'M404', 'severity': 'error',
             'schematic_object': 'device:M404', 'message': 'Schematic device is absent from layout.'},
        ]}


def payload(document=None):
    document = report() if document is None else document
    return {'import_id': str(uuid.uuid4()), 'stage': 'routing', 'filename': 'calibre-lvs.json',
        'tool_version': document.get('tool_version', '2025.2'), 'design_revision': 'rev-lvs',
        'scenario': 'signoff-extracted', 'source_text': json.dumps(document, indent=2) + '\n'}


def attest_lvs(body, project_id, secret='lvs-collector-secret-with-at-least-32-bytes'):
    now = datetime.now(timezone.utc); document = json.loads(body['source_text'])
    value = {'format': 'signoff/coverage-attestation/v1', 'attestation_id': body['import_id'],
        'key_id': 'qa-lvs-collector', 'issued_at': now.isoformat(),
        'expires_at': (now + timedelta(hours=1)).isoformat(), 'project_id': project_id,
        'stage': body['stage'], 'domain': 'lvs', 'design_revision': body['design_revision'],
        'source_sha256': hashlib.sha256(body['source_text'].encode()).hexdigest(),
        'tool': document['tool'], 'tool_version': body['tool_version'], 'scenario': body['scenario'],
        'claims': {claim: True for claim in REQUIRED_LVS_CLAIMS}, 'signature': '0' * 64}
    parsed = CoverageAttestationPayload.model_validate(value)
    value['signature'] = hmac.new(secret.encode(), canonical_payload(parsed), hashlib.sha256).hexdigest()
    return value


def matched(tool='Siemens Calibre nmLVS'):
    document = report(tool); document['status'] = 'matched'; document['mismatches'] = []
    document['summary'] = {'layout_devices': 1001, 'schematic_devices': 1001,
                           'layout_nets': 803, 'schematic_nets': 803}
    return document


def test_parser_preserves_counts_mismatches_and_identity():
    result = parse_commercial_lvs(json.dumps(report()))
    assert result['status'] == 'failed' and result['lvs_status'] == 'mismatched'
    assert result['metrics']['reported_mismatches'] == 2
    assert result['metrics']['short_mismatches'] == 1
    changed = report(); changed['mismatches'][0]['message'] = 'different detail'
    assert parse_commercial_lvs(json.dumps(changed))['items'][0]['fingerprint'] == result['items'][0]['fingerprint']
    assert parse_commercial_lvs(json.dumps(matched('Cadence Pegasus LVS')))['status'] == 'incomplete'


@pytest.mark.parametrize('field,value', [('format', 'bad'), ('tool', 'bad'), ('status', 'unknown'),
    ('summary', {}), ('mismatches', [{}])])
def test_invalid_reports(field, value):
    document = copy.deepcopy(report()); document[field] = value
    with pytest.raises(ValueError): parse_commercial_lvs(json.dumps(document))


def test_rejects_contradictory_verdicts_and_error_shape():
    document = matched(); document['mismatches'] = report()['mismatches']
    with pytest.raises(ValueError, match='matched'): parse_commercial_lvs(json.dumps(document))
    document = report(); document['mismatches'] = []
    with pytest.raises(ValueError, match='at least one'): parse_commercial_lvs(json.dumps(document))
    document = matched(); document['status'] = 'error'; document['error_message'] = 'extraction failed'
    assert parse_commercial_lvs(json.dumps(document))['status'] == 'failed'


def test_import_evidence_violations_retry_and_unattested_gate(accounts):
    _, ids, login = accounts; path = f"/projects/{ids['project']}/imports/commercial-lvs"; body = payload()
    viewer, editor, outsider = login('viewer'), login('editor'), login('outsider')
    assert viewer.post(path + '/preview', json=body).status_code == 403
    assert outsider.post(path, json=body).status_code == 404
    assert editor.post(path + '/preview', json=body).json()['metrics']['reported_mismatches'] == 2
    response = editor.post(path, json=body); assert response.status_code == 201, response.text
    run = response.json(); assert run['domain'] == 'lvs' and run['evidence_source'] == 'commercial_lvs_report'
    assert editor.post(path, json=body).json()['id'] == run['id']
    assert editor.post(path, json={**body, 'scenario': 'changed'}).status_code == 409
    evidence = viewer.get(f"/runs/{run['id']}/evidence").json()
    assert evidence['source_sha256'] == hashlib.sha256(body['source_text'].encode()).hexdigest()
    violations = viewer.get(f"/runs/{run['id']}/violations").json()
    assert len(violations) == 2 and all(item['check_name'].startswith('calibre-lvs/') for item in violations)
    page = viewer.get(f"/runs/{run['id']}/lvs-mismatches").json()
    assert page['reported_total'] == 2 and page['lvs_status'] == 'mismatched'
    assert viewer.get(f"/runs/{run['id']}/lvs-mismatches?kind=short").json()['total'] == 1
    assert viewer.get(f"/runs/{run['id']}/lvs-mismatches?q=M404").json()['total'] == 1
    assert outsider.get(f"/runs/{run['id']}/lvs-mismatches").status_code == 404
    gate = viewer.get(f"/projects/{ids['project']}/signoff-status?stage=routing").json()
    lvs = next(item for item in gate['domains'] if item['domain'] == 'lvs')
    assert not lvs['ready'] and 'full LVS coverage' in lvs['reason']


def test_trusted_matched_lvs_establishes_gate_coverage(accounts, monkeypatch):
    secret = 'lvs-collector-secret-with-at-least-32-bytes'
    monkeypatch.setenv('SIGNOFF_COVERAGE_HMAC_KEYS', json.dumps({
        'qa-lvs-collector': {'secret': secret, 'domains': ['lvs']}}))
    _, ids, login = accounts; body = payload(matched()); body['coverage_attestation'] = attest_lvs(body, ids['project'], secret)
    path = f"/projects/{ids['project']}/imports/commercial-lvs"; editor = login('editor')
    preview = editor.post(path + '/preview', json=body)
    assert preview.status_code == 200 and preview.json()['status'] == 'passed'
    run = editor.post(path, json=body).json(); assert run['status'] == 'passed'
    lvs = next(item for item in editor.get(f"/projects/{ids['project']}/signoff-status?stage=routing").json()['domains'] if item['domain'] == 'lvs')
    assert lvs['ready'] and lvs['run_id'] == run['id']
    monkeypatch.delenv('SIGNOFF_COVERAGE_HMAC_KEYS')
    assert editor.post(path, json=body).json()['id'] == run['id']


def test_invalid_or_mismatched_attestation_never_passes(accounts, monkeypatch):
    secret = 'lvs-collector-secret-with-at-least-32-bytes'
    monkeypatch.setenv('SIGNOFF_COVERAGE_HMAC_KEYS', json.dumps({
        'qa-lvs-collector': {'secret': secret, 'domains': ['lvs']}}))
    _, ids, login = accounts; editor = login('editor'); path = f"/projects/{ids['project']}/imports/commercial-lvs"
    bad = payload(matched()); bad['coverage_attestation'] = attest_lvs(bad, ids['project'], secret)
    bad['coverage_attestation']['claims'].pop('comparison_complete')
    assert editor.post(path + '/preview', json=bad).status_code == 422
    failing = payload(); failing['coverage_attestation'] = attest_lvs(failing, ids['project'], secret)
    assert editor.post(path + '/preview', json=failing).json()['status'] == 'failed'
