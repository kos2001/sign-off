import hashlib
import json
import shutil
import sys

import pytest

from app.services.rtl import simulation
from test_rtl_signoff import GOOD_RTL
from test_run_evidence import project, rtl_gate

TB = '''module tb;
  reg src = 0, dst = 0, rst = 1, pulse = 0;
  wire observed;
  integer pulses = 0;
  ibex_pulse_sync dut(src, dst, rst, pulse, observed);
  always #5 src = ~src;
  always #7 dst = ~dst;
  always @(posedge dst) if (observed === 1'b1) pulses = pulses + 1;
  initial begin
    #1 rst = 0;
    #20;
    if (observed !== 1'b0) $fatal(1, "reset output mismatch");
    rst = 1;
    @(negedge src); pulse = 1;
    @(negedge src); pulse = 0;
    #100;
    if (pulses !== 1) $fatal(1, "expected exactly one synchronized pulse");
    $display("SIGNOFF_TEST_PASS");
    $finish;
  end
endmodule
'''


@pytest.fixture
def enabled(monkeypatch):
    if not shutil.which('iverilog') or not shutil.which('vvp'):
        pytest.skip('Icarus required for real simulation checks')
    monkeypatch.setenv('SIGNOFF_SIMULATION_MODE', 'trusted_local')


def test_actual_success_and_evidence(enabled):
    result = simulation.simulate(GOOD_RTL, TB, 'tb')
    assert result['status'] == 'pass', result
    assert result['runtime']['exit_code'] == 0
    assert result['testbench_source'] == TB
    assert result['testbench_sha256'] == hashlib.sha256(TB.encode()).hexdigest()
    assert 'Icarus' in result['tool_version']


@pytest.mark.parametrize('body', [
    '$fatal(1, "bad output");',
    '$error("bad output"); $display("SIGNOFF_TEST_PASS"); $finish;',
    '$display("SIGNOFF_TEST_PASS"); $stop;',
    '$finish;',
    '$display("almost SIGNOFF_TEST_PASS"); $finish;',
    'this is invalid verilog;',
    'assert (0); $display("SIGNOFF_TEST_PASS"); $finish;',
])
def test_false_pass_prevention(enabled, body):
    result = simulation.simulate(GOOD_RTL, 'module tb; initial begin ' + body + ' end endmodule', 'tb')
    assert result['status'] == 'fail', result


def test_timeout_and_output_limit(enabled, monkeypatch):
    monkeypatch.setattr(simulation, 'TIMEOUT_SECONDS', 0.15)
    result = simulation.simulate(GOOD_RTL, 'module tb; initial forever #1; endmodule', 'tb')
    assert result['status'] == 'fail'
    assert 'timed out' in result['detail']
    monkeypatch.setattr(simulation, 'TIMEOUT_SECONDS', 3)
    monkeypatch.setattr(simulation, 'MAX_OUTPUT_BYTES', 1024)
    result = simulation.simulate(GOOD_RTL, 'module tb; initial forever $display("flood"); endmodule', 'tb')
    assert result['status'] == 'fail'
    assert 'output exceeded' in result['detail']
    assert len(result['runtime']['log'].encode()) <= 1024


def test_disabled_and_absent_tools_preserve_inputs(monkeypatch):
    monkeypatch.delenv('SIGNOFF_SIMULATION_MODE', raising=False)
    assert simulation.simulate(GOOD_RTL)['status'] == 'skip'
    result = simulation.simulate(GOOD_RTL, TB, 'tb')
    assert result['status'] == 'skip' and 'disabled' in result['detail']
    assert result['testbench_source'] == TB
    monkeypatch.setenv('SIGNOFF_SIMULATION_MODE', 'trusted_local')
    monkeypatch.setattr(simulation.shutil, 'which', lambda _: None)
    result = simulation.simulate(GOOD_RTL, TB, 'tb')
    assert result['status'] == 'skip' and 'not installed' in result['detail']


@pytest.mark.parametrize('stream', [False, True])
def test_real_api_pass_gate_and_immutable_bench(client, enabled, stream):
    pid = project(client)
    response = client.post('/analysis/rtl-signoff' + ('/stream' if stream else ''), json={
        'code': GOOD_RTL, 'testbench': TB, 'testbench_top': 'tb', 'project_id': pid,
    })
    assert response.status_code == 200
    result = json.loads(response.text.splitlines()[-1])['result'] if stream else response.json()
    assert result['verdict'] == 'SIGNED_OFF', result
    assert rtl_gate(client, pid)['ready']
    original = client.get(f"/runs/{result['run_id']}/evidence").json()
    assert original['result']['simulation'] == result['simulation']
    assert client.patch(f"/runs/{result['run_id']}", json={'status': 'passed', 'metrics': {'simulation': {}}}).status_code == 409
    assert client.get(f"/runs/{result['run_id']}/evidence").json() == original
    if stream:
        events = [json.loads(line) for line in response.text.splitlines()]
        assert {'event': 'stage_start', 'stage': 'simulate'} in events


def test_failure_blocks_gate_and_keeps_logs(client, enabled):
    pid = project(client)
    result = client.post('/analysis/rtl-signoff', json={
        'code': GOOD_RTL, 'testbench': TB.replace('pulses !== 1', 'pulses !== 2'), 'testbench_top': 'tb', 'project_id': pid,
    }).json()
    assert result['verdict'] == 'REJECTED'
    assert 'expected exactly one' in result['simulation']['runtime']['log']
    assert not rtl_gate(client, pid)['ready']


@pytest.mark.parametrize('extra', [
    {'testbench': TB}, {'testbench_top': 'tb'}, {'testbench': ' ', 'testbench_top': 'tb'},
    {'testbench': TB, 'testbench_top': '-o /tmp/injected'},
    {'testbench': TB, 'testbench_top': 'tb\n'},
])
def test_invalid_payload_never_executes(client, monkeypatch, extra):
    def unexpected(*args):
        raise AssertionError('invalid request must not execute')
    monkeypatch.setattr('app.routers.analysis.run_signoff', unexpected)
    response = client.post('/analysis/rtl-signoff', json={'code': GOOD_RTL, **extra})
    assert response.status_code == 422


def test_process_cleanup_on_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr(simulation, 'TIMEOUT_SECONDS', 0.1)
    result = simulation.run_command([sys.executable, '-c', 'import time; time.sleep(20)'], tmp_path)
    assert 'timed out' in result['error']
    assert result['exit_code'] != 0
