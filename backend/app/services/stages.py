"""Shift-left signoff stage gates.

Signoff checks are no longer a single final step: each design stage has a set
of domains that must have a passing run before the design advances. The matrix
below encodes that shift-left policy: RTL-quality signoff (lint/CDC/synth
ladder) plus early timing at RTL, glitch power from
synthesis (vectorless estimation needs no simulation vectors), IR/PV screening
from placement, and the full multi-physics set (including thermal) at final
signoff.
"""

from ..models import Domain, RunStatus, Severity, SignoffRun, Stage, ViolationStatus
from .evidence import rtl_result_status

REQUIRED_DOMAINS: dict[Stage, tuple[Domain, ...]] = {
    Stage.rtl: (Domain.rtl, Domain.sta),
    Stage.synthesis: (Domain.sta, Domain.glitch_power),
    Stage.placement: (Domain.sta, Domain.emir, Domain.pv),
    Stage.routing: (Domain.sta, Domain.emir, Domain.pv),
    Stage.final: (Domain.sta, Domain.emir, Domain.pv, Domain.glitch_power, Domain.thermal),
}

BLOCKING_SEVERITIES = (Severity.error, Severity.critical)


def evaluate_gate(runs: list[SignoffRun], stage: Stage) -> dict:
    """Evaluate whether a project's signoff gate is ready at the given stage.

    Use latest runs only. Captured coverage and matching declared revisions are
    necessary; manual status changes are not verification evidence.
    """
    domains = []
    for domain in REQUIRED_DOMAINS[stage]:
        candidates = [r for r in runs if r.stage == stage and r.domain == domain]
        latest = max(candidates, key=lambda r: (r.created_at, r.id), default=None)

        if latest is None:
            domains.append(
                {"domain": domain.value, "ready": False, "reason": "no run for this stage", "design_revision": None}
            )
            continue

        blocking = [
            v
            for v in latest.violations
            if v.severity in BLOCKING_SEVERITIES and v.status == ViolationStatus.open
        ]
        evidence_result = latest.evidence.result if latest.evidence_source == "rtl_ladder" else latest.metrics
        if latest.domain == Domain.rtl and latest.evidence_source != "rtl_ladder":
            reason = "RTL requires captured ladder evidence; rerun the analysis"
            ready = False
        elif latest.evidence_source in {'opensta_report', 'opensta_execution', 'commercial_sta_report'}:
            reason = ('Executed path sample does not establish full STA coverage' if latest.evidence_source == 'opensta_execution'
                      else 'Imported path report does not establish full STA coverage')
            ready = False
        elif latest.evidence_source in {'klayout_report', 'commercial_drc_report'}:
            reason = 'Imported marker report does not establish full DRC coverage'
            ready = False
        elif latest.evidence_source == 'commercial_emir_report':
            reason = 'Imported power-integrity findings do not establish full EM/IR coverage'
            ready = False
        elif latest.evidence_source == 'commercial_power_report':
            reason = 'Imported power summary does not establish full activity and mode coverage'
            ready = False
        elif latest.domain == Domain.rtl and latest.result_locked and rtl_result_status(evidence_result) != RunStatus.passed:
            reason = f"RTL evidence is {rtl_result_status(evidence_result).value}; required stages must all pass"
            ready = False
        elif latest.status != RunStatus.passed:
            reason = f"latest run status is '{latest.status.value}'"
            ready = False
        elif blocking:
            reason = f"{len(blocking)} open blocking violation(s)"
            ready = False
        elif latest.evidence_source != 'rtl_ladder' or latest.domain != Domain.rtl:
            reason = 'Captured verification coverage required; manual status is not evidence'
            ready = False
        else:
            reason = None
            ready = True

        domains.append(
            {
                "domain": domain.value,
                "ready": ready,
                "reason": reason,
                "run_id": latest.id,
                "open_blocking_violations": len(blocking),
                "evidence_source": latest.evidence_source,
                "design_revision": latest.evidence.design_revision if latest.evidence else None,
            }
        )

    # Labels are declarations, not cryptographic proof that all tools used the
    # same design. Never select older runs merely to make these labels match.
    revisions = sorted({d['design_revision'] for d in domains if d['design_revision'] and d['design_revision'].strip()})
    missing = [d['domain'] for d in domains if not d['design_revision'] or not d['design_revision'].strip()]
    revision_state = 'mismatch' if len(revisions) > 1 else 'missing' if missing else 'consistent'
    return {
        "stage": stage.value,
        "ready": all(d["ready"] for d in domains) and revision_state == 'consistent',
        "domains": domains,
        "revision_check": {"status": revision_state, "revisions": revisions, "missing_domains": missing,
                           "common_revision": revisions[0] if revision_state == 'consistent' else None},
    }
