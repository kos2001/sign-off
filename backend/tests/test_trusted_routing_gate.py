import io
import json
import zipfile

from test_commercial_drc import attest as attest_drc
from test_commercial_drc import payload as drc_payload
from test_commercial_drc import report as drc_report
from test_commercial_emir import attest as attest_emir
from test_commercial_emir import payload as emir_payload
from test_commercial_emir import report as emir_report
from test_commercial_lvs import attest_lvs, matched as lvs_matched, payload as lvs_payload
from test_report_import import attest_sta, commercial_payload, commercial_report


def test_same_revision_trusted_reports_open_and_archive_routing_gate(client, monkeypatch):
    keys = {
        'qa-collector-1': 'collector-secret-that-is-at-least-32-bytes',
        'qa-drc-collector': 'drc-collector-secret-with-at-least-32-bytes',
        'qa-emir-collector': 'emir-collector-secret-with-at-least-32-bytes',
        'qa-lvs-collector': 'lvs-collector-secret-with-at-least-32-bytes',
    }
    monkeypatch.setenv('SIGNOFF_COVERAGE_HMAC_KEYS', json.dumps({
        'qa-collector-1': {'secret': keys['qa-collector-1'], 'domains': ['sta']},
        'qa-drc-collector': {'secret': keys['qa-drc-collector'], 'domains': ['pv']},
        'qa-emir-collector': {'secret': keys['qa-emir-collector'], 'domains': ['emir']},
        'qa-lvs-collector': {'secret': keys['qa-lvs-collector'], 'domains': ['lvs']},
    }))
    project = client.post('/projects', json={
        'name': 'trusted-routing-gate', 'foundry': 'QA', 'process_node': '5nm',
    }).json()
    pid, revision = project['id'], 'routing-release-r1'

    sta = commercial_payload({**commercial_report(slack=0.1), 'paths': []})
    sta['design_revision'] = revision
    sta['coverage_attestation'] = attest_sta(sta, pid, keys['qa-collector-1'])
    drc = drc_payload({**drc_report(), 'markers': []})
    drc['design_revision'] = revision
    drc['coverage_attestation'] = attest_drc(drc, pid, keys['qa-drc-collector'])
    emir = emir_payload({**emir_report(), 'findings': []})
    emir['design_revision'] = revision
    emir['coverage_attestation'] = attest_emir(emir, pid, keys['qa-emir-collector'])
    lvs = lvs_payload(lvs_matched()); lvs['design_revision'] = revision
    lvs['coverage_attestation'] = attest_lvs(lvs, pid, keys['qa-lvs-collector'])

    runs = [
        client.post(f'/projects/{pid}/imports/commercial-sta', json=sta),
        client.post(f'/projects/{pid}/imports/commercial-drc', json=drc),
        client.post(f'/projects/{pid}/imports/commercial-emir', json=emir),
        client.post(f'/projects/{pid}/imports/commercial-lvs', json=lvs),
    ]
    assert [response.status_code for response in runs] == [201] * 4
    assert [response.json()['status'] for response in runs] == ['passed'] * 4

    gate = client.get(f'/projects/{pid}/signoff-status?stage=routing').json()
    assert gate['ready'] is True
    assert gate['revision_check'] == {
        'status': 'consistent', 'revisions': [revision], 'missing_domains': [],
        'common_revision': revision,
    }
    assert all(item['ready'] for item in gate['domains'])

    pin = client.put(f'/projects/{pid}/target-revisions/routing', json={
        'expected_version': 0, 'design_revision': revision,
        'reason': 'Pin routing release candidate.',
    })
    assert pin.status_code == 200, pin.text
    reviewed = client.get(f'/projects/{pid}/signoff-releases/review?stage=routing').json()
    decision = client.post(f'/projects/{pid}/signoff-releases', json={
        'stage': 'routing', 'decision': 'approved',
        'reason': 'Trusted collectors completed the routing signoff scope.',
        'expected_evidence_sha256': reviewed['evidence_snapshot_sha256'],
    })
    assert decision.status_code == 201, decision.text
    saved = decision.json()
    assert saved['decision'] == 'approved' and saved['design_revision'] == revision
    package = client.get(f"/projects/{pid}/signoff-releases/{saved['id']}/package")
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['gate']['ready'] is True
        assert {row['domain'] for row in manifest['runs']} == {'sta', 'pv', 'emir', 'lvs'}
        assert len(manifest['files']) == 4
