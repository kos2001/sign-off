---
name: sign-off-api
description: Query Sign-off Hub projects, runs, violations, evidence and stage gates, or carry out a user-requested analysis or review update using its REST API.
---

# Sign-off Hub API

Use `${SIGNOFF_API:-http://127.0.0.1:18000}`; `/docs` and `/openapi.json` describe the running API. The browser at port 15173 proxies `/api/*` to this backend without the `/api` prefix.

## Session and permissions

Read `GET /auth/session` first. `mode=local` permits local access; `mode=required` uses the user's authenticated session and project role. Do not assume anonymous access or use the Hermes API_SERVER_KEY as a Sign-off credential. Do not display passwords, session cookies or API keys. For mutations in required mode, send the session's `csrf_token` in `X-CSRF-Token` alongside its session cookie. If no authenticated session is available, explain which access is missing.

## Inspect a project

| Purpose | Request |
|---|---|
| List/select projects | `GET /projects` |
| Project and runs | `GET /projects/{id}`, `GET /projects/{id}/runs` |
| Gate for a stage | `GET /projects/{id}/signoff-status?stage=placement` |
| Filtered violations | `GET /projects/{id}/violations` |
| Current violation/version | `GET /violations/{id}` |
| Run violations | `GET /runs/{id}/violations` |
| Recorded review events | `GET /violations/{id}/history/page` |
| Full history export | `GET /violations/{id}/history/export` |

Read the live schema for evidence, report import, timing-path, and comparison endpoints and query parameters. Do not guess endpoint paths. Follow pagination until the requested scope is covered; do not label a first page as all results. History cursors and snapshot IDs belong to the selected violation and filters.

Stages: `rtl`, `synthesis`, `placement`, `routing`, `final`. Use the gate response for the requested stage. Its latest run per domain and stage decides readiness; an earlier-stage pass cannot substitute. The gate also checks evidence coverage, so a passed status alone is insufficient.

## Analyses and writes

For an explicitly requested analysis, inspect the request schema before calling `/analysis/rtl-signoff`, `/analysis/ir-drop`, `/analysis/glitch-power` or `/analysis/timing-summary`. Omit `project_id` for a no-save RTL check; including it persists a run. Explain screening limits using `sign-off-evidence-review`. Do not execute submitted RTL merely to answer a status question.

For an authorized violation update, read the current `status` and `version`, then send `expected_status`, `expected_version`, target `status`, `actor`, and `reason` to `PATCH /violations/{id}`. A waiver can also use `POST /violations/{id}/waiver` with `expected_version`, `approved_by`, and `reason`. Actual roles and attribution are enforced by the server. On 409, show the changed record and reassess; do not blindly retry against a newer version.

A request to explain readiness does not authorize changing results, approvals or waivers. When updates are requested, report the actual returned state and event; an LLM recommendation is not an approval record.
