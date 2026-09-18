# VC LP / Conformal Low Power 결과 가져오기

프로젝트의 **보고서 가져오기 → VC LP / Conformal Low Power**에서 수집기가 만든
`signoff/commercial-low-power/v1` JSON을 미리 보고 저장한다. 지원 범위는
[Synopsys VC LP](https://www.synopsys.com/verification/static-and-formal-verification/vc-lp.html)와
[Cadence Conformal Low Power](https://login.cadence.com/content/cadence-www/global/en_US/home/resources/datasheets/encounter-conformal-low-power-ds.html)의 정적 저전력 결과다.

```json
{"format":"signoff/commercial-low-power/v1","tool":"Synopsys VC LP","tool_version":"T-2025.06","top":"CHIP","status":"clean","summary":{"power_domains":4,"power_states":8,"domain_crossings":19,"checked_rules":650},"findings":[]}
```

finding 종류는 `power_intent`, `isolation`, `level_shifter`, `retention`, `power_switch`,
`always_on`, `pg_connectivity`, `power_state`다. `clean` 결과에는 error/critical finding이 없어야
하고 `violations`에는 적어도 하나가 있어야 한다. 모순된 결과는 저장 전에 거부한다.

API는 `POST /projects/{id}/imports/commercial-low-power/preview`,
`POST /projects/{id}/imports/commercial-low-power`, `GET /runs/{id}/low-power-findings`다.
서명 없는 clean 보고서는 `incomplete`다. 수집기 HMAC 증명이 power intent, 설계 입력, 라이브러리,
power domain/state, 구조·기능, PG 검사와 finding 전체 범위를 결합해야만 `passed`가 된다.
저전력 기능은 모든 설계에 존재하지 않으므로 현재 공통 스테이지 게이트에는 강제하지 않는다.
AI는 파싱·서명·판정·탐색에 개입하지 않는다.
