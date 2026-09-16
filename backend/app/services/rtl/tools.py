"""EDA tool wrappers: verilator lint and yosys synthesis.

Adapted from ai_driven_rtl (src/simulator.py, src/synth.py, src/text_utils.py).
Both degrade gracefully when the tool is not on PATH — callers record the stage
as skipped instead of failing, so the ladder still runs on boxes without an
EDA toolchain.
"""

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .process import run_command
from .artifacts import MAX_NETLIST_BYTES, NetlistArtifact

VERILATOR = "verilator"
YOSYS = "yosys"
TOOL_TIMEOUT = 60
MAX_OUTPUT_BYTES = 128 * 1024

_MODULE_RE = re.compile(r"\bmodule\s+(\w+)\b")
_FENCE_RE = re.compile(r"^```[\w-]*\n|\n?```$", re.M)


def read_regular_output(path: Path, limit: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("output is not a regular file")
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("output exceeds size limit")
    return raw


def read_design_statistics(path: Path) -> tuple[int, int, int]:
    """Read expanded design totals, not the sum of module definitions."""
    raw = read_regular_output(path, MAX_OUTPUT_BYTES)
    data = json.loads(raw)
    design = data["design"]
    cells = design["num_cells"]
    types = design["num_cells_by_type"]
    if type(cells) is not int or cells < 0 or not isinstance(types, dict):
        raise ValueError("invalid design counts")
    if any(type(value) is not int or value < 0 for value in types.values()):
        raise ValueError("invalid cell type count")
    flops = sum(count for name, count in types.items() if re.fullmatch(r"\$_S?DFF\w*", name))
    latches = sum(count for name, count in types.items() if re.fullmatch(r"\$_DLATCH\w*", name))
    if flops + latches > cells:
        raise ValueError("inconsistent design counts")
    return cells, flops, latches


def strip_fences(code: str) -> str:
    return _FENCE_RE.sub("", code).strip()


def detect_top_module(code: str) -> str | None:
    m = _MODULE_RE.search(code)
    return m.group(1) if m else None


def selected_top(code: str, requested: str | None):
    if requested is not None:
        if not isinstance(requested, str) or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]{0,119}', requested) is None:
            raise ValueError('invalid RTL top module')
        return requested
    return detect_top_module(code)


@dataclass
class LintResult:
    ok: bool
    available: bool
    issues: list[str] = field(default_factory=list)
    top: str | None = None
    execution: dict | None = None
    strict_execution: dict | None = None
    requested_top: str | None = None


@dataclass
class SynthResult:
    ok: bool
    available: bool
    cells: int | None = None
    flops: int | None = None
    latches: int | None = None
    netlist: dict | None = None
    execution: dict | None = None
    issues: list[str] = field(default_factory=list)


def verilator_available() -> bool:
    return shutil.which(VERILATOR) is not None


def yosys_available() -> bool:
    return shutil.which(YOSYS) is not None


def lint(code: str, strict: bool = False, *, top_module: str | None = None) -> LintResult:
    """`verilator --lint-only -Wall` on a single-file SystemVerilog source.

    strict=True keeps the WIDTH truncation/expansion warnings that the default
    pass suppresses (surfaced by the analyzer as a graded finding).
    """
    code = strip_fences(code)
    top = selected_top(code, top_module)
    if not verilator_available():
        return LintResult(ok=False, available=False, issues=["verilator not installed"], top=top, requested_top=top_module)
    if not code:
        return LintResult(ok=False, available=True, issues=["empty source"], top=top, requested_top=top_module)

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
        cmd += ["--timing", "design.sv"]
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
    return LintResult(ok=ok, available=True, issues=issues, top=top, execution={"command": cmd, **proc}, requested_top=top_module)


def synthesize(code: str, *, top_module: str | None = None) -> SynthResult:
    """Generic yosys synthesis pass with gate-level stats (cells/flops/latches)."""
    code = strip_fences(code)
    top = selected_top(code, top_module)
    if not yosys_available():
        return SynthResult(ok=False, available=False, issues=["yosys not installed"])
    if not code:
        return SynthResult(ok=False, available=True, issues=["empty source"])

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "design.sv"
        src.write_text(code if code.endswith("\n") else code + "\n")
        hier = f"hierarchy -simcheck -top {top}" if top else "hierarchy -simcheck -auto-top"
        # Inspect a fully expanded copy: check alone cannot see a loop that
        # crosses module ports. Restore the hierarchy for synthesis/statistics.
        # keep_hierarchy is an optimization preference, not a validation waiver.
        connection_check = (
            "check -assert; design -push-copy; "
            "setattr -mod -unset keep_hierarchy; setattr -unset keep_hierarchy; "
            "flatten -wb; check -assert; design -pop"
        )
        script = (
            f"read_verilog -sv design.sv; {hier}; proc; {connection_check}; "
            f"opt; techmap; opt; {connection_check}; tee -o stats.json stat -json; write_verilog -noattr netlist.v"
        )
        cmd = [YOSYS, '-p', script]
        proc = run_command(cmd, td, timeout_seconds=TOOL_TIMEOUT, max_output_bytes=MAX_OUTPUT_BYTES)
        counts = (None, None, None)
        statistics_error = None
        netlist = None
        if proc['exit_code'] == 0 and proc['error'] is None:
            try:
                counts = read_design_statistics(Path(td) / "stats.json")
                raw_netlist = read_regular_output(Path(td) / "netlist.v", MAX_NETLIST_BYTES)
                netlist = NetlistArtifact(format='yosys-generic-verilog/v1', text=raw_netlist.decode('utf-8'),
                                          sha256=hashlib.sha256(raw_netlist).hexdigest(),
                                          byte_length=len(raw_netlist)).model_dump()
            except (OSError, ValueError, KeyError, TypeError, RecursionError):
                statistics_error = "yosys: design statistics or netlist unavailable or invalid"

    raw = proc['log']
    ok = proc['exit_code'] == 0 and proc['error'] is None
    issues = []
    if not ok:
        issues = [line.strip() for line in raw.splitlines() if line.startswith(('ERROR', 'Warning:')) or '%Error' in line][:8]
    if proc['error']:
        issues.append(f"yosys: {proc['error']}")

    if statistics_error:
        counts = (None, None, None)
        ok = False
        issues.append(statistics_error)

    return SynthResult(
        ok=ok,
        available=True,
        cells=counts[0],
        flops=counts[1],
        latches=counts[2],
        netlist=netlist,
        issues=issues or ([] if ok else ["synthesis failed"]),
        execution={"command": cmd, **proc},
    )
