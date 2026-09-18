"""Read OpenSTA report_checks JSON as submitted evidence, never as full coverage."""
import hashlib
import json
import math

PARSER = 'opensta-report-checks-json/v1'
MAX_BYTES = 2_000_000
MAX_PATHS = 1000
COVERAGE_NOTE = 'Path reports may be filtered or limited; full STA coverage is not established.'


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate JSON field')
        value[key] = item
    return value


def reject_constant(value):
    raise ValueError('non-finite JSON number')


class JsonNumberRangeError(ValueError):
    pass


def finite_json_float(raw):
    value = float(raw)
    # A nonzero mantissa must not silently become zero during JSON decoding.
    # Inspect only the mantissa: 0e-400 is a valid exact zero.
    mantissa = raw.lower().split('e', 1)[0]
    if not math.isfinite(value) or value == 0 and any(digit in mantissa for digit in '123456789'):
        raise JsonNumberRangeError('JSON number outside the supported floating-point range')
    return value


def path_pins(nodes, label, *, allow_empty=False):
    if not isinstance(nodes, list) or len(nodes) > 10000 or (not nodes and not allow_empty):
        raise ValueError(f'{label}: expected at most 10000 path pins')
    pins = []
    for node in nodes:
        pin = node.get('pin') if isinstance(node, dict) else None
        if not isinstance(pin, str) or not pin or len(pin) > 200:
            raise ValueError(f'{label}: invalid path pin')
        pins.append(pin)
    return pins


def parse_opensta(source: str) -> dict:
    if len(source.encode('utf-8')) > MAX_BYTES:
        raise ValueError('report exceeds 2 MB')
    try:
        document = json.loads(source.removeprefix('\ufeff'), object_pairs_hook=unique_object,
                              parse_constant=reject_constant, parse_float=finite_json_float)
    except JsonNumberRangeError:
        raise ValueError('JSON number outside the supported floating-point range; check report units and values') from None
    except (ValueError, RecursionError):
        raise ValueError('invalid JSON report (check syntax, duplicate fields and finite numbers)') from None
    if not isinstance(document, dict) or not isinstance(document.get('checks'), list):
        raise ValueError('expected OpenSTA report_checks -format json with a checks array')
    if len(document['checks']) > MAX_PATHS:
        raise ValueError('report exceeds 1000 paths; export a smaller report')
    paths = []
    for index, check in enumerate(document['checks'], 1):
        def text(key, limit=200):
            value = check.get(key)
            if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
                raise ValueError(f'path {index}: invalid {key}')
            return value
        if not isinstance(check, dict):
            raise ValueError(f'path {index}: expected an object')
        kind, group = text('type', 80), text('path_group')
        start, end = text('startpoint'), text('endpoint')
        path_type = text('path_type', 8)
        if path_type not in {'min', 'max'}:
            raise ValueError(f'path {index}: unsupported path_type')
        nodes = check.get('source_path')
        pins = path_pins(nodes, f'path {index}: source_path')
        for field in ('source_clock_path', 'target_clock_path'):
            if field in check:
                path_pins(check[field], f'path {index}: {field}', allow_empty=True)
        if pins[0] != start or pins[-1] != end:
            raise ValueError(f'path {index}: source_path does not match startpoint/endpoint')
        slack = check.get('slack')
        if slack is None:
            if kind != 'unconstrained':
                raise ValueError(f'path {index}: missing slack for constrained path')
            slack_ps = None
        elif type(slack) not in (int, float) or abs(slack) > 1e100 or not math.isfinite(slack) or not math.isfinite(slack * 1e12):
            raise ValueError(f'path {index}: slack must be a finite number in seconds')
        elif kind == 'unconstrained':
            raise ValueError(f'path {index}: unconstrained path cannot have slack')
        else:
            slack_ps = slack * 1e12
        identity = {key: check.get(key) for key in ['type', 'path_group', 'path_type', 'startpoint', 'endpoint', 'source_clock', 'source_clock_edge', 'target_clock', 'target_clock_edge']}
        for key in ['source_clock', 'source_clock_edge', 'target_clock', 'target_clock_edge']:
            if key in check:
                text(key)
        identity['pins'] = pins
        fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        paths.append({'index': index, 'type': kind, 'path_type': path_type, 'path_group': group,
                      'startpoint': start, 'endpoint': end, 'slack_ps': slack_ps, 'fingerprint': fingerprint})
    constrained = [path['slack_ps'] for path in paths if path['slack_ps'] is not None]
    violating = sum(slack < 0 for slack in constrained)
    return {'parser': PARSER, 'coverage': 'reported_paths_only', 'coverage_note': COVERAGE_NOTE,
            'status': 'failed' if violating else 'incomplete',
            'source_sha256': hashlib.sha256(source.encode('utf-8')).hexdigest(),
            'metrics': {'reported_paths': len(paths), 'violating_paths': violating,
                        'unconstrained_paths': len(paths) - len(constrained),
                        'worst_reported_slack_ps': min(constrained, default=None)}, 'paths': paths}
