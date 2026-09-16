import os
import json
import resource
import subprocess
import sys
import time

import pytest

from app.services.rtl import tools
from app.services.rtl.process import run_command


def test_stdout_stderr_and_exact_output_limit(tmp_path):
    result = run_command([sys.executable, '-c', "import os; os.write(1,b'out'); os.write(2,b'err')"], tmp_path, max_output_bytes=6)
    assert result == {'exit_code': 0, 'log': 'outerr', 'error': None}


def test_output_flood_and_invalid_utf8_are_bounded(tmp_path):
    result = run_command([sys.executable, '-c', "import os\nwhile True: os.write(1,b'\\xff'*8192)"], tmp_path, max_output_bytes=1024)
    assert 'output exceeded' in result['error']
    assert len(result['log'].encode('utf-8')) <= 1024


@pytest.mark.parametrize('inherited_pipe', [False, True])
def test_descendants_terminated_after_parent_exit(tmp_path, inherited_pipe):
    script = f"import subprocess,sys\nchild=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'], stdout={'None' if inherited_pipe else 'subprocess.DEVNULL'}, stderr=subprocess.DEVNULL)\nprint(child.pid, flush=True)"
    result = run_command([sys.executable, '-c', script], tmp_path, timeout_seconds=0.2)
    pid = int(result['log'].strip())
    if inherited_pipe:
        assert 'timed out' in result['error']
    else:
        assert result['exit_code'] == 0 and result['error'] is None
    # A zombie has already stopped executing, even if init has not reaped it.
    deadline = time.monotonic() + 2
    while True:
        status = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True, timeout=1).stdout.strip()
        if not status or status.startswith('Z'):
            break
        if time.monotonic() >= deadline:
            os.kill(pid, 9)
            pytest.fail('tool descendant remained alive')
        time.sleep(0.01)


def fake_tool(tmp_path, monkeypatch, name, body):
    binary = tmp_path / name
    binary.write_text(f'#!{sys.executable}\n' + body + '\n')
    binary.chmod(0o700)
    monkeypatch.setattr(tools, name.upper(), str(binary))


@pytest.mark.parametrize('name,invoke', [('verilator', tools.lint), ('yosys', tools.synthesize)])
@pytest.mark.parametrize('failure', ['timeout', 'output'])
def test_lint_and_synth_fail_on_limits_even_with_success_text(tmp_path, monkeypatch, name, invoke, failure):
    prefix = "print('%Warning-TEST: warning', flush=True)" if name == 'verilator' else "print('3 cells', flush=True)"
    body = 'import time,os\n' + prefix + '\n' + ('time.sleep(30)' if failure == 'timeout' else "os.write(1, b'x'*100000)")
    fake_tool(tmp_path, monkeypatch, name, body)
    monkeypatch.setattr(tools, 'TOOL_TIMEOUT', 0.15 if failure == 'timeout' else 3)
    monkeypatch.setattr(tools, 'MAX_OUTPUT_BYTES', 1024)
    result = invoke('module top; endmodule')
    assert result.available and not result.ok
    assert result.execution['error'] is not None
    assert len(result.execution['log'].encode()) <= 1024
    assert any(('timed out' if failure == 'timeout' else 'output exceeded') in issue for issue in result.issues), result.issues


def test_synthesis_stats_and_lint_diagnostics_survive_bounded_runner(tmp_path, monkeypatch):
    fake_tool(tmp_path, monkeypatch, 'yosys', "print('  3 cells\\n  2 $_DFF_P_\\n  1 $_DLATCH_P_')")
    result = tools.synthesize('module top; endmodule')
    assert result.ok and result.cells == 3 and result.flops == 2 and result.latches == 1
    assert result.execution['exit_code'] == 0
    assert '$_DLATCH_P_' in result.execution['log']
    assert result.execution['command'][1] == '-p'
    fake_tool(tmp_path, monkeypatch, 'verilator', "import sys; print('%Error: bad RTL',file=sys.stderr); sys.exit(1)")
    result = tools.lint('module top; endmodule')
    assert not result.ok and result.issues == ['%Error: bad RTL']
    assert result.execution['exit_code'] == 1
    assert result.execution['log'].strip() == '%Error: bad RTL'
    assert 'design.sv' in result.execution['command']
    from app.services.rtl.analyzer import strict_width_findings
    strict_width_findings('module top; endmodule', result)
    assert result.strict_execution is not None
    assert '-Wno-WIDTHTRUNC' not in result.strict_execution['command']
    assert '-Wno-WIDTHTRUNC' in result.execution['command']


def test_missing_executable_is_a_failure(tmp_path):
    result = run_command([str(tmp_path / 'not-installed')], tmp_path)
    assert result['exit_code'] == 127 and result['error'] == 'tool could not execute'


def test_file_growth_is_limited(tmp_path):
    result = run_command([sys.executable, '-c', "with open('output.bin','wb') as f: f.write(b'x'*8192)"],
                         tmp_path, max_file_bytes=4096)
    assert result['exit_code'] != 0
    assert (tmp_path / 'output.bin').stat().st_size <= 4096


def test_limits_inherited_by_descendants_and_server_unchanged(tmp_path):
    before = {key: resource.getrlimit(key) for key in [resource.RLIMIT_CORE, resource.RLIMIT_CPU, resource.RLIMIT_FSIZE, resource.RLIMIT_NOFILE]}
    child = "import resource,json; print(json.dumps([resource.getrlimit(k) for k in [resource.RLIMIT_CORE,resource.RLIMIT_CPU,resource.RLIMIT_FSIZE,resource.RLIMIT_NOFILE]]))"
    script = f'import subprocess,sys; subprocess.run([sys.executable,"-c",{child!r}],check=True)'
    result = run_command([sys.executable, '-c', script], tmp_path, cpu_seconds=2, max_file_bytes=4096, max_open_files=64)
    assert result['exit_code'] == 0, result
    limits = json.loads(result['log'])
    assert limits[0] == [0, 0]
    assert all(soft == hard and soft <= expected for (soft, hard), expected in zip(limits[1:], [2, 4096, 64]))
    assert {key: resource.getrlimit(key) for key in before} == before


def test_cpu_busy_loop_terminated_before_wall_deadline(tmp_path):
    start = time.monotonic()
    result = run_command([sys.executable, '-c', 'while True: pass'], tmp_path,
                         cpu_seconds=1, timeout_seconds=8)
    assert result['exit_code'] != 0
    assert time.monotonic() - start < 6
    assert 'timed out' not in (result['error'] or '')


@pytest.mark.skipif(not sys.platform.startswith('linux'), reason='RLIMIT_AS is enforced only on Linux')
def test_linux_address_space_limit(tmp_path):
    result = run_command([sys.executable, '-c', 'value = bytearray(256 * 1024 * 1024)'], tmp_path,
                         max_memory_bytes=128 * 1024 * 1024)
    assert result['exit_code'] != 0
    assert 'MemoryError' in result['log']


def test_resource_setup_failure_does_not_execute_tool(monkeypatch, tmp_path, capsys):
    from app.services.rtl import launcher
    executed = []
    monkeypatch.setattr(launcher.os, 'execvp', lambda *args: executed.append(args))
    def fail(*args):
        raise OSError('cannot apply limits')
    monkeypatch.setattr(launcher, 'lower_limit', fail)
    assert launcher.main(['1', '4096', '134217728', '64', 'unused']) == 125
    assert not executed
    assert 'resource setup failed' in capsys.readouterr().err


def test_yosys_legacy_statistics_format_preserves_nonzero_counts(tmp_path, monkeypatch):
    fake_tool(tmp_path, monkeypatch, 'yosys', "print('   Number of cells: 7\\n   $_DFF_P_ 3\\n   $_SDFFE_PP0P_ 2\\n   $_DLATCH_P_ 1\\n   $_NOT_ 1')")
    result = tools.synthesize('module top; endmodule')
    assert result.ok and result.cells == 7 and result.flops == 5 and result.latches == 1
