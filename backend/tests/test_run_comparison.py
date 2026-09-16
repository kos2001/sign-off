import uuid

import pytest


def project(client):
    return client.post('/projects', json={
        'name': f'comparison-{uuid.uuid4()}', 'process_node': '130nm', 'foundry': 'SkyWater',
    }).json()['id']


def run(client, pid, domain='sta', stage='placement', tool='Timer', metrics=None):
    return client.post(f'/projects/{pid}/runs', json={
        'domain': domain, 'stage': stage, 'tool': tool, 'metrics': metrics or {},
    }).json()['id']


def violations(client, rid, rows):
    response = client.post(f'/runs/{rid}/violations', json=rows)
    assert response.status_code == 201
    return response.json()


def issue(name, severity='error', location='u_core', description=None):
    return dict(check_name=name, severity=severity, location=location, description=description)


@pytest.fixture
def pair(client):
    pid = project(client)
    baseline = run(client, pid, metrics={'wns_ps': -20, 'area': 100, 'only_before': 0, 'null': None, 'flag': True, 'nested': {'value': True}})
    candidate = run(client, pid, metrics={'wns_ps': -5, 'area': 100, 'only_after': 0, 'flag': 1, 'nested': {'value': 1}})
    before = violations(client, baseline, [
        issue('same'), issue('changed', 'warning', description='before'),
        issue('absent'), issue('duplicates', 'error'), issue('duplicates', 'warning'),
    ])
    after = violations(client, candidate, [
        issue('same'), issue('changed', 'critical', description='after'),
        issue('new'), issue('duplicates', 'warning'), issue('duplicates', 'error'), issue('duplicates', 'info'),
    ])
    return pid, baseline, candidate, before, after


def compare(client, pair, **params):
    pid, baseline, candidate, *_ = pair
    return client.get(f'/projects/{pid}/run-comparison', params={
        'baseline_run_id': baseline, 'candidate_run_id': candidate, **params,
    })


def test_diff_preserves_duplicates_and_metric_semantics(client, pair):
    response = compare(client, pair)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['summary'] == {'new': 2, 'changed': 1, 'removed': 1, 'unchanged': 3}
    assert data['total'] == 7
    assert data['partial'] is True
    assert data['different_tools'] is False
    duplicate_rows = [row for row in data['items'] if (row['candidate'] or row['baseline'])['check_name'] == 'duplicates']
    assert [row['kind'] for row in duplicate_rows] == ['new', 'unchanged', 'unchanged']
    assert all(row['ambiguous_match'] for row in duplicate_rows)
    changed = next(row for row in data['items'] if row['kind'] == 'changed')
    assert changed['changed_fields'] == ['severity', 'description']
    metrics = {row['name']: row for row in data['metrics']}
    assert metrics['wns_ps']['delta'] == 15
    assert metrics['area']['changed'] is False
    assert metrics['only_before']['candidate_present'] is False
    assert metrics['only_after']['baseline_present'] is False
    assert metrics['null']['baseline_present'] is True
    assert metrics['null']['baseline'] is None
    assert metrics['null']['candidate_present'] is False
    assert metrics['flag']['changed'] is True and metrics['flag']['delta'] is None
    assert metrics['nested']['changed'] is True


def test_swap_and_filter_pagination(client, pair):
    _, baseline, candidate, *_ = pair
    original = compare(client, pair).json()
    reverse = compare(client, pair, baseline_run_id=candidate, candidate_run_id=baseline).json()
    assert reverse['summary']['new'] == original['summary']['removed']
    assert reverse['summary']['removed'] == original['summary']['new']
    assert next(m for m in reverse['metrics'] if m['name'] == 'wns_ps')['delta'] == -15
    pages = [compare(client, pair, limit=2, offset=offset).json() for offset in [0, 2, 4, 6]]
    assert [item for page in pages for item in page['items']] == original['items']
    for kind in ['new', 'changed', 'removed', 'unchanged']:
        filtered = compare(client, pair, kind=kind).json()
        assert filtered['total'] == original['summary'][kind]
        assert filtered['summary'] == original['summary']
        assert all(row['kind'] == kind for row in filtered['items'])
    assert compare(client, pair, offset=100).json()['items'] == []


def test_comparison_is_read_only_and_tracks_review_state(client, pair):
    _, baseline, candidate, before, after = pair
    client.post(f"/violations/{before[0]['id']}/waiver", json={'expected_version': 1, 'approved_by': 'Reviewer', 'reason': 'Exception'})
    before_snapshot = client.get(f'/runs/{baseline}/violations').json()
    candidate_snapshot = client.get(f'/runs/{candidate}/violations').json()
    result = compare(client, pair).json()
    row = next(row for row in result['items'] if row['baseline'] and row['baseline']['id'] == before[0]['id'])
    assert row['changed_fields'] == ['status', 'waiver']
    assert row['baseline']['waiver']['reason'] == 'Exception'
    assert row['candidate']['status'] == 'open'
    assert client.get(f'/runs/{baseline}/violations').json() == before_snapshot
    assert client.get(f'/runs/{candidate}/violations').json() == candidate_snapshot
    assert client.get(f"/violations/{after[0]['id']}/history").json() == []


def test_empty_partial_and_different_tools(client):
    pid = project(client)
    baseline = run(client, pid, tool='Timer A')
    candidate = run(client, pid, tool='Timer B')
    for rid in [baseline, candidate]:
        client.patch(f'/runs/{rid}', json={'status': 'passed'})
    body = compare(client, (pid, baseline, candidate)).json()
    assert body['total'] == 0 and body['metrics'] == []
    assert body['partial'] is False and body['different_tools'] is True
    assert body['summary'] == {'new': 0, 'changed': 0, 'removed': 0, 'unchanged': 0}


def test_identity_uses_location_and_retains_missing_locations(client):
    pid = project(client)
    baseline, candidate = run(client, pid), run(client, pid)
    violations(client, baseline, [issue('setup', location='a'), issue('unknown', location=None), issue('unknown', location=None)])
    violations(client, candidate, [issue('setup', location='b'), issue('unknown', location=None)])
    body = compare(client, (pid, baseline, candidate)).json()
    assert body['summary'] == {'new': 1, 'changed': 0, 'removed': 2, 'unchanged': 1}
    assert next(row for row in body['items'] if row['kind'] == 'unchanged')['ambiguous_match'] is True


def test_rejects_invalid_pairs_and_cross_project(client, pair):
    pid, baseline, candidate, *_ = pair
    assert compare(client, pair, candidate_run_id=baseline).status_code == 422
    for domain, stage in [('pv', 'placement'), ('sta', 'routing')]:
        incompatible = run(client, pid, domain=domain, stage=stage)
        assert compare(client, pair, candidate_run_id=incompatible).status_code == 422
    outside = run(client, project(client))
    assert compare(client, pair, candidate_run_id=outside).status_code == 404
    assert compare(client, pair, candidate_run_id=99999999).status_code == 404
    assert compare(client, (99999999, baseline, candidate)).status_code == 404


@pytest.mark.parametrize('params', [{'kind': 'bad'}, {'limit': 0}, {'limit': 101}, {'offset': -1}, {'offset': 2**63}, {'baseline_run_id': 0}])
def test_query_validation(client, pair, params):
    assert compare(client, pair, **params).status_code == 422


def test_imported_provenance_preserves_metadata_and_direction(client):
    from test_report_import import payload
    pid = project(client)
    left = payload()
    right = {**payload(), 'design_revision': 'rev-def', 'scenario': 'fast', 'tool_version': 'QA v2'}
    ids = [client.post(f'/projects/{pid}/imports/opensta', json=value).json()['id'] for value in [left, right]]
    result = compare(client, (pid, *ids)).json()
    before, after = result['baseline_provenance'], result['candidate_provenance']
    assert before['source'] == 'opensta_report'
    assert before['design_revision'] == 'rev-abc' and after['design_revision'] == 'rev-def'
    assert before['scenario'] == 'slow' and after['scenario'] == 'fast'
    assert before['tool_version'] == 'QA fixture' and after['tool_version'] == 'QA v2'
    assert before['coverage'] == after['coverage'] == 'reported_paths_only'
    assert before['source_sha256'] == after['source_sha256']  # Same bytes, different submitted context.
    assert set(before) == {'source', 'design_revision', 'scenario', 'tool_version', 'coverage', 'source_sha256'}
    assert 'source_text' not in result  # Full input remains available through the evidence endpoint.
    reverse = compare(client, (pid, ids[1], ids[0])).json()
    assert reverse['baseline_provenance'] == after and reverse['candidate_provenance'] == before
    filtered = compare(client, (pid, *ids), kind='removed', offset=100).json()
    assert filtered['baseline_provenance'] == before and filtered['candidate_provenance'] == after


def test_missing_provenance_is_not_fabricated(client, pair):
    result = compare(client, pair).json()
    for key in ['baseline_provenance', 'candidate_provenance']:
        assert result[key] == dict(source='manual', design_revision=None, source_sha256=None,
                                   scenario=None, tool_version=None, coverage=None)
