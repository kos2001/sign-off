"""Require installed RTL binaries, then run Linux integration regressions."""
import shutil
import subprocess
import sys


def main():
    if sys.platform != 'linux':
        print('This check requires Linux.', file=sys.stderr)
        return 1
    for name, argument in [('iverilog', '-V'), ('vvp', '-V'), ('verilator', '--version'), ('yosys', '-V')]:
        if shutil.which(name) is None:
            print(f'Required RTL tool is missing: {name}', file=sys.stderr)
            return 1
        version = subprocess.run([name, argument], capture_output=True, text=True, timeout=15)
        if version.returncode:
            print(f'Required RTL tool failed its version check: {name}', file=sys.stderr)
            return 1
        print(next((line for line in (version.stdout + version.stderr).splitlines() if line.strip()), name), flush=True)
    return subprocess.call([sys.executable, '-m', 'pytest', '-ra', '-p', 'no:cacheprovider',
                            'tests/test_rtl_process.py', 'tests/test_rtl_simulation.py',
                            'tests/test_rtl_signoff.py', 'tests/test_rtl_admission.py'])


if __name__ == '__main__':
    sys.exit(main())
