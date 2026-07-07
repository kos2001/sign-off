# Sign-off Hub

칩 설계 사인오프(sign-off) 관리·분석 플랫폼. `signoff-latest-tech-and-skills.md` 리서치 리포트의
최신 사인오프 기술(shift-left 게이트, IR-drop 스크리닝, 벡터리스 글리치 파워, MMMC/PBA 타이밍)을
실행 가능한 풀스택 앱으로 구현한 MVP입니다.

**실제 예제**: lowRISC **Ibex RISC-V 코어 × SkyWater SKY130** (OpenROAD/OpenLane 레퍼런스 플로우
컨텍스트 — 실제 리버티 코너 명명, VDD 1.8V, SKY130 DRC 룰 이름, Ibex 모듈/넷 이름 기반).

## 구조

- `backend/` — FastAPI + SQLAlchemy + SQLite. 사인오프 런/위반/웨이버 관리, shift-left 스테이지
  게이트, 분석 API 3종. 상세: `backend/README.md`
- `frontend/` — Vite 7 + React 19 + TypeScript + Tailwind CSS v4 + TanStack Query + React Router 7.
  커스텀 SVG 시각화(IR-drop 히트맵, 슬랙 다이버징 바, 전력 스택 바), 라이트/다크 모드.

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

테스트: `cd backend && .venv/bin/python -m pytest` (22개)
