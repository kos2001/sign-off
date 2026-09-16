"""EDA tool wrappers: verilator lint and yosys synthesis.

Adapted from ai_driven_rtl (src/simulator.py, src/synth.py, src/text_utils.py).
Both degrade gracefully when the tool is not on PATH — callers record the stage
as skipped instead of failing, so the ladder still runs on boxes without an
EDA toolchain.
"""

import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .process import run_command

VERILATOR = "verilator"
YOSYS = "yosys"
TOOL_TIMEOUT = 60
MAX_OUTPUT_BYTES = 128 * 1024

_MODULE_RE = re.compile(r"\bmodule\s+(\w+)\b")
_FENCE_RE = re.compile(r"^```[\w-]*\n|\n?```$", re.M)

_CELLS_RE = re.compile(r"^\s*(\d+)\s+cells\s*$", re.M)
_DFF_RE = re.compile(r"^\s*(\d+)\s+\$_S?DFF\w*", re.M)
_LATCH_RE = re.compile(r"^\s*(\d+)\s+\$_DLATCH\w*", re.M)


def strip_fences(code: str) -> str:
    return _FENCE_RE.sub("", code).strip()


def detect_top_module(code: str) -> str | None:
    m = _MODULE_RE.search(code)
    return m.group(1) if m else None


@dataclass
class LintResult:
    ok: bool
    available: bool
    issues: list[str] = field(default_factory=list)
    top: str | None = None


@dataclass
class SynthResult:
    ok: bool
    available: bool
    cells: int = 0
    flops: int = 0
    latches: int = 0
    issues: list[str] = field(default_factory=list)


def verilator_available() -> bool:
    return shutil.which(VERILATOR) is not None


def yosys_available() -> bool:
    return shutil.which(YOSYS) is not None


def lint(code: str, strict: bool = False) -> LintResult:
    """`verilator --lint-only -Wall` on a single-file SystemVerilog source.

    strict=True keeps the WIDTH truncation/expansion warnings that the default
    pass suppresses (surfaced by the analyzer as a graded finding).
    """
    code = strip_fences(code)
    top = detect_top_module(code)
    if not verilator_available():
        return LintResult(ok=False, available=False, issues=["verilator not installed"], top=top)
    if not code:
        return LintResult(ok=False, available=True, issues=["empty source"], top=top)

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "design.sv"
        src.write_text(code if code.endswith("\n") else code + "\n")
        cmd = [
            VERILATOR, "--lint-only", "-Wall",
            "-Wno-DECLFILENAME",
            "-Wno-UNUSEDSIGNAL",
            "-Wno-UNUSEDPARAM",
            "-Wno-EOFNEWLINE",
        ]
        if not strict:
            cmd += ["-Wno-WIDTHEXPAND", "-Wno-WIDTHTRUNC"]
        cmd += ["--timing", str(src)]
        if top:
            cmd += ["--top-module", top]
        proc = run_command(cmd, td, timeout_seconds=TOOL_TIMEOUT, max_output_bytes=MAX_OUTPUT_BYTES)

    raw = proc['log'].strip()
    issues = [line for line in raw.splitlines() if line and ('%Error' in line or '%Warning' in line)]
    if proc['error']:
        issues.append(f"verilator: {proc['error']}")
    ok = proc['exit_code'] == 0 and proc['error'] is None
    if not ok and not issues:
        issues = [f"verilator failed (exit code {proc['exit_code']})"]
    return LintResult(ok=ok, available=True, issues=issues, top=top)


def synthesize(code: str) -> SynthResult:
    """Generic yosys synthesis pass with gate-level stats (cells/flops/latches)."""
    code = strip_fences(code)
    top = detect_top_module(code)
    if not yosys_available():
        return SynthResult(ok=False, available=False, issues=["yosys not installed"])
    if not code:
        return SynthResult(ok=False, available=True, issues=["empty source"])

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "design.sv"
        src.write_text(code if code.endswith("\n") else code + "\n")
        hier = f"hierarchy -top {top}" if top else "hierarchy -auto-top"
        script = f"read_verilog -sv design.sv; {hier}; proc; opt; techmap; opt; stat"
        proc = run_command([YOSYS, '-p', script], td, timeout_seconds=TOOL_TIMEOUT, max_output_bytes=MAX_OUTPUT_BYTES)

    raw = proc['log']
    ok = proc['exit_code'] == 0 and proc['error'] is None
    issues = []
    if not ok:
        issues = [line.strip() for line in raw.splitlines() if line.startswith('ERROR') or '%Error' in line][:8]
    if proc['error']:
        issues.append(f"yosys: {proc['error']}")

    def first_int(rx: re.Pattern) -> int:
        m = rx.search(raw)
        return int(m.group(1)) if m else 0

    return SynthResult(
        ok=ok,
        available=True,
        cells=first_int(_CELLS_RE),
        flops=sum(int(n) for n in _DFF_RE.findall(raw)),
        latches=sum(int(n) for n in _LATCH_RE.findall(raw)),
        issues=issues or ([] if ok else ["synthesis failed"]),
    )
