"""app/routers/agents.py — trigger gating and graceful hermes-unreachable degrade."""


def test_rtl_review_not_triggered_on_clean_result(client):
    resp = client.post("/agents/review/rtl", json={"rtl_signoff_result": {"rules": [{"status": "pass"}]}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "a1_rtl"
    assert body["triggered"] is False
    assert body["available"] is None
    assert body["review"] is None


def test_rtl_review_triggers_and_degrades_when_hermes_unreachable(client):
    resp = client.post(
        "/agents/review/rtl",
        json={"rtl_signoff_result": {"rules": [{"status": "violation"}]}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["triggered"] is True
    assert body["available"] is False  # nothing listening on the default hermes port in tests
    assert body["review"] is None
    assert body["error"]


def test_timing_review_not_triggered_on_positive_wns(client):
    resp = client.post("/agents/review/timing", json={"timing_result": {"merged": {"wns_ps": 50}}})
    assert resp.json()["triggered"] is False


def test_timing_review_triggers_on_negative_wns(client):
    resp = client.post("/agents/review/timing", json={"timing_result": {"merged": {"wns_ps": -10}}})
    body = resp.json()
    assert body["triggered"] is True
    assert body["available"] is False


def test_power_ir_review_not_triggered_when_both_clean(client):
    resp = client.post(
        "/agents/review/power-ir",
        json={"ir_drop_result": {"passed": True}, "glitch_result": {"glitch_share": 0.1}},
    )
    assert resp.json()["triggered"] is False


def test_power_ir_review_triggers_on_hotspot(client):
    resp = client.post("/agents/review/power-ir", json={"ir_drop_result": {"passed": False}})
    assert resp.json()["triggered"] is True


def test_gate_review_not_triggered_when_ready(client):
    resp = client.post("/agents/review/gate", json={"gate_status": {"ready": True}})
    body = resp.json()
    assert body["a5"]["triggered"] is False
    assert body["v"] is None


def test_gate_review_chains_a5_then_v_when_not_ready(client):
    resp = client.post("/agents/review/gate", json={"gate_status": {"ready": False}})
    body = resp.json()
    assert body["a5"]["triggered"] is True
    assert body["a5"]["role"] == "a5_synth"
    assert body["v"]["triggered"] is True
    assert body["v"]["role"] == "v_verify"
