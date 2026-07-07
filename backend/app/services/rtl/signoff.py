"""RTL sign-off ladder with a consolidated verdict.

Adapted from ai_driven_rtl (src/signoff.py, src/drc.py):

  1. lint        — verilator static elaboration (gating)
  2. design      — coded design-rule checks incl. CDC / non-blocking (gating)
  3. synthesize  — yosys generic synthesis must succeed (gating)
  4. simulate    — needs a testbench; without one it is skipped

SIGNED_OFF requires every applicable gating stage to pass. A skipped gating
stage (missing tool or no testbench) downgrades to CONDITIONAL; any gating
failure is REJECTED. Findings carry SpyGlass-style DRC rule codes so they can
be filed as violations against a signoff run.
"""

from dataclasses import dataclass, field

from .analyzer import analyze

DRC_RULES = {
    "module_present":     ("DRC-STRUCT-001", "Module declaration present"),
    "sv_types":           ("DRC-STYLE-001", "Use SystemVerilog logic types"),
    "explicit_always":    ("DRC-STYLE-002", "Use always_ff/always_comb"),
    "ff_nonblocking":     ("DRC-SEQ-001", "Non-blocking assignment in sequential logic"),
    "reset_present":      ("DRC-RST-001", "Reset present"),
    "reset_classified":   ("DRC-RST-002", "Reset classified (sync/async, level)"),
    "sized_literals":     ("DRC-WIDTH-001", "No unsized magic constants"),
    "width_clean":        ("DRC-WIDTH-002", "No width truncation/expansion"),
    "synthesizable":      ("DRC-SYNTH-001", "Synthesizable"),
    "no_inferred_latches": ("DRC-LATCH-001", "No inferred latches"),
    "cdc_safe":           ("DRC-CDC-001", "No unsynchronized clock-domain crossing"),
    "fsm_reachable":      ("DRC-FSM-001", "All FSM states reachable"),
    "fsm_no_deadlock":    ("DRC-FSM-002", "No FSM dead-end states"),
    "fsm_clean":          ("DRC-FSM-003", "FSM well-formed"),
}


@dataclass
class LadderStage:
    name: str
    status: str  # "pass" | "fail" | "skip"
    gating: bool
    detail: str = ""


@dataclass
class SignoffResult:
    verdict: str  # "SIGNED_OFF" | "CONDITIONAL" | "REJECTED"
    score: int
    grade: str
    module: str | None
    stages: list[LadderStage] = field(default_factory=list)
    rules: list[dict] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    report: dict = field(default_factory=dict)


def _verdict(stages: list[LadderStage]) -> str:
    gating = [s for s in stages if s.gating]
    if any(s.status == "fail" for s in gating):
        return "REJECTED"
    if any(s.status == "skip" for s in gating):
        return "CONDITIONAL"
    return "SIGNED_OFF"


def _suggestions(stages: list[LadderStage]) -> list[str]:
    out = []
    for s in stages:
        if s.name == "lint" and s.status == "fail":
            out.append(f"Fix the lint errors first ({s.detail}) — they block everything downstream.")
        elif s.name == "design" and s.status == "fail":
            out.append(f"Resolve the design-rule violation: {s.detail}. Add a synchronizer for a "
                       "CDC, or correct reset/blocking-assignment issues, then re-run.")
        elif s.name == "synthesize" and s.status == "fail":
            out.append("RTL does not synthesize — remove unsynthesizable constructs and check for "
                       "inferred latches (drive every output on every path).")
        elif s.gating and s.status == "skip":
            out.append(f"Stage '{s.name}' was skipped ({s.detail}) — provide it to make the "
                       "verdict unconditional.")
    return out


def run_signoff(rtl_code: str) -> SignoffResult:
    report = analyze(rtl_code)
    stages: list[LadderStage] = []

    # 1. lint
    if not report["lint_available"]:
        stages.append(LadderStage("lint", "skip", gating=True, detail="verilator not installed"))
    else:
        stages.append(LadderStage(
            "lint", "pass" if report["lint_pass"] else "fail", gating=True,
            detail=f"verilator: {len(report['lint_findings'])} finding(s)",
        ))

    # 2. design — error-severity structural checks gate (synthesizable is stage 3)
    failing_errors = [
        c for c in report["checks"]
        if c.severity == "error" and not c.ok and c.id != "synthesizable"
    ]
    stages.append(LadderStage(
        "design", "pass" if not failing_errors else "fail", gating=True,
        detail="; ".join(c.detail for c in failing_errors) or "structural checks ok",
    ))

    # 3. synthesize
    synth = report["synth"]
    if not synth["available"]:
        stages.append(LadderStage("synthesize", "skip", gating=True, detail="yosys not installed"))
    else:
        stages.append(LadderStage(
            "synthesize", "pass" if synth["ok"] else "fail", gating=True,
            detail=f"cells={synth['cells']} flops={synth['flops']} latches={synth['latches']}",
        ))

    # 4. simulate — testbench integration not wired here; skipped (gating)
    stages.append(LadderStage("simulate", "skip", gating=True, detail="no testbench available"))

    rules = []
    for c in report["checks"]:
        code_id, name = DRC_RULES.get(c.id, (f"DRC-GEN-{c.id.upper()}", c.id))
        rules.append({
            "code": code_id,
            "name": name,
            "severity": c.severity,
            "status": "pass" if c.ok else "violation",
            "detail": c.detail,
        })

    verdict = _verdict(stages)
    return SignoffResult(
        verdict=verdict,
        score=report["score"],
        grade=report["grade"],
        module=report["module"],
        stages=stages,
        rules=rules,
        suggestions=_suggestions(stages) if verdict != "SIGNED_OFF" else [],
        report=report,
    )
