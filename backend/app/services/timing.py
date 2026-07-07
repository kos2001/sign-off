"""MMMC timing signoff summary.

Aggregates endpoint slacks per corner (WNS / TNS / violating endpoints) and
merges corners endpoint-wise (worst slack across corners), the standard
multi-mode multi-corner signoff view. Optionally applies a uniform GBA->PBA
pessimism credit: PBA slack is never worse than GBA slack, so a credit on
failing endpoints estimates how many violations are GBA pessimism artifacts
(the trade-off behind ML-based PBA estimation, e.g. Synopsys US 12,124,782).
"""


def _stats(slacks: list[float]) -> dict:
    violating = [s for s in slacks if s < 0]
    return {
        "wns_ps": round(min(slacks), 3),
        "tns_ps": round(sum(violating), 3),
        "violating_endpoints": len(violating),
        "total_endpoints": len(slacks),
    }


def summarize_corners(
    corners: list[dict],
    pba_pessimism_credit_ps: float = 0.0,
) -> dict:
    """Summarize STA results across corners.

    Each corner dict: ``name`` and ``endpoint_slacks_ps``. All corners must
    report the same endpoints in the same order (equal-length lists), which is
    what makes the endpoint-wise MMMC merge meaningful.
    """
    if not corners:
        raise ValueError("corners must not be empty")
    if pba_pessimism_credit_ps < 0:
        raise ValueError("pba_pessimism_credit_ps must be non-negative")

    lengths = {len(c["endpoint_slacks_ps"]) for c in corners}
    if lengths == {0}:
        raise ValueError("endpoint_slacks_ps must not be empty")
    if len(lengths) != 1:
        raise ValueError("all corners must report the same number of endpoints")

    per_corner = [
        {"name": c["name"], **_stats([float(s) for s in c["endpoint_slacks_ps"]])}
        for c in corners
    ]

    merged_slacks = [
        min(float(c["endpoint_slacks_ps"][i]) for c in corners)
        for i in range(lengths.pop())
    ]
    merged = _stats(merged_slacks)

    result = {
        "corners": per_corner,
        "merged": merged,
        "signoff_clean": merged["violating_endpoints"] == 0,
    }

    if pba_pessimism_credit_ps > 0:
        # PBA can only improve on GBA: credit applies to failing endpoints only,
        # and a passing GBA endpoint stays passing.
        pba_slacks = [
            s + pba_pessimism_credit_ps if s < 0 else s for s in merged_slacks
        ]
        recovered = sum(1 for s, p in zip(merged_slacks, pba_slacks) if s < 0 <= p)
        result["estimated_pba"] = {
            "pessimism_credit_ps": pba_pessimism_credit_ps,
            **_stats(pba_slacks),
            "recovered_endpoints": recovered,
        }

    return result
