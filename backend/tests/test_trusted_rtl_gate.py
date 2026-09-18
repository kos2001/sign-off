import io
import json
import zipfile

from test_commercial_rtl import attest_rtl, payload as rtl_payload, report as rtl_report
from test_commercial_cdc import attest as attest_cdc, clean as cdc_clean, payload as cdc_payload
from test_report_import import attest_sta, commercial_payload, commercial_report


def test_same_revision_trusted_reports_open_and_archive_rtl_gate(client, monkeypatch):
    keys = {
        'qa-rtl-collector': 'rtl-collector-secret-with-at-least-32-bytes',
        'qa-collector-1': 'collector-secret-that-is-at-least-32-bytes',
        'qa-cdc': 'cdc-collector-secret-with-at-least-32-bytes',
    }
    monkeypatch.setenv('SIGNOFF_COVERAGE_HMAC_KEYS', json.dumps({
        'qa-rtl-collector': {'secret': keys['qa-rtl-collector'], 'domains': ['rtl']},
        'qa-collector-1': {'secret': keys['qa-collector-1'], 'domains': ['sta']},
        'qa-cdc': {'secret': keys['qa-cdc'], 'domains': ['cdc']},
    }))
    project = client.post('/projects', json={
        'name': 'trusted-rtl-gate', 'foundry': 'QA', 'process_node': '5nm',
    }).json()
    pid, revision = project['id'], 'rtl-release-r1'
    rtl_document = rtl_report()
    rtl_document['tests'] = rtl_document['tests'][:1]
    rtl = rtl_payload(rtl_document)
    sta = commercial_payload({**commercial_report(slack=0.1), 'paths': []})
    cdc = cdc_payload(cdc_clean())
    for body in (rtl, sta, cdc):
        body['stage'] = 'rtl'
        body['design_revision'] = revision
    rtl['coverage_attestation'] = attest_rtl(rtl, pid, keys['qa-rtl-collector'])
    sta['coverage_attestation'] = attest_sta(sta, pid, keys['qa-collector-1'])
    cdc['coverage_attestation'] = attest_cdc(cdc, pid, keys['qa-cdc'])
    responses = [
        client.post(f'/projects/{pid}/imports/commercial-rtl', json=rtl),
        client.post(f'/projects/{pid}/imports/commercial-sta', json=sta),
        client.post(f'/projects/{pid}/imports/commercial-cdc', json=cdc),
    ]
    assert [response.status_code for response in responses] == [201, 201, 201]
    assert [response.json()['status'] for response in responses] == ['passed', 'passed', 'passed']
    gate = client.get(f'/projects/{pid}/signoff-status?stage=rtl').json()
    assert gate['ready'] is True and gate['revision_check']['common_revision'] == revision
    decision = client.post(f'/projects/{pid}/signoff-releases', json={
        'stage': 'rtl', 'decision': 'approved',
        'reason': 'Trusted collectors completed RTL regression and timing scope.',
    })
    assert decision.status_code == 201, decision.text
    package = client.get(f"/projects/{pid}/signoff-releases/{decision.json()['id']}/package")
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['gate']['ready'] is True
        assert {row['domain'] for row in manifest['runs']} == {'rtl', 'sta', 'cdc'}
        assert len(manifest['files']) == 3
