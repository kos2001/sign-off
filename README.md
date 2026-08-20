# Sign-off Hub

칩 설계 사인오프(sign-off) 관리·분석 플랫폼. `signoff-latest-tech-and-skills.md` 리서치 리포트의
최신 사인오프 기술(shift-left 게이트, IR-drop 스크리닝, 벡터리스 글리치 파워, MMMC/PBA 타이밍)을
실행 가능한 풀스택 앱으로 구현한 MVP입니다.

**실제 예제**: lowRISC **Ibex RISC-V 코어 × SkyWater SKY130** (OpenROAD/OpenLane 레퍼런스 플로우
컨텍스트 — 실제 리버티 코너 명명, VDD 1.8V, SKY130 DRC 룰 이름, Ibex 모듈/넷 이름 기반). RTL
사인오프 래더의 기본 예제는 실제로 검출되는 버그(CDC 미동기화 + FSM dead-end)가 있는
`cdc_status_bridge` 모듈이며, 클린한 2-FF 동기화 예제와 버튼 하나로 비교할 수 있습니다.

## 구조

- `backend/` — FastAPI + SQLAlchemy + SQLite. 사인오프 런/위반/웨이버 관리, shift-left 스테이지
  게이트, 분석 API 4종. RTL 사인오프 래더(verilator lint → CDC/리셋/FSM 설계 룰 → yosys 합성 →
  SIGNED_OFF/CONDITIONAL/REJECTED)는 `~/gitspace/ai_driven_rtl`의 결정론적 검증 모듈을 이식한 것.
  hermes-agent 기반 6-역할 LLM 분석 파이프라인(`app/hermes.py`, `app/routers/agents.py`)도
  포함 — 상세: `backend/README.md`
- `frontend/` — Vite 7 + React 19 + TypeScript + Tailwind CSS v4 + TanStack Query + React Router 7.
  다크 테마 전용. 카테고리별 사이드바 내비게이션(개요/프로젝트/분석 도구), 런 상태·게이트 준비율
  시각화, 커스텀 SVG 차트(IR-drop 히트맵, 슬랙 다이버징 바, 전력 스택 바), agent 개입 여부를
  명시적으로 보여주는 리뷰 패널.

## 실행

```bash
# backend (http://127.0.0.1:8000, Swagger: /docs)
cd backend
uv venv --python 3.11 .venv && uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python scripts/seed_demo.py        # Ibex 실제 예제 시드
.venv/bin/uvicorn app.main:app

# frontend (http://localhost:5173, /api → backend 프록시)
cd frontend
pnpm install
pnpm dev
```

테스트: `cd backend && .venv/bin/python -m pytest` (54개)

## hermes-agent 연동 (선택)

RTL/타이밍/파워-IR/게이트 분석 결과를 실제로 위반·이상 징후가 있을 때만 LLM이 검토하는
6-역할 파이프라인(RTL 리뷰어 → 타이밍 분석가 → 파워/IR 분석가 → 웨이버 심사관 →
사인오프 종합 판정관 → 검증 에이전트)이 붙어 있습니다. 각 역할의 정확한 개입 조건과 셋업
방법은 `backend/README.md`의 "hermes-agent 연동" 절 참고. 미기동 상태에서도 프론트엔드는
"agent 미개입"/"개입함 — hermes 연결 안 됨" 상태를 명확히 보여주도록 우아하게 강등됩니다.

## CI

`.github/workflows/ci.yml`이 `main` push/PR마다 backend pytest + frontend build를 실행합니다.
Dependabot이 backend(pip)/frontend(npm)/GitHub Actions 의존성을 매주 점검합니다.
