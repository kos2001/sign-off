"""Strict exchange format for commercial static low-power verification results."""

import hashlib
import json

from .report_import import reject_constant, unique_object

FORMAT = "signoff/commercial-low-power/v1"
PARSER = "commercial-low-power-json/v1"
TOOLS = {"Synopsys VC LP", "Cadence Conformal Low Power"}
KINDS = {
    "power_intent", "isolation", "level_shifter", "retention", "power_switch",
    "always_on", "pg_connectivity", "power_state",
}


def _text(value, label: str, limit: int, *, optional: bool = False):
    if value is None and optional:
        return None
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or len(value) > limit or any(ord(char) < 32 for char in value)):
        raise ValueError(f"{label}: invalid text")
    return value


def _count(value, label: str) -> int:
    if type(value) is not int or not 0 <= value <= 10**12:
        raise ValueError(f"{label}: invalid count")
    return value


def parse_commercial_low_power(source: str) -> dict:
    raw = source.encode()
    if len(raw) > 2_000_000:
        raise ValueError("report exceeds 2 MB")
    try:
        document = json.loads(source.removeprefix("\ufeff"), object_pairs_hook=unique_object,
                              parse_constant=reject_constant)
    except (ValueError, RecursionError):
        raise ValueError("invalid JSON report (check syntax, duplicate fields and finite numbers)") from None
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise ValueError(f"expected {FORMAT} report")
    tool = document.get("tool")
    if tool not in TOOLS:
        raise ValueError("unsupported commercial low-power tool")
    tool_version = _text(document.get("tool_version"), "tool_version", 80)
    top = _text(document.get("top"), "top", 200)
    status = document.get("status")
    if status not in {"clean", "violations", "error"}:
        raise ValueError("status must be clean, violations or error")

    summary_keys = {"power_domains", "power_states", "domain_crossings", "checked_rules"}
    summary = document.get("summary")
    if not isinstance(summary, dict) or set(summary) != summary_keys:
        raise ValueError("summary must contain the exact low-power count fields")
    normalized_summary = {key: _count(summary[key], f"summary.{key}") for key in summary_keys}

    findings = document.get("findings")
    if not isinstance(findings, list) or len(findings) > 5000:
        raise ValueError("findings must contain at most 5000 entries")
    items = []
    required = {"kind", "severity", "rule", "name", "source_domain", "destination_domain", "object", "message"}
    for index, finding in enumerate(findings, 1):
        if not isinstance(finding, dict) or set(finding) != required:
            raise ValueError(f"finding {index}: expected exact fields")
        kind = finding["kind"]
        severity = finding["severity"]
        if kind not in KINDS or severity not in {"warning", "error", "critical"}:
            raise ValueError(f"finding {index}: unsupported kind or severity")
        identity = {
            "kind": kind,
            "rule": _text(finding["rule"], f"finding {index} rule", 200),
            "name": _text(finding["name"], f"finding {index} name", 500),
            "source_domain": _text(finding["source_domain"], f"finding {index} source_domain", 200, optional=True),
            "destination_domain": _text(finding["destination_domain"], f"finding {index} destination_domain", 200, optional=True),
            "object": _text(finding["object"], f"finding {index} object", 500, optional=True),
        }
        items.append({
            "index": index,
            **identity,
            "severity": severity,
            "message": _text(finding["message"], f"finding {index} message", 2000),
            "fingerprint": hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest(),
        })

    blocking = sum(item["severity"] in {"error", "critical"} for item in items)
    error_message = _text(document.get("error_message"), "error_message", 2000, optional=status != "error")
    if status != "error" and document.get("error_message") is not None:
        raise ValueError("error_message is only valid for an error result")
    if status == "clean" and blocking:
        raise ValueError("clean low-power result cannot contain blocking findings")
    if status == "violations" and not blocking:
        raise ValueError("violations result must contain an error or critical finding")
    metrics = {
        **normalized_summary,
        "reported_findings": len(items),
        "blocking_findings": blocking,
        **{f"{kind}_findings": sum(item["kind"] == kind for item in items) for kind in sorted(KINDS)},
    }
    return {
        "parser": PARSER, "tool": tool, "tool_version": tool_version, "top": top,
        "low_power_status": status, "error_message": error_message,
        "summary": normalized_summary, "items": items, "metrics": metrics,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "coverage": "reported_low_power_findings_only",
        "coverage_note": "Submitted low-power findings only; complete UPF, design, library, power-state and PG checking scope are not established.",
        "status": "failed" if status != "clean" else "incomplete",
    }
