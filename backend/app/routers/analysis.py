from fastapi import APIRouter, HTTPException

from ..schemas import GlitchPowerRequest, IrDropRequest, TimingSummaryRequest
from ..services.glitch import estimate_glitch_power
from ..services.irdrop import screen_ir_drop
from ..services.timing import summarize_corners

router = APIRouter(prefix="/analysis", tags=["analysis"])


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


@router.post("/timing-summary")
def timing_summary(payload: TimingSummaryRequest):
    try:
        return summarize_corners(
            corners=[c.model_dump() for c in payload.corners],
            pba_pessimism_credit_ps=payload.pba_pessimism_credit_ps,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
