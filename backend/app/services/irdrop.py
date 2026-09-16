"""Pre-signoff IR-drop screening.

Physics-inspired surrogate model from arXiv:2601.22707: IR-drop is proportional
to cell density x switching activity / PDN strength on a 2D tile grid. This is a
fast screening layer that flags hotspots before a golden EM/IR signoff run
(RedHawk-SC / Voltus) — it does not replace it.
"""

import numpy as np

MAX_REPORTED_HOTSPOTS = 100


def screen_ir_drop(
    cell_density: list[list[float]],
    switching_activity: list[list[float]],
    pdn_strength: list[list[float]],
    vdd: float = 0.75,
    scale: float = 0.1,
    hotspot_threshold_ratio: float = 0.05,
) -> dict:
    """Estimate the IR-drop map (mV) over a tile grid and locate hotspots.

    All three input grids must share the same 2D shape. ``cell_density`` and
    ``switching_activity`` are normalized per-tile values in [0, 1];
    ``pdn_strength`` is a positive relative grid-strength factor (1.0 = nominal).
    A tile is a hotspot when its estimated drop exceeds
    ``vdd * hotspot_threshold_ratio``.
    """
    density = np.asarray(cell_density, dtype=float)
    activity = np.asarray(switching_activity, dtype=float)
    strength = np.asarray(pdn_strength, dtype=float)

    if density.ndim != 2:
        raise ValueError("grids must be 2D")
    if not (density.shape == activity.shape == strength.shape):
        raise ValueError("cell_density, switching_activity and pdn_strength must have the same shape")
    if np.any(strength <= 0):
        raise ValueError("pdn_strength values must be positive")
    if np.any((density < 0) | (density > 1)) or np.any((activity < 0) | (activity > 1)):
        raise ValueError("cell_density and switching_activity values must be within [0, 1]")
    if vdd <= 0:
        raise ValueError("vdd must be positive")

    with np.errstate(over='raise', divide='raise', invalid='raise'):
        drop_v = np.clip(vdd * scale * density * activity / strength, 0.0, vdd)
        drop_mv = drop_v * 1000.0
    threshold_mv = vdd * hotspot_threshold_ratio * 1000.0

    hotspot_indices = np.argwhere(drop_mv > threshold_mv)
    hotspots = sorted(
        (
            {"row": int(r), "col": int(c), "drop_mv": round(float(drop_mv[r, c]), 3)}
            for r, c in hotspot_indices
        ),
        key=lambda h: h["drop_mv"],
        reverse=True,
    )

    return {
        "grid_shape": list(density.shape),
        "vdd": vdd,
        "threshold_mv": round(threshold_mv, 3),
        "worst_drop_mv": round(float(drop_mv.max()), 3),
        "mean_drop_mv": round(float(drop_mv.mean()), 3),
        "hotspot_count": len(hotspots),
        "hotspots": hotspots[:MAX_REPORTED_HOTSPOTS],
        "passed": len(hotspots) == 0,
        "drop_map_mv": np.round(drop_mv, 3).tolist(),
    }
