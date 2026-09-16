"""Real synthesis checks: elaboration success alone is not structural validity."""
import json
import pytest
from app.services.rtl import tools

INVALID_DESIGNS = {
    'undefined': ('module top(input a, output y); missing u(a,y); endmodule', 'not part of the design'),
    'blackbox': ('(* blackbox *) module macro(input a,output y); endmodule\nmodule top(input a,output y); macro u(a,y); endmodule', 'blackbox'),
    'undriven': ('module top(input a,output y); wire x; assign y=x & a; endmodule', 'no driver'),
    'loop': ('module top(input a,output y); wire x; assign x=~y; assign y=x&a; endmodule', 'logic loop'),
    'drivers': ('module top(input clk,input a,input b,output reg y); always @(posedge clk) y<=a; always @(negedge clk) y<=b; endmodule', 'conflicting drivers'),
}


@pytest.mark.skipif(not tools.yosys_available(), reason='requires Yosys')
@pytest.mark.parametrize('case', INVALID_DESIGNS)
def test_real_synthesis_rejects_invalid_structure(case):
    code, diagnostic = INVALID_DESIGNS[case]
    result = tools.synthesize(code, top_module='top')
    assert not result.ok and result.available
    assert result.execution['exit_code'] != 0
    assert diagnostic in result.execution['log'], result.execution['log']
    assert result.cells is result.flops is result.latches is None
    assert result.issues


@pytest.mark.skipif(not tools.yosys_available(), reason='requires Yosys')
def test_unused_blackbox_outside_selected_hierarchy_is_allowed():
    result = tools.synthesize('(* blackbox *) module macro(input a,output y); endmodule\n'
                              'module top(input a,output y); assign y=~a; endmodule', top_module='top')
    assert result.ok and result.cells == 1, result.issues


@pytest.mark.skipif(not (tools.yosys_available() and tools.verilator_available()), reason='requires RTL tools')
@pytest.mark.parametrize('streaming', [False, True])
def test_failed_structure_is_saved_as_failed_synthesis_evidence(client, streaming):
    pid = client.post('/projects', json={'name': f'structure QA {streaming}', 'foundry': 'QA', 'process_node': '5nm'}).json()['id']
    response = client.post('/analysis/rtl-signoff' + ('/stream' if streaming else ''),
                           json={'project_id': pid, 'code': INVALID_DESIGNS['undriven'][0], 'top_module': 'top'})
    assert response.status_code == 200, response.text
    result = json.loads(response.text.splitlines()[-1])['result'] if streaming else response.json()
    assert result['verdict'] == 'REJECTED'
    synth = next(s for s in result['stages'] if s['name'] == 'synthesize')
    assert synth['status'] == 'fail' and 'cells=unknown' in synth['detail']
    evidence = client.get(f"/runs/{result['run_id']}/evidence").json()
    assert evidence['result']['stages'] == result['stages']
    assert evidence['result']['tool_runs'] == result['tool_runs']
    assert 'no driver' in evidence['result']['tool_runs']['synthesize']['log']
