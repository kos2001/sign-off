from sqlalchemy import delete
from app.db import SessionLocal
from app.models import Violation
from test_auth import accounts
from test_klayout_import import SOURCE, payload


def test_links_scope_current_states_duplicates_and_no_inferred_approval(accounts):
    _, ids, login = accounts
    editor, approver, viewer, outsider = [login(role) for role in ['editor','approver','viewer','outsider']]
    endpoint = f"/projects/{ids['project']}/imports/klayout"
    rid = editor.post(endpoint, json=payload()).json()['id']
    other = editor.post(endpoint, json=payload()).json()['id']
    path = f'/runs/{rid}/markers/1'
    original = viewer.get(path).json()
    links = original['violation_matches']
    assert links['status'] == 'unique' and links['source_marker_count'] == 1
    assert len(links['items']) == 1 and links['items'][0]['status'] == 'open'
    vid = links['items'][0]['id']
    assert viewer.get(f'/runs/{other}/markers/1').json()['violation_matches']['items'][0]['id'] != vid
    assert outsider.get(path).status_code == 404
    fixed = {'expected_status':'open','expected_version':1,'status':'fixed','actor':'forged','reason':'checked geometry'}
    assert viewer.patch(f'/violations/{vid}', json=fixed).status_code == 403
    assert editor.patch(f'/violations/{vid}', json=fixed).status_code == 200
    updated = viewer.get(path).json()
    assert updated['violation_matches']['items'] == [{'id':vid,'status':'fixed','version':2}]
    assert updated['item'] == original['item'] and updated['geometry'] == original['geometry']
    assert editor.patch(f'/violations/{vid}', json={**fixed, 'expected_status':'fixed', 'expected_version':2, 'status':'open'}).status_code == 200
    waived = approver.post(f'/violations/{vid}/waiver', json={'expected_version':3,'reason':'approved exception','approved_by':'forged'})
    assert waived.status_code == 201
    assert viewer.get(path).json()['violation_matches']['items'][0]['status'] == 'waived'
    item = SOURCE.split('<item>')[1].split('</item>')[0]
    duplicate_source = SOURCE.replace('</items>', '<item>'+item+'</item></items>')
    dup_run = editor.post(endpoint, json=payload(duplicate_source)).json()['id']
    first = viewer.get(f'/runs/{dup_run}/markers/1').json()['violation_matches']
    second = viewer.get(f'/runs/{dup_run}/markers/2').json()['violation_matches']
    assert first == second and first['status'] == 'ambiguous'
    assert first['source_marker_count'] == len(first['items']) == 2
    assert all(item['status'] == 'open' for item in first['items'])


def test_missing_link_never_implies_fixed(accounts):
    _, ids, login = accounts
    caller = login('editor')
    rid = caller.post(f"/projects/{ids['project']}/imports/klayout", json=payload()).json()['id']
    with SessionLocal() as db:
        db.execute(delete(Violation).where(Violation.run_id == rid))
        db.commit()
    links = caller.get(f'/runs/{rid}/markers/1').json()['violation_matches']
    assert links == {'status':'missing', 'source_marker_count':1, 'items':[]}
