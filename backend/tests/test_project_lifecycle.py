import uuid

from sqlalchemy import create_engine, inspect, text

from app.migrations import initialize_schema
from test_auth import accounts


def create_project(client):
    response = client.post('/projects', json={
        'name': f'lifecycle-{uuid.uuid4().hex}', 'process_node': '3nm', 'foundry': 'QA',
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_archive_is_reversible_audited_and_read_only(client):
    project = create_project(client)
    run = client.post(f"/projects/{project['id']}/runs", json={
        'domain': 'sta', 'stage': 'routing', 'tool': 'PrimeTime',
    })
    assert run.status_code == 201
    assert client.patch(f"/runs/{run.json()['id']}", json={'status': 'passed'}).status_code == 200

    archived = client.put(f"/projects/{project['id']}/lifecycle", json={
        'expected_version': 1, 'archived': True, 'reason': 'Tapeout completed',
    })
    assert archived.status_code == 200, archived.text
    body = archived.json()
    assert body['lifecycle_version'] == 2
    assert body['archived_at'] is not None
    assert body['archived_by'] == 'local operator'

    assert project['id'] not in {item['id'] for item in client.get('/projects').json()}
    assert project['id'] in {item['id'] for item in client.get('/projects?include_archived=true').json()}
    assert project['id'] not in {item['id'] for item in client.get('/projects/summary').json()}
    archived_page = client.get('/projects/summary/page?lifecycle=archived').json()
    assert project['id'] in {item['id'] for item in archived_page['items']}
    assert client.get(f"/projects/{project['id']}").status_code == 200
    assert client.post(f"/projects/{project['id']}/runs", json={
        'domain': 'sta', 'stage': 'routing', 'tool': 'blocked',
    }).status_code == 409
    assert client.post('/analysis/rtl-signoff', json={
        'project_id': project['id'], 'code': 'module top; endmodule',
    }).status_code == 409

    history = client.get(f"/projects/{project['id']}/lifecycle/history").json()
    assert [(item['version'], item['after_state'], item['reason']) for item in history['items']] == [
        (2, 'archived', 'Tapeout completed')]
    assert client.put(f"/projects/{project['id']}/lifecycle", json={
        'expected_version': 1, 'archived': False, 'reason': 'stale restore',
    }).status_code == 409
    restored = client.put(f"/projects/{project['id']}/lifecycle", json={
        'expected_version': 2, 'archived': False, 'reason': 'ECO requested',
    })
    assert restored.status_code == 200
    assert restored.json()['lifecycle_version'] == 3
    assert restored.json()['archived_at'] is None
    assert project['id'] in {item['id'] for item in client.get('/projects').json()}


def test_archive_rejects_active_work(client):
    project = create_project(client)
    assert client.post(f"/projects/{project['id']}/runs", json={
        'domain': 'sta', 'stage': 'routing', 'tool': 'running',
    }).status_code == 201
    response = client.put(f"/projects/{project['id']}/lifecycle", json={
        'expected_version': 1, 'archived': True, 'reason': 'too early',
    })
    assert response.status_code == 409
    assert response.json()['detail'] == 'finish or cancel active runs and STA batches before archiving'


def test_project_lifecycle_requires_owner(accounts):
    users, _, login = accounts
    owner = login('owner')
    project = create_project(owner)
    assert owner.put(f"/projects/{project['id']}/members", json={
        'username': users['editor'].username, 'role': 'editor',
    }).status_code == 200
    editor = login('editor')
    assert editor.put(f"/projects/{project['id']}/lifecycle", json={
        'expected_version': 1, 'archived': True, 'reason': 'unauthorized',
    }).status_code == 403
    assert editor.get(f"/projects/{project['id']}/lifecycle/history").status_code == 403


def test_existing_project_table_is_upgraded_without_changing_rows(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'legacy-project.db'))
    with engine.begin() as connection:
        connection.execute(text('''CREATE TABLE projects (
            id INTEGER PRIMARY KEY, name VARCHAR(120) UNIQUE NOT NULL,
            process_node VARCHAR(40) NOT NULL, foundry VARCHAR(60) NOT NULL,
            created_at DATETIME NOT NULL
        )'''))
        connection.execute(text("INSERT INTO projects VALUES (7, 'legacy', '5nm', 'QA', '2026-01-01')"))
    initialize_schema(engine)
    columns = {column['name'] for column in inspect(engine).get_columns('projects')}
    assert {'lifecycle_version', 'archived_at', 'archived_by', 'archived_by_user_id',
            'release_decision_chain_head_sha256'} <= columns
    with engine.connect() as connection:
        row = connection.execute(text(
            'SELECT name, lifecycle_version, archived_at FROM projects WHERE id = 7')).one()
    assert tuple(row) == ('legacy', 1, None)
