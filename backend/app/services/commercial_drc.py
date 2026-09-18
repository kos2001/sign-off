"""Strict vendor-neutral exchange format for commercial DRC marker evidence."""
import hashlib
import json
import math
from decimal import Decimal

from .report_import import JsonNumberRangeError, finite_json_float, reject_constant, unique_object

PARSER = 'commercial-drc-markers-json/v1'
FORMAT = 'signoff/commercial-drc-markers/v1'
MAX_BYTES = 2_000_000
MAX_MARKERS = 1000
MAX_SHAPES = 100
MAX_POINTS = 2000
TOOLS = {'Siemens Calibre nmDRC', 'Cadence Pegasus'}
SEVERITIES = {'info', 'warning', 'error', 'critical'}


def parse_commercial_drc(source: str) -> dict:
    raw = source.encode('utf-8')
    if len(raw) > MAX_BYTES:
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
        raise ValueError('tool must be Siemens Calibre nmDRC or Cadence Pegasus')
    tool_version = clean_text(document.get('tool_version'), 'tool_version', 80)
    if tool_version != tool_version.strip():
        raise ValueError('tool_version must not have surrounding whitespace')
    unit = document.get('coordinate_unit')
    factors = {'um': Decimal('1'), 'nm': Decimal('0.001')}
    if unit not in factors:
        raise ValueError('coordinate_unit must be um or nm')
    top_cell = clean_text(document.get('top_cell'), 'top_cell', 200)
    rule_deck = clean_text(document.get('rule_deck'), 'rule_deck', 500) if 'rule_deck' in document else ''
    markers = document.get('markers')
    if not isinstance(markers, list) or len(markers) > MAX_MARKERS:
        raise ValueError('markers must contain at most 1000 entries')

    items = []
    for index, marker in enumerate(markers, 1):
        if not isinstance(marker, dict):
            raise ValueError(f'marker {index}: expected an object')
        rule = clean_text(marker.get('rule'), f'marker {index} rule', 2000)
        cell = clean_text(marker.get('cell'), f'marker {index} cell', 200, allow_empty=True)
        severity = marker.get('severity')
        if severity not in SEVERITIES:
            raise ValueError(f'marker {index}: severity must be info, warning, error or critical')
        multiplicity = marker.get('multiplicity', 1)
        if type(multiplicity) is not int or not 1 <= multiplicity <= 1_000_000_000:
            raise ValueError(f'marker {index}: invalid multiplicity')
        message = clean_text(marker.get('message'), f'marker {index} message', 20000,
                             allow_empty=True) if 'message' in marker else ''
        shapes = marker.get('shapes')
        if not isinstance(shapes, list) or not shapes or len(shapes) > MAX_SHAPES:
            raise ValueError(f'marker {index}: shapes must contain 1 to 100 entries')
        values, point_count = [], 0
        for shape_index, shape in enumerate(shapes, 1):
            value, count = normalize_shape(shape, factors[unit], f'marker {index} shape {shape_index}')
            point_count += count
            if point_count > MAX_POINTS:
                raise ValueError(f'marker {index}: shapes exceed 2000 points')
            values.append(value)
        identity = {'category': rule, 'cell': cell, 'severity': severity, 'values': values}
        items.append({'index': index, 'category': rule, 'cell': cell, 'severity': severity,
                      'values': values, 'multiplicity': multiplicity, 'tags': '', 'visited': '',
                      'comment': message,
                      'fingerprint': hashlib.sha256(json.dumps(identity, sort_keys=True,
                                                               ensure_ascii=False).encode()).hexdigest()})
    severity_counts = {severity: sum(item['multiplicity'] for item in items if item['severity'] == severity)
                       for severity in sorted(SEVERITIES)}
    blocking = sum(item['multiplicity'] for item in items if item['severity'] in {'error', 'critical'})
    return {'parser': PARSER, 'tool': tool, 'tool_version': tool_version,
            'coordinate_unit': unit, 'coverage': 'reported_markers_only',
            'coverage_note': 'Marker exchange only; rule-deck execution, checked layers and complete DRC coverage are not established.',
            'severity_policy': 'Severity is supplied by the collector and preserved as evidence; it does not approve or waive a marker.',
            'coordinate_note': 'Coordinates are normalized to micrometers in the reported cell context; no hierarchy transform is applied.',
            'source_sha256': hashlib.sha256(raw).hexdigest(),
            'status': 'failed' if blocking else 'incomplete',
            'metrics': {'reported_items': len(items),
                        'reported_multiplicity': sum(item['multiplicity'] for item in items),
                        'blocking_multiplicity': blocking, 'severity_counts': severity_counts},
            'description': rule_deck, 'top_cell': top_cell, 'generator': f'{tool} {tool_version}',
            'violation_prefix': 'calibre' if tool == 'Siemens Calibre nmDRC' else 'pegasus',
            'items': items}


def clean_text(value, label, limit, *, allow_empty=False):
    if (not isinstance(value, str) or len(value) > limit or any(ord(char) < 32 for char in value)
            or (not allow_empty and not value.strip())):
        raise ValueError(f'{label}: invalid text')
    return value


def normalize_shape(shape, factor: Decimal, label: str):
    if not isinstance(shape, dict) or shape.get('type') not in {'box', 'edge', 'polygon'}:
        raise ValueError(f'{label}: type must be box, edge or polygon')
    kind = shape['type']
    if kind == 'polygon':
        contours = shape.get('contours')
        if not isinstance(contours, list) or not contours:
            raise ValueError(f'{label}: polygon requires contours')
        normalized = []
        for contour_index, contour in enumerate(contours, 1):
            if not isinstance(contour, list) or len(contour) < 3:
                raise ValueError(f'{label}: contour {contour_index} requires at least 3 points')
            normalized.append([normalize_point(point, factor, label) for point in contour])
    else:
        points = shape.get('points')
        if not isinstance(points, list) or len(points) != 2:
            raise ValueError(f'{label}: {kind} requires exactly 2 points')
        normalized = [[normalize_point(point, factor, label) for point in points]]
    count = sum(len(contour) for contour in normalized)
    body = '/'.join(';'.join(f'{x},{y}' for x, y in contour) for contour in normalized)
    return f'{kind}: ({body})', count


def normalize_point(point, factor: Decimal, label: str):
    if not isinstance(point, list) or len(point) != 2:
        raise ValueError(f'{label}: each point must be [x, y]')
    result = []
    for value in point:
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f'{label}: coordinate must be finite')
        converted = Decimal(str(value)) * factor
        if converted.copy_abs() > Decimal('1e12') or (converted and converted.copy_abs() < Decimal('1e-12')):
            raise ValueError(f'{label}: coordinate is outside the supported range')
        result.append(format(converted, 'f'))
    return result
