"""Apply per-process Unix limits before exec; deliberately not a sandbox.

Executed as an isolated Python script, avoiding preexec_fn in threaded servers.
"""
import os
import resource
import sys


def lower_limit(kind, requested):
    soft, hard = resource.getrlimit(kind)
    finite = [value for value in (soft, hard, requested) if value != resource.RLIM_INFINITY]
    ceiling = min(finite)
    resource.setrlimit(kind, (ceiling, ceiling))


def main(argv):
    try:
        cpu, file_bytes, memory_bytes, files = map(int, argv[:4])
        if min(cpu, file_bytes, memory_bytes, files) <= 0 or len(argv) < 5:
            raise ValueError('invalid limits')
        lower_limit(resource.RLIMIT_CORE, 0)
        lower_limit(resource.RLIMIT_CPU, cpu)
        lower_limit(resource.RLIMIT_FSIZE, file_bytes)
        lower_limit(resource.RLIMIT_NOFILE, files)
        # macOS does not provide the Linux RLIMIT_AS enforcement contract.
        if sys.platform.startswith('linux'):
            lower_limit(resource.RLIMIT_AS, memory_bytes)
    except (OSError, ValueError) as error:
        print(f'Sign-off resource setup failed: {type(error).__name__}', file=sys.stderr)
        return 125
    try:
        os.execvp(argv[4], argv[4:])
    except OSError as error:
        print(f'Sign-off tool could not execute: {type(error).__name__}', file=sys.stderr)
        return 127


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
