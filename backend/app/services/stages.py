"""Shift-left signoff stage gates.

Signoff checks are no longer a single final step: each design stage has a set
of domains that must have a passing run before the design advances. The matrix
below encodes that shift-left policy: RTL-quality signoff (lint/CDC/synth
ladder) plus early timing at RTL, glitch power from
synthesis (vectorless estimation needs no simulation vectors), IR/PV screening
from placement, and the full multi-physics set (including thermal) at final
signoff.
"""

from sqlalchemy import select

from ..models import Domain, ProjectSignoffPlanRevision, RunStatus, Severity, SignoffRun, Stage, ViolationStatus
from .evidence import rtl_result_status

REQUIRED_DOMAINS: dict[Stage, tuple[Domain, ...]] = {
    Stage.rtl: (Domain.rtl, Domain.cdc, Domain.sta),
    Stage.synthesis: (Domain.sta, Domain.glitch_power, Domain.lec, Domain.dft),
    Stage.placement: (Domain.sta, Domain.emir, Domain.pv),
    Stage.routing: (Domain.sta, Domain.emir, Domain.pv, Domain.lvs),
    Stage.final: (Domain.sta, Domain.emir, Domain.pv, Domain.lvs, Domain.lec, Domain.dft, Domain.glitch_power, Domain.thermal),
}

BLOCKING_SEVERITIES = (Severity.error, Severity.critical)


def resolve_signoff_plan(db, project_id: int, stage: Stage) -> dict:
    revision = db.scalar(select(ProjectSignoffPlanRevision).where(
        ProjectSignoffPlanRevision.project_id == project_id,
        ProjectSignoffPlanRevision.stage == stage,
    ).order_by(ProjectSignoffPlanRevision.version.desc()).limit(1))
    if revision is None:
        domains = REQUIRED_DOMAINS[stage]
        return {
            "stage": stage.value, "version": 0, "source": "default",
            "required_domains": [domain.value for domain in domains], "reason": None,
            "updated_by": None, "updated_by_user_id": None, "created_at": None,
        }
    domains = tuple(Domain(value) for value in revision.required_domains)
    return {
        "stage": stage.value, "version": revision.version, "source": "custom",
        "required_domains": [domain.value for domain in domains], "reason": revision.reason,
        "updated_by": revision.updated_by, "updated_by_user_id": revision.updated_by_user_id,
        "created_at": revision.created_at,
    }


def evaluate_gate(runs: list[SignoffRun], stage: Stage, plan: dict | None = None) -> dict:
    """Evaluate whether a project's signoff gate is ready at the given stage.

    Use latest runs only. Captured coverage and matching declared revisions are
    necessary; manual status changes are not verification evidence.
    """
    plan = plan or {
        "stage": stage.value, "version": 0, "source": "default",
        "required_domains": [domain.value for domain in REQUIRED_DOMAINS[stage]],
        "reason": None, "updated_by": None, "updated_by_user_id": None, "created_at": None,
    }
    required_domains = tuple(Domain(value) for value in plan["required_domains"])
    domains = []
    for domain in required_domains:
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
            if v.severity in BLOCKING_SEVERITIES
            and (v.status == ViolationStatus.open
                 or (v.status == ViolationStatus.waived
                     and (v.waiver is None or not v.waiver.active)))
        ]
        inactive_waivers = sum(
            v.status == ViolationStatus.waived and (v.waiver is None or not v.waiver.active)
            for v in latest.violations if v.severity in BLOCKING_SEVERITIES
        )
        evidence_result = latest.evidence.result if latest.evidence_source == "rtl_ladder" else latest.metrics
        attested_source = {
            Domain.sta: 'commercial_sta_report',
            Domain.pv: 'commercial_drc_report',
            Domain.emir: 'commercial_emir_report',
            Domain.glitch_power: 'commercial_power_report',
            Domain.thermal: 'commercial_thermal_report',
            Domain.rtl: 'commercial_rtl_report',
            Domain.lvs: 'commercial_lvs_report',
            Domain.lec: 'commercial_lec_report',
            Domain.cdc: 'commercial_cdc_report',
            Domain.dft: 'commercial_dft_report',
        }.get(latest.domain)
        attested_coverage = bool(
            attested_source
            and latest.evidence_source == attested_source
            and latest.evidence
            and latest.evidence.result.get('coverage_attestation', {}).get('verified') is True
            and latest.evidence.result.get('coverage') == 'collector_attested_complete'
        )
        if latest.domain == Domain.rtl and latest.evidence_source != "rtl_ladder" and not attested_coverage:
            reason = "RTL requires captured ladder evidence; rerun the analysis"
            ready = False
        elif latest.evidence_source in {'opensta_report', 'opensta_execution', 'commercial_sta_report'} and not attested_coverage:
            reason = ('Executed path sample does not establish full STA coverage' if latest.evidence_source == 'opensta_execution'
                      else 'Imported path report does not establish full STA coverage')
            ready = False
        elif latest.evidence_source in {'klayout_report', 'commercial_drc_report'} and not attested_coverage:
            reason = 'Imported marker report does not establish full DRC coverage'
            ready = False
        elif latest.evidence_source == 'commercial_emir_report' and not attested_coverage:
            reason = 'Imported power-integrity findings do not establish full EM/IR coverage'
            ready = False
        elif latest.evidence_source == 'commercial_power_report' and not attested_coverage:
            reason = 'Imported power summary does not establish full activity and mode coverage'
            ready = False
        elif latest.evidence_source == 'commercial_thermal_report' and not attested_coverage:
            reason = 'Imported thermal hotspots do not establish full thermal coverage'
            ready = False
        elif latest.evidence_source == 'commercial_lvs_report' and not attested_coverage:
            reason = 'Imported LVS result does not establish full LVS coverage'
            ready = False
        elif latest.evidence_source == 'commercial_lec_report' and not attested_coverage:
            reason = 'Imported LEC result does not establish full equivalence coverage'
            ready = False
        elif latest.evidence_source == 'commercial_cdc_report' and not attested_coverage:
            reason = 'Imported CDC/RDC findings do not establish full crossing coverage'
            ready = False
        elif latest.evidence_source == 'commercial_dft_report' and not attested_coverage:
            reason = 'Imported DFT result does not establish full scan and ATPG coverage'
            ready = False
        elif latest.domain == Domain.rtl and latest.evidence_source == 'rtl_ladder' and latest.result_locked and rtl_result_status(evidence_result) != RunStatus.passed:
            reason = f"RTL evidence is {rtl_result_status(evidence_result).value}; required stages must all pass"
            ready = False
        elif latest.status != RunStatus.passed:
            reason = f"latest run status is '{latest.status.value}'"
            ready = False
        elif inactive_waivers:
            reason = f"{inactive_waivers} expired or out-of-scope waiver(s)"
            ready = False
        elif blocking:
            reason = f"{len(blocking)} open blocking violation(s)"
            ready = False
        elif not attested_coverage and (latest.evidence_source != 'rtl_ladder' or latest.domain != Domain.rtl):
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
                "inactive_waivers": inactive_waivers,
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
        "plan": plan,
        "ready": all(d["ready"] for d in domains) and revision_state == 'consistent',
        "domains": domains,
        "revision_check": {"status": revision_state, "revisions": revisions, "missing_domains": missing,
                           "common_revision": revisions[0] if revision_state == 'consistent' else None},
    }
