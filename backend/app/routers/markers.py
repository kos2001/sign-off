"""Read-only marker exploration over captured DRC report items."""
from collections import Counter
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session
from sqlalchemy import select
from ..db import get_db
from ..models import Violation
from ..schemas import RunOut
from ..services.marker_geometry import marker_geometry
from .runs import get_run_or_404

router = APIRouter(tags=['drc-markers'])


def captured(run_id, db):
    run = get_run_or_404(run_id, db)
    if run.evidence_source not in {'klayout_report', 'commercial_drc_report'}:
        raise HTTPException(409, 'this run has no imported DRC markers')
    return run


@router.get('/runs/{run_id}/markers')
def list_markers(run_id: int, q: str = Query('', max_length=200), category: str | None = Query(None, max_length=2000),
                 cell: str | None = Query(None, max_length=200), offset: int = Query(0, ge=0, le=1000),
                 limit: int = Query(25, ge=1, le=100), db: Session = Depends(get_db)):
    run = captured(run_id, db)
    original = run.evidence.result['items']
    query = q.casefold()
    items = [item for item in original if (category is None or item['category'] == category) and
             (cell is None or item['cell'] == cell) and (not query or any(query in value.casefold() for value in
              [item['category'], item['cell'], item['comment'], item['tags'], *item['values']]))]
    def facets(key):
        return [{'value': value, 'count': count} for value, count in sorted(Counter(item[key] for item in original).items())]
    return {'run': RunOut.model_validate(run), 'source_sha256': run.evidence.source_sha256,
            'design_revision': run.evidence.design_revision, 'reported_total': len(original), 'total': len(items),
            'matched_multiplicity': sum(item['multiplicity'] for item in items), 'offset': offset, 'limit': limit,
            'categories': facets('category'), 'cells': facets('cell'),
            'items': [{key: item[key] for key in ['index', 'category', 'cell', 'multiplicity']} for item in items[offset:offset+limit]]}


@router.get('/runs/{run_id}/markers/{marker_index}')
def get_marker(run_id: int, marker_index: int = Path(ge=1, le=1000), db: Session = Depends(get_db)):
    run = captured(run_id, db)
    item = next((item for item in run.evidence.result['items'] if item['index'] == marker_index), None)
    if item is None:
        raise HTTPException(404, 'marker not found')
    prefix = item['fingerprint'][:32]
    check_prefix = run.evidence.result.get('violation_prefix', 'klayout')
    original_matches = sum(other['fingerprint'][:32] == prefix for other in run.evidence.result['items'])
    rows = db.execute(select(Violation.id, Violation.status, Violation.version).where(
        Violation.run_id == run_id, Violation.check_name == f'{check_prefix}/{prefix}',
    ).order_by(Violation.id)).all()
    return {'item': item, 'geometry': marker_geometry(item['values']),
            'violation_matches': {
                'status': 'missing' if not rows else 'unique' if len(rows) == original_matches == 1 else 'ambiguous',
                'source_marker_count': original_matches,
                'items': [{'id': row.id, 'status': row.status.value, 'version': row.version} for row in rows],
            }}
