---
name: sign-off-drc-rules
description: "Reference for the Sign-off Hub RTL ladder's DRC-XXX rule codes and the shift-left stage-gate domain matrix. Use WHENEVER a DRC code (e.g. DRC-CDC-001), a gating-stage/design-rule question, or 'why is this rule failing / why won't this stage gate open' comes up — these are app-specific and not standard SpyGlass/industry codes, so don't guess their meaning from the code alone."
---

# DRC 룰 카탈로그 (RTL 사인오프 래더)

`backend/app/services/rtl/signoff.py`의 `DRC_RULES`에서 뽑음. 코드는 SpyGlass 스타일 이름을
흉내내지만 이 앱 자체 정의이며, 매핑은 `sign-off-api`로 얻은 `rules[]` 응답의 `code`/`name`과
1:1 대응한다.

| 코드 | 심각도 | 검사 | 위반 시 의미 · 전형적 수정 |
|---|---|---|---|
| DRC-STRUCT-001 | error (게이팅) | 모듈 선언 존재 | 파싱 자체가 안 됨 — 소스가 비어있거나 `module` 키워드 누락 |
| DRC-STYLE-001 | warn | SystemVerilog `logic` 타입 사용 | 레거시 `reg`/`wire` 발견 — `logic`으로 교체 (기능에는 영향 없음) |
| DRC-STYLE-002 | warn | `always_ff`/`always_comb` 사용 | 구식 `always @(...)` 발견 — 블록 타입을 명시적으로 분리 |
| DRC-SEQ-001 | error (게이팅) | 순차 로직에 non-blocking `<=` | `always_ff` 안에서 blocking `=` 사용 — 레이스 컨디션 위험, `<=`로 교체 |
| DRC-RST-001 | warn | 리셋 신호 존재 | `rst`/`reset` 패턴이 코드에 없음 — 실제로 리셋이 없는 설계라면 무시 가능 |
| DRC-RST-002 | info | 리셋 분류(sync/async, 극성) | 정보성 — 분류 결과가 의도한 리셋 스타일과 다르면 확인 |
| DRC-WIDTH-001 | info | 크기 없는 매직 상수 없음 | `[N:0]` 폭 문맥에서 `= <digit>;` 같은 무폭 리터럴 발견 — `N'dNN` 형태로 명시 |
| DRC-WIDTH-002 | warn | 폭 truncation/expansion 없음 | strict verilator lint(WIDTH*)에서 발견 — 대입 좌우 비트폭을 맞춤 |
| DRC-SYNTH-001 | error (게이팅) | yosys 합성 성공 | 합성 불가 구문 — 비합성 시스템 함수·초기화 등을 제거 |
| DRC-LATCH-001 | warn | 추론된 latch 없음 | `always_comb`에서 모든 출력이 모든 경로에서 대입되지 않음 — 조합 블록의 모든 분기를 커버 |
| DRC-CDC-001 | error (게이팅) | 동기화 안 된 클럭 도메인 교차 없음 | 한 클럭에서 구동된 신호를 동기화 없이 다른 클럭 블록에서 직접 읽음 — 수신 도메인에 2단 이상 동기화 플롭 추가 (레벨: 표준 2-FF, 펄스: toggle/handshake). 정규식 휴리스틱이라 `_sync`/`_meta`/`_ff2`/`_q2`/`_r2` 접미사가 붙은 신호는 이미 동기화된 것으로 간주해 건너뜀 |
| DRC-FSM-001 | warn | 모든 FSM 상태 도달 가능 | 리셋 상태에서 BFS로 도달 안 되는 state 존재 — 전이 누락이거나 죽은 코드 |
| DRC-FSM-002 | warn | FSM dead-end 상태 없음 | 그 상태에서 나가는 전이가 하나도 없음 — 의도한 terminal state면 웨이버, 아니면 복구 전이 추가 |
| DRC-FSM-003 | info | FSM 정상(정보성 요약) | 위 두 검사가 모두 통과했을 때만 나타남 |

`error` 심각도는 4개뿐이다: STRUCT-001, SEQ-001, CDC-001, SYNTH-001. 이 중 **STRUCT-001/SEQ-001/CDC-001**은
`design` 스테이지를 게이팅하고, **SYNTH-001**은 별도의 `synthesize` 스테이지를 게이팅한다(design
단계 판정에서는 `synthesizable` 체크를 일부러 제외 — 자기 스테이지에서 따로 본다). 즉 CDC 위반
1건만 있어도 design 단계가 fail → 래더 전체가 REJECTED. FSM/style 계열은 `warn`이라 단독으로는
어떤 스테이지도 게이팅하지 않지만 QoR 점수를 깎는다.

## Shift-left 스테이지 게이트 매트릭스

`backend/app/services/stages.py`의 `REQUIRED_DOMAINS`. 스테이지별로 "이 도메인의 **그 스테이지에서의**
최신 런"이 passed 이고 open 상태의 error/critical 위반이 없어야 ready.

| 스테이지 | 필수 도메인 |
|---|---|
| rtl | rtl(RTL 품질), sta |
| synthesis | sta, glitch_power |
| placement | sta, emir, pv |
| routing | sta, emir, pv |
| final | sta, emir, pv, glitch_power, thermal |

흔한 오해: "STA가 이전 스테이지에서 통과했으니 이번 스테이지도 괜찮겠지" — 아니다. 같은 도메인이라도
스테이지가 다르면 별개의 런이고, 게이트는 **그 스테이지의** 런만 본다.
