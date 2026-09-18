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
uv pip install --python .venv/bin/python --require-hashes -r requirements.txt
.venv/bin/uvicorn app.main:app --reload   # http://127.0.0.1:8000/docs
```

## 테스트

```bash
.venv/bin/python -m pytest -q
```

## API 개요

- `POST/GET /projects` — 프로젝트(칩) 등록: 이름, 공정 노드, 파운드리
- `POST /projects/{id}/runs` — 사인오프 런 생성 (`domain`, `stage`, `tool`, `metrics`)
- `PATCH /runs/{id}` — 런 상태 갱신 (`running`/`passed`/`failed`/`incomplete`)
- `POST /runs/{id}/violations` — 위반 일괄 등록 (severity: info/warning/error/critical)
- `POST /violations/{id}/waiver` — 웨이버 승인 (사유·승인자 기록, 상태 waived 전환)
- `GET /projects/{id}/signoff-status?stage=placement` — shift-left 게이트 판정: 해당 스테이지의 필수 도메인이 모두 passed이고 미웨이버 error/critical 위반이 없어야 ready
- `POST /analysis/ir-drop` · `POST /analysis/glitch-power` · `POST /analysis/timing-summary`

DB는 기본 `sqlite:///./signoff.db` (`SIGNOFF_DATABASE_URL`로 교체 가능).

## hermes-agent 연동 ('sign-off' 프로파일)

`weekly-report-harness`의 hermes 프로파일 구조(SOUL.md + 스킬 + api_server)를 참조해,
이 앱의 도메인(RTL/타이밍/파워-IR/웨이버/게이트)에 맞춘 6개 역할의 LLM 분석 파이프라인을
붙일 수 있습니다.

각 역할은 상시 실행되지 않고, **아래 조건을 만족할 때만** 개입합니다 — 위반도 음의 슬랙도
핫스팟도 없는 깨끗한 결과에는 어떤 역할도 개입하지 않습니다. A1/A2/A3/A5 의 조건은
`app/hermes.py` 의 `a1_should_review` / `a2_should_review` / `a3_should_review` /
`a5_gate_needs_synthesis` 로 기계적으로도 판별할 수 있습니다 (테스트: `tests/test_hermes.py`).

| 역할 | 담당 | 개입 시점 (트리거) |
|---|---|---|
| A1 RTL 리뷰어 | lint/CDC/리셋/FSM 위반의 근본 원인과 수정 방향 | `rtl-signoff` 응답 `rules[]` 에 `status="violation"` 이 하나라도 있을 때 |
| A2 타이밍 분석가 | MMMC WNS/TNS, 원인 코너·엔드포인트, PBA 회복 추정 해석 | `timing-summary` 응답 `merged.wns_ps < 0` 일 때 |
| A3 파워/IR 무결성 분석가 | IR-drop 핫스팟, 글리치 파워 네트 분해 원인 설명 | `ir-drop` 응답 `passed=false` 이거나 `glitch-power` 응답 `glitch_share >= 0.3` 일 때 |
| A4 웨이버 심사관 | 웨이버 사유의 타당성·잔여 리스크 심사 | 역할 정의만 존재; 승인 API 자동 연동 없음 |
| A5 사인오프 종합 판정관 | A1~A4 종합 → 판정 초안 + 우선순위 조치 목록 | `signoff-status` 응답 `ready=false`일 때; 현재 UI는 게이트만 전달하고 소견은 선택 입력 |
| V 검증 에이전트 | A5 판정을 원본 데이터에서 독립 재검증 | A5 가 판정을 낸 직후 항상 자동 이어서 실행 (단독 호출 없음) |

- 역할 정의·클라이언트: `app/hermes.py` (`ROLES`, `HermesClient`)
- 프로파일 소스: `profiles/sign-off/SOUL.md`, `profiles/sign-off/skills/{sign-off-api,sign-off-drc-rules,sign-off-evidence-review}/`
- 셋업: `../scripts/setup_hermes_profile.sh [--apply]` (dry-run 기본, api_server 포트 8657)
- 연결 설정: `.env.example` 참고 (`SIGNOFF_LLM_BASE_URL`/`_API_KEY`/`_MODEL`)

api_server 경로는 도구/스킬을 실행하지 않으므로, 런/위반/게이트 데이터는 프롬프트에
JSON으로 직접 넣어 호출합니다 (`sign-off-api`/`sign-off-drc-rules` 스킬은 대화형 모드
(`sign-off chat`)에서만 로드됨 — 사람이 직접 hermes와 대화하며 프로젝트를 조회하거나
DRC 코드의 의미를 물어볼 때 쓰입니다).

## 위반 처리와 변경 이력

`PATCH /violations/{id}`는 `expected_status`, `expected_version`, `status`, `actor`, `reason`을 받습니다.
허용 전이는 `open → fixed/waived`, `fixed/waived → open`입니다. 현재 상태가
`expected_status` 또는 조회한 `expected_version`과 다르면 409를 반환합니다. 처리자(80자), 사유(4000자)는 공백을
제거한 후 필수 검사합니다. 수정 완료 처리에는 검증 근거를 사유로 기록하세요.

`GET /violations/{id}/history`에서 이전/다음 상태, 처리자, 사유와 시간을 조회합니다.
기존 웨이버 API도 이력을 기록하며, 웨이버 해제 시 승인 근거는 이력에 보존합니다.
기존 DB는 서버 시작 시 `violation_events` 테이블이 추가됩니다. 과거 변경 전체를
복원하지는 않으며, 기존 웨이버의 승인 근거는 해제 시 이력으로 이관됩니다.
처리자는 아직 직접 입력한 값이며 로그인 신원이나 승인 권한을 검증하지 않습니다.

## 프로젝트 위반 검색

`GET /projects/{id}/violations`는 `items`, `total`, `open_blocking`, `offset`, `limit`을 반환합니다.
`total`과 `open_blocking`은 현재 필터 전체의 집계이며 현재 페이지의 개수가 아닙니다.

- `q`: 체크 이름·위치·설명·툴의 부분 문자열 검색(최대 200자, `%`/`_`는 문자 그대로 검색).
- `status`, `severity`, `domain`, `stage`: 열거형 필터, 생략 시 전체.
- `latest_only`: 기본 true. 각 단계·도메인의 최신 런을 먼저 선택하고 위반을 조회합니다.
  false이면 과거 런도 포함합니다. 최신 런 선택은 게이트와 같은 생성 시간/ID 순서를 사용합니다.
- `sort`: severity(기본, Critical→Error→Warning→Info), newest, oldest.
  같은 심각도에서는 위반 ID 내림차순으로 정렬합니다.
- `offset`: 기본 0. `limit`: 기본 25, 최대 100.

최신 실행에 위반이 없더라도 과거 실행의 위반으로 대체하지 않습니다. 미완료 실행에도
위반이 없을 수 있으므로 위반 수를 게이트 통과 판정으로 해석하지 마세요.

## 런 비교

`GET /projects/{id}/run-comparison?baseline_run_id=1&candidate_run_id=2`

- 같은 프로젝트·도메인·스테이지의 서로 다른 런만 비교합니다. 프로젝트 밖의 런은 404,
  같은 런이나 호환되지 않는 조합은 422입니다.
- `kind=all|new|changed|removed|unchanged`, `offset`, `limit`(기본 25, 최대 100).
  `summary`는 전체 비교 집계, `total`은 현재 kind 필터의 전체 개수입니다.
- `metrics`: 각 키의 원래 값, 존재 여부, 변경 여부, 숫자 차이(candidate−baseline).
  bool은 숫자로 취급하지 않고, 미등록과 null을 구분합니다. 중첩 지표는 원래 JSON으로 표시합니다.
- `items`: 기준/대상 위반, 변경 필드, 중복 체크·위치의 불확실한 대응 여부.
  체크 이름과 위치가 같으면 동일 내용부터 대응하고, 남은 기록은 ID 순으로 대응합니다.
  중복 항목 개수는 보존하며, 자동 상태 변경이나 웨이버 전파는 수행하지 않습니다.
- `baseline_provenance`, `candidate_provenance`: 근거 종류, 설계 리비전, 원본 SHA-256,
  시나리오, 툴 버전, 검증 범위입니다. 저장된 정보가 없으면 null이며 필터·페이지와 무관합니다.
  원본 텍스트 전체는 별도 실행 근거 API로 조회합니다.
- `partial`은 실행 중·미완료 또는 OpenSTA 경로 보고서가 포함된 잠정 비교 여부,
  `different_tools`는 툴 이름 불일치 여부입니다.

`removed`는 기준에만 기록이 있다는 뜻으로, 수정 완료를 증명하지 않습니다.
현재 DB에는 설계 리비전·툴 설정·원본 리포트의 동일성 증명이 없으므로, 지표 차이를
같은 조건의 회귀 판정이나 사인오프 승인으로 간주하지 않습니다.

## RTL 근거와 게이트 정책

Linux의 실제 툴 통합 검사는 `Dockerfile.rtl-check`로 재실행할 수 있습니다.
[검증 이미지 실행 절차](../docs/rtl-simulation.md#실제-linux-rtl-툴-통합-검사)를 참고하세요.
[단일 작업 워커](../docs/rtl-worker.md)는 `SIGNOFF_RTL_EXECUTION=container`로 API에 연결할 수 있습니다.
최종 결과 검증·정상 종료·컨테이너 정리 후 저장하며, 기본 실행 방식은 local입니다.

- RTL 요청의 `design_revision`(선택, 160자)은 입력한 식별자이며 Git 저장소와 대조하지 않습니다.
- 기록된 분석에는 `run_evidence` 행이 생성됩니다. `GET /runs/{id}/evidence`로 실행한
  단일 `design.sv` 소스(코드 펜스 제거·양끝 공백 정리·마지막 줄바꿈), 소스 SHA-256,
  원래 판정·규칙·단계별 결과와 시간을 조회합니다. SHA-256은 소스 식별용이며 전자서명이 아닙니다.
- 런 응답의 `evidence_source`는 서버 실행(`rtl_ladder`, `opensta_execution`), 보고서 가져오기(`opensta_report`, `klayout_report`), `manual`, `legacy`를 구분합니다.

### OpenSTA 실행 워커

`../scripts/build_sta_worker.sh`는 OpenSTA를 파서와 맞춘 커밋 `d97587f669b4f169be7132346df70e7d634500c3`으로 고정해 `signoff-sta-worker:d97587f` 이미지를 만듭니다. `SIGNOFF_STA_WORKER_IMAGE`로 이미지 이름을 바꿀 수 있습니다. `/analysis/sta-signoff`는 게이트 레벨 Verilog, Liberty, SDC를 네트워크와 호스트 마운트가 없는 읽기 전용 컨테이너에서 실행합니다. SDC의 일반 프로세스·소켓·동적 로드 Tcl 명령은 비활성화됩니다.

결과에는 입력별 SHA-256과 원문, 워커 이미지 ID, OpenSTA 커밋, 생성된 `report_checks -format json`을 보존합니다. 이 실행에는 AI가 개입하지 않습니다. 생성된 경로는 제한된 표본이므로 전체 STA 커버리지를 주장하거나 단독으로 스테이지 게이트를 통과시키지 않습니다. 저장된 런에서 A2 검토를 별도로 요청할 때만 Hermes 에이전트가 보고된 최저 슬랙 경로의 제한된 스냅샷을 받습니다.
  `result_locked=true`인 분석 결과에는 PATCH 및 수동 위반 추가가 409를 반환합니다.
  기존 위반의 수정 완료·웨이버·재오픈은 가능하며 원래 분석 근거는 그대로 보존합니다.
- `SIGNED_OFF`라도 lint/design/synthesize/simulate 필수 단계가 모두 명시적으로 pass가
  아니면 게이트를 통과시키지 않습니다. 생략/누락은 incomplete, 필수 실패는 failed입니다.
  테스트벤치 미제공 또는 실행 비활성 시 simulate가 skip이므로 클린 RTL도 incomplete입니다.
- 원본 근거가 없는 기존 RTL 런과 수동 RTL 런은 상태가 passed여도 RTL 게이트를 차단합니다.
  과거 상태를 임의로 변경하거나 실행 근거를 소급 생성하지 않습니다. 다시 분석하여 기록하세요.
- 다른 도메인의 수동 런은 기존 관리 게이트 정책을 유지합니다. 관리 게이트 준비 상태는
  외부 사인오프 툴의 원본 보고서 검증이나 최종 승인과 같지 않습니다.
- 툴 실행 시간 초과/시작 오류는 실패 판정에 반영되고 결과 상세에 원인을 기록합니다.
  프런트엔드는 최종 result 이벤트 없이 스트림이 끝나면 연결 중단 오류를 표시합니다.

### 기존 DB

기본 SQLite는 시작 시 `run_evidence` 테이블을 추가합니다. 기존 VARCHAR 상태 열에
incomplete를 저장할 수 있으며 기존 스키마로 만든 DB의 호환성을 회귀 테스트했습니다.
기존 PostgreSQL에서 native `runstatus` enum을 사용했다면 앱을 시작하기 전에 아래 enum
확장을 별도 마이그레이션으로 적용해야 합니다. PostgreSQL 업그레이드 자체는 아직 검증하지 않았습니다.

```sql
ALTER TYPE runstatus ADD VALUE IF NOT EXISTS 'incomplete';
```

## 동시 검토와 클라이언트 갱신

`GET /violations/{id}` 또는 기존 목록 API의 위반 객체에는 `version`이 포함됩니다.
상태 변경과 웨이버 승인 양쪽 모두 `expected_version`이 필수입니다. 생략, 문자열,
bool, 양수가 아닌 값은 422입니다. 조회한 값을 그대로 보내고 409를 받은 경우 현재 상태와
이력을 다시 검토하세요. 새 버전으로 자동 재시도하면 다른 검토자의 결정을 덮어쓸 수 있습니다.

```json
{
  "expected_status": "open",
  "expected_version": 3,
  "status": "waived",
  "actor": "reviewer",
  "reason": "검토한 승인 근거"
}
```

기존 `POST /violations/{id}/waiver` 요청도 `{reason, approved_by, expected_version}`을
보내야 합니다. 상태·버전 비교, 버전 증가, 웨이버 변경과 이력 추가는 한 트랜잭션입니다.
실패한 저장과 충돌은 상태·버전·웨이버·이력을 변경하지 않습니다.

### DB와 배포 순서

`app/migrations.py`가 시작 시 기존 violations 테이블에 `version INTEGER NOT NULL DEFAULT 1`을
추가합니다. 기존 행과 이력은 유지하며, 기존 행의 버전은 업그레이드 시점부터 1로 시작합니다.
SQLite는 BEGIN IMMEDIATE로, PostgreSQL은 트랜잭션 advisory lock으로 여러 새 서버의
동시 초기화를 직렬화합니다. SQLite의 동시·반복 실행과 데이터 보존은 테스트했으며,
PostgreSQL 실환경 업그레이드 검증은 남아 있습니다. 앞 절의 runstatus enum 확장도 필요합니다.

구버전 서버는 버전을 증가시키지 않으므로 신·구 서버의 쓰기 요청을 혼용하지 마세요.
기존 서버를 종료한 뒤 새 서버를 시작하고, 클라이언트도 expected_version을 보내도록 갱신합니다.

브라우저 초안은 React 메모리에서만 유지합니다. 필터로 항목이 사라지거나 앱 내부에서
화면을 이동해도 보존하지만 탭 새로고침·닫기 후 복원하는 영구 저장은 아닙니다.
충돌 후에는 저장을 잠그고 변경 이력을 확인하도록 하며, 취소·저장 완료 시 사유를 지웁니다.

### SQLite 백업·복원

`python -m app.backup create|verify|restore`로 온라인 스냅샷, 무결성 검증,
새 DB 경로 복원을 수행합니다. WAL과 실행 근거·검토 이력을 포함하며 기존 파일은
덮어쓰지 않습니다. [운영 복구 절차](../docs/backup-recovery.md)를 참고하세요.

### RTL 테스트벤치

선택 입력 `testbench`와 `testbench_top`을 받아 Icarus 시뮬레이션 결과와 원본 근거를 저장합니다.
기본 실행은 비활성이며 신뢰된 로컬 환경에서 명시적으로 활성화합니다.
[설정·판정 계약·운영 범위](../docs/rtl-simulation.md)

### 계정 인증과 권한

`SIGNOFF_AUTH_MODE=required`에서 세션 로그인과 프로젝트별 역할을 적용합니다.
기본 local 모드는 인증 없는 데모용입니다. [초기 관리자·배포·계정 운영 안내](../docs/authentication.md)를 따르세요.


### Hermes 검토 운영 설정

서비스 전용 프로파일 권장 설정은 `platform_toolsets.api_server: [no_mcp]`,
`agent.reasoning_effort: medium`입니다. 모델은 기존 `gpt-5.6-sol`을 유지합니다.
설정 예시는 `profiles/sign-off/config.snippets.yaml`을 참고하세요.
API 요청에는 공통 근거 검토 규약과 역할 프롬프트를 직접 전달합니다.
대화형 스킬 설치만으로 API 검토 품질이 바뀐다고 가정하지 않습니다.

검토는 요청별 독립 스냅샷입니다. `X-Hermes-Session-Id/Key`를 보내지 않아 이전 설계의
대화 이력을 이어받지 않으며, 동일 호출의 재시도는 같은 `Idempotency-Key`를 사용합니다.
`finish_reason=length/error/tool_calls/content_filter` 응답은 완료된 검토로 표시하지 않습니다.
원본 데이터 누락과 `reported_paths_only` 범위 한계를 명시하고, 출력은 승인 기록이 아닌
참고 의견으로 취급합니다. 이 지침은 모델의 정확성을 보장하는 증명은 아닙니다.
