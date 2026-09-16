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


CROSS_HIERARCHY_LOOP = """
module inv(input a,output y); assign y=~a; endmodule
module gate(input a,input b,output y); assign y=a&b; endmodule
module top(input en,output y);
  wire x;
  inv u(y,x);
  gate v(x,en,y);
endmodule
"""


@pytest.mark.skipif(not tools.yosys_available(), reason='requires Yosys')
@pytest.mark.parametrize('keep', ['none', 'module', 'cell', 'both'])
def test_cross_hierarchy_loop_cannot_be_hidden_by_keep_hierarchy(keep):
    code = CROSS_HIERARCHY_LOOP
    if keep in ('module', 'both'):
        code = code.replace('module inv', '(* keep_hierarchy *) module inv').replace('module gate', '(* keep_hierarchy *) module gate')
    if keep in ('cell', 'both'):
        code = code.replace('inv u', '(* keep_hierarchy *) inv u').replace('gate v', '(* keep_hierarchy *) gate v')
    result = tools.synthesize(code, top_module='top')
    assert not result.ok and result.execution['exit_code'] != 0
    assert 'logic loop' in result.execution['log']
    assert result.cells is None


@pytest.mark.skipif(not tools.yosys_available(), reason='requires Yosys')
def test_registered_feedback_is_allowed_and_hierarchy_restored():
    code = """
(* keep_hierarchy *) module invert(input a,output y); assign y=~a; endmodule
(* keep_hierarchy *) module register(input clk,input d,output reg q);
 always @(posedge clk) q<=d;
endmodule
module top(input clk,output q);
 wire d;
 (* keep_hierarchy *) invert u(q,d);
 (* keep_hierarchy *) register v(clk,d,q);
endmodule
"""
    result = tools.synthesize(code, top_module='top')
    assert result.ok, result.issues
    assert result.cells == 2 and result.flops == 1 and result.latches == 0
    # Read the preserved JSON, not the temporary flattened check's module list.
    log = result.execution['log']
    statistics, _ = json.JSONDecoder().raw_decode(log[log.index('{\n   "creator"'):])
    assert set(statistics['modules']) == {'\\top', '\\invert', '\\register'}
    assert statistics['modules']['\\top']['num_cells_by_type'] == {'invert': 1, 'register': 1}
