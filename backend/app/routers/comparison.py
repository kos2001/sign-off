from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..models import SignoffRun, Violation
from ..schemas import RunComparisonOut
from ..services.comparison import compare_runs
from .projects import get_project_or_404

router = APIRouter(tags=["run-comparison"])


@router.get("/projects/{project_id}/run-comparison", response_model=RunComparisonOut)
def run_comparison(
    project_id: int,
    baseline_run_id: int = Query(gt=0, le=2**63 - 1),
    candidate_run_id: int = Query(gt=0, le=2**63 - 1),
    kind: Literal["all", "new", "changed", "removed", "unchanged"] = "all",
    offset: int = Query(default=0, ge=0, le=2_147_483_647),
    limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    get_project_or_404(project_id, db)
    runs = {run.id: run for run in db.scalars(select(SignoffRun).where(
        SignoffRun.project_id == project_id,
        SignoffRun.id.in_([baseline_run_id, candidate_run_id]),
    ).options(selectinload(SignoffRun.violations).selectinload(Violation.waiver),
              selectinload(SignoffRun.evidence))).all()}
    if baseline_run_id not in runs or candidate_run_id not in runs:
        raise HTTPException(status_code=404, detail="run not found in this project")
    if baseline_run_id == candidate_run_id:
        raise HTTPException(status_code=422, detail="select two different runs")
    baseline, candidate = runs[baseline_run_id], runs[candidate_run_id]
    if (baseline.domain, baseline.stage) != (candidate.domain, candidate.stage):
        raise HTTPException(status_code=422, detail="runs must have the same domain and stage")
    result = compare_runs(baseline, candidate)
    items = result["items"]
    if kind != "all":
        items = [row for row in items if row["kind"] == kind]
    result.update(total=len(items), offset=offset, limit=limit, items=items[offset:offset + limit])
    return result
