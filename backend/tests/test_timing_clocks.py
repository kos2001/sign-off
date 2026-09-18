import copy
import hashlib
import json

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import RunEvidence
from app.services.report_import import parse_opensta
from test_auth import accounts
from test_report_import import payload, project, report


def clock_report():
    doc = report()
    doc['checks'][0].update(
        source_clock='launch_clk', target_clock='capture_clk',
        source_clock_edge='rise', target_clock_edge='fall',
        source_clock_path=[{'pin': f'launch_clk/buf{i}/Y', 'arrival': i * 1e-12} for i in range(103)],
        target_clock_path=[{'pin': 'capture_clk', 'arrival': 1e-9}, {'pin': 'capture/CK', 'arrival': 1.2e-9}],
        crpr=2e-12, margin=30e-12, path_margin=-5e-12, path_delay=2e-9, multi_cycle_path=0,
    )
    return doc


def save(client, doc, pid=None):
    response = client.post(f'/projects/{pid or project(client)}/imports/opensta', json=payload(doc))
    assert response.status_code == 201, response.text
    return response.json()['id']


def test_clock_sections_units_pagination_deltas_terms_and_immutable_evidence(client):
    run = save(client, clock_report())
    before = client.get(f'/runs/{run}/evidence').json()
    route = f'/runs/{run}/timing-paths/1'
    data = client.get(route).json()
    assert data['section'] == 'data' and data['point_total'] == 2
    assert data['source_clock_edge'] == 'rise' and data['target_clock_edge'] == 'fall'
    assert data['check_terms']['crpr_ps'] == pytest.approx(2)
    assert data['check_terms']['margin_ps'] == pytest.approx(30)
    assert data['check_terms']['path_margin_ps'] == pytest.approx(-5)
    assert data['check_terms']['path_delay_ps'] == pytest.approx(2000)
    assert data['check_terms']['multi_cycle_path'] == 0
    assert data['sections'] == {'data': {'reported': True, 'point_total': 2}, 'source_clock': {'reported': True, 'point_total': 103}, 'target_clock': {'reported': True, 'point_total': 2}}
    launch = client.get(route, params={'section': 'source_clock', 'point_offset': 100}).json()
    assert launch['section_reported'] is True
    assert [p['index'] for p in launch['points']] == [101, 102, 103]
    assert launch['points'][0]['arrival_ps'] == pytest.approx(100)
    assert launch['points'][0]['arrival_delta_ps'] == pytest.approx(1)
    assert launch['arrival_delta_summary']['total_pairs'] == 102
    capture = client.get(route, params={'section': 'target_clock'}).json()
    assert capture['points'][1]['pin'] == 'capture/CK'
    assert capture['points'][1]['arrival_delta_ps'] == pytest.approx(200)
    assert client.get(f'/runs/{run}/evidence').json() == before


def test_absent_empty_and_unconstrained_clock_paths(client):
    doc = report()
    doc['checks'][0].update(type='unconstrained', target_clock_path=[])
    doc['checks'][0].pop('slack')
    run = save(client, doc)
    for section, reported in [('source_clock', False), ('target_clock', True)]:
        result = client.get(f'/runs/{run}/timing-paths/1', params={'section': section}).json()
        assert result['section_reported'] is reported
        assert result['point_total'] == 0 and result['points'] == []
        assert all(value is None for value in result['check_terms'].values())
    assert client.get(f'/runs/{run}/timing-paths/1?section=unknown').status_code == 422


@pytest.mark.parametrize('value', [None, {}, False, [None], [{'pin': ''}], [{'pin': 5}], [{'pin': 'x' * 201}], [{'pin': 'x'}] * 10001])
@pytest.mark.parametrize('field', ['source_clock_path', 'target_clock_path'])
def test_malformed_optional_clocks_rejected_at_import(value, field):
    doc = report()
    doc['checks'][0][field] = value
    with pytest.raises(ValueError, match=field):
        parse_opensta(json.dumps(doc))


@pytest.mark.parametrize('value', [True, '1', 10**200, None])
def test_invalid_optional_terms_remain_unknown(client, value):
    doc = report()
    doc['checks'][0].update(crpr=value, margin=value, multi_cycle_path=value)
    run = save(client, doc)
    result = client.get(f'/runs/{run}/timing-paths/1').json()
    assert result['check_terms']['crpr_ps'] is None
    assert result['check_terms']['margin_ps'] is None
    assert result['check_terms']['multi_cycle_path'] is None


@pytest.mark.parametrize('damage', ['hash', 'saved_path', 'malformed_clock'])
def test_corrupt_captured_report_is_not_used_for_details(client, damage):
    run = save(client, clock_report())
    with SessionLocal() as db:
        evidence = db.scalar(select(RunEvidence).where(RunEvidence.run_id == run))
        assert evidence is not None
        if damage == 'hash':
            evidence.source_text += ' '
        elif damage == 'saved_path':
            changed = copy.deepcopy(evidence.result)
            changed['paths'][0]['slack_ps'] = 0
            evidence.result = changed
        else:
            doc = json.loads(evidence.source_text)
            doc['checks'][0]['source_clock_path'] = [False]
            evidence.source_text = json.dumps(doc)
            evidence.source_sha256 = hashlib.sha256(evidence.source_text.encode()).hexdigest()
        db.commit()
    for section in ['data', 'source_clock', 'target_clock']:
        assert client.get(f'/runs/{run}/timing-paths/1?section={section}').status_code == 409


def test_clock_path_permissions(accounts):
    _, ids, login = accounts
    run = save(login('editor'), clock_report(), ids['project'])
    assert login('viewer').get(f'/runs/{run}/timing-paths/1?section=source_clock').status_code == 200
    assert login('outsider').get(f'/runs/{run}/timing-paths/1?section=source_clock').status_code == 404
