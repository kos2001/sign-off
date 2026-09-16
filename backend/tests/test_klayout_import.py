import hashlib
from pathlib import Path
import uuid
import pytest
from app.services.klayout_report import parse_klayout
from test_auth import accounts

SOURCE = (Path(__file__).parent/'fixtures/drc.lyrdb').read_text()

def payload(source=SOURCE):
    return dict(import_id=str(uuid.uuid4()), stage='placement', filename='drc.lyrdb', tool_version='QA', design_revision='rev-A', scenario='DRC fixture', source_text=source)


def test_parser_preserves_cell_values_tags_and_multiplicity():
    result = parse_klayout(SOURCE)
    assert result['metrics'] == {'reported_items': 1, 'reported_multiplicity': 3}
    item = result['items'][0]
    assert item['cell'] == 'BLOCK:1' and item['category'] == 'M1.spacing'
    assert item['values'] == ['box: (1.5,2;3,4)', "text: 'spacing < 0.1'"]
    assert item['tags'] == 'waived,important' and item['visited'] == 'true'
    assert result['status'] == 'failed' and result['coverage'] == 'reported_markers_only'
    assert result['source_sha256'] == hashlib.sha256(SOURCE.encode()).hexdigest()


@pytest.mark.parametrize('source', [
    '<wrong/>', '<report-database/>', '<report-database><items/><items/></report-database>',
    '<!DOCTYPE report-database [<!ENTITY x "expanded">]><report-database><items/></report-database>',
    SOURCE.replace('<multiplicity>3</multiplicity>', '<multiplicity>-1</multiplicity>'),
    SOURCE.replace('<category>M1.spacing</category>', '<category>M1</category><category>M2</category>'),
    SOURCE.replace('<cell>BLOCK:1</cell>', ''),
    '<report-database><items>'+'<item/>'*1001+'</items></report-database>',
    '<report-database><items/>'+('<x>'*33)+('</x>'*33)+'</report-database>',
])
def test_invalid_reports_rejected(source):
    with pytest.raises(ValueError):
        parse_klayout(source)


def test_empty_report_is_incomplete_and_duplicates_preserved():
    empty = parse_klayout('<report-database><items/></report-database>')
    assert empty['status'] == 'incomplete'
    repeated = SOURCE.replace('</item>', '</item>'+SOURCE.split('<item>')[1].split('</item>')[0].join(['<item>', '</item>']))
    result = parse_klayout(repeated)
    assert result['metrics'] == {'reported_items': 2, 'reported_multiplicity': 6}
    assert result['items'][0]['fingerprint'] == result['items'][1]['fingerprint']


def test_import_auth_idempotency_source_immutability_and_gate(accounts):
    _, ids, login = accounts
    path = f"/projects/{ids['project']}/imports/klayout"
    body = payload('\ufeff'+SOURCE.replace('\n','\r\n'))
    viewer, editor, outsider = login('viewer'), login('editor'), login('outsider')
    assert viewer.post(path, json=body).status_code == 403
    assert outsider.post(path, json=body).status_code == 404
    preview = editor.post(path+'/preview', json=body)
    assert preview.status_code == 200
    first = editor.post(path, json=body)
    assert first.status_code == 201, first.text
    row = first.json()
    assert row['domain'] == 'pv' and row['result_locked'] and row['evidence_source'] == 'klayout_report'
    assert editor.post(path, json=body).json()['id'] == row['id']
    assert editor.post(path, json={**body, 'scenario': 'changed'}).status_code == 409
    rid = row['id']
    violations = viewer.get(f'/runs/{rid}/violations').json()
    assert len(violations) == 1 and violations[0]['status'] == 'open' and violations[0]['waiver'] is None
    assert violations[0]['location'] == 'BLOCK:1' and 'box: (1.5,2;3,4)' in violations[0]['description']
    assert editor.patch(f'/runs/{rid}', json={'status': 'passed'}).status_code == 409
    original = viewer.get(f'/runs/{rid}/evidence/source')
    assert original.content == body['source_text'].encode()
    assert '.lyrdb' in original.headers['content-disposition']
    gate = viewer.get(f"/projects/{ids['project']}/signoff-status?stage=placement").json()
    pv = next(d for d in gate['domains'] if d['domain'] == 'pv')
    assert not pv['ready'] and 'full DRC coverage' in pv['reason']
    evidence = viewer.get(f'/runs/{rid}/evidence').json()
    assert evidence['result']['submitted_by']['username'] == accounts[0]['editor'].username


def test_actual_klayout_width_check_fixture(client):
    source = (Path(__file__).parent/'fixtures/klayout-width.lyrdb').read_text()
    parsed = parse_klayout(source)
    assert parsed['metrics'] == {'reported_items': 2, 'reported_multiplicity': 2}
    assert parsed['items'][0]['category'] == "'M1.width'"
    assert all(item['values'][0].startswith('edge-pair:') for item in parsed['items'])
    assert 'KLayout 0.30.12' in parsed['generator']
    pid = client.post('/projects', json={'name': str(uuid.uuid4()), 'process_node': 'test', 'foundry': 'test'}).json()['id']
    response = client.post(f'/projects/{pid}/imports/klayout', json=payload(source))
    assert response.status_code == 201 and response.json()['metrics'] == parsed['metrics']
