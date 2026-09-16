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
from .simulation import simulate
from .analyzer import build_report, design_checks, strict_width_findings
from ..evidence import rtl_result_status

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
    simulation: dict = field(default_factory=dict)
    top_module_requested: str | None = None

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "score": self.score,
            "grade": self.grade,
            "module": self.module,
            "top_module_requested": self.top_module_requested,
            "stages": [
                {"name": s.name, "status": s.status, "gating": s.gating, "detail": s.detail}
                for s in self.stages
            ],
            "rules": self.rules,
            "suggestions": self.suggestions,
            "simulation": self.simulation,
            "netlist": self.report.get("netlist"),
            "tool_runs": self.report.get("tool_runs", {}),
        }


def _verdict(stages: list[LadderStage]) -> str:
    status = rtl_result_status({"verdict": "SIGNED_OFF", "stages": [vars(stage) for stage in stages]})
    return {"passed": "SIGNED_OFF", "failed": "REJECTED", "incomplete": "CONDITIONAL"}[status.value]


def _suggestions(stages: list[LadderStage]) -> list[str]:
    out = []
    for s in stages:
        if s.name == "lint" and s.status == "fail":
            out.append(f"Fix the lint errors first ({s.detail}) — they block everything downstream.")
        elif s.name == "design" and s.status == "fail":
            out.append(f"Resolve the design-rule violation: {s.detail}. Add a synchronizer for a "
                       "CDC, or correct reset/blocking-assignment issues, then re-run.")
        elif s.name == "synthesize" and s.status == "fail":
            out.append("Synthesis validation failed. Review the Yosys diagnostics for unsupported RTL, "
                       "missing modules or blackboxes, undriven/conflicting drivers, logic loops, "
                       "or unavailable statistics. Correct the reported cause and re-run.")
        elif s.name == "simulate" and s.status == "fail":
            out.append("Review the testbench compile/runtime logs, fix the failure, and re-run all checks.")
        elif s.gating and s.status == "skip":
            out.append(f"Stage '{s.name}' was skipped ({s.detail}) — provide it to make the "
                       "verdict unconditional.")
    return out


def _lint_stage(lr: tools.LintResult) -> LadderStage:
    if not lr.available:
        return LadderStage("lint", "skip", gating=True, detail="verilator not installed")
    return LadderStage(
        "lint", "pass" if lr.ok else "fail", gating=True,
        detail=f"verilator: {len(lr.issues)} finding(s)" + ("; " + "; ".join(lr.issues[:8]) if lr.issues else ""),
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
        detail="scope=selected design hierarchy; " + " ".join(
            f"{name}={value if value is not None else 'unknown'}"
            for name, value in (("cells", sr.cells), ("flops", sr.flops), ("latches", sr.latches))
        ) + ("; " + "; ".join(sr.issues[:8]) if sr.issues else ""),
    )



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


def run_signoff(rtl_code: str, testbench: str | None = None, testbench_top: str | None = None, *, top_module: str | None = None) -> SignoffResult:
    """Run the full ladder at once and return the consolidated result."""
    options = {"top_module": top_module} if top_module is not None else {}
    code = tools.strip_fences(rtl_code)
    lr = tools.lint(code, **options)
    width = strict_width_findings(code, lr)
    sr = tools.synthesize(code, **options)
    report = build_report(code, lr, width, sr)
    simulation = simulate(code, testbench, testbench_top)
    stages = [
        _lint_stage(lr),
        _design_stage(report["checks"]),
        _synth_stage(sr),
        LadderStage("simulate", simulation["status"], True, simulation["detail"]),
    ]
    result = _build_result(report, stages)
    result.simulation = simulation
    result.top_module_requested = top_module
    return result


def stream_signoff(rtl_code: str, testbench: str | None = None, testbench_top: str | None = None, *, top_module: str | None = None) -> Iterator[dict]:
    """Run the ladder stage by stage, yielding progress events as each real
    tool executes, ending with the consolidated result:

      {"event": "stage_start", "stage": "lint"}
      {"event": "stage_done", "stage": "lint", "status": "pass", "detail": ...}
      ...
      {"event": "result", "result": {<SignoffResult.to_dict()>}}
    """
    options = {"top_module": top_module} if top_module is not None else {}
    code = tools.strip_fences(rtl_code)

    yield {"event": "stage_start", "stage": "lint"}
    lr = tools.lint(code, **options)
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
    sr = tools.synthesize(code, **options)
    synth_stage = _synth_stage(sr)
    yield {"event": "stage_done", "stage": "synthesize",
           "status": synth_stage.status, "detail": synth_stage.detail}

    yield {"event": "stage_start", "stage": "simulate"}
    simulation = simulate(code, testbench, testbench_top)
    simulation_stage = LadderStage("simulate", simulation["status"], True, simulation["detail"])
    yield {"event": "stage_done", "stage": "simulate",
           "status": simulation_stage.status, "detail": simulation_stage.detail}

    report = build_report(code, lr, width, sr)
    result = _build_result(report, [lint_stage, design_stage, synth_stage, simulation_stage])
    result.simulation = simulation
    result.top_module_requested = top_module
    yield {"event": "result", "result": result.to_dict()}
