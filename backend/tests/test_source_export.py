import hashlib

import pytest

from app.db import SessionLocal
from app.models import SignoffRun
from test_auth import accounts
from test_report_import import payload, project


def imported(client, pid=None, source=None):
    body = payload()
    if source is not None:
        body['source_text'] = source
    result = client.post(f'/projects/{pid or project(client)}/imports/opensta', json=body)
    assert result.status_code == 201
    return result.json()['id'], body['source_text']


@pytest.mark.parametrize('source', [None, '\ufeff{\r\n  "checks": [], "note": "한글 µW"\r\n}\r\n'])
def test_source_export_preserves_exact_utf8_and_hash(client, source):
    rid, original = imported(client, source=source)
    before = client.get(f'/runs/{rid}/evidence').json()
    response = client.get(f'/runs/{rid}/evidence/source')
    assert response.status_code == 200
    assert response.content == original.encode('utf-8')
    assert response.headers['x-source-sha256'] == hashlib.sha256(response.content).hexdigest()
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['content-disposition'] == f'attachment; filename="run-{rid}-source.json"'
    assert client.get(f'/runs/{rid}/evidence').json() == before


@pytest.mark.parametrize('damage', ['content', 'hash', 'missing_hash'])
def test_corrupt_source_is_not_exported(client, damage):
    rid, _ = imported(client)
    with SessionLocal() as db:
        evidence = db.get(SignoffRun, rid).evidence
        if damage == 'content':
            evidence.source_text += '\n'
        else:
            evidence.source_sha256 = None if damage == 'missing_hash' else '0' * 64
        db.commit()
    response = client.get(f'/runs/{rid}/evidence/source')
    assert response.status_code == 409
    assert 'content-disposition' not in response.headers
    assert 'source_text' not in response.json()


def test_rtl_export_uses_captured_source_and_fixed_filename(client):
    rid, _ = imported(client)
    source = 'module test;\r\n// 한글\r\nendmodule\r\n'
    with SessionLocal() as db:
        evidence = db.get(SignoffRun, rid).evidence
        evidence.source = 'rtl_ladder'
        evidence.source_text = source
        evidence.source_sha256 = hashlib.sha256(source.encode()).hexdigest()
        db.commit()
    response = client.get(f'/runs/{rid}/evidence/source')
    assert response.status_code == 200
    assert response.content == source.encode()
    assert response.headers['content-disposition'].endswith(f'run-{rid}-source.sv"')


def test_source_export_permissions_and_absent_source(accounts):
    _, ids, login = accounts
    editor, viewer, outsider = login('editor'), login('viewer'), login('outsider')
    rid, source = imported(editor, ids['project'])
    assert viewer.get(f'/runs/{rid}/evidence/source').content == source.encode()
    assert outsider.get(f'/runs/{rid}/evidence/source').status_code == 404
    assert viewer.get(f"/runs/{ids['run']}/evidence/source").status_code == 404
    manual = editor.post(f"/projects/{ids['project']}/runs", json={'domain': 'sta', 'stage': 'placement', 'tool': 'manual'}).json()['id']
    assert viewer.get(f'/runs/{manual}/evidence/source').status_code == 409
    assert viewer.get('/runs/999999999/evidence/source').status_code == 404
