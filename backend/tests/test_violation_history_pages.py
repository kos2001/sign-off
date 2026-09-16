import pytest

from app.db import SessionLocal
from app.models import ViolationEvent
from test_auth import accounts
from test_violation_lifecycle import issue


def seed(vid, count):
    with SessionLocal() as db:
        rows = [ViolationEvent(violation_id=vid, from_status='open', to_status='fixed',
                               actor='Page QA', reason=f'Event {index}') for index in range(count)]
        db.add_all(rows)
        db.commit()
        return [row.id for row in rows]


def test_history_pages_are_bounded_ordered_and_complete(client, issue):
    _, _, vid = issue
    ids = seed(vid, 53)
    route = f'/violations/{vid}/history/page'
    params, captured, totals = {}, [], []
    for expected_size in [25, 25, 3]:
        response = client.get(route, params=params)
        assert response.status_code == 200
        page = response.json()
        assert len(page['items']) == expected_size
        captured.extend(item['id'] for item in page['items'])
        totals.append(page['total'])
        params = {'before_id': page['next_before_id'], 'snapshot_max_id': page['snapshot_max_id']}
    assert captured == list(reversed(ids)) and totals == [53] * 3
    assert params['before_id'] is None


def test_appended_events_wait_for_a_fresh_snapshot(client, issue):
    _, _, vid = issue
    ids = seed(vid, 30)
    route = f'/violations/{vid}/history/page'
    first = client.get(route).json()
    added = seed(vid, 2)
    second = client.get(route, params={'before_id': first['next_before_id'],
                                      'snapshot_max_id': first['snapshot_max_id']}).json()
    assert second['total'] == 30
    assert [item['id'] for item in first['items'] + second['items']] == list(reversed(ids))
    refreshed = client.get(route).json()
    assert refreshed['total'] == 32
    assert [item['id'] for item in refreshed['items'][:2]] == list(reversed(added))


def test_empty_history_and_end_cursor(client, issue):
    _, _, vid = issue
    route = f'/violations/{vid}/history/page'
    assert client.get(route).json() == {'items': [], 'total': 0, 'snapshot_max_id': 0, 'next_before_id': None}
    seed(vid, 2)
    assert client.get(route + '?snapshot_max_id=0').json()['items'] == []
    assert client.get(route + '?snapshot_max_id=9223372036854775807&before_id=1').json()['items'] == []
    assert client.get('/violations/99999999/history/page').status_code == 404


@pytest.mark.parametrize('query', ['limit=0', 'limit=101', 'before_id=0', 'snapshot_max_id=-1',
    'before_id=1', 'before_id=9223372036854775808&snapshot_max_id=2', 'snapshot_max_id=9223372036854775808'])
def test_history_page_rejects_invalid_cursors(client, issue, query):
    assert client.get(f'/violations/{issue[2]}/history/page?{query}').status_code == 422


def test_history_page_scope_cannot_be_changed_by_cursor(accounts):
    _, ids, login = accounts
    seed(ids['violation'], 3)
    viewer, outsider = login('viewer'), login('outsider')
    route = f"/violations/{ids['violation']}/history/page"
    assert viewer.get(route).json()['total'] == 3
    assert outsider.get(route).status_code == 404
    assert outsider.get(route + '?snapshot_max_id=9223372036854775807').status_code == 404


@pytest.mark.parametrize('query,expected', [
    ({'q': 'ALICE'}, [2, 0]), ({'q': '  100%_  '}, [0]), ({'q': '%_'}, [1, 0]),
    ({'q': 'review', 'to_status': 'fixed'}, [3, 0]), ({'q': 'review', 'to_status': 'waived'}, []),
    ({'to_status': 'open'}, [1]), ({'to_status': 'waived'}, [2]),
])
def test_history_search_actor_reason_literal_wildcards_and_status(client, issue, query, expected):
    _, _, vid = issue
    with SessionLocal() as db:
        rows = [ViolationEvent(violation_id=vid, from_status='open', to_status=status, actor=actor, reason=reason)
                for actor, reason, status in [('Alice', 'review 100%_done', 'fixed'),
                    ('Bob', 'Reopen %_', 'open'), ('alice', 'approved waiver', 'waived'),
                    ('Carol', 'review 100percentXdone', 'fixed')]]
        db.add_all(rows)
        db.commit()
        ids = [row.id for row in rows]
    response = client.get(f'/violations/{vid}/history/page', params=query)
    assert response.status_code == 200
    assert response.json()['total'] == len(expected)
    assert [row['id'] for row in response.json()['items']] == [ids[index] for index in expected]


def test_filtered_history_keeps_snapshot_while_paging(client, issue):
    _, _, vid = issue
    ids = seed(vid, 5)
    route = f'/violations/{vid}/history/page'
    filters = {'q': 'Event', 'to_status': 'fixed', 'limit': 2}
    first = client.get(route, params=filters).json()
    seed(vid, 2)
    captured = [item['id'] for item in first['items']]
    page = first
    while page['next_before_id'] is not None:
        page = client.get(route, params={**filters, 'before_id': page['next_before_id'],
                         'snapshot_max_id': first['snapshot_max_id']}).json()
        assert page['total'] == 5
        captured.extend(item['id'] for item in page['items'])
    assert captured == list(reversed(ids))
    assert client.get(route, params=filters).json()['total'] == 7


@pytest.mark.parametrize('query', [{'q': 'x' * 201}, {'to_status': 'invalid'}])
def test_history_filter_validation(client, issue, query):
    assert client.get(f'/violations/{issue[2]}/history/page', params=query).status_code == 422
