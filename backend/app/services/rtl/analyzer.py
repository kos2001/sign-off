"""Static RTL quality (QoR) analysis — deterministic, no LLM.

Adapted from ai_driven_rtl (src/analyzer.py, src/fsm.py): verilator lint plus
structural checks (SV types, non-blocking in always_ff, reset classification,
unsized literals, CDC regex heuristic, FSM reachability) and a yosys synthesis
layer, scored 0-100 with a letter grade.
"""

import re
from collections import deque
from dataclasses import dataclass

from . import tools

# ---------------------------------------------------------------------------
# Structure extraction
# ---------------------------------------------------------------------------
_MODULE_RE = re.compile(r"\bmodule\s+(\w+)")
_PORT_RE = re.compile(
    r"\b(input|output|inout)\b\s+"
    r"(?:(wire|reg|logic|bit)\s+)?"
    r"(?:(signed|unsigned)\s+)?"
    r"(\[[^\]]*\]\s*)?"
    r"(\w+)"
)
_RST_NAME_RE = re.compile(r"\b(\w*(?:rst|reset)\w*)\b", re.I)
_ALWAYS_FF_RE = re.compile(r"always_ff\s*@\s*\(([^)]*)\)")
_CLK_IN_SENS_RE = re.compile(r"(?:pos|neg)edge\s+(\w+)")
_ENUM_RE = re.compile(r"\benum\b[^{}]*\{([^}]*)\}", re.S)
_CASE_RE = re.compile(r"\bcase\s*\(\s*([\w.]+)\s*\)(.*?)\bendcase", re.S)
_RESET_STATE_RE = re.compile(
    r"\b(?:!|~)?\s*\w*(?:rst|reset)\w*[^;]*?\b(\w+)\s*<=\s*(\w+)\s*;", re.I | re.S
)


@dataclass
class Check:
    id: str
    severity: str  # "error" | "warn" | "info"
    ok: bool
    detail: str


def extract_ports(code: str) -> list[dict]:
    ports = []
    seen = set()
    for m in _PORT_RE.finditer(code):
        direction, _typ, _sign, width, name = m.groups()
        if name in seen or name in {"wire", "reg", "logic", "bit"}:
            continue
        seen.add(name)
        ports.append({"name": name, "direction": direction, "width": (width or "").strip()})
    return ports


def reset_analysis(code: str) -> dict:
    """Classify the reset: present?, async vs sync, active level."""
    names = set(_RST_NAME_RE.findall(code))
    rst = next((n for n in sorted(names) if re.fullmatch(r"\w*(rst|reset)\w*", n, re.I)), None)
    if not rst:
        return {"present": False, "kind": "none", "active": "unknown", "signal": None}

    kind = "async" if re.search(rf"(?:pos|neg)edge\s+{re.escape(rst)}\b", code) else "sync"
    active = "unknown"
    if (
        re.search(rf"negedge\s+{re.escape(rst)}\b", code)
        or re.search(rf"!\s*{re.escape(rst)}\b", code)
        or rst.lower().endswith("_n")
    ):
        active = "low"
    elif re.search(rf"posedge\s+{re.escape(rst)}\b", code) or re.search(
        rf"\bif\s*\(\s*{re.escape(rst)}\s*\)", code
    ):
        active = "high"
    return {"present": True, "kind": kind, "active": active, "signal": rst}


def cdc_analysis(code: str) -> dict:
    """Regex CDC heuristic: a signal registered in one clock domain and read in
    a block clocked by another, minus name-based 2-FF synchronizer hints
    (sig_meta / sig_sync / ...). Reports risks, not proofs."""
    blocks = []
    matches = list(_ALWAYS_FF_RE.finditer(code))
    for i, m in enumerate(matches):
        sens = m.group(1)
        clk_m = _CLK_IN_SENS_RE.search(sens)
        clk = clk_m.group(1) if clk_m else None
        if clk and re.search(r"rst|reset", clk, re.I):
            clks = _CLK_IN_SENS_RE.findall(sens)
            clk = next((c for c in clks if not re.search(r"rst|reset", c, re.I)), clk)
        end = matches[i + 1].start() if i + 1 < len(matches) else len(code)
        blocks.append((clk, code[m.end() : end]))

    clocks = sorted({c for c, _ in blocks if c})
    driven: dict[str, str] = {}
    for clk, body in blocks:
        if not clk:
            continue
        for sig in re.findall(r"(\w+)\s*<=", body):
            driven.setdefault(sig, clk)

    crossings = []
    seen = set()
    for clk, body in blocks:
        if not clk:
            continue
        for sig in set(re.findall(r"\b(\w+)\b", body)):
            src = driven.get(sig)
            if src and src != clk and sig != clk:
                if re.search(rf"{re.escape(sig)}_(sync|meta|ff2|q2|r2)\b", body):
                    continue  # synchronizer naming hint
                key = (sig, src, clk)
                if key not in seen:
                    seen.add(key)
                    crossings.append({"signal": sig, "from": src, "to": clk})

    return {"clocks": clocks, "multi_clock": len(clocks) > 1, "crossings": crossings}


def fsm_analysis(code: str) -> dict:
    """FSM reachability / dead-end heuristic over enum + case(state) patterns."""
    m = _ENUM_RE.search(code)
    states = []
    if m:
        for item in m.group(1).split(","):
            name = item.strip().split("=")[0].strip()
            if re.fullmatch(r"[A-Za-z_]\w*", name):
                states.append(name)
    case_m = _CASE_RE.search(code)
    if len(states) < 2 or not case_m:
        return {"has_fsm": False, "states": states, "unreachable": [], "dead_ends": []}

    state_set = set(states)
    case_body = case_m.group(2)
    label_re = re.compile(r"(\b(?:" + "|".join(map(re.escape, states)) + r")\b)\s*:")
    marks = [(mm.group(1), mm.end()) for mm in label_re.finditer(case_body)]
    transitions: dict[str, set] = {s: set() for s in states}
    for i, (st, start) in enumerate(marks):
        nxt = label_re.search(case_body, start)
        body = case_body[start : nxt.start() if nxt else len(case_body)]
        for tgt in re.findall(r"=\s*(\w+)", body):
            if tgt in state_set and tgt != st:
                transitions[st].add(tgt)

    reset_state = states[0]
    for _var, val in _RESET_STATE_RE.findall(code):
        if val in state_set:
            reset_state = val
            break

    reached: set = set()
    q = deque([reset_state])
    while q:
        s = q.popleft()
        if s in reached:
            continue
        reached.add(s)
        q.extend(t for t in transitions.get(s, ()) if t not in reached)

    return {
        "has_fsm": True,
        "states": states,
        "unreachable": sorted(state_set - reached),
        "dead_ends": sorted(s for s in states if not transitions.get(s)),
    }


def _static_checks(code: str) -> list[Check]:
    checks = []
    has_module = bool(_MODULE_RE.search(code))
    checks.append(Check("module_present", "error", has_module,
                        "module declaration found" if has_module else "no module declaration"))

    legacy = re.search(r"\b(reg|wire)\b", code)
    checks.append(Check("sv_types", "warn", legacy is None,
                        "uses SystemVerilog logic types" if legacy is None
                        else "legacy reg/wire present (prefer logic)"))

    has_ff = "always_ff" in code
    has_comb = "always_comb" in code
    has_legacy_always = bool(re.search(r"always\s*@", code))
    checks.append(Check("explicit_always", "warn", not has_legacy_always or (has_ff or has_comb),
                        "uses always_ff/always_comb" if (has_ff or has_comb)
                        else "no always_ff/always_comb blocks"))

    # Blocking assignment inside always_ff is a classic race bug.
    blk_in_ff = bool(
        re.search(r"always_ff\b[^;]*?\bbegin\b.*?[^<]=[^=].*?\bend\b", code, re.S)
    ) and not re.search(r"always_ff\b.*?<=", code, re.S)
    checks.append(Check("ff_nonblocking", "error", not blk_in_ff,
                        "sequential logic uses non-blocking <=" if not blk_in_ff
                        else "blocking '=' inside always_ff (race risk)"))

    has_reset = bool(re.search(r"\brst\w*|\breset\b", code, re.I))
    checks.append(Check("reset_present", "warn", has_reset,
                        "reset signal present" if has_reset else "no reset detected"))

    magic = re.search(r"=\s*\d+\s*;", code) and re.search(r"\[\s*\d+\s*:\s*\d+\s*\]", code)
    checks.append(Check("sized_literals", "info", not magic,
                        "no obvious unsized magic constants" if not magic
                        else "unsized decimal literal in a sized context"))
    return checks


def _grade(score: int) -> str:
    return ("A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70
            else "D" if score >= 60 else "F")


def strict_width_findings(code: str, lint_result: tools.LintResult) -> int:
    """Count WIDTH truncation/expansion findings from the strict lint pass."""
    if not lint_result.available:
        return 0
    options = {'top_module': lint_result.requested_top} if lint_result.requested_top is not None else {}
    wr = tools.lint(code, strict=True, **options)
    lint_result.strict_execution = wr.execution
    return sum(1 for i in wr.issues if "WIDTH" in i.upper())


def design_checks(code: str, width_findings: int) -> tuple[list[Check], dict, dict, dict]:
    """Structural design-rule checks plus reset/FSM/CDC analyses."""
    checks = _static_checks(code)

    if width_findings:
        checks.append(Check("width_clean", "warn", False,
                            f"{width_findings} width mismatch finding(s)"))

    rst = reset_analysis(code)
    if rst["present"]:
        checks.append(Check("reset_classified", "info", True,
                            f"{rst['kind']} reset, active-{rst['active']} ({rst['signal']})"))

    fsm = fsm_analysis(code)
    if fsm["has_fsm"]:
        if fsm["unreachable"]:
            checks.append(Check("fsm_reachable", "warn", False,
                                f"unreachable FSM state(s): {', '.join(fsm['unreachable'])}"))
        if fsm["dead_ends"]:
            checks.append(Check("fsm_no_deadlock", "warn", False,
                                f"dead-end FSM state(s): {', '.join(fsm['dead_ends'])}"))
        if not fsm["unreachable"] and not fsm["dead_ends"]:
            checks.append(Check("fsm_clean", "info", True,
                                f"FSM ok — {len(fsm['states'])} states reachable, no dead ends"))

    cdc = cdc_analysis(code)
    if cdc["crossings"]:
        sigs = ", ".join(c["signal"] for c in cdc["crossings"][:4])
        checks.append(Check("cdc_safe", "error", False,
                            f"{len(cdc['crossings'])} unsynchronized clock-domain crossing(s): {sigs}"))
    elif cdc["multi_clock"]:
        checks.append(Check("cdc_safe", "info", True,
                            f"multi-clock ({len(cdc['clocks'])} domains), no unsynchronized crossing detected"))

    return checks, rst, fsm, cdc


def build_report(
    code: str,
    lr: tools.LintResult,
    width_findings: int,
    sr: tools.SynthResult,
) -> dict:
    """Assemble the QoR report from precomputed tool results (streaming-friendly)."""
    lint_tool = "verilator" if lr.available else "unavailable"
    lint_pass = lr.ok if lr.available else True  # tool absence never fails the design

    checks, rst, fsm, cdc = design_checks(code, width_findings)

    synthesizable = sr.ok if sr.available else None
    if sr.available:
        checks.append(Check("synthesizable", "error", sr.ok,
                            f"synthesizes with yosys (cells={sr.cells}, flops={sr.flops})"
                            if sr.ok else "yosys synthesis failed: " + "; ".join(sr.issues[:2])))
        if sr.latches:
            checks.append(Check("no_inferred_latches", "warn", False,
                                f"{sr.latches} inferred latch(es) in synthesis"))

    # Score: 100 minus severity-weighted failed checks and lint findings.
    sev_weight = {"error": 30, "warn": 12, "info": 4}
    penalty = sum(sev_weight[c.severity] for c in checks if not c.ok)
    if lr.available and not lint_pass:
        penalty += 25
    penalty += min(20, len(lr.issues) * 3 if lr.available else 0)
    score = max(0, 100 - penalty)

    return {
        "module": lr.top or tools.detect_top_module(code),
        "ports": extract_ports(code),
        "checks": checks,
        "score": score,
        "grade": _grade(score),
        "tool_runs": {"lint": lr.execution, "width": lr.strict_execution, "synthesize": sr.execution},
        "lint_tool": lint_tool,
        "lint_pass": lint_pass,
        "lint_available": lr.available,
        "lint_findings": lr.issues,
        "clock_domains": cdc["clocks"],
        "cdc_crossings": cdc["crossings"],
        "reset": rst,
        "fsm": fsm,
        "synth": {
            "available": sr.available,
            "ok": synthesizable,
            "cells": sr.cells,
            "flops": sr.flops,
            "latches": sr.latches,
        },
    }


def analyze(code: str) -> dict:
    """Deterministic QoR report: lint + structural checks + synth + score."""
    code = tools.strip_fences(code)
    lr = tools.lint(code)
    width = strict_width_findings(code, lr)
    sr = tools.synthesize(code)
    return build_report(code, lr, width, sr)
