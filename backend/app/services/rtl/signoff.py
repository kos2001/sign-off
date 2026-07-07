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

from collections.abc import Iterator
from dataclasses import dataclass, field

from . import tools
from .analyzer import build_report, design_checks, strict_width_findings

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

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "score": self.score,
            "grade": self.grade,
            "module": self.module,
            "stages": [
                {"name": s.name, "status": s.status, "gating": s.gating, "detail": s.detail}
                for s in self.stages
            ],
            "rules": self.rules,
            "suggestions": self.suggestions,
        }


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


def _lint_stage(lr: tools.LintResult) -> LadderStage:
    if not lr.available:
        return LadderStage("lint", "skip", gating=True, detail="verilator not installed")
    return LadderStage(
        "lint", "pass" if lr.ok else "fail", gating=True,
        detail=f"verilator: {len(lr.issues)} finding(s)",
    )


def _design_stage(checks) -> LadderStage:
    failing_errors = [
        c for c in checks if c.severity == "error" and not c.ok and c.id != "synthesizable"
    ]
    return LadderStage(
        "design", "pass" if not failing_errors else "fail", gating=True,
        detail="; ".join(c.detail for c in failing_errors) or "structural checks ok",
    )


def _synth_stage(sr: tools.SynthResult) -> LadderStage:
    if not sr.available:
        return LadderStage("synthesize", "skip", gating=True, detail="yosys not installed")
    return LadderStage(
        "synthesize", "pass" if sr.ok else "fail", gating=True,
        detail=f"cells={sr.cells} flops={sr.flops} latches={sr.latches}",
    )


_SIMULATE_SKIP = LadderStage("simulate", "skip", gating=True, detail="no testbench available")


def _build_result(report: dict, stages: list[LadderStage]) -> SignoffResult:
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


def run_signoff(rtl_code: str) -> SignoffResult:
    """Run the full ladder at once and return the consolidated result."""
    code = tools.strip_fences(rtl_code)
    lr = tools.lint(code)
    width = strict_width_findings(code, lr)
    sr = tools.synthesize(code)
    report = build_report(code, lr, width, sr)
    stages = [
        _lint_stage(lr),
        _design_stage(report["checks"]),
        _synth_stage(sr),
        _SIMULATE_SKIP,
    ]
    return _build_result(report, stages)


def stream_signoff(rtl_code: str) -> Iterator[dict]:
    """Run the ladder stage by stage, yielding progress events as each real
    tool executes, ending with the consolidated result:

      {"event": "stage_start", "stage": "lint"}
      {"event": "stage_done", "stage": "lint", "status": "pass", "detail": ...}
      ...
      {"event": "result", "result": {<SignoffResult.to_dict()>}}
    """
    code = tools.strip_fences(rtl_code)

    yield {"event": "stage_start", "stage": "lint"}
    lr = tools.lint(code)
    width = strict_width_findings(code, lr)
    lint_stage = _lint_stage(lr)
    yield {"event": "stage_done", "stage": "lint",
           "status": lint_stage.status, "detail": lint_stage.detail}

    yield {"event": "stage_start", "stage": "design"}
    checks, _rst, _fsm, _cdc = design_checks(code, width)
    design_stage = _design_stage(checks)
    yield {"event": "stage_done", "stage": "design",
           "status": design_stage.status, "detail": design_stage.detail}

    yield {"event": "stage_start", "stage": "synthesize"}
    sr = tools.synthesize(code)
    synth_stage = _synth_stage(sr)
    yield {"event": "stage_done", "stage": "synthesize",
           "status": synth_stage.status, "detail": synth_stage.detail}

    yield {"event": "stage_done", "stage": "simulate",
           "status": _SIMULATE_SKIP.status, "detail": _SIMULATE_SKIP.detail}

    report = build_report(code, lr, width, sr)
    result = _build_result(report, [lint_stage, design_stage, synth_stage, _SIMULATE_SKIP])
    yield {"event": "result", "result": result.to_dict()}
