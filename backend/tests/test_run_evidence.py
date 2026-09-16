import hashlib
import json
import uuid

import pytest

from app.models import RunStatus
from app.services.evidence import rtl_result_status
from app.services.rtl import tools
from app.services.rtl.signoff import LadderStage, _verdict
from test_rtl_signoff import GOOD_RTL, CDC_BAD_RTL


def project(client):
    return client.post('/projects', json={'name': f'evidence-{uuid.uuid4()}', 'process_node': '130nm', 'foundry': 'SkyWater'}).json()['id']


def rtl_gate(client, pid):
    return next(d for d in client.get(f'/projects/{pid}/signoff-status?stage=rtl').json()['domains'] if d['domain'] == 'rtl')


@pytest.mark.parametrize('stream', [False, True])
def test_conditional_capture_roundtrip_and_gate(client, stream):
    pid = project(client)
    code = f'```systemverilog\n{GOOD_RTL}\n```'
    response = client.post('/analysis/rtl-signoff' + ('/stream' if stream else ''), json={
        'code': code, 'project_id': pid, 'design_revision': 'review-commit-42',
    })
    assert response.status_code == 200
    result = json.loads(response.text.splitlines()[-1])['result'] if stream else response.json()
    assert result['verdict'] == 'CONDITIONAL'
    rid = result['run_id']
    run = client.get(f'/projects/{pid}/runs').json()[0]
    assert run['status'] == 'incomplete'
    assert run['result_locked'] and run['evidence_source'] == 'rtl_ladder'
    evidence = client.get(f'/runs/{rid}/evidence').json()
    expected = tools.strip_fences(code) + "\n"
    assert evidence['source_text'] == expected
    assert evidence['source_sha256'] == hashlib.sha256(expected.encode()).hexdigest()
    assert evidence['design_revision'] == 'review-commit-42'
    assert evidence['result']['stages'] == result['stages']
    assert evidence['result']['rules'] == result['rules']
    assert evidence['created_at']
    gate = rtl_gate(client, pid)
    assert not gate['ready'] and 'incomplete' in gate['reason']
    for payload in [{'status': 'passed'}, {'status': 'passed', 'metrics': {'verdict': 'SIGNED_OFF'}}]:
        assert client.patch(f'/runs/{rid}', json=payload).status_code == 409
    assert client.post(f'/runs/{rid}/violations', json=[{'check_name': 'injected', 'severity': 'info'}]).status_code == 409
    assert client.get(f'/runs/{rid}/evidence').json() == evidence


def test_waiving_findings_cannot_override_failed_captured_stages(client):
    pid = project(client)
    result = client.post('/analysis/rtl-signoff', json={'code': CDC_BAD_RTL, 'project_id': pid}).json()
    rid = result['run_id']
    original = client.get(f'/runs/{rid}/evidence').json()
    for violation in client.get(f'/runs/{rid}/violations').json():
        assert client.post(f"/violations/{violation['id']}/waiver", json={'expected_version': 1, 'reason': 'Review exception', 'approved_by': 'Reviewer'}).status_code == 201
    gate = rtl_gate(client, pid)
    assert gate['open_blocking_violations'] == 0
    assert gate['ready'] is False
    assert client.get(f'/runs/{rid}/evidence').json() == original


def test_manual_origin_cannot_spoof_captured_evidence(client):
    pid = project(client)
    result = client.post(f'/projects/{pid}/runs', json={
        'domain': 'rtl', 'stage': 'rtl', 'tool': 'rtl-signoff-ladder',
        'evidence_source': 'rtl_ladder', 'metrics': {'verdict': 'SIGNED_OFF'},
    }).json()
    rid = result['id']
    assert result['evidence_source'] == 'manual'
    assert not result['result_locked']
    assert client.patch(f'/runs/{rid}', json={'status': 'passed'}).status_code == 200
    assert rtl_gate(client, pid)['ready'] is False
    assert client.get(f'/runs/{rid}/evidence').json()['source_text'] is None


def test_missing_project_does_not_execute_tools(client, monkeypatch):
    def unexpected(*args):
        raise AssertionError('tools must not run before project validation')
    monkeypatch.setattr('app.routers.analysis.run_signoff', unexpected)
    monkeypatch.setattr('app.routers.analysis.stream_signoff', unexpected)
    for suffix in ['', '/stream']:
        assert client.post(f'/analysis/rtl-signoff{suffix}', json={'code': GOOD_RTL, 'project_id': 9999999}).status_code == 404


def test_completion_policy_requires_every_required_stage():
    stages = [dict(name=name, status='pass', gating=True) for name in ['lint', 'design', 'synthesize', 'simulate']]
    assert rtl_result_status({'verdict': 'SIGNED_OFF', 'stages': stages}) == RunStatus.passed
    for missing in range(4):
        assert rtl_result_status({'verdict': 'SIGNED_OFF', 'stages': stages[:missing] + stages[missing + 1:]}) == RunStatus.incomplete
    for status, expected in [('skip', RunStatus.incomplete), ('fail', RunStatus.failed), ('unknown', RunStatus.incomplete)]:
        altered = [*stages[:-1], {**stages[-1], 'status': status}]
        assert rtl_result_status({'verdict': 'SIGNED_OFF', 'stages': altered}) == expected
    assert rtl_result_status({'verdict': 'SIGNED_OFF', 'stages': [*stages, stages[0]]}) == RunStatus.incomplete
    assert rtl_result_status({'verdict': 'SIGNED_OFF', 'stages': None}) == RunStatus.incomplete
    assert _verdict([]) == 'CONDITIONAL'
    assert _verdict([LadderStage(**stage) for stage in stages]) == 'SIGNED_OFF'


@pytest.mark.parametrize('tool_name, function', [('verilator_available', tools.lint), ('yosys_available', tools.synthesize)])
@pytest.mark.parametrize('failure', ['tool timed out after 60s', 'tool could not execute'])
def test_tool_failure_becomes_recordable_failure(monkeypatch, tool_name, function, failure):
    monkeypatch.setattr(tools, tool_name, lambda: True)
    def fail(*args, **kwargs):
        return {'exit_code': None, 'log': '', 'error': failure}
    monkeypatch.setattr(tools, 'run_command', fail)
    result = function(GOOD_RTL)
    assert result.available and not result.ok
    assert result.issues


def test_existing_sqlite_schema_adds_evidence_without_changing_legacy_data(tmp_path):
    import sqlite3
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db import Base
    from app.models import SignoffRun
    from app.services.stages import evaluate_gate
    from app.models import Stage
    path = tmp_path / 'legacy.db'
    with sqlite3.connect(path) as db:
        db.executescript('''
            CREATE TABLE projects (id INTEGER PRIMARY KEY, name VARCHAR(120), process_node VARCHAR(40), foundry VARCHAR(60), created_at DATETIME);
            CREATE TABLE signoff_runs (id INTEGER PRIMARY KEY, project_id INTEGER, domain VARCHAR(12), stage VARCHAR(9), tool VARCHAR(80), status VARCHAR(7), metrics JSON, created_at DATETIME);
            INSERT INTO projects VALUES (1, 'Legacy', '130nm', 'SkyWater', '2026-01-01');
            INSERT INTO signoff_runs VALUES (1, 1, 'rtl', 'rtl', 'rtl-signoff-ladder', 'passed', '{"verdict":"CONDITIONAL"}', '2026-01-01');
        ''')
    engine = create_engine(f'sqlite:///{path}')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        legacy = db.get(SignoffRun, 1)
        assert legacy.status == RunStatus.passed
        assert legacy.evidence is None and legacy.result_locked
        assert not evaluate_gate([legacy], Stage.rtl)['domains'][0]['ready']
        legacy.status = RunStatus.incomplete
        db.commit()
        db.expire_all()
        assert db.get(SignoffRun, 1).status == RunStatus.incomplete
    engine.dispose()
