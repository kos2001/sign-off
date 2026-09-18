import uuid
import hashlib
import io
import json
import zipfile
from sqlalchemy import event
from app.db import SessionLocal, engine
from app.models import RunEvidence, SignoffRun
from test_auth import accounts


def test_export_selected_runs_and_current_waiver(client, accounts):
    _, ids, login = accounts
    owner = login('owner')
    path = f"/projects/{ids['project']}/signoff-status"
    run = ids['run']
    waiver = owner.post(f"/violations/{ids['violation']}/waiver", json={'expected_version': 1, 'reason': '한글 근거', 'approved_by': 'forged'})
    assert waiver.status_code == 201
    with SessionLocal() as db:
        db.get(SignoffRun, run).evidence = RunEvidence(source='manual', source_text='excluded source', design_revision='rev-1', result={'qa': True})
        db.commit()
    response = login('viewer').get(path+'/export?stage=final')
    assert response.status_code == 200
    bundle = response.json()
    assert bundle['format'] == 'signoff/stage-gate-export/v1'
    assert bundle['gate'] == owner.get(path+'?stage=final').json()
    assert [r['id'] for r in bundle['runs']] == [run]
    record = bundle['runs'][0]
    assert record['evidence']['result'] == {'qa': True}
    assert 'source_text' not in record['evidence'] and 'excluded source' not in response.text
    assert record['violations'][0]['waiver']['reason'] == '한글 근거'
    assert record['violations'][0]['waiver']['approved_by'] == accounts[0]['owner'].username
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert f'project-{ids["project"]}-final-gate.json' in response.headers['content-disposition']
    assert login('outsider').get(path+'/export?stage=final').status_code == 404
    assert owner.get(path+'/export?stage=unknown').status_code == 422
    empty = owner.get(path+'/export?stage=rtl').json()
    assert empty['runs'] == [] and empty['gate']['ready'] is False


def test_gate_query_uses_latest_single_snapshot_without_source_text(client):
    from app.models import Domain, RunStatus, Stage
    from app.routers.runs import gate_runs
    pid = client.post('/projects', json={'name': str(uuid.uuid4()), 'process_node': 'test', 'foundry': 'test'}).json()['id']
    with SessionLocal() as db:
        for i in range(3):
            db.add(SignoffRun(project_id=pid, domain=Domain.sta, stage=Stage.final, tool='test', status=RunStatus.passed, evidence=RunEvidence(source='manual', source_text='large historical text')))
        db.commit()
    statements = []
    def capture(conn, cursor, statement, *args):
        statements.append(statement)
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        with SessionLocal() as db:
            rows = gate_runs(pid, Stage.final, db)
            assert len(rows) == 1
            assert rows[0].evidence.source == 'manual'
            assert rows[0].violations == []
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    assert len(statements) == 1
    assert 'row_number()' in statements[0]
    assert 'source_text' not in statements[0]


def test_export_size_limit_returns_no_partial_file(client, monkeypatch):
    pid = client.post('/projects', json={'name': str(uuid.uuid4()), 'process_node': 'test', 'foundry': 'test'}).json()['id']
    monkeypatch.setattr('app.routers.runs.MAX_GATE_EXPORT_BYTES', 1)
    response = client.get(f'/projects/{pid}/signoff-status/export?stage=final')
    assert response.status_code == 413
    assert 'content-disposition' not in response.headers


def test_export_violation_count_cap(client):
    from sqlalchemy import insert
    from app.models import Violation
    pid = client.post('/projects', json={'name': str(uuid.uuid4()), 'process_node': 'test', 'foundry': 'test'}).json()['id']
    rid = client.post(f'/projects/{pid}/runs', json={'domain': 'sta', 'stage': 'final', 'tool': 'test'}).json()['id']
    with SessionLocal() as db:
        db.execute(insert(Violation), [{'run_id': rid, 'check_name': 'overflow', 'severity': 'error'} for _ in range(10001)])
        db.commit()
    response = client.get(f'/projects/{pid}/signoff-status/export?stage=final')
    assert response.status_code == 413 and 'content-disposition' not in response.headers


def test_export_exact_byte_boundary(client, monkeypatch):
    from datetime import datetime, timezone
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 16, tzinfo=timezone.utc)
    monkeypatch.setattr('app.routers.runs.datetime', FixedDateTime)
    pid = client.post('/projects', json={'name': str(uuid.uuid4()), 'process_node': 'test', 'foundry': 'test'}).json()['id']
    url = f'/projects/{pid}/signoff-status/export?stage=final'
    original = client.get(url)
    monkeypatch.setattr('app.routers.runs.MAX_GATE_EXPORT_BYTES', len(original.content))
    assert client.get(url).content == original.content
    monkeypatch.setattr('app.routers.runs.MAX_GATE_EXPORT_BYTES', len(original.content)-1)
    assert client.get(url).status_code == 413


def test_evidence_package_contains_verified_sources_and_manifest(client):
    pid = client.post('/projects', json={'name': str(uuid.uuid4()), 'process_node': 'test', 'foundry': 'test'}).json()['id']
    rid = client.post(f'/projects/{pid}/runs', json={'domain': 'sta', 'stage': 'final', 'tool': 'PrimeTime'}).json()['id']
    source = 'PrimeTime report\nslack -0.100\n'
    with SessionLocal() as db:
        evidence = db.get(SignoffRun, rid).evidence
        evidence.source = 'commercial_sta_report'
        evidence.source_text = source
        evidence.source_sha256 = hashlib.sha256(source.encode()).hexdigest()
        evidence.design_revision = 'rev-package'
        evidence.result = {'parser': 'commercial-sta/v1'}
        db.commit()

    response = client.get(f'/projects/{pid}/signoff-package?stage=final')
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/zip'
    assert response.headers['cache-control'] == 'no-store'
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == ['manifest.json', f'evidence/run-{rid}-source.txt']
        manifest_bytes = archive.read('manifest.json')
        manifest = json.loads(manifest_bytes)
        assert archive.read(manifest['files'][0]['path']).decode() == source
    assert hashlib.sha256(manifest_bytes).hexdigest() == response.headers['x-signoff-manifest-sha256']
    assert manifest['format'] == 'signoff/evidence-package/v1'
    assert manifest['gate']['revision_check']['revisions'] == ['rev-package']
    assert manifest['gate']['revision_check']['status'] == 'missing'
    assert manifest['runs'][0]['evidence']['source_sha256'] == manifest['files'][0]['sha256']


def test_evidence_package_refuses_missing_or_tampered_source(client):
    pid = client.post('/projects', json={'name': str(uuid.uuid4()), 'process_node': 'test', 'foundry': 'test'}).json()['id']
    rid = client.post(f'/projects/{pid}/runs', json={'domain': 'sta', 'stage': 'final', 'tool': 'test'}).json()['id']
    url = f'/projects/{pid}/signoff-package?stage=final'
    assert client.get(url).status_code == 409
    with SessionLocal() as db:
        evidence = db.get(SignoffRun, rid).evidence
        evidence.source_text = 'changed bytes'
        evidence.source_sha256 = hashlib.sha256(b'original bytes').hexdigest()
        db.commit()
    response = client.get(url)
    assert response.status_code == 409
    assert '무결성' in response.json()['detail']


def test_evidence_package_permissions_and_size_cap(client, accounts, monkeypatch):
    _, ids, login = accounts
    assert login('outsider').get(f"/projects/{ids['project']}/signoff-package?stage=final").status_code == 404
    owner = login('owner')
    pid = owner.post('/projects', json={'name': str(uuid.uuid4()), 'process_node': 'test', 'foundry': 'test'}).json()['id']
    monkeypatch.setattr('app.routers.runs.MAX_EVIDENCE_PACKAGE_BYTES', 1)
    response = owner.get(f'/projects/{pid}/signoff-package?stage=final')
    assert response.status_code == 413
    assert 'content-disposition' not in response.headers
