"""Wires the six hermes-agent roles (app/hermes.py) to this app's own
analysis results. Each endpoint checks the matching trigger predicate first —
a clean result returns {"triggered": false, ...} with no LLM call at all, so
the frontend can render "agent 개입 없음" as a first-class, honest state
rather than always showing a spinner."""
from __future__ import annotations

import json
import asyncio
import logging
import uuid
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Request

from .. import hermes
from ..services.rtl.artifacts import netlist_metadata_only
from ..review_capacity import acquire, ReviewCapacityFull

router = APIRouter(prefix="/agents", tags=["agents"])
logger = logging.getLogger(__name__)
REVIEW_TIMEOUT_SECONDS = 45


async def _run_role(role: hermes.Role, payload: dict, *, session_id: str) -> dict:
    """Call the role's LLM pass; degrade to a clear unreachable-state result
    instead of a 500 when the hermes 'sign-off' profile isn't running yet —
    this is expected until `scripts/setup_hermes_profile.sh --apply` has run."""
    client = None
    slot = None
    review_id = uuid.uuid4().hex
    started = time.monotonic()
    def metadata():
        return {"review_id": review_id, "completed_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": round((time.monotonic() - started) * 1000)}
    try:
        slot = acquire()
        client = hermes.HermesClient()
        async with asyncio.timeout(REVIEW_TIMEOUT_SECONDS):
            review = await client.chat(role, json.dumps(payload, ensure_ascii=False), session_id=session_id)
        if not isinstance(review, str) or not review.strip():
            raise ValueError('empty review')
        return {"available": True, "review": review, "error": None, **metadata()}
    except ReviewCapacityFull:
        return {"available": False, "review": None, "error": "review_capacity", **metadata()}
    except Exception as exc:  # httpx connection errors, timeouts, bad hermes response
        reference = review_id
        # Upstream exceptions can contain credentials, URLs or submitted design
        # data. Log only a correlation ID, role and exception class.
        logger.warning('review unavailable reference=%s role=%s failure=%s', reference, role.id, type(exc).__name__)
        return {"available": False, "review": None, "error": "review_unavailable", "error_id": reference, **metadata()}
    finally:
        try:
            if client is not None:
                await client.aclose()
        finally:
            if slot is not None:
                slot.close()


def _not_triggered(role: hermes.Role) -> dict:
    return {
        "role": role.id,
        "role_name": role.name_ko,
        "triggered": False,
        "trigger": role.trigger_ko,
        "available": None,
        "review": None,
        "error": None,
    }


@router.post("/review/rtl")
async def review_rtl(request: Request, rtl_signoff_result: dict = Body(embed=True)):
    role = hermes.ROLES["a1_rtl"]
    if not hermes.a1_should_review(rtl_signoff_result):
        return _not_triggered(role)
    outcome = await _run_role(role, netlist_metadata_only(rtl_signoff_result), session_id=f"{getattr(request.state, 'user_id', 'local')}:{role.id}:{rtl_signoff_result.get('run_id') or 'adhoc'}")
    return {"role": role.id, "role_name": role.name_ko, "triggered": True, "trigger": role.trigger_ko, **outcome}


@router.post("/review/timing")
async def review_timing(request: Request, timing_result: dict = Body(embed=True)):
    role = hermes.ROLES["a2_timing"]
    if not hermes.a2_should_review(timing_result):
        return _not_triggered(role)
    outcome = await _run_role(role, timing_result, session_id=f"{getattr(request.state, 'user_id', 'local')}:{role.id}:adhoc")
    return {"role": role.id, "role_name": role.name_ko, "triggered": True, "trigger": role.trigger_ko, **outcome}


@router.post("/review/power-ir")
async def review_power_ir(request: Request, ir_drop_result: dict | None = None, glitch_result: dict | None = None):
    role = hermes.ROLES["a3_power_ir"]
    if not hermes.a3_should_review(ir_drop_result=ir_drop_result, glitch_result=glitch_result):
        return _not_triggered(role)
    payload = {"ir_drop": ir_drop_result, "glitch_power": glitch_result}
    outcome = await _run_role(role, payload, session_id=f"{getattr(request.state, 'user_id', 'local')}:{role.id}:adhoc")
    return {"role": role.id, "role_name": role.name_ko, "triggered": True, "trigger": role.trigger_ko, **outcome}


@router.post("/review/gate")
async def review_gate(request: Request, gate_status: dict, findings: dict = {}):
    """A5 synthesizer, then V verifier — always chained, per trigger_ko."""
    a5 = hermes.ROLES["a5_synth"]
    if not hermes.a5_gate_needs_synthesis(gate_status):
        return {"a5": _not_triggered(a5), "v": None}

    payload = {"gate_status": gate_status, "findings": findings}
    a5_outcome = await _run_role(a5, payload, session_id=f"{getattr(request.state, 'user_id', 'local')}:{a5.id}:adhoc")
    a5_result = {"role": a5.id, "role_name": a5.name_ko, "triggered": True, "trigger": a5.trigger_ko, **a5_outcome}

    if not a5_outcome['available']:
        return {"a5": a5_result, "v": None}

    v = hermes.ROLES["v_verify"]
    v_payload = {**payload, "a5_review": a5_outcome.get("review")}
    v_outcome = await _run_role(v, v_payload, session_id=f"{getattr(request.state, 'user_id', 'local')}:{v.id}:adhoc")
    v_result = {"role": v.id, "role_name": v.name_ko, "triggered": True, "trigger": v.trigger_ko, **v_outcome}

    return {"a5": a5_result, "v": v_result}
