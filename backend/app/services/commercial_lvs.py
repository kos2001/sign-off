"""Strict exchange format for commercial layout-versus-schematic results."""

import hashlib
import json

from .report_import import reject_constant, unique_object

FORMAT = 'signoff/commercial-lvs/v1'
PARSER = 'commercial-lvs-json/v1'
TOOLS = {'Siemens Calibre nmLVS', 'Cadence Pegasus LVS'}
KINDS = {'open', 'short', 'missing_device', 'extra_device', 'device_mismatch',
         'port_mismatch', 'property_mismatch'}


def text(value, label, limit, *, optional=False):
    if value is None and optional:
        return None
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or len(value) > limit or any(ord(char) < 32 for char in value)):
        raise ValueError(f'{label}: invalid text')
    return value


def count(value, label):
    if type(value) is not int or not 0 <= value <= 10**12:
        raise ValueError(f'{label}: invalid count')
    return value


def parse_commercial_lvs(source: str) -> dict:
    raw = source.encode()
    if len(raw) > 2_000_000:
        raise ValueError('report exceeds 2 MB')
    try:
        document = json.loads(source.removeprefix('\ufeff'), object_pairs_hook=unique_object,
                              parse_constant=reject_constant)
    except (ValueError, RecursionError):
        raise ValueError('invalid JSON report (check syntax, duplicate fields and finite numbers)') from None
    if not isinstance(document, dict) or document.get('format') != FORMAT:
        raise ValueError(f'expected {FORMAT} report')
    tool = document.get('tool')
    if tool not in TOOLS:
        raise ValueError('tool must be Siemens Calibre nmLVS or Cadence Pegasus LVS')
    version = text(document.get('tool_version'), 'tool_version', 80)
    layout_top = text(document.get('layout_top'), 'layout_top', 200)
    schematic_top = text(document.get('schematic_top'), 'schematic_top', 200)
    verdict = document.get('status')
    if verdict not in {'matched', 'mismatched', 'error'}:
        raise ValueError('status must be matched, mismatched or error')
    summary = document.get('summary')
    if not isinstance(summary, dict) or set(summary) != {
        'layout_devices', 'schematic_devices', 'layout_nets', 'schematic_nets',
    }:
        raise ValueError('summary must contain the exact LVS count fields')
    normalized_summary = {key: count(summary[key], f'summary.{key}') for key in summary}
    rows = document.get('mismatches')
    if not isinstance(rows, list) or len(rows) > 5000:
        raise ValueError('mismatches must contain at most 5000 entries')
    items = []
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f'mismatch {index}: expected an object')
        kind = row.get('kind')
        if kind not in KINDS:
            raise ValueError(f'mismatch {index}: unsupported kind')
        severity = row.get('severity')
        if severity not in {'error', 'critical'}:
            raise ValueError(f'mismatch {index}: severity must be error or critical')
        name = text(row.get('name'), f'mismatch {index} name', 500)
        layout_object = text(row.get('layout_object'), f'mismatch {index} layout_object', 500, optional=True)
        schematic_object = text(row.get('schematic_object'), f'mismatch {index} schematic_object', 500, optional=True)
        message = text(row.get('message'), f'mismatch {index} message', 2000)
        identity = {'kind': kind, 'name': name, 'layout_object': layout_object,
                    'schematic_object': schematic_object}
        items.append({'index': index, **identity, 'severity': severity, 'message': message,
                      'fingerprint': hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()})
    error_message = text(document.get('error_message'), 'error_message', 2000,
                         optional=verdict != 'error')
    if verdict == 'matched' and items:
        raise ValueError('matched LVS result cannot contain mismatches')
    if verdict == 'mismatched' and not items:
        raise ValueError('mismatched LVS result must contain at least one mismatch')
    if verdict != 'error' and document.get('error_message') is not None:
        raise ValueError('error_message is only valid for an error result')
    metrics = {**normalized_summary, 'reported_mismatches': len(items),
               **{f'{kind}_mismatches': sum(item['kind'] == kind for item in items) for kind in sorted(KINDS)}}
    return {'parser': PARSER, 'tool': tool, 'tool_version': version,
            'layout_top': layout_top, 'schematic_top': schematic_top, 'lvs_status': verdict,
            'error_message': error_message, 'summary': normalized_summary, 'items': items,
            'metrics': metrics, 'source_sha256': hashlib.sha256(raw).hexdigest(),
            'coverage': 'reported_lvs_result_only',
            'coverage_note': 'Submitted LVS result only; complete decks, inputs, hierarchy and tool execution are not established.',
            'status': 'failed' if verdict != 'matched' else 'incomplete'}
