import math

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Domain, RunEvidence, RunStatus, SignoffRun, StaScenarioDefinition, Stage
from ..schemas import StaMatrixOut, StaScenarioDefinitionOut, StaScenarioSetIn
from .projects import get_project_or_404

router = APIRouter(tags=["sta-matrix"])
MAX_MATCHING_RUNS = 1000


@router.get("/projects/{project_id}/sta-scenarios/{stage}", response_model=list[StaScenarioDefinitionOut])
def list_sta_scenarios(project_id: int, stage: Stage, db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    return db.scalars(select(StaScenarioDefinition).where(
        StaScenarioDefinition.project_id == project_id,
        StaScenarioDefinition.stage == stage,
    ).order_by(StaScenarioDefinition.name)).all()


@router.put("/projects/{project_id}/sta-scenarios/{stage}", response_model=list[StaScenarioDefinitionOut])
def replace_sta_scenarios(
    project_id: int, stage: Stage, payload: StaScenarioSetIn, db: Session = Depends(get_db),
):
    get_project_or_404(project_id, db)
    db.execute(delete(StaScenarioDefinition).where(
        StaScenarioDefinition.project_id == project_id,
        StaScenarioDefinition.stage == stage,
    ))
    rows = [StaScenarioDefinition(project_id=project_id, stage=stage,
        name=item.name, require_spef=item.require_spef) for item in payload.scenarios]
    db.add_all(rows)
    db.commit()
    for row in rows:
        db.refresh(row)
    return sorted(rows, key=lambda row: row.name.casefold())


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

    definitions = db.scalars(select(StaScenarioDefinition).where(
        StaScenarioDefinition.project_id == project_id,
        StaScenarioDefinition.stage == stage,
    )).all()
    expected = {row.name: row for row in definitions}
    scenarios = []
    for name in expected.keys() | latest.keys():
        definition = expected.get(name)
        item = latest.get(name)
        if item is None:
            scenarios.append(dict(scenario=name, expected=True,
                require_spef=definition.require_spef, coverage_state="missing",
                run_id=None, run_count=0, status=None, tool=None, tool_version=None,
                parasitics=None, source_sha256=None, metrics={}, created_at=None))
            continue
        item["expected"] = definition is not None
        item["require_spef"] = definition.require_spef if definition else False
        item["coverage_state"] = ("parasitics_missing" if definition and definition.require_spef
                                  and item["parasitics"] != "spef" else
                                  "recorded" if definition else "unplanned")
        scenarios.append(item)
    scenarios.sort(key=lambda item: item["scenario"].casefold())
    for item in scenarios:
        item["run_count"] = counts.get(item["scenario"], 0)
    slacks = [_finite_number(item["metrics"], "worst_reported_slack_ps") for item in scenarios]
    slacks = [value for value in slacks if value is not None]
    return {
        "project_id": project_id, "stage": stage, "design_revision": revision,
        "summary": {
            "scenario_count": len(scenarios),
            "expected_scenario_count": len(expected),
            "recorded_expected_scenarios": sum(item["expected"] and item["run_id"] is not None for item in scenarios),
            "missing_scenarios": sum(item["coverage_state"] == "missing" for item in scenarios),
            "unexpected_scenarios": sum(item["coverage_state"] == "unplanned" for item in scenarios),
            "parasitic_requirement_gaps": sum(item["coverage_state"] == "parasitics_missing" for item in scenarios),
            "scenario_coverage_complete": bool(expected) and all(item["coverage_state"] == "recorded" for item in scenarios if item["expected"]),
            "failed_scenarios": sum(item["status"] == RunStatus.failed for item in scenarios),
            "incomplete_scenarios": sum(item["status"] in {RunStatus.running, RunStatus.incomplete} for item in scenarios),
            "spef_scenarios": sum(item["parasitics"] == "spef" for item in scenarios),
            "total_violating_paths": sum(_nonnegative_integer(item["metrics"], "violating_paths") for item in scenarios),
            "worst_reported_slack_ps": min(slacks) if slacks else None,
        },
        "scenarios": scenarios,
        "coverage": "reported_paths_only",
        "coverage_note": "Scenario coverage compares the configured expected set with the latest captured OpenSTA execution. Counts and worst slack cover reported path samples only and do not establish full timing sign-off coverage.",
    }
