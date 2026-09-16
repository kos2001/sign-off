import copy
import csv
import io
import json

import pytest

from test_auth import accounts
from test_report_import import payload, project, report


def imported(client, pid=None):
    pid = pid or project(client)
    doc = report(-1e-11)
    original = doc['checks'][0]
    paths = []
    for i, slack in enumerate([20e-12, -10e-12, 0, -10e-12, None]):
        path = copy.deepcopy(original)
        path.update(endpoint=f'cap_{i}%/D', path_type='min' if i % 2 else 'max')
        path['source_path'][-1]['pin'] = path['endpoint']
        if slack is None:
            path['type'] = 'unconstrained'
            path.pop('slack')
        else:
            path['slack'] = slack
        paths.append(path)
    response = client.post(f'/projects/{pid}/imports/opensta', json=payload({'checks': paths}))
    assert response.status_code == 201, response.text
    return response.json()['id']


def test_timing_path_sort_filter_and_pagination(client):
    run = imported(client)
    route = f'/runs/{run}/timing-paths'
    first = client.get(route + '?limit=2').json()
    assert first['total'] == first['reported_total'] == 5
    assert [p['index'] for p in first['items']] == [2, 4]
    assert [p['index'] for p in client.get(route + '?offset=2&limit=2').json()['items']] == [3, 1]
    assert [p['index'] for p in client.get(route + '?sort=slack_desc').json()['items']] == [1, 3, 2, 4, 5]
    assert [p['index'] for p in client.get(route + '?sort=report').json()['items']] == [1, 2, 3, 4, 5]
    assert client.get(route + '?status=violated&path_type=min').json()['total'] == 2
    assert client.get(route + '?status=met').json()['total'] == 2
    assert client.get(route + '?status=unconstrained').json()['items'][0]['index'] == 5
    assert client.get(route, params={'q': 'CAP_0%'}).json()['total'] == 1
    assert client.get(route, params={'q': '%_'}).json()['total'] == 0
    assert client.get(route + '?offset=999').json()['items'] == []


def test_path_detail_units_pins_missing_values_and_read_only(client):
    pid = project(client)
    doc = report()
    path = doc['checks'][0]
    path.update(source_clock='clk', target_clock='clk', data_arrival_time=2e-9, required_time=1.975e-9)
    nodes = [{'pin': 'launch/Q', 'arrival': 0, 'slew': 3e-12, 'cell': 'DFF'}]
    nodes += [{'pin': f'buffer_{i}/Y'} for i in range(101)]
    nodes += [{'pin': 'capture/D', 'arrival': 2e-9, 'slew': 10**200}]
    path['source_path'] = nodes
    run = client.post(f'/projects/{pid}/imports/opensta', json=payload(doc)).json()['id']
    before = client.get(f'/runs/{run}/evidence').json()
    first = client.get(f'/runs/{run}/timing-paths/1').json()
    assert first['arrival_ps'] == pytest.approx(2000) and first['required_ps'] == pytest.approx(1975)
    assert first['point_total'] == 103
    assert len(first['points']) == 100
    assert first['points'][0]['arrival_ps'] == 0
    assert first['points'][0]['slew_ps'] == 3
    assert first['points'][1]['arrival_ps'] is None
    end = client.get(f'/runs/{run}/timing-paths/1?point_offset=100').json()
    assert [p['index'] for p in end['points']] == [101, 102, 103]
    assert end['points'][-1]['pin'] == 'capture/D'
    assert end['points'][-1]['slew_ps'] is None
    assert client.get(f'/runs/{run}/timing-paths/2').status_code == 404
    assert client.get(f'/runs/{run}/evidence').json() == before


@pytest.mark.parametrize('query', ['limit=0', 'limit=101', 'offset=-1', 'status=bad', 'sort=bad', 'path_type=both',
                                 'slack_min_ps=NaN', 'slack_max_ps=Infinity', 'slack_min_ps=-Infinity',
                                 'slack_max_ps=1e999', 'slack_min_ps=oops', 'slack_min_ps=1&slack_max_ps=0'])
def test_timing_path_invalid_filters(client, query):
    run = imported(client)
    assert client.get(f'/runs/{run}/timing-paths?{query}').status_code == 422


def test_timing_path_access_roles_and_manual_run(accounts):
    _, ids, login = accounts
    editor, viewer, outsider = login('editor'), login('viewer'), login('outsider')
    run = imported(editor, ids['project'])
    for path in [f'/runs/{run}/timing-paths', f'/runs/{run}/timing-paths/1']:
        assert viewer.get(path).status_code == 200
        assert outsider.get(path).status_code == 404
    assert viewer.get(f"/runs/{ids['run']}/timing-paths").status_code == 409


def test_slack_range_inclusive_bounds_missing_slack_and_combined_filters(client):
    run = imported(client)
    route = f'/runs/{run}/timing-paths'
    evidence = client.get(f'/runs/{run}/evidence').json()
    for query, expected in [
        ('slack_min_ps=-10&slack_max_ps=0', [2, 4, 3]),
        ('slack_min_ps=0&slack_max_ps=0', [3]),
        ('slack_min_ps=0', [3, 1]),
        ('slack_max_ps=-10', [2, 4]),
        ('slack_max_ps=0&path_type=max', [3]),
        ('slack_max_ps=0&status=unconstrained', []),
        ('slack_min_ps=-9&slack_max_ps=-1', []),
        ('slack_max_ps=0&q=cap_3', [4]),
        ('slack_min_ps=-10&slack_max_ps=0&sort=slack_desc&offset=1&limit=1', [2]),
    ]:
        response = client.get(f'{route}?{query}')
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['reported_total'] == 5
        assert [item['index'] for item in result['items']] == expected
    assert client.get(f'/runs/{run}/evidence').json() == evidence


def test_slack_range_preserves_tiny_negative_boundaries(client):
    pid = project(client)
    run = client.post(f'/projects/{pid}/imports/opensta', json=payload(report(-1e-17))).json()['id']
    route = f'/runs/{run}/timing-paths'
    assert client.get(route + '?slack_min_ps=-1e-5&slack_max_ps=-1e-5').json()['total'] == 1
    assert client.get(route + '?slack_min_ps=0').json()['total'] == 0


def test_export_matches_filtered_paths_and_preserves_provenance(client):
    run = imported(client)
    route = f'/runs/{run}/timing-paths'
    evidence = client.get(f'/runs/{run}/evidence').json()
    filters = {'slack_min_ps': '-10', 'slack_max_ps': '0', 'sort': 'slack_desc', 'q': 'CAP_'}
    expected = client.get(route, params=filters).json()
    response = client.get(route + '/export', params=filters)
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['content-disposition'] == f'attachment; filename="run-{run}-timing-paths.json"'
    bundle = response.json()
    assert bundle['format'] == 'signoff/timing-path-export/v1'
    assert bundle['exported_at'].endswith('+00:00')
    assert bundle['items'] == expected['items']
    assert bundle['summary'] == expected['summary']
    assert bundle['total'] == 3 and bundle['reported_total'] == 5
    assert bundle['report']['source_sha256'] == evidence['source_sha256']
    assert bundle['report']['design_revision'] == evidence['design_revision']
    assert bundle['report']['coverage'] == 'reported_paths_only'
    assert bundle['report']['parser'] == evidence['result']['parser']
    assert bundle['report']['metadata'] == evidence['result']['metadata']
    assert bundle['filters'] == {'q': 'CAP_', 'path_type': None, 'status': 'all', 'slack_min_ps': -10, 'slack_max_ps': 0, 'sort': 'slack_desc'}
    assert bundle['units'] == {'slack_ps': 'ps'}
    assert bundle['run']['id'] == run
    assert 'source_text' not in bundle['report']
    assert client.get(f'/runs/{run}/evidence').json() == evidence


def test_export_includes_all_pages_and_explicit_empty_or_unconstrained_results(client):
    pid = project(client)
    doc = report()
    doc['checks'] *= 101
    run = client.post(f'/projects/{pid}/imports/opensta', json=payload(doc)).json()['id']
    route = f'/runs/{run}/timing-paths'
    assert len(client.get(route).json()['items']) == 25
    bundle = client.get(route + '/export').json()
    assert len(bundle['items']) == bundle['total'] == 101
    assert bundle['summary']['violated_paths'] == 101
    assert [path['index'] for path in bundle['items']] == list(range(1, 102))
    empty = client.get(route + '/export?slack_min_ps=0').json()
    assert empty['items'] == [] and empty['total'] == 0 and empty['reported_total'] == 101
    mixed = imported(client)
    missing = client.get(f'/runs/{mixed}/timing-paths/export?status=unconstrained').json()
    assert missing['items'][0]['slack_ps'] is None
    assert missing['items'][0]['status'] == 'unconstrained'


def test_export_uses_viewer_scope_and_validates_filters(accounts):
    _, ids, login = accounts
    run = imported(login('editor'), ids['project'])
    viewer = login('viewer')
    route = f'/runs/{run}/timing-paths/export'
    assert viewer.get(route).status_code == 200
    assert login('outsider').get(route).status_code == 404
    assert viewer.get(f"/runs/{ids['run']}/timing-paths/export").status_code == 409
    for query in ['slack_min_ps=NaN', 'slack_min_ps=10&slack_max_ps=0', 'status=bad']:
        assert viewer.get(route + '?' + query).status_code == 422


@pytest.mark.parametrize('query,counts,worst', [
    ('', (2, 2, 1), -10),
    ('status=met', (0, 2, 0), 0),
    ('status=unconstrained', (0, 0, 1), None),
    ('slack_min_ps=-10&slack_max_ps=0', (2, 1, 0), -10),
    ('q=nonexistent', (0, 0, 0), None),
])
def test_filtered_summary_covers_all_pages_and_preserves_missing_values(client, query, counts, worst):
    run = imported(client)
    route = f'/runs/{run}/timing-paths'
    expected = dict(zip(['violated_paths', 'met_paths', 'unconstrained_paths'], counts))
    expected['worst_slack_ps'] = worst
    for page in ['limit=1', 'offset=3&limit=1', 'offset=999&sort=slack_desc']:
        response = client.get(f'{route}?{query}&{page}')
        assert response.status_code == 200
        result = response.json()
        assert result['summary'] == expected
        assert sum(counts) == result['total']
        assert result['reported_total'] == 5
    assert client.get(f'{route}/export?{query}').json()['summary'] == expected


def test_summary_does_not_round_small_negative_slack(client):
    pid = project(client)
    run = client.post(f'/projects/{pid}/imports/opensta', json=payload(report(-1e-17))).json()['id']
    summary = client.get(f'/runs/{run}/timing-paths').json()['summary']
    assert summary['worst_slack_ps'] == -0.00001
    assert summary['violated_paths'] == 1


def csv_rows(response):
    assert response.status_code == 200, response.text
    assert response.content.startswith(b'\xef\xbb\xbf')
    return list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))


def test_csv_export_matches_json_filters_order_and_provenance(client):
    run = imported(client)
    route = f'/runs/{run}/timing-paths/export'
    filters = {'slack_max_ps': '0', 'sort': 'slack_desc'}
    bundle = client.get(route, params=filters).json()
    response = client.get(route, params={**filters, 'format': 'csv'})
    rows = csv_rows(response)
    assert response.headers['content-type'].startswith('text/csv')
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['content-disposition'] == f'attachment; filename="run-{run}-timing-paths.csv"'
    assert [int(row['path_index']) for row in rows] == [path['index'] for path in bundle['items']]
    for row, path in zip(rows, bundle['items']):
        assert float(row['slack_ps']) == path['slack_ps']
        assert row['source_sha256'] == bundle['report']['source_sha256']
        assert row['design_revision'] == bundle['report']['design_revision']
        assert row['coverage'] == 'reported_paths_only'
        assert json.loads(row['filters_json']) == bundle['filters']
        assert int(row['filtered_total']) == bundle['total']
        assert int(row['reported_total']) == bundle['reported_total']


def test_csv_all_pages_empty_missing_and_tiny_slack(client):
    pid = project(client)
    doc = report(-1e-17)
    doc['checks'] *= 101
    run = client.post(f'/projects/{pid}/imports/opensta', json=payload(doc)).json()['id']
    route = f'/runs/{run}/timing-paths/export?format=csv'
    rows = csv_rows(client.get(route + '&offset=100&limit=1'))
    assert len(rows) == 101
    assert float(rows[0]['slack_ps']) == -0.00001
    assert csv_rows(client.get(route + '&slack_min_ps=0')) == []
    mixed = imported(client)
    rows = csv_rows(client.get(f'/runs/{mixed}/timing-paths/export?format=csv&status=unconstrained'))
    assert rows[0]['slack_ps'] == '' and rows[0]['status'] == 'unconstrained'


@pytest.mark.parametrize('name', ['=1+1', '+SUM(1,2)', '-1+2', '@SUM(1)', '  =1'])
def test_csv_formula_like_text_is_escaped_without_changing_evidence(client, name):
    pid = project(client)
    doc = report()
    doc['checks'][0]['endpoint'] = name
    doc['checks'][0]['source_path'][-1]['pin'] = name
    run = client.post(f'/projects/{pid}/imports/opensta', json=payload(doc)).json()['id']
    route = f'/runs/{run}/timing-paths/export'
    original = client.get(route).json()['items'][0]['endpoint']
    rows = csv_rows(client.get(route + '?format=csv'))
    assert rows[0]['endpoint'] == "'" + original
    assert client.get(route).json()['items'][0]['endpoint'] == original


def test_csv_quotes_unicode_and_commas(client):
    pid = project(client)
    doc = report()
    endpoint = 'capture,"한글"/D'
    doc['checks'][0]['endpoint'] = endpoint
    doc['checks'][0]['source_path'][-1]['pin'] = endpoint
    run = client.post(f'/projects/{pid}/imports/opensta', json=payload(doc)).json()['id']
    assert csv_rows(client.get(f'/runs/{run}/timing-paths/export?format=csv'))[0]['endpoint'] == endpoint


def test_csv_export_enforces_viewer_scope_and_format(accounts):
    _, ids, login = accounts
    run = imported(login('editor'), ids['project'])
    viewer = login('viewer')
    route = f'/runs/{run}/timing-paths/export'
    assert viewer.get(route + '?format=csv').status_code == 200
    assert login('outsider').get(route + '?format=csv').status_code == 404
    assert viewer.get(route + '?format=xlsx').status_code == 422
    assert viewer.get(route + '?format=csv&slack_min_ps=NaN').status_code == 422
    assert viewer.get(f"/runs/{ids['run']}/timing-paths/export?format=csv").status_code == 409


def test_arrival_differences_preserve_page_boundary_missing_and_signed_values(client):
    doc = report()
    nodes = [{'pin': 'launch/Q', 'arrival': 0}]
    nodes += [{'pin': f'b{i}/Y', 'arrival': i * 1e-12} for i in range(1, 103)]
    nodes[-1]['pin'] = 'capture/D'
    nodes[100]['arrival'] = 150e-12
    nodes[101]['arrival'] = 149e-12
    doc['checks'][0]['source_path'] = nodes
    rid = client.post(f'/projects/{project(client)}/imports/opensta', json=payload(doc)).json()['id']
    url = f'/runs/{rid}/timing-paths/1'
    before = client.get(f'/runs/{rid}/evidence').json()
    first = client.get(url).json()
    second = client.get(url, params={'point_offset': 100}).json()
    assert first['points'][0]['arrival_delta_ps'] is None
    assert second['points'][0]['arrival_delta_ps'] == pytest.approx(51)
    assert second['points'][1]['arrival_delta_ps'] == pytest.approx(-1)
    assert second['arrival_delta_summary'] == first['arrival_delta_summary']
    summary = first['arrival_delta_summary']
    assert summary['reported_pairs'] == summary['total_pairs'] == 102
    assert summary['largest_increases'][0]['to_index'] == 101
    assert summary['largest_increases'][0]['from_index'] == 100
    assert len(summary['largest_increases']) == 5
    assert client.get(f'/runs/{rid}/evidence').json() == before


def test_arrival_differences_do_not_bridge_missing_or_invalid_nodes():
    from app.routers.timing_paths import arrival_deltas
    for missing in [None, True, '0.1', float('inf'), float('nan'), 10**200]:
        deltas, summary = arrival_deltas([{'arrival': 1e-12}, {'arrival': missing}, {'arrival': 3e-12}])
        assert deltas == [None, None, None]
        assert summary == {'total_pairs': 2, 'reported_pairs': 0, 'largest_increases': []}


def test_arrival_differences_rank_ties_by_report_order_and_keep_zero_negative():
    from app.routers.timing_paths import arrival_deltas
    deltas, summary = arrival_deltas([{'arrival': value} for value in [0, 2e-12, 4e-12, 4e-12, 3e-12]])
    assert deltas == [None, 2, 2, 0, -1]
    assert [item['to_index'] for item in summary['largest_increases']] == [2, 3]
    assert summary['reported_pairs'] == 4
    assert arrival_deltas([{'arrival': 0}, {'arrival': -1e-25}])[0][1] < 0
    assert arrival_deltas([]) == ([], {'total_pairs': 0, 'reported_pairs': 0, 'largest_increases': []})
