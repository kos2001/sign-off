import pytest

from app.services.glitch import estimate_glitch_power
from app.services.irdrop import screen_ir_drop
from app.services.timing import summarize_corners


class TestIrDrop:
    def test_hotspot_detected_where_density_and_activity_peak(self):
        result = screen_ir_drop(
            cell_density=[[0.1, 0.9], [0.1, 0.1]],
            switching_activity=[[0.1, 0.9], [0.1, 0.1]],
            pdn_strength=[[1.0, 1.0], [1.0, 1.0]],
            vdd=0.75,
            scale=1.0,
            hotspot_threshold_ratio=0.05,
        )
        assert result["passed"] is False
        assert result["hotspot_count"] == 1
        assert result["hotspots"][0] == {"row": 0, "col": 1, "drop_mv": 607.5}
        assert result["worst_drop_mv"] == 607.5

    def test_strong_pdn_suppresses_drop(self):
        weak = screen_ir_drop([[0.5]], [[0.5]], [[0.5]])
        strong = screen_ir_drop([[0.5]], [[0.5]], [[2.0]])
        assert strong["worst_drop_mv"] < weak["worst_drop_mv"]

    def test_clean_grid_passes(self):
        result = screen_ir_drop([[0.1, 0.1]], [[0.1, 0.1]], [[1.0, 1.0]])
        assert result["passed"] is True
        assert result["hotspots"] == []

    def test_shape_mismatch_rejected(self):
        with pytest.raises(ValueError, match="same shape"):
            screen_ir_drop([[0.1]], [[0.1, 0.2]], [[1.0]])

    def test_nonpositive_pdn_strength_rejected(self):
        with pytest.raises(ValueError, match="positive"):
            screen_ir_drop([[0.1]], [[0.1]], [[0.0]])


class TestGlitchPower:
    def test_glitch_share_matches_toggle_excess(self):
        # total 0.6 vs functional 0.2 -> glitch rate 0.4, share 2/3
        result = estimate_glitch_power(
            nets=[
                {
                    "cap_ff": 10.0,
                    "functional_toggle_rate": 0.2,
                    "total_toggle_rate": 0.6,
                }
            ]
        )
        assert result["glitch_share"] == pytest.approx(2 / 3, abs=1e-3)
        assert result["total_dynamic_power_mw"] == pytest.approx(
            result["functional_power_mw"] + result["glitch_power_mw"]
        )

    def test_inertial_glitches_are_derated(self):
        full = estimate_glitch_power(
            nets=[{"cap_ff": 10.0, "functional_toggle_rate": 0.2, "total_toggle_rate": 0.6}]
        )
        derated = estimate_glitch_power(
            nets=[
                {
                    "cap_ff": 10.0,
                    "functional_toggle_rate": 0.2,
                    "total_toggle_rate": 0.6,
                    "transport_fraction": 0.5,
                }
            ]
        )
        assert derated["nets"][0]["glitch_power_uw"] == pytest.approx(
            full["nets"][0]["glitch_power_uw"] / 2
        )

    def test_total_below_functional_means_no_glitch(self):
        result = estimate_glitch_power(
            nets=[{"cap_ff": 5.0, "functional_toggle_rate": 0.5, "total_toggle_rate": 0.4}]
        )
        assert result["glitch_power_mw"] == 0.0

    def test_invalid_cap_rejected(self):
        with pytest.raises(ValueError, match="cap_ff"):
            estimate_glitch_power(
                nets=[{"cap_ff": 0, "functional_toggle_rate": 0.1, "total_toggle_rate": 0.2}]
            )


class TestTimingSummary:
    CORNERS = [
        {"name": "ss_125c", "endpoint_slacks_ps": [-30.0, 5.0, -10.0]},
        {"name": "ff_m40c", "endpoint_slacks_ps": [12.0, -8.0, 40.0]},
    ]

    def test_per_corner_and_merged_stats(self):
        result = summarize_corners(self.CORNERS)
        ss = result["corners"][0]
        assert ss["wns_ps"] == -30.0
        assert ss["tns_ps"] == -40.0
        assert ss["violating_endpoints"] == 2
        # merged: endpoint-wise min -> [-30, -8, -10]
        assert result["merged"]["wns_ps"] == -30.0
        assert result["merged"]["tns_ps"] == -48.0
        assert result["merged"]["violating_endpoints"] == 3
        assert result["signoff_clean"] is False

    def test_pba_credit_recovers_endpoints(self):
        result = summarize_corners(self.CORNERS, pba_pessimism_credit_ps=15.0)
        pba = result["estimated_pba"]
        # [-30, -8, -10] + 15 on failing endpoints -> [-15, 7, 5]
        assert pba["violating_endpoints"] == 1
        assert pba["recovered_endpoints"] == 2
        assert pba["wns_ps"] == -15.0

    def test_clean_corners(self):
        result = summarize_corners([{"name": "tt", "endpoint_slacks_ps": [1.0, 2.0]}])
        assert result["signoff_clean"] is True
        assert result["merged"]["tns_ps"] == 0.0

    def test_mismatched_endpoint_counts_rejected(self):
        with pytest.raises(ValueError, match="same number of endpoints"):
            summarize_corners(
                [
                    {"name": "a", "endpoint_slacks_ps": [1.0]},
                    {"name": "b", "endpoint_slacks_ps": [1.0, 2.0]},
                ]
            )
