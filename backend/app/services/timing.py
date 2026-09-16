"""MMMC timing signoff summary.

Aggregates endpoint slacks per corner (WNS / TNS / violating endpoints) and
merges corners endpoint-wise (worst slack across corners), the standard
multi-mode multi-corner signoff view. Optionally applies a uniform GBA->PBA
pessimism credit: PBA slack is never worse than GBA slack, so a credit on
failing endpoints estimates how many violations are GBA pessimism artifacts
(the trade-off behind ML-based PBA estimation, e.g. Synopsys US 12,124,782).
"""

from math import fsum


def _stats(slacks: list[float]) -> dict:
    violating = [s for s in slacks if s < 0]
    return {
        "wns_ps": min(slacks),
        "tns_ps": fsum(violating),
        "violating_endpoints": len(violating),
        "total_endpoints": len(slacks),
    }


def summarize_corners(
    corners: list[dict],
    pba_pessimism_credit_ps: float = 0.0,
) -> dict:
    """Summarize STA results across corners.

    With endpoint_ids, align equal unique endpoint sets regardless of order.
    Without IDs, retain the legacy positional assumption and report it explicitly.
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

    identities = [corner.get('endpoint_ids') for corner in corners]
    has_ids = any(ids is not None for ids in identities)
    if has_ids and not all(ids is not None for ids in identities):
        raise ValueError('all corners must provide endpoint_ids, or all must omit them')
    baseline_ids = identities[0] if has_ids else None
    if has_ids:
        for corner, ids in zip(corners, identities):
            if len(ids) != len(corner['endpoint_slacks_ps']) or len(set(ids)) != len(ids):
                raise ValueError('each corner requires one unique ID per endpoint slack')
            if set(ids) != set(baseline_ids):
                raise ValueError('all corners must report the same endpoint ID set')
        mapped = [dict(zip(ids, corner['endpoint_slacks_ps'])) for corner, ids in zip(corners, identities)]
        aligned = [[float(values[endpoint]) for endpoint in baseline_ids] for values in mapped]
    else:
        aligned = [[float(slack) for slack in corner['endpoint_slacks_ps']] for corner in corners]

    per_corner = [
        {"name": c["name"], **_stats([float(s) for s in c["endpoint_slacks_ps"]])}
        for c in corners
    ]

    merged_slacks = [
        min(values[i] for values in aligned)
        for i in range(lengths.pop())
    ]
    merged = _stats(merged_slacks)

    result = {
        "corners": per_corner,
        "merged": merged,
        "signoff_clean": merged["violating_endpoints"] == 0,
        'endpoint_alignment': 'by_id' if has_ids else 'positional',
        'endpoint_ids': baseline_ids,
        'merged_slacks_ps': merged_slacks,
        'worst_endpoints': [
            {'index': index, 'endpoint_id': baseline_ids[index] if has_ids else None,
             'slack_ps': merged_slacks[index],
             'limiting_corners': [corner['name'] for corner, values in zip(corners, aligned) if values[index] == merged_slacks[index]]}
            for index in sorted(range(len(merged_slacks)), key=lambda i: (merged_slacks[i], i))[:20]
        ],
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
