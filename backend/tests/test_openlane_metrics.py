import hashlib
import json
import uuid
from pathlib import Path

import pytest

from app.services.openlane_metrics import parse_openlane_metrics
from test_auth import accounts  # noqa: F401

FIXTURES = Path(__file__).parent / 'fixtures' / 'openlane'


def source(name):
    # Real OpenLane 2 sky130 runs from the ppa-eda-agent reference experiments.
    return (FIXTURES / f'{name}.json').read_text()


def domains(result):
    return {item['domain']: item for item in result['domains']}


def payload(name='aes-timing-fail', **changes):
    return {'import_id': str(uuid.uuid4()), 'stage': 'routing', 'filename': 'metrics.json',
            'tool_version': '2.3.10', 'design_revision': 'rev-openlane', 'scenario': 'aes-closure',
            'source_text': source(name), **changes}


def test_clean_run_creates_three_unproven_domains_with_design_summary():
    result = parse_openlane_metrics(source('sram-clean'))
    by_domain = domains(result)
    assert list(by_domain) == ['sta', 'pv', 'lvs']
    assert all(item['status'] == 'incomplete' and not item['items'] for item in by_domain.values())
    sta = by_domain['sta']['metrics']
    assert sta['corners'] == 9 and sta['setup_wns_ps'] == pytest.approx(9172.641573)
    assert by_domain['lvs']['metrics']['lvs_errors'] == 0
    assert result['design_summary']['instances'] == 4547
    assert result['design_summary']['total_power_mw'] == pytest.approx(2.464507474)
    assert result['source_sha256'] == hashlib.sha256(source('sram-clean').encode()).hexdigest()


def test_failing_corners_become_blocking_findings_in_ps():
    by_domain = domains(parse_openlane_metrics(source('aes-timing-fail')))
    sta = by_domain['sta']
    assert sta['status'] == 'failed'
    assert sta['metrics']['setup_wns_ps'] == pytest.approx(-1467.023877)
    # The file's aggregate (237) is the sum of the per-corner counts.
    assert sta['metrics']['setup_violations'] == 237 and sta['metrics']['hold_violations'] == 294
    errors = {item['check'] for item in sta['items'] if item['severity'] == 'error'}
    assert errors == {f'{check}/{corner}' for check in ('setup', 'hold')
                      for corner in ('min_ss_100C_1v60', 'nom_ss_100C_1v60', 'max_ss_100C_1v60')}
    assert any(item['check'] == 'max-slew/max_ss_100C_1v60' and item['severity'] == 'warning' for item in sta['items'])
    # OpenLane has no antenna checker: antenna nets are warnings, not blocking errors.
    assert by_domain['pv']['status'] == 'incomplete'
    assert {item['check'] for item in by_domain['pv']['items']} == {'antenna-nets', 'antenna-pins'}


def test_partial_files_only_create_reported_domains_and_keep_aggregate_drv():
    result = parse_openlane_metrics(source('aes-sta-only'))
    assert [item['domain'] for item in result['domains']] == ['sta']
    checks = {item['check'] for item in result['domains'][0]['items']}
    assert {'max-slew/all corners', 'max-cap/all corners', 'max-fanout/all corners'} <= checks


def test_failed_run_state_out_is_accepted():
    result = parse_openlane_metrics(source('aes-state-out'))
    assert result['source_format'] == 'state_out.json' and result['metric_count'] == 321
    assert domains(result)['pv']['metrics']['antenna_nets'] == 11


def test_unbounded_slack_and_time_unit():
    document = json.loads(source('sram-clean'))
    key = 'timing__setup__ws__corner:nom_tt_025C_1v80'
    text = json.dumps(document).replace(json.dumps(key) + ': ' + json.dumps(document[key]), json.dumps(key) + ': Infinity')
    result = parse_openlane_metrics(text)
    assert result['non_finite_metrics'] == [key]
    row = next(row for row in domains(result)['sta']['corners'] if row['corner'] == 'nom_tt_025C_1v80')
    assert row['setup_ws_ps'] is None
    assert domains(parse_openlane_metrics(source('sram-clean'), 'ps'))['sta']['metrics']['setup_wns_ps'] == pytest.approx(9.172642)


@pytest.mark.parametrize('text,match', [
    ('[]', 'flat metrics.json'),
    ('{"format": "signoff/commercial-lvs/v1"}', 'no timing'),
    ('{"route__drc_errors": NaN}', 'invalid JSON'),
    ('{"route__drc_errors": 1, "route__drc_errors": 2}', 'invalid JSON'),
    ('{"route__drc_errors": -1}', 'non-negative count'),
    ('{"route__drc_errors": "3"}', 'expected a number'),
    ('{"Route DRC": 3}', 'unsupported metric name'),
    ('{"route__drc_errors": {"value": 3}}', 'nested values'),
])
def test_rejects_malformed_metrics(text, match):
    with pytest.raises(ValueError, match=match):
        parse_openlane_metrics(text)


def test_import_creates_domain_runs_idempotently_and_never_opens_the_gate(accounts):  # noqa: F811
    _, ids, login = accounts
    path = f"/projects/{ids['project']}/imports/openlane-metrics"
    viewer, editor, outsider = login('viewer'), login('editor'), login('outsider')
    body = payload()
    assert viewer.post(path, json=body).status_code == 403
    assert outsider.post(path, json=body).status_code == 404
    preview = editor.post(path + '/preview', json=body)
    assert preview.status_code == 200 and [item['domain'] for item in preview.json()['domains']] == ['sta', 'pv', 'lvs']
    response = editor.post(path, json=body)
    assert response.status_code == 201, response.text
    runs = response.json()['runs']
    assert [(run['domain'], run['status'], run['evidence_source']) for run in runs] == [
        ('sta', 'failed', 'openlane_metrics'), ('pv', 'incomplete', 'openlane_metrics'),
        ('lvs', 'incomplete', 'openlane_metrics')]
    assert all(run['design_revision'] == 'rev-openlane' and run['tool'] == 'OpenLane 2' for run in runs)
    assert [run['id'] for run in editor.post(path, json=body).json()['runs']] == [run['id'] for run in runs]
    assert editor.post(path, json={**body, 'scenario': 'changed'}).status_code == 409
    sta_id = runs[0]['id']
    evidence = viewer.get(f'/runs/{sta_id}/evidence').json()
    assert evidence['source_sha256'] == hashlib.sha256(body['source_text'].encode()).hexdigest()
    assert evidence['result']['flow_domains'] == ['sta', 'pv', 'lvs']
    assert evidence['result']['design_summary']['instances'] == 20761
    violations = viewer.get(f'/runs/{sta_id}/violations').json()
    blocking = [item for item in violations if item['severity'] == 'error']
    assert len(blocking) == 6 and all(item['check_name'].startswith('openlane/sta/') for item in violations)
    assert editor.patch(f'/runs/{sta_id}', json={'status': 'passed'}).status_code == 409
    gate = viewer.get(f"/projects/{ids['project']}/signoff-status?stage=routing").json()
    for domain in ('sta', 'pv', 'lvs'):
        row = next(item for item in gate['domains'] if item['domain'] == domain)
        assert not row['ready'] and 'OpenLane flow metrics' in row['reason']


def test_two_imports_compare_corner_findings_and_metrics(accounts):  # noqa: F811
    _, ids, login = accounts
    editor = login('editor')
    path = f"/projects/{ids['project']}/imports/openlane-metrics"
    before = editor.post(path, json=payload('aes-timing-fail', design_revision='rev-a')).json()['runs'][0]
    after = editor.post(path, json=payload('aes-antenna', design_revision='rev-b')).json()['runs'][0]
    comparison = editor.get(f"/projects/{ids['project']}/run-comparison",
                            params={'baseline_run_id': before['id'], 'candidate_run_id': after['id'], 'limit': 100}).json()
    assert comparison['partial'] is True
    metrics = {row['name']: row for row in comparison['metrics']}
    assert metrics['setup_wns_ps']['delta'] > 0 and metrics['setup_violations']['candidate'] == 0
    assert comparison['summary']['removed'] >= 6


def test_source_download_returns_exact_metrics_and_lvs_reports(accounts):  # noqa: F811
    from test_commercial_lvs import payload as lvs_payload
    _, ids, login = accounts
    editor = login('editor')
    body = payload('sram-clean')
    run = editor.post(f"/projects/{ids['project']}/imports/openlane-metrics", json=body).json()['runs'][0]
    download = editor.get(f"/runs/{run['id']}/evidence/source")
    assert download.status_code == 200 and download.content == body['source_text'].encode()
    assert download.headers['x-source-sha256'] == hashlib.sha256(download.content).hexdigest()
    # The run evidence panel offers this download for commercial LVS reports too.
    lvs = editor.post(f"/projects/{ids['project']}/imports/commercial-lvs", json=lvs_payload()).json()
    assert editor.get(f"/runs/{lvs['id']}/evidence/source").status_code == 200
