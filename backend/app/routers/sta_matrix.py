import math

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Domain, RunEvidence, RunStatus, SignoffRun, Stage
from ..schemas import StaMatrixOut
from .projects import get_project_or_404

router = APIRouter(tags=["sta-matrix"])
MAX_MATCHING_RUNS = 1000


def _nonnegative_integer(metrics: dict, name: str) -> int:
    value = metrics.get(name)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _finite_number(metrics: dict, name: str) -> float | int | None:
    value = metrics.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return value


@router.get("/projects/{project_id}/sta-matrix", response_model=StaMatrixOut)
def sta_matrix(
    project_id: int,
    stage: Stage,
    design_revision: str = Query(min_length=1, max_length=160),
    db: Session = Depends(get_db),
):
    get_project_or_404(project_id, db)
    revision = design_revision.strip()
    if not revision:
        raise HTTPException(status_code=422, detail="design_revision must not be blank")

    metadata = RunEvidence.result["metadata"]
    rows = db.execute(select(
        SignoffRun.id, SignoffRun.status, SignoffRun.tool, SignoffRun.metrics,
        SignoffRun.created_at, RunEvidence.source_sha256,
        metadata["scenario"].as_string().label("scenario"),
        metadata["tool_version"].as_string().label("tool_version"),
        metadata["parasitics"].as_string().label("parasitics"),
    ).join(RunEvidence, RunEvidence.run_id == SignoffRun.id).where(
        SignoffRun.project_id == project_id,
        SignoffRun.domain == Domain.sta,
        SignoffRun.stage == stage,
        RunEvidence.source == "opensta_execution",
        RunEvidence.design_revision == revision,
    ).order_by(SignoffRun.created_at.desc(), SignoffRun.id.desc()).limit(MAX_MATCHING_RUNS + 1)).all()
    if len(rows) > MAX_MATCHING_RUNS:
        raise HTTPException(status_code=413, detail="too many matching STA runs; use a more specific design revision")

    latest: dict[str, dict] = {}
    counts: dict[str, int] = {}
    for row in rows:
        scenario = row.scenario.strip() if isinstance(row.scenario, str) else ""
        tool_version = row.tool_version.strip() if isinstance(row.tool_version, str) else ""
        if not scenario or not tool_version or row.parasitics not in {"spef", "none"} or not row.source_sha256:
            raise HTTPException(status_code=409, detail=f"run {row.id} has incomplete OpenSTA provenance")
        counts[scenario] = counts.get(scenario, 0) + 1
        if scenario not in latest:
            latest[scenario] = dict(
                scenario=scenario, run_id=row.id, status=row.status, tool=row.tool,
                tool_version=tool_version, parasitics=row.parasitics,
                source_sha256=row.source_sha256, metrics=row.metrics or {}, created_at=row.created_at,
            )

    scenarios = sorted(latest.values(), key=lambda item: item["scenario"].casefold())
    for item in scenarios:
        item["run_count"] = counts[item["scenario"]]
    slacks = [_finite_number(item["metrics"], "worst_reported_slack_ps") for item in scenarios]
    slacks = [value for value in slacks if value is not None]
    return {
        "project_id": project_id, "stage": stage, "design_revision": revision,
        "summary": {
            "scenario_count": len(scenarios),
            "failed_scenarios": sum(item["status"] == RunStatus.failed for item in scenarios),
            "incomplete_scenarios": sum(item["status"] in {RunStatus.running, RunStatus.incomplete} for item in scenarios),
            "spef_scenarios": sum(item["parasitics"] == "spef" for item in scenarios),
            "total_violating_paths": sum(_nonnegative_integer(item["metrics"], "violating_paths") for item in scenarios),
            "worst_reported_slack_ps": min(slacks) if slacks else None,
        },
        "scenarios": scenarios,
        "coverage": "reported_paths_only",
        "coverage_note": "Latest captured OpenSTA execution per recorded scenario. Counts and worst slack cover reported path samples only; this does not establish the expected scenario set or full sign-off coverage.",
    }
