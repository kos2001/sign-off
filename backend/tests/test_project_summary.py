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
