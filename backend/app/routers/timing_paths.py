"""Read-only exploration of paths captured in an imported OpenSTA report."""
import json
import csv
import io
import math
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import RunOut
from .runs import get_run_or_404

router = APIRouter(tags=['timing-paths'])


def captured_run(run_id, db):
    run = get_run_or_404(run_id, db)
    if run.evidence_source != 'opensta_report':
        raise HTTPException(409, 'this run has no imported timing paths')
    return run


def outcome(path):
    slack = path['slack_ps']
    return 'unconstrained' if slack is None else 'violated' if slack < 0 else 'met'


def timing_filters(
    q: str = Query(default='', max_length=200),
    path_type: Literal['min', 'max'] | None = None,
    status: Literal['all', 'violated', 'met', 'unconstrained'] = 'all',
    slack_min_ps: float | None = Query(default=None, allow_inf_nan=False),
    slack_max_ps: float | None = Query(default=None, allow_inf_nan=False),
    sort: Literal['slack_asc', 'slack_desc', 'report'] = 'slack_asc',
):
    if slack_min_ps is not None and slack_max_ps is not None and slack_min_ps > slack_max_ps:
        raise HTTPException(422, 'slack_min_ps must be less than or equal to slack_max_ps')
    return dict(q=q, path_type=path_type, status=status, slack_min_ps=slack_min_ps,
                slack_max_ps=slack_max_ps, sort=sort)


def matching_paths(result, *, q, path_type, status, slack_min_ps, slack_max_ps, sort):
    query = q.casefold()
    paths = [path for path in result['paths'] if
             (path_type is None or path['path_type'] == path_type) and
             (status == 'all' or outcome(path) == status) and
             (slack_min_ps is None or (path['slack_ps'] is not None and path['slack_ps'] >= slack_min_ps)) and
             (slack_max_ps is None or (path['slack_ps'] is not None and path['slack_ps'] <= slack_max_ps)) and
             (not query or any(query in path[key].casefold() for key in ['startpoint', 'endpoint', 'path_group', 'type']))]
    if sort != 'report':
        direction = -1 if sort == 'slack_desc' else 1
        paths.sort(key=lambda path: (path['slack_ps'] is None, direction * (path['slack_ps'] or 0), path['index']))
    return [{**path, 'status': outcome(path)} for path in paths]


def path_summary(paths):
    slacks = [path['slack_ps'] for path in paths if path['slack_ps'] is not None]
    return {'violated_paths': sum(slack < 0 for slack in slacks),
            'met_paths': sum(slack >= 0 for slack in slacks),
            'unconstrained_paths': len(paths) - len(slacks),
            'worst_slack_ps': min(slacks, default=None)}


@router.get('/runs/{run_id}/timing-paths')
def list_paths(
    run_id: int, filters: dict = Depends(timing_filters),
    offset: int = Query(default=0, ge=0, le=1000), limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    run = captured_run(run_id, db)
    result = run.evidence.result
    paths = matching_paths(result, **filters)
    return {'run': RunOut.model_validate(run), 'metadata': result.get('metadata', {}),
            'design_revision': run.evidence.design_revision, 'source_sha256': run.evidence.source_sha256,
            'reported_total': len(result['paths']), 'total': len(paths), 'offset': offset, 'limit': limit,
            'summary': path_summary(paths), 'items': paths[offset:offset + limit]}


@router.get('/runs/{run_id}/timing-paths/export')
def export_paths(
    run_id: int, response: Response, filters: dict = Depends(timing_filters),
    format: Literal['json', 'csv'] = 'json',
    db: Session = Depends(get_db),
):
    run = captured_run(run_id, db)
    result = run.evidence.result
    paths = matching_paths(result, **filters)
    if format == 'csv':
        output = io.StringIO(newline='')
        output.write('\ufeff')
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
        columns = ['run_id', 'project_id', 'stage', 'design_revision', 'source_sha256', 'filename',
                   'scenario', 'tool_version', 'coverage', 'filtered_total', 'reported_total', 'filters_json',
                   'path_index', 'path_type', 'status', 'slack_ps', 'startpoint', 'endpoint',
                   'path_group', 'check_type', 'fingerprint']
        writer.writerow(columns)
        metadata = result.get('metadata', {})
        context = [run.id, run.project_id, run.stage, run.evidence.design_revision,
                   run.evidence.source_sha256, metadata.get('filename'), metadata.get('scenario'),
                   metadata.get('tool_version'), result['coverage'], len(paths), len(result['paths']),
                   json.dumps(filters, ensure_ascii=False, separators=(',', ':'))]
        for path in paths:
            values = context + [path[key] for key in ['index', 'path_type', 'status', 'slack_ps',
                                                     'startpoint', 'endpoint', 'path_group', 'type', 'fingerprint']]
            writer.writerow([csv_cell(value) for value in values])
        return Response(output.getvalue(), media_type='text/csv; charset=utf-8', headers={
            'Content-Disposition': f'attachment; filename="run-{run_id}-timing-paths.csv"',
            'Cache-Control': 'no-store',
        })
    response.headers['Content-Disposition'] = f'attachment; filename="run-{run_id}-timing-paths.json"'
    response.headers['Cache-Control'] = 'no-store'
    return {
        'format': 'signoff/timing-path-export/v1',
        'exported_at': datetime.now(timezone.utc),
        'run': RunOut.model_validate(run),
        'report': {
            'source': run.evidence_source, 'parser': result['parser'],
            'source_sha256': run.evidence.source_sha256,
            'design_revision': run.evidence.design_revision,
            'metadata': result.get('metadata', {}),
            'coverage': result['coverage'], 'coverage_note': result['coverage_note'],
        },
        'filters': filters, 'units': {'slack_ps': 'ps'},
        'reported_total': len(result['paths']), 'total': len(paths), 'summary': path_summary(paths), 'items': paths,
    }


def csv_cell(value):
    # CSV quoting protects separators, not spreadsheet formula interpretation.
    # Only untrusted strings are escaped; numeric negative slacks stay numeric.
    if isinstance(value, str) and (value.lstrip().startswith(('=', '+', '-', '@'))
                                  or value.startswith(('\t', '\r', '\n'))):
        return "'" + value
    return value


def finite_ps(value):
    if type(value) not in (int, float) or abs(value) > 1e100 or not math.isfinite(value):
        return None
    return value * 1e12


def optional_text(value):
    return value if isinstance(value, str) else None


def arrival_deltas(nodes):
    """Adjacent reported arrival differences, not isolated cell/net delays."""
    deltas = [None] * len(nodes)
    increases = []
    for index in range(1, len(nodes)):
        before, after = nodes[index - 1].get('arrival'), nodes[index].get('arrival')
        if finite_ps(before) is None or finite_ps(after) is None:
            continue
        delta = float((Decimal(str(after)) - Decimal(str(before))) * Decimal('1e12'))
        deltas[index] = delta
        if delta > 0:
            increases.append({'from_index': index, 'to_index': index + 1,
                              'from_pin': optional_text(nodes[index - 1].get('pin')),
                              'to_pin': optional_text(nodes[index].get('pin')), 'delta_ps': delta})
    increases.sort(key=lambda item: (-item['delta_ps'], item['to_index']))
    return deltas, {'total_pairs': max(0, len(nodes) - 1),
                    'reported_pairs': sum(value is not None for value in deltas),
                    'largest_increases': increases[:5]}


@router.get('/runs/{run_id}/timing-paths/{path_index}')
def path_detail(
    run_id: int, path_index: int = Path(ge=1),
    point_offset: int = Query(default=0, ge=0, le=10000),
    point_limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
):
    run = captured_run(run_id, db)
    paths = run.evidence.result['paths']
    if path_index > len(paths):
        raise HTTPException(404, 'timing path not found')
    try:
        check = json.loads(run.evidence.source_text.removeprefix('\ufeff'))['checks'][path_index - 1]
    except (ValueError, AttributeError, KeyError, IndexError, TypeError):
        raise HTTPException(409, 'captured report is unreadable') from None
    nodes = check['source_path']
    deltas, delta_summary = arrival_deltas(nodes)
    return {
        'path': {**paths[path_index - 1], 'status': outcome(paths[path_index - 1])},
        'source_clock': optional_text(check.get('source_clock')),
        'target_clock': optional_text(check.get('target_clock')),
        'arrival_ps': finite_ps(check.get('data_arrival_time')),
        'required_ps': finite_ps(check.get('required_time')),
        'point_total': len(nodes), 'point_offset': point_offset, 'point_limit': point_limit,
        'arrival_delta_summary': delta_summary,
        'points': [{'index': index + 1, **{key: optional_text(node.get(key)) for key in ['pin', 'instance', 'cell', 'net']},
                    'arrival_ps': finite_ps(node.get('arrival')), 'slew_ps': finite_ps(node.get('slew')),
                    'arrival_delta_ps': deltas[index]}
                   for index, node in enumerate(nodes[point_offset:point_offset + point_limit], point_offset)],
    }
