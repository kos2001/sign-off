import pytest
from app.services.marker_geometry import marker_geometry
from test_auth import accounts
from test_klayout_import import payload


def test_real_edge_pair_preview_preserves_aspect_and_y_direction():
    geometry = marker_geometry(['edge-pair: (0,0;0,0.1)/(0.1,0.1;0.1,0)'])
    assert geometry['bounds_um'] == {'xmin': '0', 'xmax': '0.1', 'ymin': '0', 'ymax': '0.1'}
    assert geometry['shapes'][0]['contours'] == [[[10, 190], [10, 10]], [[190, 10], [190, 190]]]
    assert not geometry['shapes'][0]['closed']


def test_box_polygon_holes_and_degenerate_geometry():
    box = marker_geometry(['box: (0,0;2,1)'])
    assert box['shapes'][0]['contours'][0] == [[10,145],[190,145],[190,55],[10,55]]
    holes = marker_geometry(['polygon: (0,0;4,0;4,4;0,4/1,1;2,1;2,2)'])
    assert holes['shapes'][0]['closed'] and len(holes['shapes'][0]['contours']) == 2
    point = marker_geometry(['edge: (1,1;1,1)'])
    assert point['shapes'][0]['contours'] == [[[100,100],[100,100]]]


def test_decimal_subtraction_preserves_small_shape_at_large_origin():
    geometry = marker_geometry(['edge: (1000000000000,0;999999999999.999,0)'])
    assert geometry['shapes'][0]['contours'] == [[[190,100],[10,100]]]
    assert geometry['bounds_um']['xmin'] == '999999999999.999'


@pytest.mark.parametrize('value', ["text: 'keep original'", 'path: (0,0;1,1) w=1', 'box: (nan,0;1,1)', 'edge: (1e9999,0;0,0)', 'edge: (1e-400,0;0,0)', 'edge: (1e13,0;0,0)', 'polygon: (0,0;1,1)', 'edge-pair: (0,0)/(1,1)'])
def test_unsupported_values_are_counted_without_inventing_geometry(value):
    geometry = marker_geometry([value, 'edge: (0,0;1,0)'])
    assert geometry['unrendered_values'] == [1]
    assert geometry['rendered_values'] == 1 and geometry['shapes'][0]['value_index'] == 2


def test_point_budget_does_not_silently_truncate_polygon():
    geometry = marker_geometry(['polygon: ('+';'.join(f'{i},0' for i in range(2001))+')'])
    assert geometry['shapes'] == [] and geometry['unrendered_values'] == [1]


def test_marker_api_filters_paging_details_and_permissions(accounts):
    _, ids, login = accounts
    editor, viewer, outsider = login('editor'), login('viewer'), login('outsider')
    items = ''.join(f'<item><category>{"Width" if i%2 else "Spacing"}</category><cell>{"" if i == 0 else "BLOCK"}</cell><multiplicity>{i+1}</multiplicity><values><value>box: ({i},0;{i+1},1)</value></values><comment>Literal %_ text</comment></item>' for i in range(27))
    source = f'<report-database><items>{items}</items></report-database>'
    response = editor.post(f"/projects/{ids['project']}/imports/klayout", json=payload(source))
    assert response.status_code == 201
    rid = response.json()['id']
    endpoint = f'/runs/{rid}/markers'
    first = viewer.get(endpoint).json()
    second = viewer.get(endpoint+'?offset=25').json()
    assert first['total'] == 27 and first['matched_multiplicity'] == sum(range(1,28))
    assert [item['index'] for item in first['items']+second['items']] == list(range(1,28))
    assert 'values' not in first['items'][0]
    assert viewer.get(endpoint, params={'category':'Width'}).json()['total'] == 13
    assert viewer.get(endpoint, params={'cell':''}).json()['total'] == 1
    assert viewer.get(endpoint, params={'q':'%_ TEXT'}).json()['total'] == 27
    assert viewer.get(endpoint, params={'q':'absent'}).json()['items'] == []
    detail = viewer.get(endpoint+'/1').json()
    assert detail['item']['cell'] == '' and detail['geometry']['rendered_values'] == 1
    assert detail['item']['values'] == ['box: (0,0;1,1)']
    assert viewer.get(endpoint+'/28').status_code == 404
    assert viewer.get(endpoint+'/1001').status_code == 422
    assert outsider.get(endpoint).status_code == 404
    assert outsider.get(endpoint+'/1').status_code == 404
    assert viewer.get(f"/runs/{ids['run']}/markers").status_code == 409
    assert viewer.get(f'/runs/{rid}/evidence/source').content == source.encode()
