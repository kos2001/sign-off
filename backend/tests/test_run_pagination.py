import uuid

from sqlalchemy import update

from app.db import SessionLocal
from app.models import RunEvidence


def project(client):
    return client.post('/projects', json={
        'name': f'run-pagination-{uuid.uuid4().hex}', 'process_node': '4nm', 'foundry': 'test',
    }).json()['id']


def create_run(client, project_id, index, domain='sta'):
    return client.post(f'/projects/{project_id}/runs', json={
        'domain': domain, 'stage': 'routing', 'tool': f'tool-{index}',
    }).json()


def test_run_history_uses_stable_descending_cursor_and_global_counts(client):
    project_id = project(client)
    runs = [create_run(client, project_id, index, 'pv' if index == 4 else 'sta')
            for index in range(6)]
    client.patch(f"/runs/{runs[1]['id']}", json={'status': 'passed'})
    client.patch(f"/runs/{runs[2]['id']}", json={'status': 'failed'})

    first = client.get(f'/projects/{project_id}/runs/page?limit=2')
    assert first.status_code == 200, first.text
    page = first.json()
    assert [item['id'] for item in page['items']] == [runs[5]['id'], runs[4]['id']]
    assert page['total'] == 6
    assert page['status_counts'] == {'running': 4, 'incomplete': 0, 'passed': 1, 'failed': 1}
    assert page['next_before_id'] == runs[4]['id']

    inserted = create_run(client, project_id, 6)
    second = client.get(f"/projects/{project_id}/runs/page?limit=2&before_id={page['next_before_id']}").json()
    assert [item['id'] for item in second['items']] == [runs[3]['id'], runs[2]['id']]
    assert inserted['id'] not in {item['id'] for item in second['items']}
    assert second['total'] == 7 and second['status_counts']['running'] == 5

    filtered = client.get(f'/projects/{project_id}/runs/page?domain=pv&stage=routing').json()
    assert filtered['total'] == 1 and [item['id'] for item in filtered['items']] == [runs[4]['id']]
    filtered = client.get(f'/projects/{project_id}/runs/page?status=passed&q=TOOL-1').json()
    assert filtered['total'] == 1 and filtered['items'][0]['id'] == runs[1]['id']
    assert filtered['status_counts'] == {
        'running': 0, 'incomplete': 0, 'passed': 1, 'failed': 0,
    }
    assert client.get(f'/projects/{project_id}/runs/page', params={'q': '   '}).status_code == 422
    literal = create_run(client, project_id, '%_literal')
    literal_search = client.get(f'/projects/{project_id}/runs/page', params={'q': '%_'}).json()
    assert literal_search['total'] == 1 and literal_search['items'][0]['id'] == literal['id']


def test_legacy_run_list_fails_explicitly_above_safety_limit(client, monkeypatch):
    project_id = project(client)
    for index in range(4):
        create_run(client, project_id, index)
    monkeypatch.setattr('app.routers.runs.MAX_LEGACY_RUN_LIST', 3)
    response = client.get(f'/projects/{project_id}/runs')
    assert response.status_code == 413
    assert 'runs/page' in response.json()['detail']


def test_run_history_filters_and_lists_exact_design_revisions(client):
    project_id = project(client)
    runs = [create_run(client, project_id, index) for index in range(5)]
    with SessionLocal.begin() as db:
        for run, revision in zip(runs[:4], ['rev-A', 'rev-A', 'rev-B', '%_literal']):
            db.execute(update(RunEvidence).where(RunEvidence.run_id == run['id'])
                       .values(design_revision=revision))

    page = client.get(f'/projects/{project_id}/runs/page', params={'revision': 'rev-A'}).json()
    assert page['total'] == 2
    assert [item['id'] for item in page['items']] == [runs[1]['id'], runs[0]['id']]
    assert {item['design_revision'] for item in page['items']} == {'rev-A'}
    labeled = client.get(f'/projects/{project_id}/runs/page?revision_scope=labeled').json()
    assert labeled['total'] == 4
    unlabeled = client.get(f'/projects/{project_id}/runs/page?revision_scope=unlabeled').json()
    assert unlabeled['total'] == 1 and unlabeled['items'][0]['id'] == runs[4]['id']
    assert client.get(f'/projects/{project_id}/runs/page', params={
        'revision': 'rev-A', 'revision_scope': 'unlabeled',
    }).status_code == 422

    revisions = client.get(f'/projects/{project_id}/run-revisions?limit=2').json()
    assert revisions['total'] == 3 and revisions['unlabeled_runs'] == 1
    assert len(revisions['items']) == 2
    assert revisions['items'][0] == {
        'design_revision': '%_literal', 'run_count': 1, 'latest_run_id': runs[3]['id'],
    }
    filtered = client.get(f'/projects/{project_id}/run-revisions', params={'q': '%_'}).json()
    assert [item['design_revision'] for item in filtered['items']] == ['%_literal']
    assert client.get(f'/projects/{project_id}/run-revisions', params={'q': '   '}).status_code == 422
