import io
import json
import zipfile

from test_commercial_drc import attest as attest_drc
from test_commercial_drc import payload as drc_payload
from test_commercial_drc import report as drc_report
from test_commercial_emir import attest as attest_emir
from test_commercial_emir import payload as emir_payload
from test_commercial_emir import report as emir_report
from test_commercial_power import attest_power, payload as power_payload, report as power_report
from test_commercial_thermal import attest_thermal, payload as thermal_payload, report as thermal_report
from test_commercial_lvs import attest_lvs, matched as lvs_matched, payload as lvs_payload
from test_commercial_lec import attest as attest_lec, equivalent as lec_equivalent, payload as lec_payload
from test_commercial_dft import attest as attest_dft, passed as dft_passed, payload as dft_payload
from test_report_import import attest_sta, commercial_payload, commercial_report


def test_same_revision_trusted_reports_open_and_archive_final_gate(client, monkeypatch):
    keys = {
        'qa-collector-1': 'collector-secret-that-is-at-least-32-bytes',
        'qa-drc-collector': 'drc-collector-secret-with-at-least-32-bytes',
        'qa-emir-collector': 'emir-collector-secret-with-at-least-32-bytes',
        'qa-power-collector': 'power-collector-secret-with-at-least-32-bytes',
        'qa-thermal-collector': 'thermal-collector-secret-with-at-least-32-bytes',
        'qa-lvs-collector': 'lvs-collector-secret-with-at-least-32-bytes',
        'qa-lec': 'lec-collector-secret-with-at-least-32-bytes',
        'qa-dft': 'dft-collector-secret-with-at-least-32-bytes',
    }
    monkeypatch.setenv('SIGNOFF_COVERAGE_HMAC_KEYS', json.dumps({
        key_id: {'secret': secret, 'domains': [domain]}
        for key_id, secret, domain in [
            ('qa-collector-1', keys['qa-collector-1'], 'sta'),
            ('qa-drc-collector', keys['qa-drc-collector'], 'pv'),
            ('qa-emir-collector', keys['qa-emir-collector'], 'emir'),
            ('qa-power-collector', keys['qa-power-collector'], 'glitch_power'),
            ('qa-thermal-collector', keys['qa-thermal-collector'], 'thermal'),
            ('qa-lvs-collector', keys['qa-lvs-collector'], 'lvs'),
            ('qa-lec', keys['qa-lec'], 'lec'),
            ('qa-dft', keys['qa-dft'], 'dft'),
        ]
    }))
    project = client.post('/projects', json={
        'name': 'trusted-final-gate', 'foundry': 'QA', 'process_node': '5nm',
    }).json()
    pid, revision = project['id'], 'final-release-r1'

    sta = commercial_payload({**commercial_report(slack=0.1), 'paths': []})
    drc = drc_payload({**drc_report(), 'markers': []})
    emir = emir_payload({**emir_report(), 'findings': []})
    power_document = power_report()
    power_document['summary']['glitch_power'] = 100
    power_document['hierarchy'][0]['glitch_power'] = 50
    power = power_payload(power_document)
    thermal = thermal_payload({**thermal_report(), 'hotspots': []})
    lvs = lvs_payload(lvs_matched())
    lec = lec_payload(lec_equivalent())
    dft = dft_payload(dft_passed())
    payloads = [sta, drc, emir, power, thermal, lvs, lec, dft]
    for body in payloads:
        body['stage'] = 'final'
        body['design_revision'] = revision
    sta['coverage_attestation'] = attest_sta(sta, pid, keys['qa-collector-1'])
    drc['coverage_attestation'] = attest_drc(drc, pid, keys['qa-drc-collector'])
    emir['coverage_attestation'] = attest_emir(emir, pid, keys['qa-emir-collector'])
    power['coverage_attestation'] = attest_power(power, pid, keys['qa-power-collector'])
    thermal['coverage_attestation'] = attest_thermal(thermal, pid, keys['qa-thermal-collector'])
    lvs['coverage_attestation'] = attest_lvs(lvs, pid, keys['qa-lvs-collector'])
    lec['coverage_attestation'] = attest_lec(lec, pid, keys['qa-lec'])
    dft['coverage_attestation'] = attest_dft(dft, pid, keys['qa-dft'])

    endpoints = ['commercial-sta', 'commercial-drc', 'commercial-emir', 'commercial-power', 'commercial-thermal', 'commercial-lvs', 'commercial-lec', 'commercial-dft']
    responses = [client.post(f'/projects/{pid}/imports/{endpoint}', json=body)
                 for endpoint, body in zip(endpoints, payloads)]
    assert [response.status_code for response in responses] == [201] * 8
    assert [response.json()['status'] for response in responses] == ['passed'] * 8

    gate = client.get(f'/projects/{pid}/signoff-status?stage=final').json()
    assert gate['ready'] is True
    assert gate['revision_check']['common_revision'] == revision
    assert all(item['ready'] for item in gate['domains'])

    decision = client.post(f'/projects/{pid}/signoff-releases', json={
        'stage': 'final', 'decision': 'approved',
        'reason': 'Trusted collectors completed the final signoff scope.',
    })
    assert decision.status_code == 201, decision.text
    package = client.get(f"/projects/{pid}/signoff-releases/{decision.json()['id']}/package")
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['gate']['ready'] is True
        assert {row['domain'] for row in manifest['runs']} == {
            'sta', 'pv', 'emir', 'lvs', 'lec', 'dft', 'glitch_power', 'thermal',
        }
        assert len(manifest['files']) == 8
