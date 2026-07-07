"""Vectorless glitch power estimation.

Simplified form of the timing-window approach in Synopsys patent US 12,001,768:
the glitch toggle rate of a net is the excess of its total toggle rate over its
functional toggle rate, and only transport (propagating) glitches burn dynamic
power downstream. Dynamic power per net: P = 0.5 * C * Vdd^2 * f * toggle_rate.
"""


def estimate_glitch_power(
    nets: list[dict],
    vdd: float = 0.75,
    clock_period_ns: float = 1.0,
) -> dict:
    """Estimate functional vs glitch dynamic power for a set of nets.

    Each net dict: ``name`` (optional), ``cap_ff`` (load capacitance, fF),
    ``functional_toggle_rate`` and ``total_toggle_rate`` (toggles per clock
    cycle), ``transport_fraction`` (fraction of glitches that propagate,
    default 1.0 = worst case).
    """
    if vdd <= 0:
        raise ValueError("vdd must be positive")
    if clock_period_ns <= 0:
        raise ValueError("clock_period_ns must be positive")
    if not nets:
        raise ValueError("nets must not be empty")

    freq_hz = 1.0 / (clock_period_ns * 1e-9)
    per_net = []
    total_functional_w = 0.0
    total_glitch_w = 0.0

    for i, net in enumerate(nets):
        cap_ff = float(net["cap_ff"])
        functional = float(net["functional_toggle_rate"])
        total = float(net["total_toggle_rate"])
        transport_fraction = float(net.get("transport_fraction", 1.0))

        if cap_ff <= 0:
            raise ValueError(f"net[{i}]: cap_ff must be positive")
        if functional < 0 or total < 0:
            raise ValueError(f"net[{i}]: toggle rates must be non-negative")
        if not 0.0 <= transport_fraction <= 1.0:
            raise ValueError(f"net[{i}]: transport_fraction must be within [0, 1]")

        glitch_rate = max(0.0, total - functional)
        effective_glitch_rate = glitch_rate * transport_fraction

        energy_per_toggle_j = 0.5 * cap_ff * 1e-15 * vdd * vdd
        functional_w = energy_per_toggle_j * functional * freq_hz
        glitch_w = energy_per_toggle_j * effective_glitch_rate * freq_hz

        total_functional_w += functional_w
        total_glitch_w += glitch_w
        per_net.append(
            {
                "name": net.get("name", f"net_{i}"),
                "glitch_toggle_rate": round(glitch_rate, 6),
                "functional_power_uw": round(functional_w * 1e6, 6),
                "glitch_power_uw": round(glitch_w * 1e6, 6),
            }
        )

    total_w = total_functional_w + total_glitch_w
    return {
        "vdd": vdd,
        "clock_period_ns": clock_period_ns,
        "net_count": len(nets),
        "functional_power_mw": round(total_functional_w * 1e3, 6),
        "glitch_power_mw": round(total_glitch_w * 1e3, 6),
        "total_dynamic_power_mw": round(total_w * 1e3, 6),
        "glitch_share": round(total_glitch_w / total_w, 4) if total_w > 0 else 0.0,
        "nets": per_net,
    }
