import hashlib
import json
import uuid

from app.services.report_import import parse_opensta


def project(client):
    return client.post('/projects', json={'name': f'sta-{uuid.uuid4()}', 'process_node': '5nm', 'foundry': 'QA'}).json()['id']


def worker_result():
    report = json.dumps({'checks': [{'type': 'check', 'path_type': 'max', 'path_group': 'clk',
        'startpoint': 'u1/Q', 'endpoint': 'u2/D', 'source_path': [{'pin': 'u1/Q'}, {'pin': 'u2/D'}],
        'slack': -2e-11}]})
    inputs = {name: {'sha256': hashlib.sha256(value.encode()).hexdigest(), 'byte_length': len(value.encode())}
              for name, value in {'netlist': 'module top; endmodule', 'liberty': 'library(x) {}', 'sdc': 'create_clock -period 1 clk'}.items()}
    return {'protocol': 'signoff/sta-worker/v1', 'report': report, 'log': 'OpenSTA complete',
            'opensta_commit': 'd97587f669b4f169be7132346df70e7d634500c3', 'inputs': inputs}, parse_opensta(report), 'sha256:' + 'a' * 64


def test_sta_execution_records_tool_provenance_and_paths(client, monkeypatch):
    pid = project(client)
    monkeypatch.setattr('app.routers.analysis.run_sta', lambda *args: worker_result())
    body = {'project_id': pid, 'stage': 'synthesis', 'top_module': 'top', 'design_revision': 'abc123',
            'scenario': 'slow', 'netlist': 'module top; endmodule', 'liberty': 'library(x) {}',
            'sdc': 'create_clock -period 1 clk'}
    response = client.post('/analysis/sta-signoff', json=body)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result['metrics']['violating_paths'] == 1
    assert result['execution']['agent_involved'] is False
    run = client.get(f'/projects/{pid}/runs').json()[0]
    assert run['evidence_source'] == 'opensta_execution' and run['result_locked']
    evidence = client.get(f"/runs/{run['id']}/evidence").json()
    assert evidence['result']['execution']['opensta_commit'].startswith('d97587f')
    assert 'text' not in evidence['result']['input_artifacts']['sdc']
    for kind, content in [('netlist', body['netlist']), ('liberty', body['liberty']), ('sdc', body['sdc'])]:
        artifact = client.get(f"/runs/{run['id']}/evidence/artifacts/{kind}")
        assert artifact.status_code == 200 and artifact.text == content
        assert artifact.headers['x-artifact-sha256'] == hashlib.sha256(content.encode()).hexdigest()
    assert client.get(f"/runs/{run['id']}/timing-paths").status_code == 200
    gate = client.get(f'/projects/{pid}/signoff-status?stage=synthesis').json()
    sta = next(item for item in gate['domains'] if item['domain'] == 'sta')
    assert not sta['ready'] and 'sample' in sta['reason']


def test_missing_project_does_not_start_sta(client, monkeypatch):
    monkeypatch.setattr('app.routers.analysis.run_sta', lambda *args: (_ for _ in ()).throw(AssertionError()))
    body = {'project_id': 99999999, 'stage': 'synthesis', 'top_module': 'top', 'design_revision': 'abc',
            'scenario': 'slow', 'netlist': 'module top; endmodule', 'liberty': 'library(x) {}', 'sdc': 'set x 1'}
    assert client.post('/analysis/sta-signoff', json=body).status_code == 404


def test_legacy_embedded_artifacts_are_redacted_but_downloadable(client, monkeypatch):
    pid = project(client)
    worker, parsed, image = worker_result()
    monkeypatch.setattr('app.routers.analysis.run_sta', lambda *args: (worker, parsed, image))
    body = {'project_id': pid, 'stage': 'synthesis', 'top_module': 'top', 'design_revision': 'old',
            'scenario': 'slow', 'netlist': 'module top; endmodule', 'liberty': 'library(x) {}', 'sdc': 'create_clock -period 1 clk'}
    run_id = client.post('/analysis/sta-signoff', json=body).json()['run_id']
    # Simulate an old row by moving text into JSON and deleting split artifacts.
    from app.db import SessionLocal
    from app.models import RunArtifact, RunEvidence
    from sqlalchemy import delete
    with SessionLocal() as db:
        evidence = db.query(RunEvidence).filter_by(run_id=run_id).one()
        result = dict(evidence.result)
        result['input_artifacts'] = {kind: {**metadata, 'text': body[kind]}
                                     for kind, metadata in worker['inputs'].items()}
        evidence.result = result
        db.execute(delete(RunArtifact).where(RunArtifact.run_id == run_id))
        db.commit()
    response = client.get(f'/runs/{run_id}/evidence')
    assert body['sdc'] not in response.text
    assert client.get(f'/runs/{run_id}/evidence/artifacts/sdc').text == body['sdc']
