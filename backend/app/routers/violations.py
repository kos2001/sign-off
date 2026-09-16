"""Project-wide review queries, with latest runs selected before filtering issues."""

from typing import Literal
from datetime import datetime, timezone
import json

from fastapi import APIRouter, Depends, Query, HTTPException, Response
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..models import Domain, Severity, SignoffRun, Stage, Violation, ViolationStatus
from ..schemas import ViolationPage, ProjectViolationOut
from ..services.stages import BLOCKING_SEVERITIES
from .projects import get_project_or_404

router = APIRouter(tags=["violations"])


EXPORT_LIMIT = 10000
EXPORT_MAX_BYTES = 8 * 1024 * 1024


def violation_filters(
    q: str = Query(default="", max_length=200),
    status: ViolationStatus | None = None,
    severity: Severity | None = None,
    domain: Domain | None = None,
    stage: Stage | None = None,
    latest_only: bool = True,
    sort: Literal["severity", "newest", "oldest"] = "severity",
):
    return dict(q=q, status=status, severity=severity, domain=domain, stage=stage,
                latest_only=latest_only, sort=sort)


@router.get("/projects/{project_id}/violations", response_model=ViolationPage)
def project_violations(
    project_id: int, filters: dict = Depends(violation_filters),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return violation_page(project_id, db, **filters, offset=offset, limit=limit)


@router.get('/projects/{project_id}/violations/export')
def export_violations(project_id: int, filters: dict = Depends(violation_filters),
                      db: Session = Depends(get_db)):
    page = violation_page(project_id, db, **filters, offset=0, limit=EXPORT_LIMIT + 1, exporting=True)
    metadata = {'format': 'signoff/violation-export/v1', 'exported_at': datetime.now(timezone.utc).isoformat(),
            'project_id': project_id, 'filters': filters, 'total': page['total'],
            'open_blocking': page['open_blocking'],
            'coverage_note': 'Current recorded violations only; absence of violations does not prove sign-off completion.'}
    prefix = json.dumps(metadata, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')[:-1] + b',"items":['
    size = len(prefix) + sum(map(len, page['items'])) + max(0, len(page['items']) - 1) + 2
    if size > EXPORT_MAX_BYTES:
        raise export_size_error()
    content = prefix + b','.join(page['items']) + b']}'
    return Response(content, media_type='application/json', headers={
        'Content-Disposition': f'attachment; filename="project-{project_id}-violations.json"',
        'Cache-Control': 'no-store',
    })


def export_size_error():
    return HTTPException(413, 'Violation export exceeds 8 MiB; narrow the filters and retry.')


def export_rows(db, statement):
    items, size, open_blocking = [], 0, 0
    # Stream ORM rows from a single SELECT. Do not load every long description
    # and waiver reason before discovering that the download exceeds the cap.
    rows = db.scalars(statement.execution_options(yield_per=1))
    try:
        for item in rows:
            if len(items) >= EXPORT_LIMIT:
                raise HTTPException(413, 'Too many violations to export; narrow the filters to 10000 or fewer.')
            encoded = ProjectViolationOut.model_validate(item).model_dump_json().encode('utf-8')
            size += len(encoded) + (1 if items else 0)
            if size > EXPORT_MAX_BYTES:
                raise export_size_error()
            items.append(encoded)
            open_blocking += item.status == ViolationStatus.open and item.severity in BLOCKING_SEVERITIES
    finally:
        rows.close()
    return {'items': items, 'total': len(items), 'open_blocking': open_blocking}


def violation_page(project_id, db, *, q, status, severity, domain, stage, latest_only, sort,
                   offset, limit, exporting=False):
    get_project_or_404(project_id, db)
    filters = [SignoffRun.project_id == project_id]
    if latest_only:
        # Same ordering as evaluate_gate. A clean or running new run supersedes
        # old violations, even when the new run has no matching issues yet.
        ranked_runs = select(
            SignoffRun.id,
            func.row_number().over(
                partition_by=(SignoffRun.stage, SignoffRun.domain),
                order_by=(SignoffRun.created_at.desc(), SignoffRun.id.desc()),
            ).label("rank"),
        ).where(SignoffRun.project_id == project_id).subquery()
        filters.append(SignoffRun.id.in_(select(ranked_runs.c.id).where(ranked_runs.c.rank == 1)))
    for column, value in [
        (Violation.status, status), (Violation.severity, severity),
        (SignoffRun.domain, domain), (SignoffRun.stage, stage),
    ]:
        if value is not None:
            filters.append(column == value)
    if q.strip():
        filters.append(or_(*[
            column.icontains(q.strip(), autoescape=True)
            for column in (Violation.check_name, Violation.location, Violation.description, SignoffRun.tool)
        ]))
    blocking = (Violation.status == ViolationStatus.open) & Violation.severity.in_(BLOCKING_SEVERITIES)
    if not exporting:
        total, open_blocking = db.execute(select(
            func.count(Violation.id), func.coalesce(func.sum(case((blocking, 1), else_=0)), 0),
        ).select_from(Violation).join(SignoffRun).where(*filters)).one()
    severity_rank = case(
        (Violation.severity == Severity.critical, 0),
        (Violation.severity == Severity.error, 1),
        (Violation.severity == Severity.warning, 2),
        else_=3,
    )
    ordering = {
        "severity": (severity_rank, Violation.id.desc()),
        "newest": (Violation.id.desc(),),
        "oldest": (Violation.id.asc(),),
    }[sort]
    statement = (select(Violation).join(SignoffRun).where(*filters)
        .options(joinedload(Violation.run), joinedload(Violation.waiver))
        .order_by(*ordering).offset(offset).limit(limit))
    if exporting:
        return export_rows(db, statement)
    items = db.scalars(statement).all()
    return {"items": items, "total": total, "open_blocking": open_blocking, "offset": offset, "limit": limit}
