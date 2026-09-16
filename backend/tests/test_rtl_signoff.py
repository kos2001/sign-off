import pytest

from app.services.rtl import tools
from app.services.rtl.analyzer import analyze, cdc_analysis, fsm_analysis, reset_analysis
from app.services.rtl.signoff import run_signoff

# Ibex-style pulse synchronizer: clean 2-FF CDC, async active-low reset.
GOOD_RTL = """\
module ibex_pulse_sync (
  input  logic clk_src_i,
  input  logic clk_dst_i,
  input  logic rst_ni,
  input  logic pulse_src_i,
  output logic pulse_dst_o
);
  logic toggle_q;
  logic toggle_q_meta, toggle_q_sync, toggle_q_prev;

  always_ff @(posedge clk_src_i or negedge rst_ni) begin
    if (!rst_ni) toggle_q <= 1'b0;
    else if (pulse_src_i) toggle_q <= ~toggle_q;
  end

  always_ff @(posedge clk_dst_i or negedge rst_ni) begin
    if (!rst_ni) begin
      toggle_q_meta <= 1'b0;
      toggle_q_sync <= 1'b0;
      toggle_q_prev <= 1'b0;
    end else begin
      toggle_q_meta <= toggle_q;
      toggle_q_sync <= toggle_q_meta;
      toggle_q_prev <= toggle_q_sync;
    end
  end

  assign pulse_dst_o = toggle_q_sync ^ toggle_q_prev;
endmodule
"""

# Same crossing but no synchronizer: raw domain crossing read.
CDC_BAD_RTL = """\
module bad_cdc (
  input  logic clk_a_i,
  input  logic clk_b_i,
  input  logic rst_ni,
  input  logic d_i,
  output logic q_o
);
  logic src_q;
  always_ff @(posedge clk_a_i or negedge rst_ni) begin
    if (!rst_ni) src_q <= 1'b0;
    else src_q <= d_i;
  end
  always_ff @(posedge clk_b_i or negedge rst_ni) begin
    if (!rst_ni) q_o <= 1'b0;
    else q_o <= src_q;
  end
endmodule
"""

SYNTAX_BAD_RTL = "module broken (input logic a; output logic b)\n  assign b = a\nendmodule\n"


class TestAnalyzer:
    def test_reset_classification(self):
        rst = reset_analysis(GOOD_RTL)
        assert rst == {"present": True, "kind": "async", "active": "low", "signal": "rst_ni"}

    def test_cdc_synchronizer_recognized(self):
        cdc = cdc_analysis(GOOD_RTL)
        assert cdc["multi_clock"] is True
        assert cdc["crossings"] == []

    def test_cdc_raw_crossing_flagged(self):
        cdc = cdc_analysis(CDC_BAD_RTL)
        assert any(c["signal"] == "src_q" for c in cdc["crossings"])

    def test_fsm_dead_end_detected(self):
        code = """
        module fsm (input logic clk_i, input logic rst_ni);
          typedef enum logic [1:0] {IDLE, RUN, STUCK} state_e;
          state_e state_q, state_d;
          always_comb begin
            state_d = state_q;
            case (state_q)
              IDLE:  state_d = RUN;
              RUN:   state_d = STUCK;
              STUCK: ;
            endcase
          end
          always_ff @(posedge clk_i or negedge rst_ni) begin
            if (!rst_ni) state_q <= IDLE;
            else state_q <= state_d;
          end
        endmodule
        """
        fsm = fsm_analysis(code)
        assert fsm["has_fsm"] is True
        assert "STUCK" in fsm["dead_ends"]

    def test_analyze_scores_good_rtl_high(self):
        report = analyze(GOOD_RTL)
        assert report["module"] == "ibex_pulse_sync"
        assert report["score"] >= 80
        assert report["grade"] in ("A", "B")


class TestSignoffLadder:
    def test_good_rtl_not_rejected(self):
        result = run_signoff(GOOD_RTL)
        # simulate stage is always skipped (no testbench) -> at best CONDITIONAL
        assert result.verdict == "CONDITIONAL"
        by_name = {s.name: s for s in result.stages}
        assert by_name["design"].status == "pass"
        assert by_name["simulate"].status == "skip"

    def test_unsynchronized_cdc_rejected(self):
        result = run_signoff(CDC_BAD_RTL)
        assert result.verdict == "REJECTED"
        assert any(r["code"] == "DRC-CDC-001" and r["status"] == "violation"
                   for r in result.rules)

    @pytest.mark.skipif(not tools.verilator_available(), reason="verilator not installed")
    def test_syntax_error_rejected_by_lint(self):
        result = run_signoff(SYNTAX_BAD_RTL)
        assert result.verdict == "REJECTED"
        assert {s.name: s.status for s in result.stages}["lint"] == "fail"


class TestRtlSignoffApi:
    def test_endpoint_records_run_and_violations(self, client):
        pid = client.post(
            "/projects",
            json={"name": "rtl-ladder-chip", "process_node": "SKY130", "foundry": "SkyWater"},
        ).json()["id"]

        resp = client.post(
            "/analysis/rtl-signoff", json={"code": CDC_BAD_RTL, "project_id": pid}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["verdict"] == "REJECTED"
        assert body["run_id"] is not None

        violations = client.get(f"/runs/{body['run_id']}/violations").json()
        assert any(v["check_name"].startswith("DRC-CDC-001") for v in violations)

        # the REJECTED run blocks the RTL stage gate
        gate = client.get(
            f"/projects/{pid}/signoff-status", params={"stage": "rtl"}
        ).json()
        rtl_domain = next(d for d in gate["domains"] if d["domain"] == "rtl")
        assert rtl_domain["ready"] is False

    def test_stream_endpoint_emits_stage_events_then_result(self, client):
        import json

        resp = client.post("/analysis/rtl-signoff/stream", json={"code": GOOD_RTL})
        assert resp.status_code == 200
        events = [json.loads(line) for line in resp.text.strip().splitlines()]

        starts = [e["stage"] for e in events if e["event"] == "stage_start"]
        dones = {e["stage"]: e["status"] for e in events if e["event"] == "stage_done"}
        assert starts == ["lint", "design", "synthesize", "simulate"]
        assert dones["design"] == "pass"
        assert dones["simulate"] == "skip"

        final = events[-1]
        assert final["event"] == "result"
        assert final["result"]["verdict"] == "CONDITIONAL"
        assert final["result"]["module"] == "ibex_pulse_sync"

    def test_stream_endpoint_records_run(self, client):
        import json

        pid = client.post(
            "/projects",
            json={"name": "stream-chip", "process_node": "SKY130", "foundry": "SkyWater"},
        ).json()["id"]
        resp = client.post(
            "/analysis/rtl-signoff/stream", json={"code": CDC_BAD_RTL, "project_id": pid}
        )
        final = json.loads(resp.text.strip().splitlines()[-1])
        assert final["result"]["verdict"] == "REJECTED"
        assert final["result"]["run_id"] is not None

    def test_endpoint_analysis_only(self, client):
        resp = client.post("/analysis/rtl-signoff", json={"code": GOOD_RTL})
        assert resp.status_code == 200
        body = resp.json()
        assert body["verdict"] == "CONDITIONAL"
        assert body["run_id"] is None
        assert body["module"] == "ibex_pulse_sync"
