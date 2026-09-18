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
uv venv --python 3.11 .venv && uv pip install --python .venv/bin/python --require-hashes -r requirements.txt
.venv/bin/python scripts/seed_demo.py        # Ibex 실제 예제 시드
.venv/bin/uvicorn app.main:app

# frontend (http://localhost:5173, /api → backend 프록시)
cd frontend
pnpm install
pnpm dev
```

테스트: `cd backend && .venv/bin/python -m pytest` (943개; Linux 메모리 제한 검사는 macOS에서 건너뜀)

백엔드 설치는 전이 의존성의 버전과 해시까지 고정합니다. [의존성 설치·갱신 절차](docs/dependencies.md)를 참고하세요.

## hermes-agent 연동 (선택)

RTL/타이밍/파워-IR/게이트 분석 결과를 실제로 위반·이상 징후가 있을 때만 LLM이 검토하는
6-역할 파이프라인(RTL 리뷰어 → 타이밍 분석가 → 파워/IR 분석가 → 웨이버 심사관 →
사인오프 종합 판정관 → 검증 에이전트)이 붙어 있습니다. 각 역할의 정확한 개입 조건과 셋업
방법은 `backend/README.md`의 "hermes-agent 연동" 절 참고. 미기동 상태에서도 프론트엔드는
"agent 미개입"/"개입함 — hermes 연결 안 됨" 상태를 명확히 보여주도록 우아하게 강등됩니다.

## CI

`.github/workflows/ci.yml`이 `main` push/PR마다 backend pytest + frontend build를 실행합니다.
Dependabot이 backend(pip)/frontend(npm)/GitHub Actions 의존성을 매주 점검합니다.

## 프로젝트 위반 검토

적용된 검색 조건의 전체 위반과 런·웨이버 정보를 [JSON으로 내보낼 수 있습니다](docs/violation-export.md).

프로젝트의 **전체 위반 검토**에서 검색·상태·심각도·단계·도메인 필터와 페이지 이동을
사용할 수 있습니다. 기본 범위는 단계·도메인별 최신 런이며 과거 런도 선택할 수 있습니다.
검색 조건과 선택 항목은 URL에 보존됩니다. 위반별 수정 완료·웨이버·재오픈 사유와
처리 이력을 기록합니다. 인증 모드에서는 로그인 계정, 로컬 모드에서는 직접 입력한 이름을 사용합니다.

진행 상태: [서비스 개선 기록](docs/service-improvement.md).
브라우저 검증 재현: [검증 가이드](docs/browser-verification.md).

## 실행 결과 비교

프로젝트의 **런 비교**에서 같은 도메인·단계의 두 실행을 선택합니다. 지표의 변화와
위반의 추가·내용 변경·기준에만 남은 기록을 나란히 볼 수 있습니다. 선택된 실행 ID와
차이 필터는 URL에 저장됩니다. 비교는 읽기 전용이며 미검출을 수정 완료로 처리하지 않습니다.

## STA 시나리오 커버리지

프로젝트의 **STA 시나리오 매트릭스**에서 단계별 필수 코너·모드와 SPEF 요구 여부를
정의할 수 있습니다. 지정한 설계 리비전의 실제 OpenSTA 서버 실행과 기대 세트를 비교해
실행 누락, SPEF 요구 누락, 계획 외 실행을 구분합니다. WNS와 위반 수는 OpenSTA가 보고한
경로 표본 범위이며, 시나리오가 모두 실행됐다는 사실을 전체 타이밍 사인오프와 혼동하지 않습니다.

**OpenSTA 타이밍 실행**의 MCMM 배치에서 기대 세트를 불러오고 시나리오별 Liberty·SDC·SPEF를
지정할 수 있습니다. 최대 8개 작업을 서버의 영속 큐에 접수하므로 브라우저를 닫아도 제한
컨테이너에서 순차 실행합니다. 일부 시나리오가 실패해도 나머지를 계속하고 성공 결과를 각각
독립 런과 입력 근거로 저장합니다. 배치 접수자와 항목별 대기·실행·성공·실패·취소 상태는
DB 매니페스트에 남아 실행 화면에서 다시 확인하거나 진행 중인 작업을 취소할 수 있습니다.
종결된 배치는 서버에 검증된 입력을 다시 업로드하지 않고 동일 입력으로 재실행할 수 있으며,
원본 배치 번호와 시도 번호를 보존해 결과 계보를 추적합니다.
접수·워커 시작·시나리오별 시작/종료·취소 요청·최종 상태는 행위자와 시각을 포함한
영구 타임라인으로 남아 실행 화면에서 감사할 수 있습니다.
OpenSTA는 RTL과 분리된 호스트 동시 실행 풀을 사용합니다. 여러 프로젝트가 대기하면 현재
실행이 없는 프로젝트와 가장 오래 실행 기회를 받지 못한 프로젝트부터 선택해 슬롯 독점을 막습니다.

## RTL 실행 근거

프로젝트에 기록한 RTL 분석은 실행 소스·SHA-256·입력 리비전·원래 판정과 단계별 결과를
함께 보존합니다. 런의 **실행 근거 보기**에서 조회하고 JSON으로 내려받을 수 있습니다.
`CONDITIONAL`은 `incomplete`(검증 미완료)로 저장되며 RTL 게이트를 열지 않습니다.
서버 분석 결과는 수동 Pass/Fail이나 지표 변경으로 덮어쓰지 않고 다시 실행하여 갱신합니다.

## 동시 검토 보호

위반을 처리할 때 조회한 변경 버전을 함께 검사합니다. 다른 검토자가 상태를 바꿨다가
원래대로 되돌린 경우도 충돌로 감지합니다. 충돌한 사유는 현재 브라우저 탭 안에 유지되며,
변경 내용을 확인하고 다시 처리할 수 있습니다. 탭 새로고침·닫기 이후까지 초안을 보존하지는 않습니다.

API 연동에서는 위반 응답의 `version`을 수정·웨이버 요청의 `expected_version`으로 보내야 합니다.

SQLite 운영 데이터는 온라인 백업·검증·새 경로 복원을 지원합니다.
[백업 및 복구 안내](docs/backup-recovery.md)

RTL 테스트벤치 입력, 실제 Icarus 실행, 컴파일·실행 로그와 소스 해시 보존을 지원합니다.
[테스트벤치 사용 및 서버 설정](docs/rtl-simulation.md)

로그인·프로젝트 역할과 로그인 계정 기반 승인 이력을 지원합니다. 기본 로컬 모드는 인증을
사용하지 않으며 운영 시 [인증 설정](docs/authentication.md)을 적용해야 합니다.

## 자기 개선 루프

`python3 scripts/self_improve.py check`로 현재 상태를 점검하고,
`python3 scripts/self_improve.py run --max-iterations 3`으로 분리된 작업 공간에서
점검→수정→회귀 검증을 반복합니다. 통과한 후보와 누적 패치를 남기며,
`--apply`를 지정하면 원본이 시작 시점과 같을 때만 적용합니다.
[실행·중단·검증 범위 안내](docs/self-improvement-loop.md)

프로젝트에서 [OpenSTA JSON 보고서 가져오기](docs/report-import.md)를 사용해 경로와 슬랙을 미리 보고 원본 근거·위반을 저장할 수 있습니다.
[PrimeTime / Tempus 경로 JSON 가져오기](docs/commercial-sta-import.md)는 명시적인 툴·버전·시간 단위와
핀 목록을 검증하고 같은 경로 탐색·비교·위반 검토 흐름에 연결합니다.
[신뢰된 수집기 커버리지 증명](docs/coverage-attestation.md)을 STA, DRC, EM/IR, 전력, 열 또는 RTL 회귀 보고서와 함께 제출하면
서버에 등록된 HMAC 키로 실행 범위를 검증하며, 서명 없는 보고서는 계속 부분 근거로 처리합니다.
[Calibre / Pegasus DRC 마커 JSON 가져오기](docs/commercial-drc-import.md)는 툴·버전·좌표 단위·심각도와
도형을 검증하고 마커 탐색과 위반 검토 흐름에 연결합니다.
[RedHawk-SC / Voltus / Totem EM/IR 결과 가져오기](docs/commercial-emir-import.md)는 전압 강하와
전류 밀도의 값·제한·단위·좌표를 검증하고 핫스폿 탐색과 위반 검토에 연결합니다.
[PrimePower / Joules / PowerArtist 전력 결과 가져오기](docs/commercial-power-import.md)는 전력
구성 합계와 글리치 비중을 재검증하고 계층별 전력 탐색과 위반 검토에 연결합니다.
[Celsius / Icepak / Calibre 3DSTACK 열 결과 가져오기](docs/commercial-thermal-import.md)는 온도와
제한, 3D 위치를 정규화하고 열 핫스폿 탐색과 위반 검토에 연결합니다.
[VCS / Xcelium RTL 회귀 결과 가져오기](docs/commercial-rtl-import.md)는 컴파일·테스트·assertion
집계를 검증하고 테스트별 로그 탐색과 위반 검토에 연결합니다.

운영 상태 확인과 문의 번호 로그는 [운영 점검](docs/operations.md)을 참고하세요.

스테이지 게이트는 수동 통과 상태만으로 열리지 않으며 도메인별 최신 런의 설계 리비전도 검사합니다.
검증 범위와 현재 지원 한계는 [게이트 근거 정책](docs/gate-provenance.md)을 참고하세요.
[사인오프 결정과 근거 동결](docs/signoff-release-decisions.md)은 approver의 승인·차단 사유와
그 시점의 검증된 ZIP 패키지를 SHA-256에 묶어 불변 보관합니다.

[KLayout DRC 마커 보고서 가져오기](docs/klayout-import.md)를 지원합니다. PV 런·위반·원본 근거로 보존하며 전체 DRC 통과와 구분합니다.
