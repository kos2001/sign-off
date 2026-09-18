# VCS / Xcelium RTL 회귀 결과 가져오기

`signoff/commercial-rtl-regression/v1` JSON으로 상용 시뮬레이터의 컴파일과 테스트 결과를 가져옵니다.

```json
{"format":"signoff/commercial-rtl-regression/v1","tool":"Synopsys VCS","tool_version":"V-2025.06","compile_status":"passed","compile_log_excerpt":"compile ok","tests":[{"name":"smoke_boot","status":"passed","duration_ms":12.5,"seed":42,"assertions":{"passed":20,"failed":0,"disabled":1},"log_excerpt":"PASS"}]}
```

- 툴은 `Synopsys VCS` 또는 `Cadence Xcelium`입니다.
- 컴파일 상태는 `passed|failed`, 테스트 상태는 `passed|failed|skipped`입니다.
- 테스트 이름은 중복될 수 없고 최대 5,000개입니다. 시간은 0 이상의 ms, seed는 안전한 정수 또는 null입니다.
- assertion의 passed/failed/disabled는 0 이상의 정수입니다. passed 테스트에 failed assertion을 허용하지 않습니다.
- 로그 발췌는 컴파일과 테스트별 최대 20,000자이며 원본 전체는 2 MB 이하입니다.

원본·SHA-256·툴 버전·설계 리비전·회귀 구성을 보존하고 컴파일/테스트 실패를 위반으로 만듭니다.
회귀 화면에서 상태별 테스트, 시간, seed, assertion 집계와 로그를 확인합니다. 제출된 결과는 전체
테스트 계획, 기능·코드 커버리지, plusarg, 라이브러리와 실제 시뮬레이터 실행을 증명하지 않습니다.
따라서 깨끗한 결과도 `incomplete`이고 기존 RTL 래더 근거 없이 게이트를 통과하지 않습니다.
가져오기·판정·탐색에는 AI가 개입하지 않습니다.

## 신뢰된 전체 범위

운영자가 등록한 수집기는 가져오기 요청에 `signoff/coverage-attestation/v1`을 함께 보낼 수
있습니다. 서버는 프로젝트·스테이지·리비전·툴·시나리오·원본 SHA-256과 테스트 계획,
컴파일, 시뮬레이션, assertion, 코드/기능 커버리지, 결과 완전성 claim의 HMAC 서명을 검증합니다.
유효한 증명과 컴파일·테스트·assertion 실패 0건이 함께 확인될 때만 런을 `passed`로 저장하고
RTL 게이트 근거로 사용합니다. 상세 계약은 [수집기 커버리지 증명](coverage-attestation.md)을
참고하세요.

API는 `POST /projects/{id}/imports/commercial-rtl/preview`,
`POST /projects/{id}/imports/commercial-rtl`, `GET /runs/{id}/rtl-regression`입니다.
