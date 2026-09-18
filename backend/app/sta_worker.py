"""One isolated OpenSTA job over bounded JSON input and JSON output."""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

PROTOCOL = 'signoff/sta-worker/v1'
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
OPENSTA_COMMIT = 'd97587f669b4f169be7132346df70e7d634500c3'


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError()
        envelope = json.loads(raw)
        if set(envelope) != {'protocol', 'request'} or envelope['protocol'] != PROTOCOL:
            raise ValueError()
        request = envelope['request']
        if set(request) != {'netlist', 'liberty', 'sdc', 'top_module'}:
            raise ValueError()
        top = request['top_module']
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*', top):
            raise ValueError()
        limits = {'netlist': 1_000_000, 'liberty': 5_000_000, 'sdc': 500_000}
        if any(not isinstance(request[key], str) or not request[key].strip() or
               len(request[key].encode()) > limits[key] for key in limits):
            raise ValueError()
    except (ValueError, TypeError, KeyError, UnicodeError, json.JSONDecodeError):
        print('Invalid STA worker request.', file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory() as directory:
        paths = {key: os.path.join(directory, {'netlist': 'design.v', 'liberty': 'library.lib', 'sdc': 'constraints.sdc'}[key]) for key in limits}
        for key, path in paths.items():
            with open(path, 'w', encoding='utf-8') as stream:
                stream.write(request[key])
        report = os.path.join(directory, 'report.json')
        script = os.path.join(directory, 'run.tcl')
        # Disable general-purpose Tcl access before the user-supplied SDC is read.
        # OpenSTA's own read_* commands continue to use fixed worker paths.
        commands = [
            'foreach cmd {exec socket load} { if {[llength [info commands $cmd]]} { rename $cmd {} } }',
            f'read_liberty {{{paths["liberty"]}}}',
            f'read_verilog {{{paths["netlist"]}}}',
            f'link_design {{{top}}}',
            f'read_sdc {{{paths["sdc"]}}}',
            f'report_checks -unconstrained -group_path_count 100 -endpoint_path_count 10 -format json > {{{report}}}',
        ]
        with open(script, 'w', encoding='utf-8') as stream:
            stream.write('\n'.join(commands) + '\n')
        try:
            completed = subprocess.run(['/OpenSTA/build/sta', '-no_splash', '-exit', script],
                                       capture_output=True, text=True, timeout=240)
        except (OSError, subprocess.TimeoutExpired):
            print('OpenSTA execution failed.', file=sys.stderr)
            return 1
        log = (completed.stdout + completed.stderr)[-131072:]
        if completed.returncode or not os.path.isfile(report):
            print(log or 'OpenSTA execution failed.', file=sys.stderr)
            return 1
        try:
            report_text = open(report, encoding='utf-8').read(MAX_OUTPUT_BYTES + 1)
            if len(report_text.encode()) > MAX_OUTPUT_BYTES:
                raise ValueError()
            json.loads(report_text)
        except (OSError, ValueError, UnicodeError, json.JSONDecodeError):
            print('OpenSTA produced an invalid report.', file=sys.stderr)
            return 1
        result = {'protocol': PROTOCOL, 'report': report_text, 'log': log,
                  'opensta_commit': OPENSTA_COMMIT,
                  'inputs': {key: {'sha256': digest(request[key]), 'byte_length': len(request[key].encode())} for key in limits}}
        output = json.dumps(result, ensure_ascii=False, allow_nan=False).encode()
        if len(output) > MAX_OUTPUT_BYTES:
            print('STA worker output limit exceeded.', file=sys.stderr)
            return 1
        sys.stdout.buffer.write(output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
