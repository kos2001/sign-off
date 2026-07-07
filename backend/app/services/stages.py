"""Shift-left signoff stage gates.

Signoff checks are no longer a single final step: each design stage has a set
of domains that must have a passing run before the design advances. The matrix
below encodes that shift-left policy: early timing at RTL, glitch power from
synthesis (vectorless estimation needs no simulation vectors), IR/PV screening
from placement, and the full multi-physics set (including thermal) at final
signoff.
"""

from ..models import Domain, RunStatus, Severity, SignoffRun, Stage, ViolationStatus

REQUIRED_DOMAINS: dict[Stage, tuple[Domain, ...]] = {
    Stage.rtl: (Domain.sta,),
    Stage.synthesis: (Domain.sta, Domain.glitch_power),
    Stage.placement: (Domain.sta, Domain.emir, Domain.pv),
    Stage.routing: (Domain.sta, Domain.emir, Domain.pv),
    Stage.final: (Domain.sta, Domain.emir, Domain.pv, Domain.glitch_power, Domain.thermal),
}

BLOCKING_SEVERITIES = (Severity.error, Severity.critical)


def evaluate_gate(runs: list[SignoffRun], stage: Stage) -> dict:
    """Evaluate whether a project's signoff gate is ready at the given stage.

    A domain is ready when its latest run at the stage passed and has no open
    (unwaived) error/critical violations.
    """
    domains = []
    for domain in REQUIRED_DOMAINS[stage]:
        candidates = [r for r in runs if r.stage == stage and r.domain == domain]
        latest = max(candidates, key=lambda r: (r.created_at, r.id), default=None)

        if latest is None:
            domains.append(
                {"domain": domain.value, "ready": False, "reason": "no run for this stage"}
            )
            continue

        blocking = [
            v
            for v in latest.violations
            if v.severity in BLOCKING_SEVERITIES and v.status == ViolationStatus.open
        ]
        if latest.status != RunStatus.passed:
            reason = f"latest run status is '{latest.status.value}'"
            ready = False
        elif blocking:
            reason = f"{len(blocking)} open blocking violation(s)"
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
            }
        )

    return {
        "stage": stage.value,
        "ready": all(d["ready"] for d in domains),
        "domains": domains,
    }
