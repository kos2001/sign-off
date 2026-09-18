from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import RunOut
from .runs import get_run_or_404

router = APIRouter(tags=["low-power"])
Kind = Literal["all", "power_intent", "isolation", "level_shifter", "retention", "power_switch", "always_on", "pg_connectivity", "power_state"]


@router.get("/runs/{run_id}/low-power-findings")
def findings(run_id: int, kind: Kind = "all",
             severity: Literal["all", "warning", "error", "critical"] = "all",
             q: str = Query("", max_length=200), offset: int = Query(0, ge=0, le=5000),
             limit: int = Query(25, ge=1, le=100), db: Session = Depends(get_db)):
    run = get_run_or_404(run_id, db)
    if run.evidence_source != "commercial_low_power_report":
        raise HTTPException(409, "this run has no imported low-power result")
    result = run.evidence.result
    query = q.casefold()
    items = [item for item in result["items"]
             if (kind == "all" or item["kind"] == kind)
             and (severity == "all" or item["severity"] == severity)
             and (not query or any(query in (item.get(field) or "").casefold()
                                   for field in ("rule", "name", "source_domain", "destination_domain", "object", "message")))]
    return {
        "run": RunOut.model_validate(run), "metadata": result.get("metadata", {}),
        "source_sha256": run.evidence.source_sha256, "design_revision": run.evidence.design_revision,
        "low_power_status": result["low_power_status"], "top": result["top"],
        "error_message": result.get("error_message"), "summary": result["summary"],
        "reported_total": len(result["items"]), "total": len(items), "offset": offset,
        "limit": limit, "items": items[offset:offset + limit],
    }
