#!/usr/bin/env python3
"""Create a server-ready commercial report import request without exposing the signing secret."""

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from app.services.collector_request import PARSERS, build_import_request
from app.services.report_import import unique_object


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description='Validate a commercial EDA report and sign its coverage request.')
    value.add_argument('--domain', required=True, choices=sorted(PARSERS))
    value.add_argument('--report', required=True, type=Path)
    value.add_argument('--claims-file', required=True, type=Path)
    value.add_argument('--project-id', required=True, type=int)
    value.add_argument('--stage', required=True, choices=['rtl', 'synthesis', 'placement', 'routing', 'final'])
    value.add_argument('--design-revision', required=True)
    value.add_argument('--scenario', required=True)
    value.add_argument('--scenario-plan-version', type=int,
                       help='Required for STA after a versioned scenario plan is configured.')
    value.add_argument('--tool-version', required=True)
    value.add_argument('--key-id', required=True)
    value.add_argument('--secret-env', default='SIGNOFF_COLLECTOR_HMAC_SECRET')
    value.add_argument('--valid-for-seconds', type=int, default=3600)
    value.add_argument('--import-id')
    value.add_argument('--output', type=Path, help='Publish atomically as this new 0600 file; omit for stdout.')
    return value


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', args.secret_env):
            raise ValueError('secret environment variable name is invalid')
        secret = os.environ.get(args.secret_env)
        if secret is None:
            raise ValueError(f'{args.secret_env} is not set')
        source_text = args.report.read_bytes().decode('utf-8')
        claims = json.loads(args.claims_file.read_text(encoding='utf-8'), object_pairs_hook=unique_object)
        body = build_import_request(
            domain=args.domain, source_text=source_text, filename=args.report.name,
            project_id=args.project_id, stage=args.stage, design_revision=args.design_revision,
            scenario=args.scenario, tool_version=args.tool_version, key_id=args.key_id,
            secret=secret, claims=claims, valid_for_seconds=args.valid_for_seconds,
            import_id=args.import_id,
            scenario_plan_version=args.scenario_plan_version,
        )
        encoded = (json.dumps(body, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode()
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                descriptor, temporary = tempfile.mkstemp(prefix=f'.{args.output.name}.', dir=args.output.parent)
                os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, 'wb') as target:
                    target.write(encoded)
                    target.flush()
                    os.fsync(target.fileno())
                os.link(temporary, args.output)
            finally:
                if temporary:
                    try:
                        os.unlink(temporary)
                    except FileNotFoundError:
                        pass
        else:
            sys.stdout.buffer.write(encoded)
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f'collector request failed: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
