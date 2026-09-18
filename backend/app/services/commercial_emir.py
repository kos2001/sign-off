"""Strict vendor-neutral exchange format for commercial EM/IR findings."""
import hashlib
import json
import math
from decimal import Decimal

from .report_import import JsonNumberRangeError, finite_json_float, reject_constant, unique_object

FORMAT = 'signoff/commercial-power-integrity/v1'
PARSER = 'commercial-power-integrity-json/v1'
TOOLS = {'Ansys RedHawk-SC', 'Cadence Voltus', 'Ansys Totem'}
SEVERITIES = {'info', 'warning', 'error', 'critical'}
ANALYSES = {'static_ir', 'dynamic_ir', 'em'}
VALUE_UNITS = {
    'voltage_drop': {'V': Decimal('1000'), 'mV': Decimal('1'), 'uV': Decimal('0.001')},
    'current_density': {'A/um2': Decimal('1'), 'mA/um2': Decimal('0.001')},
}
CANONICAL_UNITS = {'voltage_drop': 'mV', 'current_density': 'A/um2'}


def parse_commercial_emir(source: str) -> dict:
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
        raise ValueError('unsupported commercial power-integrity tool')
    tool_version = text(document.get('tool_version'), 'tool_version', 80)
    if tool_version != tool_version.strip():
        raise ValueError('tool_version must not have surrounding whitespace')
    coordinate_unit = document.get('coordinate_unit')
    coordinate_factor = {'um': Decimal('1'), 'nm': Decimal('0.001')}.get(coordinate_unit)
    if coordinate_factor is None:
        raise ValueError('coordinate_unit must be um or nm')
    top_cell = text(document.get('top_cell'), 'top_cell', 200)
    findings = document.get('findings')
    if not isinstance(findings, list) or len(findings) > 5000:
        raise ValueError('findings must contain at most 5000 entries')

    items = []
    for index, finding in enumerate(findings, 1):
        if not isinstance(finding, dict):
            raise ValueError(f'finding {index}: expected an object')
        analysis = finding.get('analysis')
        if analysis not in ANALYSES:
            raise ValueError(f'finding {index}: unsupported analysis')
        metric = finding.get('metric')
        if metric not in VALUE_UNITS or (analysis == 'em') != (metric == 'current_density'):
            raise ValueError(f'finding {index}: metric does not match analysis')
        unit = finding.get('unit')
        if unit not in VALUE_UNITS[metric]:
            raise ValueError(f'finding {index}: unsupported unit for metric')
        value = quantity(finding.get('value'), VALUE_UNITS[metric][unit], f'finding {index} value')
        limit = quantity(finding.get('limit'), VALUE_UNITS[metric][unit], f'finding {index} limit')
        severity = finding.get('severity')
        if severity not in SEVERITIES:
            raise ValueError(f'finding {index}: invalid severity')
        x = coordinate(finding.get('x'), coordinate_factor, f'finding {index} x')
        y = coordinate(finding.get('y'), coordinate_factor, f'finding {index} y')
        identity = {
            'analysis': analysis, 'metric': metric, 'check': text(finding.get('check'), f'finding {index} check', 500),
            'instance': optional_text(finding, 'instance', index, 500),
            'net': optional_text(finding, 'net', index, 500),
            'layer': optional_text(finding, 'layer', index, 200), 'x_um': x, 'y_um': y,
        }
        fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        items.append({'index': index, **identity, 'severity': severity, 'value': value, 'limit': limit,
                      'unit': CANONICAL_UNITS[metric], 'violated': value > limit,
                      'message': optional_text(finding, 'message', index, 2000), 'fingerprint': fingerprint})
    violated = [item for item in items if item['violated']]
    return {
        'parser': PARSER, 'tool': tool, 'tool_version': tool_version, 'coordinate_unit': coordinate_unit,
        'top_cell': top_cell, 'coverage': 'reported_findings_only',
        'coverage_note': 'Finding exchange only; complete rail, mode, vector, extraction and EM/IR coverage are not established.',
        'source_sha256': hashlib.sha256(raw).hexdigest(), 'status': 'failed' if violated else 'incomplete',
        'metrics': {'reported_findings': len(items), 'violated_findings': len(violated),
                    'static_ir_findings': sum(item['analysis'] == 'static_ir' for item in items),
                    'dynamic_ir_findings': sum(item['analysis'] == 'dynamic_ir' for item in items),
                    'em_findings': sum(item['analysis'] == 'em' for item in items)},
        'items': items,
    }


def text(value, label, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(char) < 32 for char in value):
        raise ValueError(f'{label}: invalid text')
    return value


def optional_text(source, key, index, limit):
    value = source.get(key, '')
    if not isinstance(value, str) or len(value) > limit or any(ord(char) < 32 for char in value):
        raise ValueError(f'finding {index} {key}: invalid text')
    return value


def quantity(value, factor, label):
    if type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)) or value < 0:
        raise ValueError(f'{label}: expected a non-negative finite number')
    converted = Decimal(str(value)) * factor
    if converted > Decimal('1e100') or (converted and converted < Decimal('1e-100')):
        raise ValueError(f'{label}: outside the supported range')
    return float(converted)


def coordinate(value, factor, label):
    if type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)):
        raise ValueError(f'{label}: expected a finite number')
    converted = Decimal(str(value)) * factor
    if converted.copy_abs() > Decimal('1e12') or (converted and converted.copy_abs() < Decimal('1e-12')):
        raise ValueError(f'{label}: outside the supported range')
    return format(converted, 'f')
