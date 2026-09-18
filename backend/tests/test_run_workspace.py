import uuid

from test_auth import accounts


def make_run(client):
    project = client.post('/projects', json={'name': f'workspace-{uuid.uuid4().hex}', 'foundry': 'QA', 'process_node': '5nm'}).json()
    run = client.post(f"/projects/{project['id']}/runs", json={
        'domain': 'sta', 'stage': 'placement', 'tool': 'OpenSTA',
        'metrics': {'wns_ps': -12.5, 'corner': 'ss'},
    }).json()
    findings = [
        {'check_name': 'literal%_' if index == 0 else f'setup_{index}',
         'severity': ['info', 'warning', 'error', 'critical'][index % 4],
         'location': f'u_core/reg_{index}', 'description': f'path {index}'}
        for index in range(30)
    ]
    violations = client.post(f"/runs/{run['id']}/violations", json=findings).json()
    return project, run, violations


def test_run_identity_and_paginated_findings(client):
    project, run, violations = make_run(client)
    detail = client.get(f"/runs/{run['id']}")
    assert detail.status_code == 200
    assert detail.json()['project_id'] == project['id']
    assert detail.json()['metrics'] == {'wns_ps': -12.5, 'corner': 'ss'}

    fixed = client.patch(f"/violations/{violations[1]['id']}", json={
        'expected_status': 'open', 'expected_version': 1, 'status': 'fixed',
        'actor': 'workspace QA', 'reason': 'verified correction',
    })
    assert fixed.status_code == 200
    page = client.get(f"/runs/{run['id']}/violations/page?offset=10&limit=10").json()
    assert page['run_total'] == page['total'] == 30
    assert page['offset'] == 10 and page['limit'] == 10 and len(page['items']) == 10
    assert page['status_counts'] == {'open': 29, 'fixed': 1, 'waived': 0}
    assert page['severity_counts'] == {'info': 8, 'warning': 8, 'error': 7, 'critical': 7}
    assert [item['id'] for item in page['items']] == [item['id'] for item in violations[10:20]]

    assert client.get(f"/runs/{run['id']}/violations/page?status=fixed").json()['items'][0]['id'] == violations[1]['id']
    literal = client.get(f"/runs/{run['id']}/violations/page", params={'q': '%_'}).json()
    assert literal['total'] == 1 and literal['items'][0]['check_name'] == 'literal%_'
    assert client.get(f"/runs/{run['id']}/violations/page?q=SETUP_29").json()['total'] == 1
    combined = client.get(f"/runs/{run['id']}/violations/page?severity=critical&q=reg_7").json()
    assert combined['total'] == 1 and combined['items'][0]['location'] == 'u_core/reg_7'


def test_run_workspace_validation_and_missing(client):
    _, run, _ = make_run(client)
    route = f"/runs/{run['id']}/violations/page"
    for query in ['offset=-1', 'offset=10001', 'limit=0', 'limit=101', 'status=bad', 'severity=bad']:
        assert client.get(f'{route}?{query}').status_code == 422
    assert client.get('/runs/999999').status_code == 404
    assert client.get('/runs/999999/violations/page').status_code == 404


def test_run_workspace_project_access(accounts):
    _, ids, login = accounts
    viewer, outsider = login('viewer'), login('outsider')
    for path in [f"/runs/{ids['run']}", f"/runs/{ids['run']}/violations/page"]:
        assert viewer.get(path).status_code == 200
        assert outsider.get(path).status_code == 404
