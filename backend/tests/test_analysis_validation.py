import json

import pytest

IR = {'cell_density': [[0.5]], 'switching_activity': [[0.2]], 'pdn_strength': [[1.0]]}
GLITCH = {'nets': [{'cap_ff': 10, 'functional_toggle_rate': 0.2, 'total_toggle_rate': 0.4}]}
TIMING = {'corners': [{'name': 'slow', 'endpoint_slacks_ps': [-10, 0, 20]}]}


@pytest.mark.parametrize('field,value', [
    ('cell_density', []), ('cell_density', [[]]), ('cell_density', [[0.5], [0.5, 0.2]]),
    ('switching_activity', [[0.5, 0.2]]), ('pdn_strength', [[0]]), ('cell_density', [[1.1]]),
    ('switching_activity', [[-0.1]]), ('vdd', 0), ('scale', -1), ('hotspot_threshold_ratio', 1.1),
    ('cell_density', [[True]]), ('vdd', '0.75'), ('cell_density', [[0] * 257]),
])
def test_ir_invalid_input_never_reaches_compute(client, monkeypatch, field, value):
    def unexpected(**kwargs):
        raise AssertionError('invalid input reached compute')
    monkeypatch.setattr('app.routers.analysis.screen_ir_drop', unexpected)
    response = client.post('/analysis/ir-drop', json={**IR, field: value})
    assert response.status_code == 422, response.text
    assert all('input' not in item and 'ctx' not in item for item in response.json()['detail'])


@pytest.mark.parametrize('constant', ['NaN', 'Infinity', '-Infinity', '1e999'])
@pytest.mark.parametrize('path,body', [('/analysis/ir-drop', IR), ('/analysis/glitch-power', GLITCH), ('/analysis/timing-summary', TIMING)])
def test_nonfinite_json_values_return_validation_error(client, path, body, constant):
    source = json.dumps(body)
    token = '0.5' if path.endswith('ir-drop') else '10' if path.endswith('glitch-power') else '-10'
    response = client.post(path, content=source.replace(token, constant, 1), headers={'Content-Type': 'application/json'})
    assert response.status_code == 422, response.text
    assert response.headers.get('x-request-id')
    assert all(set(item) == {'loc', 'msg', 'type'} for item in response.json()['detail'])


@pytest.mark.parametrize('patch', [{'cap_ff': 0}, {'functional_toggle_rate': -1}, {'transport_fraction': 1.1}, {'total_toggle_rate': 0.1}])
def test_glitch_rejects_inconsistent_net_data(client, patch):
    response = client.post('/analysis/glitch-power', json={'nets': [{**GLITCH['nets'][0], **patch}]})
    assert response.status_code == 422


def test_timing_dimensions_names_and_aggregate_limits(client):
    for corners in [
        [{'name': 'slow', 'endpoint_slacks_ps': []}],
        [{'name': ' ', 'endpoint_slacks_ps': [0]}],
        [{'name': 'slow', 'endpoint_slacks_ps': [0]}, {'name': ' slow ', 'endpoint_slacks_ps': [0]}],
        [{'name': 'slow', 'endpoint_slacks_ps': [0]}, {'name': 'fast', 'endpoint_slacks_ps': [0, 1]}],
        [{'name': str(i), 'endpoint_slacks_ps': [0] * 10000} for i in range(11)],
    ]:
        assert client.post('/analysis/timing-summary', json={'corners': corners}).status_code == 422
    assert client.post('/analysis/glitch-power', json={'nets': GLITCH['nets'] * 10001}).status_code == 422


@pytest.mark.parametrize('path,body', [
    ('/analysis/ir-drop', {**IR, 'vdd': 1e308}),
    ('/analysis/glitch-power', {**GLITCH, 'clock_period_ns': 1e-320}),
    ('/analysis/glitch-power', {**GLITCH, 'vdd': 1e308}),
    ('/analysis/timing-summary', {'corners': [{'name': 'slow', 'endpoint_slacks_ps': [-1e308] * 3}]}),
])
def test_finite_inputs_that_overflow_return_422(client, path, body):
    response = client.post(path, json=body)
    assert response.status_code == 422, response.text
    assert response.json()['detail'] == 'inputs exceed the supported numerical range'


def test_supported_boundary_inputs_return_finite_outputs(client):
    grid = [[0] * 256 for _ in range(256)]
    response = client.post('/analysis/ir-drop', json={'cell_density': grid, 'switching_activity': grid, 'pdn_strength': [[1] * 256 for _ in range(256)], 'scale': 0})
    assert response.status_code == 200 and response.json()['grid_shape'] == [256, 256]
    assert response.json()['worst_drop_mv'] == 0
    response = client.post('/analysis/timing-summary', json={'corners': [{'name': str(i), 'endpoint_slacks_ps': [0] * 10000} for i in range(10)]})
    assert response.status_code == 200 and response.json()['merged']['total_endpoints'] == 10000
    response = client.post('/analysis/glitch-power', json=GLITCH)
    assert response.status_code == 200 and response.json()['net_count'] == 1
