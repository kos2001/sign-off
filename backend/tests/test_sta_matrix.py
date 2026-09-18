import uuid

from app.db import SessionLocal
from app.models import Domain, RunEvidence, RunStatus, SignoffRun, Stage


def project(client):
    return client.post('/projects', json={
        'name': f'matrix-{uuid.uuid4()}', 'process_node': '5nm', 'foundry': 'QA',
    }).json()['id']


def record(pid, scenario, *, revision='rev-a', stage=Stage.routing, status=RunStatus.failed,
           slack=-10.0, violations=1, parasitics='spef', source='opensta_execution'):
    with SessionLocal() as db:
        run = SignoffRun(project_id=pid, domain=Domain.sta, stage=stage, tool='OpenSTA',
                         status=status, metrics={'reported_paths': 8, 'violating_paths': violations,
                         'unconstrained_paths': 0, 'worst_reported_slack_ps': slack})
        db.add(run)
        db.flush()
        run.evidence = RunEvidence(source=source, source_sha256=f'{run.id:064x}',
            design_revision=revision, result={'metadata': {'scenario': scenario,
            'tool_version': 'OpenSTA d97587f', 'parasitics': parasitics}})
        db.commit()
        return run.id


def test_matrix_uses_latest_execution_per_recorded_scenario(client):
    pid = project(client)
    old = record(pid, 'slow', slack=-80, violations=7)
    latest = record(pid, 'slow', slack=-20, violations=2, parasitics='none')
    fast = record(pid, 'fast', status=RunStatus.incomplete, slack=5, violations=0)
    record(pid, 'excluded-import', source='opensta_report')
    record(pid, 'other-revision', revision='rev-b')
    record(pid, 'other-stage', stage=Stage.synthesis)

    response = client.get(f'/projects/{pid}/sta-matrix', params={
        'stage': 'routing', 'design_revision': 'rev-a',
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['coverage'] == 'reported_paths_only'
    assert body['summary'] == {'scenario_count': 2, 'expected_scenario_count': 0,
        'recorded_expected_scenarios': 0, 'missing_scenarios': 0,
        'unexpected_scenarios': 2, 'parasitic_requirement_gaps': 0,
        'scenario_coverage_complete': False, 'failed_scenarios': 1,
        'incomplete_scenarios': 1, 'spef_scenarios': 1,
        'total_violating_paths': 2, 'worst_reported_slack_ps': -20.0}
    assert [(row['scenario'], row['run_id'], row['run_count']) for row in body['scenarios']] == [
        ('fast', fast, 1), ('slow', latest, 2),
    ]
    assert body['scenarios'][1]['parasitics'] == 'none'
    assert body['scenarios'][1]['coverage_state'] == 'unplanned'
    assert body['scenarios'][1]['source_sha256'] == f'{latest:064x}'
    assert old != latest


def test_matrix_validates_scope_and_execution_provenance(client):
    pid = project(client)
    assert client.get(f'/projects/{pid}/sta-matrix?stage=routing&design_revision=%20').status_code == 422
    assert client.get('/projects/999999999/sta-matrix?stage=routing&design_revision=rev').status_code == 404
    broken = record(pid, 'slow', parasitics='none')
    with SessionLocal() as db:
        evidence = db.query(RunEvidence).filter_by(run_id=broken).one()
        evidence.result = {'metadata': {'scenario': 'slow', 'tool_version': '', 'parasitics': 'none'}}
        db.commit()
    response = client.get(f'/projects/{pid}/sta-matrix?stage=routing&design_revision=rev-a')
    assert response.status_code == 409
    assert response.json()['detail'] == f'run {broken} has incomplete OpenSTA provenance'


def test_expected_scenario_set_reports_missing_and_parasitic_gaps(client):
    pid = project(client)
    path = f'/projects/{pid}/sta-scenarios/routing'
    configured = client.put(path, json={'scenarios': [
        {'name': 'slow-rc', 'require_spef': True},
        {'name': 'fast', 'require_spef': False},
        {'name': 'hold', 'require_spef': False},
    ]})
    assert configured.status_code == 200, configured.text
    assert [row['name'] for row in client.get(path).json()] == ['fast', 'hold', 'slow-rc']
    slow = record(pid, 'slow-rc', parasitics='none')
    fast = record(pid, 'fast', status=RunStatus.passed, slack=20, violations=0, parasitics='none')
    record(pid, 'exploratory', parasitics='spef')

    matrix = client.get(f'/projects/{pid}/sta-matrix?stage=routing&design_revision=rev-a').json()
    assert matrix['summary']['expected_scenario_count'] == 3
    assert matrix['summary']['recorded_expected_scenarios'] == 2
    assert matrix['summary']['missing_scenarios'] == 1
    assert matrix['summary']['unexpected_scenarios'] == 1
    assert matrix['summary']['parasitic_requirement_gaps'] == 1
    assert matrix['summary']['scenario_coverage_complete'] is False
    rows = {row['scenario']: row for row in matrix['scenarios']}
    assert rows['slow-rc']['run_id'] == slow and rows['slow-rc']['coverage_state'] == 'parasitics_missing'
    assert rows['fast']['run_id'] == fast and rows['fast']['coverage_state'] == 'recorded'
    assert rows['hold']['run_id'] is None and rows['hold']['coverage_state'] == 'missing'
    assert rows['exploratory']['coverage_state'] == 'unplanned'

    replaced = client.put(path, json={'scenarios': [
        {'name': 'slow-rc', 'require_spef': False}, {'name': 'fast'},
    ]})
    assert replaced.status_code == 200
    matrix = client.get(f'/projects/{pid}/sta-matrix?stage=routing&design_revision=rev-a').json()
    assert matrix['summary']['scenario_coverage_complete'] is True
    assert matrix['summary']['parasitic_requirement_gaps'] == 0


def test_scenario_configuration_rejects_case_insensitive_duplicates(client):
    pid = project(client)
    response = client.put(f'/projects/{pid}/sta-scenarios/routing', json={'scenarios': [
        {'name': 'Slow'}, {'name': ' slow '},
    ]})
    assert response.status_code == 422
