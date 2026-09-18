# 신뢰된 수집기 커버리지 증명

경로·마커·EM/IR finding 목록만으로는 툴이 모든 필수 입력과 검사를 끝까지 실행했는지
알 수 없다. `signoff/coverage-attestation/v1`은 운영자가 등록한 수집기가 실행 범위를 확인하고
특정 가져오기 요청에 HMAC-SHA256으로 묶는 계약이다. 사용자가 직접 입력한 체크박스나 툴 이름은
전체 범위 근거로 인정하지 않는다.

## 서버 키 설정

```sh
SIGNOFF_COVERAGE_HMAC_KEYS='{"sta-collector-2026q3":{"secret":"32-bytes-minimum-random-secret-value","domains":["sta"]}}'
```

JSON 객체의 키는 `key_id`이며 각 값은 `secret`과 `domains`를 정확히 포함한다. `secret`은 최소
32 UTF-8 바이트이고 `domains`는 `sta`, `pv`, `emir`, `glitch_power`, `thermal` 중 이 키가
서명할 수 있는 범위다. 빈 범위,
중복 또는 알 수 없는 도메인은 거부한다. 최대 16개 키를 동시에 등록해 교체 기간을 운영할 수 있다.
실제 키는 저장소나 보고서에 넣지 말고 비밀 관리 시스템에서
API 서버와 수집기에 주입한다. 설정이 존재하지만 JSON 또는 키가 잘못되면 API 서버 시작을
거부한다. 증명 기능을 사용하지 않으면 변수를 설정하지 않아도 된다.

## 증명 계약

```json
{
  "format": "signoff/coverage-attestation/v1",
  "attestation_id": "가져오기 import_id와 같은 UUID",
  "key_id": "sta-collector-2026q3",
  "issued_at": "2026-09-19T01:00:00Z",
  "expires_at": "2026-09-19T02:00:00Z",
  "project_id": 1,
  "stage": "routing",
  "domain": "sta",
  "design_revision": "release-2026.09",
  "source_sha256": "64자리 소문자 SHA-256",
  "tool": "Synopsys PrimeTime",
  "tool_version": "T-2025.06",
  "scenario": "all-signoff-views",
  "claims": {
    "tool_run_completed": true,
    "modes_corners_complete": true,
    "constraints_validated": true,
    "parasitics_requirement_satisfied": true,
    "findings_complete": true,
    "unconstrained_paths_zero": true
  },
  "signature": "64자리 소문자 HMAC-SHA256"
}
```

`issued_at`과 `expires_at`은 시간대를 포함하고 유효 기간은 0초 초과 7일 이하여야 한다. 서버
시각은 발급 시각보다 최대 5분 빠를 수 있으며 만료 뒤에는 거부한다. 모든 문자열 바인딩은
대소문자와 공백까지 정확히 비교한다. `attestation_id`를 `import_id`와 같게 강제하므로 같은
프로젝트에서 재사용하면 기존 멱등 가져오기 규칙이 적용된다.
이미 저장된 것과 바이트까지 같은 요청은 증명이 만료되거나 해당 키가 교체된 뒤에도 기존 런을
반환한다. 내용이 달라진 같은 UUID는 계속 409로 거부한다.

서명 전 UUID는 소문자 표준형, 시간은 UTC의 `Z` 표기(예: `2026-09-19T01:00:00Z`)로
정규화한다. 그 뒤 `signature` 필드를 제외한 증명 객체를 UTF-8 JSON으로 직렬화한다. 키는 사전순,
구분자는 `,`와 `:`, 비 ASCII 문자는 이스케이프하지 않는다. 서버 구현의
`canonical_payload()`와 같은 규칙이다.

```python
canonical = json.dumps(attestation_without_signature, ensure_ascii=False,
                       allow_nan=False, sort_keys=True,
                       separators=(",", ":")).encode()
signature = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
```

수집기는 원본 보고서 바이트를 최종 확정한 뒤 SHA-256을 계산하고 증명을 발급해야 한다. 서명 후
보고서, UUID, 프로젝트, 스테이지, 리비전, 툴 버전 또는 시나리오가 바뀌면 서버가 요청 전체를
422로 거부한다. 알 수 없는 키, 누락/거짓 claim, 만료, 서명 불일치도 저장 전에 거부한다.

## 판정과 감사 범위

서명 검증 성공 사실, 전체 증명과 서명은 런의 불변 evidence result에 보존된다. 보고서 자체에
음수 슬랙이 있으면 범위 증명이 유효해도 `failed`이며 위반을 생성한다. 보고서에 unconstrained
경로가 있으면 `unconstrained_paths_zero` 선언과 모순되므로 증명 자체를 거부한다.

HMAC은 Sign-off Hub 운영자와 수집기 사이의 신뢰만 증명한다. 벤더 바이너리·라이선스·실제 입력
파일의 진위, 수집기 호스트 침해 여부를 증명하지 않는다. AI는 서명 검증, 상태 계산 또는 게이트
판정에 개입하지 않는다.

### DRC claim 집합

Calibre/Pegasus 증명은 `domain: "pv"`와 다음 여섯 키를 정확히 사용하며 모두 `true`여야 한다.

- `tool_run_completed`
- `rule_deck_complete`
- `layout_inputs_complete`
- `hierarchy_complete`
- `checks_complete`
- `findings_complete`

DRC 보고서에 error/critical 마커가 있으면 증명이 유효해도 런은 `failed`다. warning/info만
있거나 마커가 없으면 `passed`가 될 수 있다. 증명은 웨이버를 만들거나 마커 상태를 바꾸지 않는다.

### EM/IR claim 집합

RedHawk-SC/Voltus/Totem 증명은 `domain: "emir"`와 다음 키를 정확히 사용하며 모두
`true`여야 한다: `tool_run_completed`, `rail_coverage_complete`,
`modes_corners_complete`, `activity_vectors_complete`, `extraction_complete`,
`checks_complete`, `findings_complete`. 제출된 값과 제한은 서버가 다시 비교한다. 제한 초과
finding이 하나라도 있으면 범위 증명이 유효해도 `failed`이며 웨이버로 자동 변환하지 않는다.

### 전력 분석 claim 집합

PrimePower/Joules/PowerArtist 증명은 `domain: "glitch_power"`와 다음 키를 정확히 사용하며
모두 `true`여야 한다: `tool_run_completed`, `modes_corners_complete`,
`activity_vectors_complete`, `power_models_complete`, `hierarchy_complete`,
`findings_complete`. TOP 또는 계층 항목의 글리치 비중이 제출된 제한을 넘으면 유효한 증명이
있어도 `failed`다.

### 열 해석 claim 집합

Celsius/Icepak/Calibre 3DSTACK 증명은 `domain: "thermal"`과 다음 키를 정확히 사용하며 모두
`true`여야 한다: `tool_run_completed`, `material_models_complete`,
`boundary_conditions_complete`, `power_map_complete`, `package_stack_complete`,
`analysis_scope_complete`, `mesh_convergence_complete`, `findings_complete`. 제한을 넘은 온도
finding이 하나라도 있으면 유효한 증명이 있어도 `failed`다.
