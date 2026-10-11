"""OpenLane 2 / OpenROAD flow `metrics.json` (METRICS2.1 naming) as sign-off evidence.

One flow run reports timing, physical verification and LVS together. The file is
a flat object of `family__metric[__modifier:value]` keys. A run that fails a
checker never writes `final/metrics.json`; the last step's `state_out.json`
carries the same object under `metrics` and is accepted too. Time is in the
liberty time unit (ns for sky130/gf180), power in W, IR drop in V, area in um^2. Each sign-off
domain with metrics in the file becomes its own run; domains without metrics are
not created. The summary is not a coverage proof, so a clean domain is
`incomplete`, never `passed`.
"""

import hashlib
import json
import math
import re

from .report_import import finite_json_float, JsonNumberRangeError, unique_object

PARSER = 'openlane-metrics-json/v1'
TOOL = 'OpenLane 2'
MAX_BYTES = 2_000_000
MAX_KEYS = 20_000
KEY = re.compile(r'^[a-z0-9_]+(?:__[a-z0-9_]+)*(?:__[a-z_]+:[A-Za-z0-9_.\-\[\]/]{1,200}){0,4}$')

# Physical checks that OpenLane's own checkers treat as flow-failing when non-zero.
PV_CHECKS = (
    ('route__drc_errors', 'route-drc', 'error', 'Detailed-route DRC errors'),
    ('magic__drc_error__count', 'magic-drc', 'error', 'Magic DRC errors'),
    ('klayout__drc_error__count', 'klayout-drc', 'error', 'KLayout DRC errors'),
    ('magic__illegal_overlap__count', 'illegal-overlap', 'error', 'Illegal cell overlaps'),
    ('design__xor_difference__count', 'xor', 'error', 'Magic/KLayout stream-out XOR differences'),
    ('design__critical_disconnected_pin__count', 'disconnected-pin', 'error', 'Critical disconnected pins'),
    ('design__power_grid_violation__count', 'power-grid', 'error', 'Power-grid (PDN) violations'),
    ('antenna__violating__nets', 'antenna-nets', 'warning', 'Antenna-violating nets'),
    ('antenna__violating__pins', 'antenna-pins', 'warning', 'Antenna-violating pins'),
)
LVS_PARTS = (
    ('design__lvs_device_difference__count', 'Device count differences'),
    ('design__lvs_net_difference__count', 'Net count differences'),
    ('design__lvs_unmatched_device__count', 'Unmatched devices'),
    ('design__lvs_unmatched_net__count', 'Unmatched nets'),
    ('design__lvs_unmatched_pin__count', 'Unmatched pins'),
    ('design__lvs_property_fail__count', 'Property failures'),
)
DRV = (('max_slew', 'max-slew', 'Max slew'), ('max_cap', 'max-cap', 'Max capacitance'),
       ('max_fanout', 'max-fanout', 'Max fanout'))
SUMMARY = (
    ('design__instance__count', 'instances', 1), ('design__instance__area', 'instance_area_um2', 1),
    ('design__instance__utilization', 'utilization', 1), ('route__wirelength', 'wirelength_um', 1),
    ('power__total', 'total_power_mw', 1e3), ('power__internal__total', 'internal_power_mw', 1e3),
    ('power__switching__total', 'switching_power_mw', 1e3), ('power__leakage__total', 'leakage_power_mw', 1e3),
    ('ir__drop__worst', 'worst_ir_drop_mv', 1e3), ('ir__drop__avg', 'average_ir_drop_mv', 1e3),
)


TIME_SCALE = {'ns': 1000, 'ps': 1}
NON_FINITE = object()


def infinity(token):
    # OpenLane serializes unbounded slack as Infinity; NaN is never a measurement.
    if token in ('Infinity', '-Infinity'):
        return NON_FINITE
    raise ValueError('non-finite JSON number')


def load(source: str) -> tuple[dict, str, list[str]]:
    if len(source.encode('utf-8')) > MAX_BYTES:
        raise ValueError('metrics file exceeds 2 MB')
    try:
        document = json.loads(source.removeprefix('﻿'), object_pairs_hook=unique_object,
                              parse_constant=infinity, parse_float=finite_json_float)
    except JsonNumberRangeError:
        raise ValueError('JSON number outside the supported floating-point range') from None
    except (ValueError, RecursionError):
        raise ValueError('invalid JSON (check syntax, duplicate fields and finite numbers)') from None
    if not isinstance(document, dict) or not document:
        raise ValueError('expected the flat metrics.json object written by OpenLane 2')
    source_format = 'metrics.json'
    if isinstance(document.get('metrics'), dict):
        document, source_format = document['metrics'], 'state_out.json'
        if not document:
            raise ValueError('state_out.json contains no metrics')
    if len(document) > MAX_KEYS:
        raise ValueError(f'metrics file has more than {MAX_KEYS} metrics')
    for key, value in document.items():
        if not KEY.fullmatch(key) or len(key) > 300:
            raise ValueError(f'unsupported metric name: {key[:80]!r}')
        if isinstance(value, (dict, list)):
            raise ValueError(f'{key}: nested values are not METRICS2.1 metrics')
        if isinstance(value, str) and (len(value) > 500 or any(ord(char) < 32 for char in value)):
            raise ValueError(f'{key}: invalid text value')
    non_finite = sorted(key for key, value in document.items() if value is NON_FINITE)
    for key in non_finite:
        document[key] = None
    return document, source_format, non_finite


def number(document, key, label=None):
    """Value of a numeric metric, None when absent or reported as null."""
    value = document.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{label or key}: expected a number')
    return value


def count(document, key):
    value = number(document, key)
    if value is None:
        return None
    if value < 0 or value != int(value):
        raise ValueError(f'{key}: expected a non-negative count')
    return int(value)


def ps(value, scale):
    return None if value is None else round(value * scale, 6)


def fingerprint(*parts):
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()


def corner_names(document):
    corners = []
    for key in document:
        if key.startswith('timing__setup__ws__corner:'):
            corners.append(key.split(':', 1)[1])
    return sorted(corners)


def parse_sta(document, scale):
    corners = corner_names(document)
    if not corners and number(document, 'timing__setup__ws') is None and number(document, 'timing__hold__ws') is None:
        return None
    rows = []
    for corner in corners or [None]:
        suffix = f'__corner:{corner}' if corner else ''
        row = {'corner': corner or 'all corners',
               'setup_ws_ps': ps(number(document, f'timing__setup__ws{suffix}'), scale),
               'setup_tns_ps': ps(number(document, f'timing__setup__tns{suffix}'), scale),
               'setup_violations': count(document, f'timing__setup_vio__count{suffix}'),
               'hold_ws_ps': ps(number(document, f'timing__hold__ws{suffix}'), scale),
               'hold_tns_ps': ps(number(document, f'timing__hold__tns{suffix}'), scale),
               'hold_violations': count(document, f'timing__hold_vio__count{suffix}')}
        for name, _, _ in DRV:
            row[f'{name}_violations'] = count(document, f'design__{name}_violation__count{suffix}')
        rows.append(row)
    items = []
    for row in rows:
        for check in ('setup', 'hold'):
            ws, tns, violations = row[f'{check}_ws_ps'], row[f'{check}_tns_ps'], row[f'{check}_violations']
            if (ws is not None and ws < 0) or violations:
                items.append({'check': f'{check}/{row["corner"]}', 'severity': 'error', 'location': row['corner'],
                              'message': f'{check.capitalize()} worst slack: {fmt(ws)} ps · TNS: {fmt(tns)} ps · '
                                         f'violating endpoints: {fmt(violations)}'})
        for name, slug, label in DRV:
            if row[f'{name}_violations']:
                items.append({'check': f'{slug}/{row["corner"]}', 'severity': 'warning', 'location': row['corner'],
                              'message': f'{label} violations: {row[f"{name}_violations"]}'})
    for name, slug, label in DRV:
        # Some flows report only the aggregate design-rule count; do not drop it.
        overall = count(document, f'design__{name}_violation__count')
        if overall and not any(row[f'{name}_violations'] for row in rows):
            items.append({'check': f'{slug}/all corners', 'severity': 'warning', 'location': 'all corners',
                          'message': f'{label} violations: {overall}'})
    def worst(field):
        values = [row[field] for row in rows if row[field] is not None]
        return min(values) if values else None
    def total(field):
        values = [row[field] for row in rows if row[field] is not None]
        return sum(values) if values else None
    metrics = {'corners': len(corners), 'setup_wns_ps': worst('setup_ws_ps'), 'setup_tns_ps': worst('setup_tns_ps'),
               'hold_wns_ps': worst('hold_ws_ps'), 'hold_tns_ps': worst('hold_tns_ps'),
               'setup_violations': total('setup_violations'), 'hold_violations': total('hold_violations'),
               **{f'{name}_violations': count(document, f'design__{name}_violation__count') for name, _, _ in DRV}}
    missing = [field for field in ('setup_wns_ps', 'hold_wns_ps') if metrics[field] is None]
    return {'domain': 'sta', 'corners': rows, 'items': items, 'metrics': metrics, 'missing': missing,
            'coverage_note': 'Flow-reported worst slack per corner only; constraints, corner set, '
                             'parasitics and path-level detail are not established.'}


def parse_pv(document):
    present = [check for check in PV_CHECKS if check[0] in document]
    if not present:
        return None
    metrics, items, missing = {}, [], []
    for key, slug, severity, label in present:
        value = count(document, key)
        metrics[slug.replace('-', '_')] = value
        if value is None:
            missing.append(slug)
        elif value:
            items.append({'check': slug, 'severity': severity, 'location': key, 'message': f'{label}: {value}'})
    return {'domain': 'pv', 'items': items, 'metrics': metrics, 'missing': missing,
            'coverage_note': 'Flow-reported violation counts only; marker locations, rule decks and '
                             'foundry sign-off DRC are not established.'}


def parse_lvs(document):
    if 'design__lvs_error__count' not in document:
        return None
    errors = count(document, 'design__lvs_error__count')
    parts, details = {}, []
    for key, label in LVS_PARTS:
        if key in document:
            name = key.removeprefix('design__lvs_').removesuffix('__count')
            parts[name] = count(document, key)
            if parts[name]:
                details.append(f'{label}: {parts[name]}')
    detail = ' · '.join(details)
    items = []
    if errors:
        items.append({'check': 'lvs', 'severity': 'error', 'location': 'design__lvs_error__count',
                      'message': f'LVS errors: {errors}' + (f'\n{detail}' if detail else '')})
    return {'domain': 'lvs', 'items': items, 'metrics': {'lvs_errors': errors, **parts},
            'missing': [] if errors is not None else ['lvs_errors'],
            'coverage_note': 'Flow-reported Netgen comparison counts only; extraction deck, hierarchy '
                             'and mismatch detail are not established.'}


def fmt(value):
    return 'not reported' if value is None else format(value, '.6g')


def parse_openlane_metrics(source: str, time_unit: str = 'ns') -> dict:
    if time_unit not in TIME_SCALE:
        raise ValueError('time_unit must be ns or ps')
    document, source_format, non_finite = load(source)
    domains = [result for result in (parse_sta(document, TIME_SCALE[time_unit]), parse_pv(document),
                                     parse_lvs(document)) if result]
    if not domains:
        raise ValueError('no timing, physical-verification or LVS metrics found; '
                         'upload the final metrics.json of an OpenLane 2 run')
    for domain in domains:
        for item in domain['items']:
            item['fingerprint'] = fingerprint(domain['domain'], item['check'])
        domain['status'] = ('failed' if any(item['severity'] == 'error' for item in domain['items'])
                            else 'incomplete')
        domain['coverage'] = 'flow_metrics_summary_only'
    design = {}
    for key, name, scale in SUMMARY:
        value = number(document, key)
        design[name] = None if value is None else round(value * scale, 9)
    return {'parser': PARSER, 'tool': TOOL, 'metric_count': len(document), 'source_format': source_format,
            'time_unit': time_unit, 'non_finite_metrics': non_finite[:200],
            'source_sha256': hashlib.sha256(source.encode('utf-8')).hexdigest(),
            'design_summary': design, 'domains': domains}
