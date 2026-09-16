import copy

import pytest

from app.services.timing import summarize_corners

CORNERS = [
    {'name': 'slow', 'endpoint_ids': ['a/D', 'b/D'], 'endpoint_slacks_ps': [-10, 20]},
    {'name': 'fast', 'endpoint_ids': ['b/D', 'a/D'], 'endpoint_slacks_ps': [5, -20]},
]


def test_alignment_changes_positional_false_violation_and_preserves_inputs():
    original = copy.deepcopy(CORNERS)
    result = summarize_corners(CORNERS, 15)
    assert result['endpoint_alignment'] == 'by_id'
    assert result['endpoint_ids'] == ['a/D', 'b/D']
    assert result['merged_slacks_ps'] == [-20, 5]
    assert result['merged']['violating_endpoints'] == 1
    assert result['merged']['tns_ps'] == -20
    assert result['estimated_pba']['recovered_endpoints'] == 0
    assert result['worst_endpoints'][0] == {'index': 0, 'endpoint_id': 'a/D', 'slack_ps': -20, 'limiting_corners': ['fast']}
    assert CORNERS == original
    positional = [{k: v for k, v in corner.items() if k != 'endpoint_ids'} for corner in CORNERS]
    assumed = summarize_corners(positional)
    assert assumed['endpoint_alignment'] == 'positional'
    assert assumed['endpoint_ids'] is None
    assert assumed['merged']['violating_endpoints'] == 2


def test_permutations_and_equal_worst_corners():
    reversed_paths = [{**corner, 'endpoint_ids': corner['endpoint_ids'][::-1], 'endpoint_slacks_ps': corner['endpoint_slacks_ps'][::-1]} for corner in CORNERS]
    assert summarize_corners(reversed_paths)['merged'] == summarize_corners(CORNERS)['merged']
    tied = copy.deepcopy(CORNERS)
    tied[0]['endpoint_slacks_ps'][0] = -20
    assert summarize_corners(tied)['worst_endpoints'][0]['limiting_corners'] == ['slow', 'fast']


@pytest.mark.parametrize('ids', [None, ['c/D', 'a/D'], ['a/D', 'a/D'], ['a/D'], [' ', 'a/D'], ['a\nD', 'b/D']])
def test_incomplete_ambiguous_or_invalid_ids_rejected(client, ids):
    corners = copy.deepcopy(CORNERS)
    corners[1]['endpoint_ids'] = ids
    response = client.post('/analysis/timing-summary', json={'corners': corners})
    assert response.status_code == 422, response.text


def test_api_merge_and_literal_identity(client):
    response = client.post('/analysis/timing-summary', json={'corners': CORNERS})
    assert response.status_code == 200
    assert response.json()['merged_slacks_ps'] == [-20, 5]
    corners = copy.deepcopy(CORNERS)
    corners[1]['endpoint_ids'][0] = ' b/D'
    assert client.post('/analysis/timing-summary', json={'corners': corners}).status_code == 422


def test_worst_endpoint_details_are_bounded_and_complete_stats_are_retained(client):
    corners = [{'name': 'slow', 'endpoint_ids': [f'q{i}/D' for i in range(100)], 'endpoint_slacks_ps': list(range(-100, 0))}]
    result = client.post('/analysis/timing-summary', json={'corners': corners}).json()
    assert len(result['worst_endpoints']) == 20
    assert len(result['merged_slacks_ps']) == result['merged']['total_endpoints'] == 100
    assert result['merged']['tns_ps'] == -5050


@pytest.mark.parametrize('slack', [-0.00001, -1e-100, -5e-324, 0.0, 0.00001])
def test_summary_preserves_small_slack_and_consistent_violation_status(client, slack):
    response = client.post('/analysis/timing-summary', json={
        'corners': [{'name': 'precision', 'endpoint_slacks_ps': [slack, 1.0]}],
    })
    assert response.status_code == 200, response.text
    result = response.json()
    for summary in [result['merged'], result['corners'][0]]:
        assert summary['wns_ps'] == slack
        assert summary['tns_ps'] == (slack if slack < 0 else 0.0)
        assert summary['violating_endpoints'] == int(slack < 0)
    assert result['signoff_clean'] == (slack >= 0)
    assert result['worst_endpoints'][0]['slack_ps'] == slack


def test_pba_retains_residual_violation_below_old_rounding_threshold(client):
    response = client.post('/analysis/timing-summary', json={
        'corners': [{'name': 'precision', 'endpoint_slacks_ps': [-0.0002, -0.0001]}],
        'pba_pessimism_credit_ps': 0.0001,
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['estimated_pba']['wns_ps'] == -0.0001
    assert result['estimated_pba']['tns_ps'] == -0.0001
    assert result['estimated_pba']['violating_endpoints'] == 1
    assert result['estimated_pba']['recovered_endpoints'] == 1


def test_tns_preserves_small_contributions_regardless_of_endpoint_order():
    slacks = [-1e16, -1.0, -1.0]
    forward = summarize_corners([{'name': 'precision', 'endpoint_slacks_ps': slacks}])
    reverse = summarize_corners([{'name': 'precision', 'endpoint_slacks_ps': slacks[::-1]}])
    assert forward['merged']['tns_ps'] == -10000000000000002.0
    assert reverse['merged']['tns_ps'] == forward['merged']['tns_ps']
