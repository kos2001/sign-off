"""Strict exchange format for commercial power-analysis summaries."""
import hashlib
import json
import math
from decimal import Decimal

from .report_import import JsonNumberRangeError, finite_json_float, reject_constant, unique_object

FORMAT = 'signoff/commercial-power/v1'
PARSER = 'commercial-power-json/v1'
TOOLS = {'Synopsys PrimePower', 'Cadence Joules', 'Ansys PowerArtist'}
FACTORS = {'W': Decimal('1000'), 'mW': Decimal('1'), 'uW': Decimal('0.001')}


def parse_commercial_power(source: str) -> dict:
    raw = source.encode('utf-8')
    if len(raw) > 2_000_000:
        raise ValueError('report exceeds 2 MB')
    try:
        document = json.loads(source.removeprefix('\ufeff'), object_pairs_hook=unique_object,
                              parse_constant=reject_constant, parse_float=finite_json_float)
    except JsonNumberRangeError:
        raise ValueError('JSON number outside the supported floating-point range; check report units and values') from None
    except (ValueError, RecursionError):
        raise ValueError('invalid JSON report (check syntax, duplicate fields and finite numbers)') from None
    if not isinstance(document, dict) or document.get('format') != FORMAT:
        raise ValueError(f'expected {FORMAT} report')
    tool = document.get('tool')
    if tool not in TOOLS:
        raise ValueError('unsupported commercial power tool')
    version = clean_text(document.get('tool_version'), 'tool_version', 80)
    if version != version.strip():
        raise ValueError('tool_version must not have surrounding whitespace')
    unit = document.get('power_unit')
    if unit not in FACTORS:
        raise ValueError('power_unit must be W, mW or uW')
    limit = document.get('glitch_share_limit')
    if type(limit) not in (int, float) or (type(limit) is float and not math.isfinite(limit)) or not 0 <= limit <= 1:
        raise ValueError('glitch_share_limit must be between 0 and 1')
    top = breakdown(document.get('summary'), FACTORS[unit], 'summary', path='TOP')
    rows = document.get('hierarchy')
    if not isinstance(rows, list) or len(rows) > 5000:
        raise ValueError('hierarchy must contain at most 5000 entries')
    items, paths = [], set()
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f'hierarchy {index}: expected an object')
        path = clean_text(row.get('path'), f'hierarchy {index} path', 1000)
        if path in paths:
            raise ValueError(f'hierarchy {index}: duplicate path')
        paths.add(path)
        item = breakdown(row, FACTORS[unit], f'hierarchy {index}', path=path)
        identity = {'path': path}
        item.update(index=index, fingerprint=hashlib.sha256(json.dumps(identity, sort_keys=True,
                    ensure_ascii=False).encode()).hexdigest(), violated=item['glitch_share'] > limit)
        items.append(item)
    top['violated'] = top['glitch_share'] > limit
    return {'parser': PARSER, 'tool': tool, 'tool_version': version, 'power_unit': unit,
            'glitch_share_limit': float(limit), 'coverage': 'reported_power_only',
            'coverage_note': 'Submitted summary only; complete vectors, activity coverage, libraries, parasitics and modes are not established.',
            'source_sha256': hashlib.sha256(raw).hexdigest(),
            'status': 'failed' if top['violated'] or any(item['violated'] for item in items) else 'incomplete',
            'metrics': {'total_power_mw': top['total_power_mw'], 'internal_power_mw': top['internal_power_mw'],
                        'switching_power_mw': top['switching_power_mw'], 'leakage_power_mw': top['leakage_power_mw'],
                        'glitch_power_mw': top['glitch_power_mw'], 'glitch_share': top['glitch_share'],
                        'reported_hierarchy_rows': len(items), 'violating_hierarchy_rows': sum(item['violated'] for item in items)},
            'summary': top, 'items': items}


def breakdown(value, factor, label, *, path):
    if not isinstance(value, dict):
        raise ValueError(f'{label}: expected an object')
    fields = {name: power(value.get(name), factor, f'{label} {name}') for name in
              ['total_power', 'internal_power', 'switching_power', 'leakage_power', 'glitch_power']}
    total, component_sum = fields['total_power'], fields['internal_power'] + fields['switching_power'] + fields['leakage_power']
    tolerance = max(Decimal('1e-9'), total * Decimal('1e-6'))
    if abs(total - component_sum) > tolerance:
        raise ValueError(f'{label}: total_power must equal internal + switching + leakage within 1 ppm')
    if fields['glitch_power'] > fields['switching_power'] + tolerance:
        raise ValueError(f'{label}: glitch_power cannot exceed switching_power')
    return {'path': path, **{f'{key}_mw': float(number) for key, number in fields.items()},
            'glitch_share': float(fields['glitch_power'] / total) if total else 0.0}


def power(value, factor, label):
    if type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)) or value < 0:
        raise ValueError(f'{label}: expected a non-negative finite number')
    converted = Decimal(str(value)) * factor
    if converted > Decimal('1e100') or (converted and converted < Decimal('1e-100')):
        raise ValueError(f'{label}: outside the supported range')
    return converted


def clean_text(value, label, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(char) < 32 for char in value):
        raise ValueError(f'{label}: invalid text')
    return value
