---
name: sign-off-api
description: "Query the Sign-off Hub REST API for chip-design sign-off data: projects, per-domain sign-off runs (STA/EM-IR/PV/glitch power/thermal), violations, waivers, shift-left stage-gate status, and the fast pre-signoff analysis endpoints (RTL ladder, IR-drop screening, MMMC timing summary, vectorless glitch power). Use WHENEVER the user asks about sign-off status, a project's gate readiness, open violations, or wants a screening analysis run — instead of guessing at numbers."
---

# Sign-off Hub API

Base URL: `${SIGNOFF_API:-http://127.0.0.1:8001}` (Swagger at `/docs`). No auth in the MVP.

## Reading state

| 목적 | 호출 |
|---|---|
| 프로젝트 목록 | `GET /projects` |
| 프로젝트 상세 | `GET /projects/{id}` |
| 프로젝트의 사인오프 런 목록 | `GET /projects/{id}/runs` |
| 스테이지 게이트 상태 | `GET /projects/{id}/signoff-status?stage=placement` |
| 런의 위반 목록 | `GET /runs/{run_id}/violations` |

`stage` is one of `rtl | synthesis | placement | routing | final`. `signoff-status` returns, per domain required at that stage, whether the latest run *at that stage* passed with no open blocking violations — this is the authority for "is the gate open", not a raw scan of `/runs`.

## Running screening analysis (stateless, no project required)

```bash
curl -s -X POST "$SIGNOFF_API/analysis/rtl-signoff" \
  -H "Content-Type: application/json" \
  -d '{"code": "<SystemVerilog source>", "project_id": 1}'
```
Runs verilator lint → CDC/reset/FSM design-rule checks → yosys synthesis and returns a `SIGNED_OFF | CONDITIONAL | REJECTED` verdict with per-rule pass/violation detail. `project_id` is optional; when given, the result is recorded as a run. A streaming variant exists at `/analysis/rtl-signoff/stream` (newline-delimited JSON events: `stage_start`, `stage_done`, `result`).

```bash
curl -s -X POST "$SIGNOFF_API/analysis/ir-drop" -H "Content-Type: application/json" \
  -d '{"cell_density": [[...]], "switching_activity": [[...]], "pdn_strength": [[...]], "vdd": 1.8}'
curl -s -X POST "$SIGNOFF_API/analysis/glitch-power" -H "Content-Type: application/json" \
  -d '{"nets": [{"name": "n1", "cap_ff": 20, "functional_toggle_rate": 0.2, "total_toggle_rate": 0.6}], "vdd": 1.8, "clock_period_ns": 10}'
curl -s -X POST "$SIGNOFF_API/analysis/timing-summary" -H "Content-Type: application/json" \
  -d '{"corners": [{"name": "ss_100C_1v60", "endpoint_slacks_ps": [-320, 60, ...]}], "pba_pessimism_credit_ps": 15}'
```

These three are **pre-signoff screening**, not golden sign-off — say so when reporting their results (see SOUL.md). None of them require a `project_id`; pass one only if the caller wants the result recorded against a project.

## Writing state

- `POST /projects` — `{name, process_node, foundry}`
- `POST /projects/{id}/runs` — `{domain, stage, tool}` (domain: `rtl|sta|emir|pv|glitch_power|thermal`)
- `PATCH /runs/{id}` — `{status: "passed"|"failed"}`
- `POST /runs/{id}/violations` — array of `{check_name, severity, location?}`
- `POST /violations/{id}/waiver` — `{reason, approved_by}` — records a waiver; does **not** change the violation's underlying risk, only its `status`.

## Traps

- `GET /projects/{id}/signoff-status` needs a `stage` query param — omitting it is a 422, not "all stages".
- A run's `status` starts `"running"` until `PATCH`ed to `passed`/`failed`; a stage gate blocked on a domain with no run at all looks identical in the UI to one blocked on a `running` run — check `reason` in the gate response to tell them apart.
- The RTL ladder's `run_id` in its result is only populated when you passed a `project_id` in the request; without it, the analysis is stateless and nothing is recorded.
