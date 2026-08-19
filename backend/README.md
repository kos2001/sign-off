# Sign-off Hub — Backend

칩 설계 사인오프 관리·분석 백엔드 (FastAPI + SQLAlchemy + SQLite).
루트의 `signoff-latest-tech-and-skills.md` 리서치 리포트에서 다룬 기술들을 실행 가능한 서비스로 구현한 MVP입니다.

## 리포트 → 구현 매핑

| 리포트 섹션 | 구현 |
|---|---|
| §2 Shift-left 방법론 | `app/services/stages.py` — 설계 단계(rtl→synthesis→placement→routing→final)별 필수 사인오프 도메인 매트릭스와 게이트 판정 (`GET /projects/{id}/signoff-status`) |
| §3 STA / MMMC / GBA→PBA | `app/services/timing.py` — 코너별 WNS/TNS/NVP 집계, 엔드포인트 단위 MMMC 머지, GBA→PBA 비관성 크레딧 추정 (`POST /analysis/timing-summary`) |
| §4 IR-drop ML 스크리닝 | `app/services/irdrop.py` — arXiv:2601.22707의 물리 기반 공식(density×activity/strength)으로 IR-drop 맵·핫스팟 사전 스크리닝 (`POST /analysis/ir-drop`) |
| §5 벡터리스 글리치 파워 | `app/services/glitch.py` — 토글률 초과분 기반 글리치 파워 추정, transport/inertial 디레이팅 (`POST /analysis/glitch-power`) |
| §9 사인오프 런 관리 실무 | 프로젝트/런/위반/웨이버 CRUD — 도메인(rtl·sta·emir·pv·glitch_power·thermal), 툴, 스테이지, 심각도 추적 |
| RTL 사인오프 래더 (ai_driven_rtl 이식) | `app/services/rtl/` — verilator lint → 설계 룰(SV 타입·non-blocking·리셋 분류·CDC·FSM 도달성, DRC-XXX 코드) → yosys 합성 → SIGNED_OFF/CONDITIONAL/REJECTED 판정 + QoR 점수 (`POST /analysis/rtl-signoff`, 실시간 NDJSON 스트리밍은 `POST /analysis/rtl-signoff/stream`). `project_id` 지정 시 런/위반 자동 기록 → RTL 스테이지 게이트 구동. 툴 부재 시 skip으로 우아하게 강등 |

분석 엔드포인트는 골든 사인오프 툴(PrimeTime/RedHawk-SC/Calibre)의 **대체가 아닌 사전 스크리닝 계층**입니다 — 리포트의 핵심 결론과 동일한 포지셔닝.

## 실행

```bash
cd backend
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/uvicorn app.main:app --reload   # http://127.0.0.1:8000/docs
```

## 테스트

```bash
.venv/bin/python -m pytest -q
```

## API 개요

- `POST/GET /projects` — 프로젝트(칩) 등록: 이름, 공정 노드, 파운드리
- `POST /projects/{id}/runs` — 사인오프 런 생성 (`domain`, `stage`, `tool`, `metrics`)
- `PATCH /runs/{id}` — 런 상태 갱신 (`running`/`passed`/`failed`)
- `POST /runs/{id}/violations` — 위반 일괄 등록 (severity: info/warning/error/critical)
- `POST /violations/{id}/waiver` — 웨이버 승인 (사유·승인자 기록, 상태 waived 전환)
- `GET /projects/{id}/signoff-status?stage=placement` — shift-left 게이트 판정: 해당 스테이지의 필수 도메인이 모두 passed이고 미웨이버 error/critical 위반이 없어야 ready
- `POST /analysis/ir-drop` · `POST /analysis/glitch-power` · `POST /analysis/timing-summary`

DB는 기본 `sqlite:///./signoff.db` (`SIGNOFF_DATABASE_URL`로 교체 가능).

## hermes-agent 연동 ('sign-off' 프로파일)

`weekly-report-harness`의 hermes 프로파일 구조(SOUL.md + 스킬 + api_server)를 참조해,
이 앱의 도메인(RTL/타이밍/파워-IR/웨이버/게이트)에 맞춘 6개 역할의 LLM 분석 파이프라인을
붙일 수 있습니다.

| 역할 | 담당 |
|---|---|
| A1 RTL 리뷰어 | lint/CDC/리셋/FSM 위반의 근본 원인과 수정 방향 |
| A2 타이밍 분석가 | MMMC WNS/TNS, 원인 코너·엔드포인트, PBA 회복 추정 해석 |
| A3 파워/IR 무결성 분석가 | IR-drop 핫스팟, 글리치 파워 네트 분해 원인 설명 |
| A4 웨이버 심사관 | 웨이버 사유의 타당성·잔여 리스크 심사 |
| A5 사인오프 종합 판정관 | A1~A4 종합 → 판정 초안 + 우선순위 조치 목록 |
| V 검증 에이전트 | A5 판정을 원본 데이터에서 독립 재검증 |

- 역할 정의·클라이언트: `app/hermes.py` (`ROLES`, `HermesClient`)
- 프로파일 소스: `profiles/sign-off/SOUL.md`, `profiles/sign-off/skills/sign-off-api/`
- 셋업: `../scripts/setup_hermes_profile.sh [--apply]` (dry-run 기본, api_server 포트 8654)
- 연결 설정: `.env.example` 참고 (`SIGNOFF_LLM_BASE_URL`/`_API_KEY`/`_MODEL`)

api_server 경로는 도구/스킬을 실행하지 않으므로, 런/위반/게이트 데이터는 프롬프트에
JSON으로 직접 넣어 호출합니다 (`sign-off-api` 스킬은 대화형 모드에서만 로드됨).
