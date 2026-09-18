import json
import os
import stat
import subprocess
import sys
from datetime import datetime, timezone

import pytest

from app.services.collector_request import build_import_request
from app.services.coverage_attestation import REQUIRED_CLAIMS
from test_report_import import commercial_report
from test_auth import accounts
from test_commercial_drc import report as drc_report
from test_commercial_emir import report as emir_report
from test_commercial_power import report as power_report
from test_commercial_rtl import report as rtl_report
from test_commercial_thermal import report as thermal_report
from test_commercial_lvs import matched as lvs_report


SECRET = 'collector-cli-secret-with-at-least-32-bytes'


def build(**changes):
    report = changes.pop('report', commercial_report(slack=0.1))
    values = {
        'domain': 'sta', 'source_text': json.dumps(report, indent=2) + '\n',
        'filename': 'primetime.json', 'project_id': 7, 'stage': 'routing',
        'design_revision': 'release-r1', 'scenario': 'all-signoff-views',
        'tool_version': report['tool_version'], 'key_id': 'collector-2026q3',
        'secret': SECRET, 'claims': {key: True for key in REQUIRED_CLAIMS['sta']},
        'import_id': '52d774d3-99ee-4e76-b900-b0a82e8e27f1',
        'now': datetime(2026, 9, 19, 1, 2, 3, tzinfo=timezone.utc),
    }
    values.update(changes)
    return build_import_request(**values)


def test_builder_validates_and_binds_server_ready_request():
    body = build()
    proof = body['coverage_attestation']
    assert body['import_id'] == proof['attestation_id']
    assert proof['project_id'] == 7 and proof['domain'] == 'sta'
    assert proof['issued_at'] == '2026-09-19T01:02:03Z'
    assert proof['expires_at'] == '2026-09-19T02:02:03Z'
    assert len(proof['source_sha256']) == 64 and len(proof['signature']) == 64
    assert SECRET not in json.dumps(body)


@pytest.mark.parametrize('domain,report', [
    ('sta', commercial_report()), ('pv', drc_report()), ('emir', emir_report()),
    ('glitch_power', power_report()), ('thermal', thermal_report()), ('rtl', rtl_report()),
    ('lvs', lvs_report()),
])
def test_builder_uses_the_server_parser_for_every_commercial_domain(domain, report):
    body = build(domain=domain, report=report, tool_version=report['tool_version'],
                 claims={key: True for key in REQUIRED_CLAIMS[domain]})
    proof = body['coverage_attestation']
    assert proof['domain'] == domain and proof['tool'] == report['tool']


@pytest.mark.parametrize('change,message', [
    ({'claims': {}}, 'exactly'),
    ({'claims': {key: key != 'findings_complete' for key in REQUIRED_CLAIMS['sta']}}, 'explicitly true'),
    ({'tool_version': 'wrong'}, 'does not match'),
    ({'secret': 'short'}, '32 to 512'),
    ({'valid_for_seconds': 0}, 'between 1 second'),
    ({'now': datetime(2026, 9, 19)}, 'timezone'),
])
def test_builder_rejects_untrusted_or_mismatched_inputs(change, message):
    with pytest.raises(ValueError, match=message):
        build(**change)


def test_cli_writes_private_request_that_server_accepts(tmp_path, accounts, monkeypatch):
    _, ids, login = accounts
    report = {**commercial_report(slack=0.1), 'paths': []}
    report_path = tmp_path / 'primetime.json'
    report_path.write_text(json.dumps(report) + '\n')
    claims_path = tmp_path / 'claims.json'
    claims_path.write_text(json.dumps({key: True for key in REQUIRED_CLAIMS['sta']}))
    output = tmp_path / 'request.json'
    environment = {**os.environ, 'SIGNOFF_COLLECTOR_HMAC_SECRET': SECRET, 'PYTHONPATH': '.'}
    command = [sys.executable, 'scripts/create_coverage_import.py', '--domain', 'sta',
        '--report', str(report_path), '--claims-file', str(claims_path),
        '--project-id', str(ids['project']), '--stage', 'routing', '--design-revision', 'cli-release-r1',
        '--scenario', 'all-signoff-views', '--tool-version', report['tool_version'],
        '--key-id', 'cli-collector', '--output', str(output)]
    completed = subprocess.run(command, cwd=os.getcwd(), env=environment, text=True,
                               capture_output=True, timeout=20)
    assert completed.returncode == 0, completed.stderr
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert SECRET not in output.read_text() and SECRET not in completed.stderr
    monkeypatch.setenv('SIGNOFF_COVERAGE_HMAC_KEYS', json.dumps({
        'cli-collector': {'secret': SECRET, 'domains': ['sta']},
    }))
    response = login('editor').post(
        f"/projects/{ids['project']}/imports/commercial-sta", json=json.loads(output.read_text()))
    assert response.status_code == 201, response.text
    assert response.json()['status'] == 'passed'
    duplicate = subprocess.run(command, cwd=os.getcwd(), env=environment, text=True,
                               capture_output=True, timeout=20)
    assert duplicate.returncode == 2 and 'File exists' in duplicate.stderr


def test_cli_never_echoes_missing_secret_value(tmp_path):
    report_path = tmp_path / 'report.json'; report_path.write_text('{}')
    claims_path = tmp_path / 'claims.json'; claims_path.write_text('{}')
    environment = {key: value for key, value in os.environ.items() if key != 'SIGNOFF_COLLECTOR_HMAC_SECRET'}
    environment['PYTHONPATH'] = '.'
    completed = subprocess.run([sys.executable, 'scripts/create_coverage_import.py', '--domain', 'sta',
        '--report', str(report_path), '--claims-file', str(claims_path), '--project-id', '1',
        '--stage', 'routing', '--design-revision', 'r1', '--scenario', 'all',
        '--tool-version', 'T', '--key-id', 'collector'], cwd=os.getcwd(), env=environment,
        text=True, capture_output=True, timeout=20)
    assert completed.returncode == 2
    assert completed.stdout == '' and 'SIGNOFF_COLLECTOR_HMAC_SECRET is not set' in completed.stderr
