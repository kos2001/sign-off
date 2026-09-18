"""Read OpenSTA report_checks JSON as submitted evidence, never as full coverage."""
import hashlib
import json
import math
from decimal import Decimal

PARSER = 'opensta-report-checks-json/v1'
EXCHANGE_PARSER = 'commercial-sta-path-json/v1'
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


def commercial_checks(source: str):
    """Validate the stable exchange contract and normalize its times to seconds."""
    if len(source.encode('utf-8')) > MAX_BYTES:
        raise ValueError('report exceeds 2 MB')
    try:
        document = json.loads(source.removeprefix('\ufeff'), object_pairs_hook=unique_object,
                              parse_constant=reject_constant, parse_float=finite_json_float)
    except JsonNumberRangeError:
        raise ValueError('JSON number outside the supported floating-point range; check report units and values') from None
    except (ValueError, RecursionError):
        raise ValueError('invalid JSON report (check syntax, duplicate fields and finite numbers)') from None
    if not isinstance(document, dict) or document.get('format') != 'signoff/commercial-sta-paths/v1':
        raise ValueError('expected signoff/commercial-sta-paths/v1 report')
    tool = document.get('tool')
    if tool not in {'Synopsys PrimeTime', 'Cadence Tempus'}:
        raise ValueError('tool must be Synopsys PrimeTime or Cadence Tempus')
    tool_version = document.get('tool_version')
    if (not isinstance(tool_version, str) or not tool_version.strip() or len(tool_version) > 80
            or tool_version != tool_version.strip()):
        raise ValueError('invalid tool_version')
    unit = document.get('time_unit')
    factors = {'s': Decimal('1'), 'ns': Decimal('1e-9'),
               'ps': Decimal('1e-12'), 'fs': Decimal('1e-15')}
    if unit not in factors:
        raise ValueError('time_unit must be s, ns, ps or fs')
    paths = document.get('paths')
    if not isinstance(paths, list) or len(paths) > MAX_PATHS:
        raise ValueError('paths must contain at most 1000 entries')
    factor = factors[unit]

    def text(value, label, limit=200):
        if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
            raise ValueError(f'{label}: invalid text')
        return value

    def seconds(value, label):
        if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e100:
            raise ValueError(f'{label}: expected a finite time value')
        converted = float(Decimal(str(value)) * factor)
        if not math.isfinite(converted) or converted == 0 and value != 0:
            raise ValueError(f'{label}: time value is outside the supported range')
        return converted

    def points(value, label):
        if not isinstance(value, list) or not value or len(value) > 10000:
            raise ValueError(f'{label}: expected 1 to 10000 path points')
        result = []
        for point_index, point in enumerate(value, 1):
            if not isinstance(point, dict):
                raise ValueError(f'{label} point {point_index}: expected an object')
            normalized = {'pin': text(point.get('pin'), f'{label} point {point_index} pin')}
            for field in ('instance', 'cell', 'net'):
                if field in point:
                    normalized[field] = text(point[field], f'{label} point {point_index} {field}')
            for field in ('arrival', 'slew'):
                if field in point:
                    normalized[field] = seconds(point[field], f'{label} point {point_index} {field}')
            result.append(normalized)
        return result

    checks = []
    for index, path in enumerate(paths, 1):
        if not isinstance(path, dict):
            raise ValueError(f'path {index}: expected an object')
        if 'slack' not in path:
            raise ValueError(f'path {index}: missing slack (use null only for an unconstrained path)')
        check_type = text(path.get('check_type'), f'path {index} check_type', 80)
        slack = path.get('slack')
        check = {
            'type': 'unconstrained' if slack is None else check_type,
            'path_type': path.get('path_type'), 'path_group': path.get('path_group'),
            'startpoint': path.get('startpoint'), 'endpoint': path.get('endpoint'),
            'source_path': points(path.get('points'), f'path {index} points'),
        }
        if slack is not None:
            check['slack'] = seconds(slack, f'path {index} slack')
        for source, target in [('source_clock_points', 'source_clock_path'),
                               ('target_clock_points', 'target_clock_path')]:
            if source in path:
                check[target] = points(path[source], f'path {index} {source}')
        for field in ('source_clock', 'source_clock_edge', 'target_clock', 'target_clock_edge'):
            if field in path:
                check[field] = text(path[field], f'path {index} {field}')
        for field in ('crpr', 'margin', 'path_margin', 'path_delay', 'data_arrival_time', 'required_time'):
            if field in path:
                check[field] = seconds(path[field], f'path {index} {field}')
        if 'multi_cycle_path' in path:
            value = path['multi_cycle_path']
            if type(value) is not int or abs(value) > 2**53 - 1:
                raise ValueError(f'path {index} multi_cycle_path: expected a safe integer')
            check['multi_cycle_path'] = value
        checks.append(check)
    return document, checks


def parse_commercial_sta(source: str) -> dict:
    document, checks = commercial_checks(source)
    result = parse_opensta(json.dumps({'checks': checks}, ensure_ascii=False, separators=(',', ':')))
    result.update(parser=EXCHANGE_PARSER,
                  source_sha256=hashlib.sha256(source.encode('utf-8')).hexdigest(),
                  tool=document['tool'], tool_version=document['tool_version'],
                  time_unit=document['time_unit'])
    return result
