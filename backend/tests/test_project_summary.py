import uuid

from test_auth import accounts


def add_run(client, project_id, status):
    run = client.post(f'/projects/{project_id}/runs', json={
        'domain': 'sta', 'stage': 'routing', 'tool': 'summary-test',
    })
    assert run.status_code == 201, run.text
    if status != 'running':
        changed = client.patch(f"/runs/{run.json()['id']}", json={'status': status})
        assert changed.status_code == 200, changed.text


def test_project_summary_aggregates_runs_and_respects_visibility(accounts):
    _, ids, login = accounts
    editor = login('editor')
    add_run(editor, ids['project'], 'passed')
    add_run(editor, ids['project'], 'failed')

    outsider = login('outsider')
    other = outsider.post('/projects', json={
        'name': f'summary-{uuid.uuid4().hex}', 'process_node': '3nm', 'foundry': 'test',
    }).json()
    add_run(outsider, other['id'], 'incomplete')

    viewer_rows = login('viewer').get('/projects/summary')
    assert viewer_rows.status_code == 200
    assert [row['id'] for row in viewer_rows.json()] == [ids['project']]
    summary = viewer_rows.json()[0]
    assert summary['total_runs'] == 3
    assert summary['status_counts'] == {
        'running': 1, 'incomplete': 0, 'passed': 1, 'failed': 1,
    }

    outsider_rows = outsider.get('/projects/summary').json()
    assert [row['id'] for row in outsider_rows] == [other['id']]
    assert outsider_rows[0]['status_counts']['incomplete'] == 1

    admin_rows = login('admin').get('/projects/summary').json()
    admin_ids = {row['id'] for row in admin_rows}
    assert {ids['project'], other['id']} <= admin_ids


def test_project_summary_page_search_sort_pagination_and_aggregates(accounts):
    _, ids, login = accounts
    owner = login('owner')
    created = []
    for name, node, foundry in [
        ('Zulu accelerator', '5nm', 'Foundry B'),
        ('Alpha compute', '3nm', 'Foundry A'),
        ('Literal %_ project', '7nm', 'Foundry A'),
    ]:
        response = owner.post('/projects', json={
            'name': f'{name}-{uuid.uuid4().hex}', 'process_node': node, 'foundry': foundry,
        })
        assert response.status_code == 201, response.text
        created.append(response.json())
    add_run(owner, created[0]['id'], 'passed')
    add_run(owner, created[1]['id'], 'failed')

    response = owner.get('/projects/summary/page', params={'sort': 'name', 'limit': 2})
    assert response.status_code == 200, response.text
    first = response.json()
    assert first['total'] == 4
    assert len(first['items']) == 2
    assert [item['name'] for item in first['items']] == sorted(
        [item['name'] for item in first['items']], key=str.lower)
    assert first['foundry_count'] >= 3
    assert first['status_counts']['passed'] == 1
    assert first['status_counts']['failed'] == 1

    second = owner.get('/projects/summary/page', params={
        'sort': 'name', 'offset': 2, 'limit': 2,
    }).json()
    assert not ({item['id'] for item in first['items']} & {item['id'] for item in second['items']})
    assert len(second['items']) == 2

    filtered = owner.get('/projects/summary/page', params={'q': 'FOUNDRY A'}).json()
    assert filtered['total'] == 2
    assert {item['id'] for item in filtered['items']} == {created[1]['id'], created[2]['id']}
    assert filtered['status_counts']['failed'] == 1
    assert filtered['status_counts']['passed'] == 0
    literal = owner.get('/projects/summary/page', params={'q': '%_'}).json()
    assert [item['id'] for item in literal['items']] == [created[2]['id']]
    assert owner.get('/projects/summary/page', params={'q': '   '}).status_code == 422

    outsider = login('outsider')
    hidden = outsider.post('/projects', json={
        'name': f'hidden-{uuid.uuid4().hex}', 'process_node': '2nm', 'foundry': 'Secret',
    }).json()
    assert hidden['id'] not in {item['id'] for item in owner.get('/projects/summary/page').json()['items']}
