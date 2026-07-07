class TestSignoffFlow:
    """End-to-end: project -> runs -> violations -> waiver -> stage gate."""

    def test_full_signoff_gate_flow(self, client):
        project = client.post(
            "/projects",
            json={"name": "orion-soc", "process_node": "3nm", "foundry": "TSMC"},
        ).json()
        pid = project["id"]

        # placement stage requires sta + emir + pv
        status = client.get(
            f"/projects/{pid}/signoff-status", params={"stage": "placement"}
        ).json()
        assert status["ready"] is False
        assert {d["domain"] for d in status["domains"]} == {"sta", "emir", "pv"}

        run_ids = {}
        for domain, tool in [("sta", "PrimeTime"), ("emir", "RedHawk-SC"), ("pv", "Calibre")]:
            r = client.post(
                f"/projects/{pid}/runs",
                json={"domain": domain, "stage": "placement", "tool": tool},
            )
            assert r.status_code == 201
            run_ids[domain] = r.json()["id"]

        # pass sta/emir; pv passes but has a blocking violation
        for domain in ["sta", "emir", "pv"]:
            client.patch(f"/runs/{run_ids[domain]}", json={"status": "passed"})

        resp = client.post(
            f"/runs/{run_ids['pv']}/violations",
            json=[
                {"check_name": "M2.S.1", "severity": "error", "location": "x=12,y=88"},
                {"check_name": "density.info", "severity": "info"},
            ],
        )
        assert resp.status_code == 201
        violation_id = resp.json()[0]["id"]

        status = client.get(
            f"/projects/{pid}/signoff-status", params={"stage": "placement"}
        ).json()
        pv = next(d for d in status["domains"] if d["domain"] == "pv")
        assert status["ready"] is False
        assert pv["open_blocking_violations"] == 1

        # waive the blocking violation -> gate becomes ready
        resp = client.post(
            f"/violations/{violation_id}/waiver",
            json={"reason": "foundry-approved metal fill exception", "approved_by": "kos"},
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "waived"

        status = client.get(
            f"/projects/{pid}/signoff-status", params={"stage": "placement"}
        ).json()
        assert status["ready"] is True

    def test_duplicate_project_name_conflict(self, client):
        payload = {"name": "dup-chip", "process_node": "5nm", "foundry": "Samsung"}
        assert client.post("/projects", json=payload).status_code == 201
        assert client.post("/projects", json=payload).status_code == 409

    def test_double_waiver_conflict(self, client):
        pid = client.post(
            "/projects",
            json={"name": "waiver-chip", "process_node": "7nm", "foundry": "Samsung"},
        ).json()["id"]
        rid = client.post(
            f"/projects/{pid}/runs",
            json={"domain": "sta", "stage": "rtl", "tool": "RTL-Timer"},
        ).json()["id"]
        vid = client.post(
            f"/runs/{rid}/violations",
            json=[{"check_name": "setup", "severity": "critical"}],
        ).json()[0]["id"]

        waiver = {"reason": "known false path", "approved_by": "kos"}
        assert client.post(f"/violations/{vid}/waiver", json=waiver).status_code == 201
        assert client.post(f"/violations/{vid}/waiver", json=waiver).status_code == 409

    def test_missing_project_404(self, client):
        assert client.get("/projects/99999").status_code == 404


class TestAnalysisEndpoints:
    def test_ir_drop_endpoint(self, client):
        resp = client.post(
            "/analysis/ir-drop",
            json={
                "cell_density": [[0.9, 0.1], [0.1, 0.1]],
                "switching_activity": [[0.9, 0.1], [0.1, 0.1]],
                "pdn_strength": [[1.0, 1.0], [1.0, 1.0]],
                "scale": 1.0,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["passed"] is False
        assert body["hotspots"][0]["row"] == 0

    def test_ir_drop_validation_error(self, client):
        resp = client.post(
            "/analysis/ir-drop",
            json={
                "cell_density": [[0.5]],
                "switching_activity": [[0.5, 0.5]],
                "pdn_strength": [[1.0]],
            },
        )
        assert resp.status_code == 422

    def test_glitch_power_endpoint(self, client):
        resp = client.post(
            "/analysis/glitch-power",
            json={
                "nets": [
                    {"cap_ff": 10, "functional_toggle_rate": 0.2, "total_toggle_rate": 0.6}
                ]
            },
        )
        assert resp.status_code == 200
        assert resp.json()["glitch_share"] > 0.6

    def test_timing_summary_endpoint(self, client):
        resp = client.post(
            "/analysis/timing-summary",
            json={
                "corners": [
                    {"name": "ss", "endpoint_slacks_ps": [-20, 10]},
                    {"name": "ff", "endpoint_slacks_ps": [5, -3]},
                ],
                "pba_pessimism_credit_ps": 25,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["merged"]["wns_ps"] == -20.0
        assert body["estimated_pba"]["violating_endpoints"] == 0
        assert body["estimated_pba"]["recovered_endpoints"] == 2

    def test_health(self, client):
        assert client.get("/health").json() == {"status": "ok"}
