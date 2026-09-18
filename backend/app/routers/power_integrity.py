"""Read-only exploration of captured commercial EM/IR findings."""
from collections import Counter
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Violation
from ..schemas import RunOut
from .runs import get_run_or_404

router = APIRouter(tags=['power-integrity-findings'])


def captured(run_id, db):
    run = get_run_or_404(run_id, db)
    if run.evidence_source != 'commercial_emir_report':
        raise HTTPException(409, 'this run has no imported power-integrity findings')
    return run


@router.get('/runs/{run_id}/power-integrity-findings')
def list_findings(
    run_id: int, q: str = Query('', max_length=200),
    analysis: Literal['static_ir', 'dynamic_ir', 'em'] | None = None,
    metric: Literal['voltage_drop', 'current_density'] | None = None,
    status: Literal['all', 'violated', 'met'] = 'all',
    offset: int = Query(0, ge=0, le=5000), limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    run = captured(run_id, db)
    original = run.evidence.result['items']
    query = q.casefold()
    items = [item for item in original if
             (analysis is None or item['analysis'] == analysis) and
             (metric is None or item['metric'] == metric) and
             (status == 'all' or item['violated'] == (status == 'violated')) and
             (not query or any(query in item[key].casefold() for key in
                               ['check', 'instance', 'net', 'layer', 'message']))]
    facets = {key: [{'value': value, 'count': count} for value, count in sorted(Counter(
        item[key] for item in original).items())] for key in ['analysis', 'metric', 'severity']}
    return {'run': RunOut.model_validate(run), 'metadata': run.evidence.result.get('metadata', {}),
            'source_sha256': run.evidence.source_sha256, 'design_revision': run.evidence.design_revision,
            'reported_total': len(original), 'total': len(items), 'offset': offset, 'limit': limit,
            'violated_total': sum(item['violated'] for item in items), 'facets': facets,
            'bounds_um': bounds(items), 'items': items[offset:offset + limit]}


@router.get('/runs/{run_id}/power-integrity-findings/{finding_index}')
def get_finding(run_id: int, finding_index: int = Path(ge=1, le=5000), db: Session = Depends(get_db)):
    run = captured(run_id, db)
    item = next((item for item in run.evidence.result['items'] if item['index'] == finding_index), None)
    if item is None:
        raise HTTPException(404, 'power-integrity finding not found')
    prefix = {'Ansys RedHawk-SC': 'redhawk', 'Cadence Voltus': 'voltus', 'Ansys Totem': 'totem'}[run.tool]
    rows = db.execute(select(Violation.id, Violation.status, Violation.version).where(
        Violation.run_id == run_id, Violation.check_name == f"{prefix}/{item['fingerprint'][:32]}",
    ).order_by(Violation.id)).all()
    return {'item': item, 'violation_match': {
        'status': 'not_applicable' if not item['violated'] else 'unique' if len(rows) == 1 else 'missing' if not rows else 'ambiguous',
        'items': [{'id': row.id, 'status': row.status.value, 'version': row.version} for row in rows],
    }}


def bounds(items):
    if not items:
        return None
    xs = [float(item['x_um']) for item in items]
    ys = [float(item['y_um']) for item in items]
    return {'xmin': min(xs), 'xmax': max(xs), 'ymin': min(ys), 'ymax': max(ys)}
