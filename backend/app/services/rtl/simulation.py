"""Bounded Icarus execution for explicitly enabled, trusted local deployments.

This runner is not an OS sandbox. Never enable it for untrusted HDL submissions.
"""

import hashlib
import os
from pathlib import Path
import re
import shutil
import tempfile

from .tools import strip_fences
from .process import run_command as bounded_command

TIMEOUT_SECONDS = 30
MAX_OUTPUT_BYTES = 128 * 1024
PASS_MARKER = 'SIGNOFF_TEST_PASS'


def normalized_source(source):
    return strip_fences(source) + '\n'


def run_command(command, cwd):
    return bounded_command(command, cwd, timeout_seconds=TIMEOUT_SECONDS, max_output_bytes=MAX_OUTPUT_BYTES)


def simulate(code, testbench=None, top=None):
    result = {'status': 'skip', 'detail': 'no testbench available', 'engine': 'iverilog/vvp',
              'testbench_source': None, 'testbench_sha256': None, 'top': top}
    if testbench is None:
        return result
    source = normalized_source(testbench)
    result.update(testbench_source=source, testbench_sha256=hashlib.sha256(source.encode()).hexdigest())
    if not source.strip() or not top or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*', top) is None:
        result.update(status='fail', detail='testbench source and a valid explicit top module are required')
        return result
    if os.environ.get('SIGNOFF_SIMULATION_MODE') != 'trusted_local':
        result['detail'] = 'testbench execution is disabled on this server'
        return result
    if not shutil.which('iverilog') or not shutil.which('vvp'):
        result['detail'] = 'iverilog or vvp is not installed'
        return result
    with tempfile.TemporaryDirectory(prefix='signoff-simulation-') as directory:
        Path(directory, 'design.sv').write_text(normalized_source(code), encoding='utf-8')
        Path(directory, 'testbench.sv').write_text(source, encoding='utf-8')
        result['tool_version'] = run_command(['iverilog', '-V'], directory)['log'][:2048]
        compiled = run_command(['iverilog', '-g2012', '-s', top, '-o', 'simulation.vvp', 'design.sv', 'testbench.sv'], directory)
        result['compile'] = compiled
        if compiled['error'] or compiled['exit_code'] != 0:
            result.update(status='fail', detail=compiled['error'] or 'testbench compilation failed')
            return result
        executed = run_command(['vvp', '-N', 'simulation.vvp'], directory)
        result['runtime'] = executed
    error_lines = re.search(r'^\s*(ERROR|FATAL):', executed['log'], flags=re.MULTILINE)
    if executed['error'] or executed['exit_code'] != 0 or error_lines:
        result.update(status='fail', detail=executed['error'] or 'testbench reported a failure')
    elif PASS_MARKER not in executed['log'].splitlines():
        result.update(status='fail', detail=f'testbench ended without the required {PASS_MARKER} completion marker')
    else:
        result.update(status='pass', detail='testbench completed with explicit success marker and no reported errors')
    return result
