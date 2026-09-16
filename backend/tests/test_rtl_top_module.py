import io
import json
import pytest
from app import rtl_worker
from app.services.rtl import tools
from app.services.rtl.signoff import run_signoff, stream_signoff

MULTI_RTL = '''module helper(input logic a, output logic y);
  assign y = ~a;
endmodule
module chip_top(input logic a, output logic y);
  helper u_helper(.a(a), .y(y));
endmodule
'''

@pytest.mark.parametrize('top', ['', 'foo; shell', 'a/b', '-top', 'a b', '\\escaped', '한글', 'a' * 121, True, 12])
def test_invalid_top_rejected_before_execution(client, monkeypatch, top):
    for name in ['run_signoff', 'stream_signoff']:
        monkeypatch.setattr('app.routers.analysis.' + name, lambda *a, **kw: pytest.fail('invalid top executed'))
    for suffix in ['', '/stream']:
        assert client.post('/analysis/rtl-signoff' + suffix, json={'code': MULTI_RTL, 'top_module': top}).status_code == 422

@pytest.mark.skipif(not (tools.verilator_available() and tools.yosys_available()), reason='RTL tools required')
def test_explicit_top_reaches_both_lint_passes_and_synthesis():
    automatic = run_signoff(MULTI_RTL).to_dict()
    assert automatic['module'] == 'helper' and automatic['top_module_requested'] is None
    for result in [run_signoff(MULTI_RTL, top_module='chip_top').to_dict(), list(stream_signoff(MULTI_RTL, top_module='chip_top'))[-1]['result']]:
        assert result['module'] == result['top_module_requested'] == 'chip_top'
        assert result['verdict'] == 'CONDITIONAL'
        for kind in ['lint', 'width']:
            record = result['tool_runs'][kind]
            assert record['command'][-2:] == ['--top-module', 'chip_top']
            assert record['exit_code'] == 0
        assert 'hierarchy -top chip_top;' in result['tool_runs']['synthesize']['command'][-1]
        assert result['tool_runs']['synthesize']['exit_code'] == 0
    missing = run_signoff(MULTI_RTL, top_module='absent').to_dict()
    assert missing['verdict'] == 'REJECTED'
    assert missing['tool_runs']['lint']['exit_code'] != 0
    assert missing['tool_runs']['synthesize']['exit_code'] != 0


def test_saved_result_preserves_selection_and_source_identity(client):
    pid = client.post('/projects', json={'name': 'top QA', 'foundry': 'QA', 'process_node': '5nm'}).json()['id']
    hashes = []
    for suffix, top in [('', 'helper'), ('/stream', 'chip_top')]:
        response = client.post('/analysis/rtl-signoff' + suffix, json={'project_id': pid, 'code': MULTI_RTL, 'top_module': top})
        assert response.status_code == 200
        result = json.loads(response.text.splitlines()[-1])['result'] if suffix else response.json()
        evidence = client.get(f"/runs/{result['run_id']}/evidence").json()
        assert result['module'] == evidence['result']['module'] == top
        assert evidence['result']['top_module_requested'] == top
        hashes.append(evidence['source_sha256'])
    assert hashes[0] == hashes[1]


def test_worker_forwards_design_top_separately_from_testbench(monkeypatch):
    received = []
    def fake(code, testbench, testbench_top, **options):
        received.append((code, testbench, testbench_top, options))
        yield {'event': 'result', 'result': {}}
    monkeypatch.setattr(rtl_worker, 'stream_signoff', fake)
    payload = {'protocol': rtl_worker.PROTOCOL, 'request': {'code': MULTI_RTL, 'top_module': 'chip_top'}}
    assert rtl_worker.main(io.BytesIO(json.dumps(payload).encode()), io.StringIO(), io.StringIO()) == 0
    assert received == [(MULTI_RTL, None, None, {'top_module': 'chip_top'})]
