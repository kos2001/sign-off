"""Read-only comparisons of recorded evidence; absence does not prove a fix."""

import math
from collections import defaultdict, deque

from ..models import RunStatus, Severity, SignoffRun, Violation


def waiver_evidence(violation: Violation):
    waiver = violation.waiver
    return (waiver.reason, waiver.approved_by) if waiver else None


def signature(violation: Violation):
    return (violation.severity, violation.status, violation.description, waiver_evidence(violation))


def metric_equal(left, right):
    # JSON booleans are not numbers even though bool subclasses int in Python.
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(metric_equal(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(metric_equal(a, b) for a, b in zip(left, right))
    return left == right


def compare_metrics(baseline: dict, candidate: dict) -> list[dict]:
    rows = []
    for name in sorted(baseline.keys() | candidate.keys()):
        before, after = baseline.get(name), candidate.get(name)
        before_present, after_present = name in baseline, name in candidate
        delta = None
        if before_present and after_present and all(type(v) in (int, float) for v in (before, after)):
            difference = after - before
            # Never emit NaN/Infinity into the JSON response.
            if isinstance(difference, int) or math.isfinite(difference):
                delta = difference
        rows.append({
            "name": name, "baseline": before, "candidate": after,
            "baseline_present": before_present, "candidate_present": after_present,
            "changed": before_present != after_present or not metric_equal(before, after),
            "delta": delta,
        })
    return rows


def compare_runs(baseline: SignoffRun, candidate: SignoffRun) -> dict:
    groups = defaultdict(lambda: ([], []))
    for side, run in enumerate((baseline, candidate)):
        for violation in sorted(run.violations, key=lambda v: v.id):
            groups[(violation.check_name, violation.location)][side].append(violation)
    changes = []

    def add(before, after, ambiguous):
        fields = []
        if before is not None and after is not None:
            fields = [name for name in ("severity", "status", "description") if getattr(before, name) != getattr(after, name)]
            if waiver_evidence(before) != waiver_evidence(after):
                fields.append("waiver")
        kind = "new" if before is None else "removed" if after is None else "changed" if fields else "unchanged"
        changes.append({
            "kind": kind, "baseline": before, "candidate": after,
            "changed_fields": fields, "ambiguous_match": ambiguous,
        })

    for before_group, after_group in groups.values():
        ambiguous = max(len(before_group), len(after_group)) > 1
        # Match identical records first so duplicates don't hide additions or
        # create spurious changes merely because a tool reordered its output.
        exact = defaultdict(deque)
        for after in after_group:
            exact[signature(after)].append(after)
        unmatched_before, matched_after = [], set()
        for before in before_group:
            matches = exact[signature(before)]
            if matches:
                after = matches.popleft()
                matched_after.add(after.id)
                add(before, after, ambiguous)
            else:
                unmatched_before.append(before)
        unmatched_after = [v for v in after_group if v.id not in matched_after]
        pairs = min(len(unmatched_before), len(unmatched_after))
        for before, after in zip(unmatched_before[:pairs], unmatched_after[:pairs]):
            add(before, after, ambiguous)
        for before in unmatched_before[pairs:]:
            add(before, None, ambiguous)
        for after in unmatched_after[pairs:]:
            add(None, after, ambiguous)

    kind_rank = {"new": 0, "changed": 1, "removed": 2, "unchanged": 3}
    severity_rank = {Severity.critical: 0, Severity.error: 1, Severity.warning: 2, Severity.info: 3}
    changes.sort(key=lambda row: (
        kind_rank[row["kind"]], severity_rank[(row["candidate"] or row["baseline"]).severity],
        (row["candidate"] or row["baseline"]).id,
    ))
    def partial_run(run):
        result = run.evidence.result if run.evidence and isinstance(run.evidence.result, dict) else {}
        attested_import = (run.evidence_source in {'commercial_sta_report', 'commercial_drc_report', 'commercial_emir_report',
                                                   'commercial_power_report', 'commercial_thermal_report'}
                           and result.get('coverage') == 'collector_attested_complete'
                           and result.get('coverage_attestation', {}).get('verified') is True)
        imported_partial = run.evidence_source in {
            'commercial_rtl_report', 'opensta_report', 'opensta_execution', 'commercial_sta_report',
            'klayout_report', 'commercial_drc_report', 'commercial_emir_report',
            'commercial_power_report', 'commercial_thermal_report',
        }
        return run.status in (RunStatus.running, RunStatus.incomplete) or imported_partial and not attested_import

    return {
        "baseline_run": baseline, "candidate_run": candidate,
        "baseline_provenance": provenance(baseline), "candidate_provenance": provenance(candidate),
        "partial": any(partial_run(run) for run in (baseline, candidate)),
        "different_tools": baseline.tool != candidate.tool,
        "summary": {kind: sum(row["kind"] == kind for row in changes) for kind in kind_rank},
        "metrics": compare_metrics(baseline.metrics, candidate.metrics),
        "items": changes,
    }


def provenance(run: SignoffRun) -> dict:
    evidence = run.evidence
    result = evidence.result if evidence and isinstance(evidence.result, dict) else {}
    metadata = result.get('metadata')
    metadata = metadata if isinstance(metadata, dict) else {}
    def text(value):
        return value if isinstance(value, str) and value.strip() else None
    return {
        'source': run.evidence_source,
        'design_revision': evidence.design_revision if evidence else None,
        'source_sha256': evidence.source_sha256 if evidence else None,
        'scenario': text(metadata.get('scenario')),
        'tool_version': text(metadata.get('tool_version')),
        'coverage': text(result.get('coverage')),
    }
