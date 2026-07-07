from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Domain, Project, RunStatus, Severity, SignoffRun, Stage, Violation
from ..schemas import (
    GlitchPowerRequest,
    IrDropRequest,
    RtlSignoffRequest,
    TimingSummaryRequest,
)
from ..services.glitch import estimate_glitch_power
from ..services.irdrop import screen_ir_drop
from ..services.rtl.signoff import run_signoff
from ..services.timing import summarize_corners

router = APIRouter(prefix="/analysis", tags=["analysis"])

_RULE_SEVERITY = {"error": Severity.error, "warn": Severity.warning, "info": Severity.info}


@router.post("/ir-drop")
def ir_drop(payload: IrDropRequest):
    try:
        return screen_ir_drop(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/glitch-power")
def glitch_power(payload: GlitchPowerRequest):
    try:
        return estimate_glitch_power(
            nets=[n.model_dump() for n in payload.nets],
            vdd=payload.vdd,
            clock_period_ns=payload.clock_period_ns,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/rtl-signoff")
def rtl_signoff(payload: RtlSignoffRequest, db: Session = Depends(get_db)):
    """Run the RTL sign-off ladder (verilator lint -> design rules -> yosys
    synth -> verdict). With `project_id`, the result is recorded as a signoff
    run and failing checks are filed as violations, driving the RTL stage gate."""
    result = run_signoff(payload.code)

    run_id = None
    if payload.project_id is not None:
        if db.get(Project, payload.project_id) is None:
            raise HTTPException(status_code=404, detail="project not found")
        run = SignoffRun(
            project_id=payload.project_id,
            domain=Domain.rtl,
            stage=Stage.rtl,
            tool=f"rtl-signoff-ladder (lint={result.report['lint_tool']})",
            status=RunStatus.failed if result.verdict == "REJECTED" else RunStatus.passed,
            metrics={
                "verdict": result.verdict,
                "score": result.score,
                "grade": result.grade,
                "module": result.module,
                "stages": [
                    {"name": s.name, "status": s.status, "detail": s.detail}
                    for s in result.stages
                ],
            },
        )
        db.add(run)
        db.flush()
        db.add_all(
            Violation(
                run_id=run.id,
                check_name=f"{r['code']}: {r['name']}",
                severity=_RULE_SEVERITY[r["severity"]],
                location=result.module,
                description=r["detail"],
            )
            for r in result.rules
            if r["status"] == "violation"
        )
        db.commit()
        run_id = run.id

    return {
        "verdict": result.verdict,
        "score": result.score,
        "grade": result.grade,
        "module": result.module,
        "stages": [
            {"name": s.name, "status": s.status, "gating": s.gating, "detail": s.detail}
            for s in result.stages
        ],
        "rules": result.rules,
        "suggestions": result.suggestions,
        "run_id": run_id,
    }


@router.post("/timing-summary")
def timing_summary(payload: TimingSummaryRequest):
    try:
        return summarize_corners(
            corners=[c.model_dump() for c in payload.corners],
            pba_pessimism_credit_ps=payload.pba_pessimism_credit_ps,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
