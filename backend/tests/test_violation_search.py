import uuid

import pytest
from test_auth import accounts


@pytest.fixture
def review_project(client):
    def project():
        return client.post('/projects', json={
            'name': f'review-{uuid.uuid4()}', 'process_node': '130nm', 'foundry': 'SkyWater',
        }).json()['id']
    pid = project()
    def run(domain='sta', stage='placement', tool='Timer'):
        return client.post(f'/projects/{pid}/runs', json={
            'domain': domain, 'stage': stage, 'tool': tool,
        }).json()['id']
    def add(rid, name, severity='error', **kwargs):
        return client.post(f'/runs/{rid}/violations', json=[{
            'check_name': name, 'severity': severity, **kwargs,
        }]).json()[0]['id']
    old = run()
    old_issue = add(old, 'old setup')
    sta = run()
    info = add(sta, 'density', 'info', description='Review CORE density')
    critical = add(sta, 'setup', 'critical', location='u_core/reg_1')
    warning = add(sta, 'load_100%', 'warning')
    pv = run('pv', tool='Calibre')
    error = add(pv, 'spacing', location='M2')
    waived = add(pv, 'waived spacing')
    client.post(f'/violations/{waived}/waiver', json={'expected_version': 1, 'approved_by': 'Reviewer', 'reason': 'Exception'})
    other = project()
    other_run = client.post(f'/projects/{other}/runs', json={
        'domain': 'sta', 'stage': 'placement', 'tool': 'Timer',
    }).json()['id']
    add(other_run, 'outside project', 'critical')
    return pid, {'old': old_issue, 'info': info, 'critical': critical, 'warning': warning, 'error': error, 'waived': waived}, run, add


def test_default_scope_counts_order_and_run_context(client, review_project):
    pid, ids, _, _ = review_project
    response = client.get(f'/projects/{pid}/violations')
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['total'] == 5
    assert body['open_blocking'] == 2
    assert [v['id'] for v in body['items']] == [ids[k] for k in ['critical', 'waived', 'error', 'warning', 'info']]
    assert body['items'][0]['run']['domain'] == 'sta'
    assert body['items'][1]['waiver']['approved_by'] == 'Reviewer'
    assert body['offset'] == 0 and body['limit'] == 25


def test_history_scope_pagination_and_sort(client, review_project):
    pid, ids, _, _ = review_project
    url = f'/projects/{pid}/violations'
    pages = [client.get(url, params={'latest_only': False, 'sort': 'oldest', 'limit': 2, 'offset': n}).json() for n in [0, 2, 4]]
    assert all(page['total'] == 6 and page['open_blocking'] == 3 for page in pages)
    combined = [v['id'] for page in pages for v in page['items']]
    assert combined == sorted(ids.values())
    assert len(set(combined)) == 6
    assert client.get(url, params={'offset': 999}).json()['items'] == []
    newest = client.get(url, params={'sort': 'newest'}).json()['items']
    assert [v['id'] for v in newest] == sorted([ids[k] for k in ids if k != 'old'], reverse=True)


@pytest.mark.parametrize('query,key', [
    ({'q': 'CORE', 'severity': 'info'}, 'info'),
    ({'q': 'reg_1'}, 'critical'),
    ({'q': '100%'}, 'warning'),
    ({'q': 'Calibre', 'status': 'waived', 'stage': 'placement', 'domain': 'pv'}, 'waived'),
    ({'severity': 'error', 'status': 'open', 'domain': 'pv'}, 'error'),
])
def test_combined_filters_and_literal_search(client, review_project, query, key):
    pid, ids, _, _ = review_project
    body = client.get(f'/projects/{pid}/violations', params=query).json()
    assert [v['id'] for v in body['items']] == [ids[key]]
    assert body['total'] == 1
    assert body['open_blocking'] == int(key in ['critical', 'error'])


def test_latest_selected_before_issue_filter_even_if_running_and_empty(client, review_project):
    pid, ids, run, add = review_project
    # The new STA run has no issues; the previous matching issues must disappear.
    run()
    assert client.get(f'/projects/{pid}/violations', params={'domain': 'sta'}).json()['total'] == 0
    routing = run(stage='routing')
    rid = add(routing, 'routing setup', 'critical')
    body = client.get(f'/projects/{pid}/violations', params={'domain': 'sta'}).json()
    assert [v['id'] for v in body['items']] == [rid]
    assert client.get(f'/projects/{pid}/violations', params={'domain': 'sta', 'latest_only': False}).json()['total'] == 5


def test_updated_issue_reflected_in_filter_and_summary(client, review_project):
    pid, ids, _, _ = review_project
    client.patch(f"/violations/{ids['critical']}", json={
        'expected_version': 1, 'expected_status': 'open', 'status': 'fixed', 'actor': 'Reviewer', 'reason': 'Validated fix',
    })
    body = client.get(f'/projects/{pid}/violations', params={'status': 'open'}).json()
    assert body['open_blocking'] == 1
    assert body['total'] == 3
    assert ids['critical'] not in [v['id'] for v in body['items']]


@pytest.mark.parametrize('params', [{'limit': 0}, {'limit': 101}, {'offset': -1}, {'sort': 'invalid'}, {'status': 'invalid'}, {'q': 'x' * 201}])
def test_query_validation(client, review_project, params):
    pid, _, _, _ = review_project
    assert client.get(f'/projects/{pid}/violations', params=params).status_code == 422


def test_missing_project(client):
    assert client.get('/projects/999999/violations').status_code == 404


@pytest.mark.parametrize('query', [{}, {'latest_only': 'false', 'sort': 'oldest'},
    {'status': 'waived'}, {'q': '100%'}, {'domain': 'sta', 'severity': 'critical'}, {'q': 'no-match'}])
def test_export_matches_filters_and_preserves_review_context(client, review_project, query):
    pid, ids, _, _ = review_project
    route = f'/projects/{pid}/violations'
    expected = client.get(route, params=query).json()
    response = client.get(route + '/export', params={**query, 'offset': 99, 'limit': 1})
    assert response.status_code == 200, response.text
    bundle = response.json()
    assert bundle['items'] == expected['items']
    assert bundle['total'] == expected['total']
    assert bundle['open_blocking'] == expected['open_blocking']
    assert bundle['format'] == 'signoff/violation-export/v1'
    assert bundle['project_id'] == pid
    assert bundle['exported_at'].endswith('+00:00')
    assert 'offset' not in bundle['filters'] and 'limit' not in bundle['filters']
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['content-disposition'] == f'attachment; filename="project-{pid}-violations.json"'
    waived = next((item for item in bundle['items'] if item['id'] == ids['waived']), None)
    if waived:
        assert waived['waiver']['reason'] == 'Exception'
        assert waived['waiver']['approved_by'] == 'Reviewer'
        assert waived['version'] > 1
    assert client.get(route, params=query).json() == expected


def test_export_all_pages_and_refuses_truncation(client, review_project, monkeypatch):
    pid, _, run, _ = review_project
    rid = run()
    response = client.post(f'/runs/{rid}/violations', json=[{'check_name': f'issue-{i}', 'severity': 'error'} for i in range(101)])
    assert response.status_code == 201
    route = f'/projects/{pid}/violations'
    expected = client.get(route).json()['total']
    assert expected > 100
    bundle = client.get(route + '/export').json()
    assert len(bundle['items']) == bundle['total'] == expected
    monkeypatch.setattr('app.routers.violations.EXPORT_LIMIT', 100)
    rejected = client.get(route + '/export')
    assert rejected.status_code == 413
    assert 'content-disposition' not in rejected.headers


def test_export_latest_run_selection_precedes_issue_filter(client, review_project):
    pid, _, run, _ = review_project
    run()
    result = client.get(f'/projects/{pid}/violations/export?domain=sta&severity=critical').json()
    assert result['items'] == [] and result['total'] == result['open_blocking'] == 0


def test_export_permissions_and_validation(accounts):
    _, ids, login = accounts
    route = f"/projects/{ids['project']}/violations/export"
    assert login('viewer').get(route).status_code == 200
    assert login('outsider').get(route).status_code == 404
    assert login('viewer').get(route + '?status=invalid').status_code == 422
    assert login('viewer').get(route + '?q=' + 'x' * 201).status_code == 422


@pytest.mark.parametrize('description', ['x' * 2000, '한' * 1000, '\n' * 1200])
def test_export_caps_encoded_bytes_without_partial_download(client, review_project, monkeypatch, description):
    pid, _, run, add = review_project
    rid = run()
    add(rid, 'large-description', description=description)
    monkeypatch.setattr('app.routers.violations.EXPORT_MAX_BYTES', 2000)
    route = f'/projects/{pid}/violations'
    before = client.get(route).json()
    response = client.get(route + '/export')
    assert response.status_code == 413, response.text
    assert response.json()['detail'].startswith('Violation export exceeds')
    assert 'content-disposition' not in response.headers
    assert 'items' not in response.json()
    assert client.get(route).json() == before
    # A narrower export is still usable after closing the rejected query.
    assert client.get(route + '/export?q=no-match').status_code == 200


def test_export_exact_byte_boundary_includes_envelope(client, review_project, monkeypatch):
    from datetime import datetime, timezone
    from app.routers import violations
    class FixedTime:
        @staticmethod
        def now(*args):
            return datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(violations, 'datetime', FixedTime)
    pid, _, _, _ = review_project
    route = f'/projects/{pid}/violations/export'
    original = client.get(route)
    assert original.status_code == 200
    size = len(original.content)
    monkeypatch.setattr(violations, 'EXPORT_MAX_BYTES', size)
    assert client.get(route).content == original.content
    monkeypatch.setattr(violations, 'EXPORT_MAX_BYTES', size - 1)
    assert client.get(route).status_code == 413


def test_export_stops_serializing_after_limit_and_closes_cursor(monkeypatch):
    from types import SimpleNamespace
    from fastapi import HTTPException
    from app.routers import violations
    closed, consumed = [], []
    class Rows:
        def __iter__(self):
            for index in range(1000):
                consumed.append(index)
                yield SimpleNamespace(status='open', severity='error')
        def close(self):
            closed.append(True)
    statement = SimpleNamespace(execution_options=lambda **kwargs: statement)
    db = SimpleNamespace(scalars=lambda query: Rows())
    monkeypatch.setattr(violations, 'EXPORT_MAX_BYTES', 10)
    monkeypatch.setattr(violations.ProjectViolationOut, 'model_validate', lambda item:
                        SimpleNamespace(model_dump_json=lambda: '"1234567890"'))
    with pytest.raises(HTTPException) as error:
        violations.export_rows(db, statement)
    assert error.value.status_code == 413
    assert consumed == [0] and closed == [True]
