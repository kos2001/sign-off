"""Portable signoff-decision ledger verification using only the Python standard library."""

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

FORMAT = 'signoff/release-decision-ledger/v1'
SHA256 = re.compile(r'^[0-9a-f]{64}$')
STAGES = {'rtl', 'synthesis', 'placement', 'routing', 'final'}
BASE_FIELDS = {
    'project_id', 'stage', 'decision', 'reason', 'design_revision', 'decided_by',
    'decided_by_user_id', 'manifest_sha256', 'package_sha256', 'byte_length', 'created_at',
}
OPTIONAL_DIGEST_FIELDS = {'gate_snapshot_sha256', 'evidence_snapshot_sha256'}
CHAIN_FIELDS = {'chain_version', 'previous_decision_sha256'}
OPTIONAL_SIGNED_FIELDS = {'credential_confirmed_at'}


def canonical_digest(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True,
                         separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def decision_payload(item: dict) -> dict:
    payload = {field: item[field] for field in BASE_FIELDS}
    for field in OPTIONAL_DIGEST_FIELDS:
        if item.get(field) is not None:
            payload[field] = item[field]
    if item.get('chain_version') is not None:
        payload['chain_version'] = item['chain_version']
        payload['previous_decision_sha256'] = item.get('previous_decision_sha256')
    if item.get('credential_confirmed_at') is not None:
        payload['credential_confirmed_at'] = item['credential_confirmed_at']
    return payload


def _digest(value, field, *, nullable=False):
    if nullable and value is None:
        return
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise ValueError(f'{field} must be a lowercase SHA-256 digest')


def verify_ledger(ledger: dict, expected_head: str | None = None) -> dict:
    if not isinstance(ledger, dict) or ledger.get('format') != FORMAT:
        raise ValueError('unsupported release decision ledger format')
    if type(ledger.get('project_id')) is not int or ledger['project_id'] < 1:
        raise ValueError('ledger project_id must be a positive integer')
    decisions = ledger.get('decisions')
    if not isinstance(decisions, list):
        raise ValueError('ledger decisions must be an array')
    try:
        exported_at = datetime.fromisoformat(ledger['exported_at'])
        if exported_at.utcoffset() is None:
            raise ValueError()
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError('ledger exported_at must include a timezone') from error
    head = ledger.get('chain_head_sha256')
    _digest(head, 'chain_head_sha256', nullable=True)
    if expected_head is not None:
        _digest(expected_head, 'expected_head')
        if head != expected_head:
            raise ValueError('ledger head does not match the externally retained head')
    previous = None
    previous_id = 0
    legacy_count = 0
    chain_count = 0
    chain_started = False
    for index, item in enumerate(decisions):
        if not isinstance(item, dict):
            raise ValueError(f'decision at index {index} must be an object')
        allowed = BASE_FIELDS | OPTIONAL_DIGEST_FIELDS | OPTIONAL_SIGNED_FIELDS | CHAIN_FIELDS | {'id', 'decision_sha256'}
        if set(item) - allowed:
            raise ValueError(f'decision at index {index} contains unsigned fields')
        decision_id = item.get('id')
        if type(decision_id) is not int or decision_id <= previous_id:
            raise ValueError('decision ids must be positive and strictly increasing')
        if item.get('project_id') != ledger['project_id']:
            raise ValueError(f'decision #{decision_id} belongs to another project')
        if item.get('stage') not in STAGES or item.get('decision') not in {'approved', 'rejected'}:
            raise ValueError(f'decision #{decision_id} has an invalid stage or decision')
        if not isinstance(item.get('reason'), str) or not isinstance(item.get('decided_by'), str):
            raise ValueError(f'decision #{decision_id} has invalid human decision fields')
        if type(item.get('byte_length')) is not int or item['byte_length'] < 1:
            raise ValueError(f'decision #{decision_id} byte_length must be a positive integer')
        _digest(item.get('decision_sha256'), f'decision #{decision_id} decision_sha256')
        for field in ('manifest_sha256', 'package_sha256'):
            _digest(item.get(field), f'decision #{decision_id} {field}')
        for field in OPTIONAL_DIGEST_FIELDS:
            if field in item:
                _digest(item[field], f'decision #{decision_id} {field}')
        try:
            created_at = datetime.fromisoformat(item['created_at'])
            if created_at.utcoffset() is None:
                raise ValueError()
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f'decision #{decision_id} created_at must include a timezone') from error
        normalized = dict(item)
        normalized['created_at'] = created_at.astimezone(timezone.utc).isoformat()
        if item.get('credential_confirmed_at') is not None:
            try:
                confirmed_at = datetime.fromisoformat(item['credential_confirmed_at'])
                if confirmed_at.utcoffset() is None:
                    raise ValueError()
            except (TypeError, ValueError) as error:
                raise ValueError(f'decision #{decision_id} credential_confirmed_at must include a timezone') from error
            normalized['credential_confirmed_at'] = confirmed_at.astimezone(timezone.utc).isoformat()
        try:
            actual = canonical_digest(decision_payload(normalized))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f'decision #{decision_id} has invalid signed fields') from error
        if actual != item['decision_sha256']:
            raise ValueError(f'decision #{decision_id} digest mismatch')
        chain_version = item.get('chain_version')
        if chain_version is None:
            if chain_started:
                raise ValueError(f'decision #{decision_id} is missing a chain version')
            legacy_count += 1
        else:
            _digest(item.get('previous_decision_sha256'),
                    f'decision #{decision_id} previous_decision_sha256', nullable=True)
            if chain_version != 1 or item.get('previous_decision_sha256') != previous:
                raise ValueError(f'decision #{decision_id} previous link mismatch')
            chain_started = True
            chain_count += 1
        previous = item['decision_sha256']
        previous_id = decision_id
    if head != (previous if chain_started else None):
        raise ValueError('ledger chain head mismatch')
    return {
        'status': 'verified', 'project_id': ledger['project_id'],
        'decision_count': len(decisions), 'legacy_decision_count': legacy_count,
        'chained_decision_count': chain_count, 'chain_head_sha256': head,
    }


def _load(path: Path) -> dict:
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('release decision ledger exceeds 16 MiB')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('release decision ledger contains duplicate fields')
            result[key] = value
        return result
    try:
        return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError('non-finite number')))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('release decision ledger is not valid UTF-8 JSON') from error


def main(argv=None):
    parser = argparse.ArgumentParser(description='Verify a portable Sign-off Hub decision ledger')
    parser.add_argument('verify', choices=['verify'])
    parser.add_argument('--ledger', required=True, type=Path)
    parser.add_argument('--expected-head')
    args = parser.parse_args(argv)
    try:
        result = verify_ledger(_load(args.ledger), args.expected_head)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
