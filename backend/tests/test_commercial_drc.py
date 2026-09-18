import copy
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services.commercial_drc import parse_commercial_drc
from app.services.coverage_attestation import REQUIRED_DRC_CLAIMS, canonical_payload
from app.routers.imports import CoverageAttestationPayload
from test_auth import accounts


def report(tool='Siemens Calibre nmDRC'):
    return {
        'format': 'signoff/commercial-drc-markers/v1', 'tool': tool,
        'tool_version': '2025.2_18.11', 'coordinate_unit': 'nm',
        'top_cell': 'CHIP', 'rule_deck': 'foundry-deck-7nm-r42',
        'markers': [
            {'rule': 'M1.SPACING.1', 'cell': 'CORE', 'severity': 'critical',
             'multiplicity': 2, 'message': 'M1 spacing below minimum',
             'shapes': [{'type': 'box', 'points': [[1500, 2000], [1600, 2100]]}]},
            {'rule': 'VIA1.ENC.2', 'cell': '', 'severity': 'warning',
             'shapes': [{'type': 'polygon', 'contours': [
                 [[0, 0], [100, 0], [100, 100], [0, 100]],
                 [[20, 20], [40, 20], [40, 40]],
             ]}]},
        ],
    }


def payload(document=None):
    document = report() if document is None else document
    return {'import_id': str(uuid.uuid4()), 'stage': 'routing', 'filename': 'calibre-markers.json',
            'tool_version': document.get('tool_version', '2025.2_18.11'),
            'design_revision': 'rev-commercial-pv', 'scenario': 'foundry-deck-7nm-r42',
            'source_text': json.dumps(document, ensure_ascii=False, indent=2) + '\n'}


def attest(body, project_id, secret='drc-collector-secret-with-at-least-32-bytes'):
    now = datetime.now(timezone.utc)
    document = json.loads(body['source_text'])
    value = {
        'format': 'signoff/coverage-attestation/v1', 'attestation_id': body['import_id'],
        'key_id': 'qa-drc-collector', 'issued_at': now.isoformat(),
        'expires_at': (now + timedelta(hours=1)).isoformat(), 'project_id': project_id,
        'stage': body['stage'], 'domain': 'pv', 'design_revision': body['design_revision'],
        'source_sha256': hashlib.sha256(body['source_text'].encode()).hexdigest(),
        'tool': document['tool'], 'tool_version': body['tool_version'], 'scenario': body['scenario'],
        'claims': {claim: True for claim in REQUIRED_DRC_CLAIMS}, 'signature': '0' * 64,
    }
    parsed = CoverageAttestationPayload.model_validate(value)
    value['signature'] = hmac.new(secret.encode(), canonical_payload(parsed), hashlib.sha256).hexdigest()
    return value


def test_parser_normalizes_units_shapes_severity_and_identity():
    source = json.dumps(report())
    result = parse_commercial_drc(source)
    assert result['tool'] == 'Siemens Calibre nmDRC'
    assert result['parser'] == 'commercial-drc-markers-json/v1'
    assert result['status'] == 'failed'
    assert result['metrics'] == {
        'reported_items': 2, 'reported_multiplicity': 3, 'blocking_multiplicity': 2,
        'severity_counts': {'critical': 2, 'error': 0, 'info': 0, 'warning': 1},
    }
    assert result['items'][0]['values'] == ['box: (1.500,2.000;1.600,2.100)']
    assert result['items'][1]['values'] == ['polygon: (0.000,0.000;0.100,0.000;0.100,0.100;0.000,0.100/0.020,0.020;0.040,0.020;0.040,0.040)']
    changed = report()
    changed['markers'][0]['multiplicity'] = 3
    assert parse_commercial_drc(json.dumps(changed))['items'][0]['fingerprint'] == result['items'][0]['fingerprint']
    pegasus = report('Cadence Pegasus')
    pegasus['markers'] = []
    assert parse_commercial_drc(json.dumps(pegasus))['status'] == 'incomplete'


@pytest.mark.parametrize('change', [
    ('format', 'wrong'), ('tool', 'unknown'), ('tool_version', ' '), ('coordinate_unit', 'mm'),
    ('markers', [{}]), ('markers', [{**report()['markers'][0], 'severity': 'blocker'}]),
    ('markers', [{**report()['markers'][0], 'multiplicity': True}]),
    ('markers', [{**report()['markers'][0], 'shapes': []}]),
    ('markers', [{**report()['markers'][0], 'shapes': [{'type': 'box', 'points': [[0, 0]]}]}]),
    ('markers', [{**report()['markers'][0], 'shapes': [{'type': 'polygon', 'contours': [[[0, 0], [1, 1]]]}]}]),
])
def test_invalid_reports_are_rejected(change):
    document = copy.deepcopy(report())
    document[change[0]] = change[1]
    with pytest.raises(ValueError):
        parse_commercial_drc(json.dumps(document))


def test_preview_import_evidence_markers_violation_and_retry(accounts):
    _, ids, login = accounts
    path = f"/projects/{ids['project']}/imports/commercial-drc"
    body = payload()
    viewer, editor, outsider = login('viewer'), login('editor'), login('outsider')
    assert viewer.post(path + '/preview', json=body).status_code == 403
    assert outsider.post(path, json=body).status_code == 404
    preview = editor.post(path + '/preview', json=body)
    assert preview.status_code == 200 and preview.json()['metrics']['blocking_multiplicity'] == 2
    response = editor.post(path, json=body)
    assert response.status_code == 201, response.text
    run = response.json()
    assert run['tool'] == 'Siemens Calibre nmDRC'
    assert run['domain'] == 'pv' and run['status'] == 'failed'
    assert run['evidence_source'] == 'commercial_drc_report' and run['result_locked']
    assert editor.post(path, json=body).json()['id'] == run['id']
    assert editor.post(path, json={**body, 'scenario': 'changed'}).status_code == 409
    assert editor.post(path + '/preview', json={**body, 'tool_version': 'wrong'}).status_code == 422
    evidence = viewer.get(f"/runs/{run['id']}/evidence").json()
    assert evidence['source_text'] == body['source_text']
    assert evidence['source_sha256'] == hashlib.sha256(body['source_text'].encode()).hexdigest()
    assert evidence['result']['metadata']['report_format'] == 'commercial-drc-markers-json/v1'
    violations = viewer.get(f"/runs/{run['id']}/violations").json()
    assert [row['severity'] for row in violations] == ['critical', 'warning']
    assert violations[0]['check_name'].startswith('calibre/')
    markers = viewer.get(f"/runs/{run['id']}/markers").json()
    assert markers['reported_total'] == 2 and markers['matched_multiplicity'] == 3
    detail = viewer.get(f"/runs/{run['id']}/markers/1").json()
    assert detail['geometry']['bounds_um'] == {'xmin': '1.500', 'xmax': '1.600', 'ymin': '2.000', 'ymax': '2.100'}
    assert detail['violation_matches']['status'] == 'unique'
    source = viewer.get(f"/runs/{run['id']}/evidence/source")
    assert source.content == body['source_text'].encode() and '.json' in source.headers['content-disposition']


def test_trusted_drc_attestation_can_establish_pv_gate_coverage(accounts, monkeypatch):
    secret = 'drc-collector-secret-with-at-least-32-bytes'
    monkeypatch.setenv('SIGNOFF_COVERAGE_HMAC_KEYS', json.dumps({'qa-drc-collector': secret}))
    _, ids, login = accounts
    body = payload({**report(), 'markers': []})
    body['coverage_attestation'] = attest(body, ids['project'], secret)
    path = f"/projects/{ids['project']}/imports/commercial-drc"
    editor = login('editor')
    preview = editor.post(path + '/preview', json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()['status'] == 'passed'
    assert preview.json()['coverage'] == 'collector_attested_complete'
    run = editor.post(path, json=body).json()
    assert run['status'] == 'passed'
    evidence = editor.get(f"/runs/{run['id']}/evidence").json()
    assert evidence['result']['coverage_attestation']['signature'] == body['coverage_attestation']['signature']
    pv = next(item for item in editor.get(
        f"/projects/{ids['project']}/signoff-status?stage=routing").json()['domains'] if item['domain'] == 'pv')
    assert pv['ready'] is True and pv['run_id'] == run['id']
    candidate_body = payload({**report(), 'markers': []})
    candidate_body['coverage_attestation'] = attest(candidate_body, ids['project'], secret)
    candidate = editor.post(path, json=candidate_body).json()
    comparison = editor.get(f"/projects/{ids['project']}/run-comparison", params={
        'baseline_run_id': run['id'], 'candidate_run_id': candidate['id'],
    }).json()
    assert comparison['partial'] is False
    monkeypatch.delenv('SIGNOFF_COVERAGE_HMAC_KEYS')
    assert editor.post(path, json=body).json()['id'] == run['id']


def test_invalid_or_failing_drc_attestation_never_opens_gate(accounts, monkeypatch):
    secret = 'drc-collector-secret-with-at-least-32-bytes'
    monkeypatch.setenv('SIGNOFF_COVERAGE_HMAC_KEYS', json.dumps({'qa-drc-collector': secret}))
    _, ids, login = accounts
    path = f"/projects/{ids['project']}/imports/commercial-drc"
    editor = login('editor')
    bad = payload({**report(), 'markers': []})
    bad['coverage_attestation'] = attest(bad, ids['project'], secret)
    bad['coverage_attestation']['signature'] = 'f' * 64
    assert editor.post(path + '/preview', json=bad).status_code == 422
    no_deck = payload({key: value for key, value in {**report(), 'markers': []}.items() if key != 'rule_deck'})
    no_deck['coverage_attestation'] = attest(no_deck, ids['project'], secret)
    assert editor.post(path + '/preview', json=no_deck).status_code == 422
    failing = payload()
    failing['coverage_attestation'] = attest(failing, ids['project'], secret)
    preview = editor.post(path + '/preview', json=failing)
    assert preview.status_code == 200 and preview.json()['status'] == 'failed'
    run = editor.post(path, json=failing).json()
    pv = next(item for item in editor.get(
        f"/projects/{ids['project']}/signoff-status?stage=routing").json()['domains'] if item['domain'] == 'pv')
    assert pv['run_id'] == run['id'] and pv['ready'] is False
    assert pv['reason'] == "latest run status is 'failed'"
