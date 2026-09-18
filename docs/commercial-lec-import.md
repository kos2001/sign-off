# Formality / Conformal 논리 등가성 결과 가져오기

프로젝트의 **보고서 가져오기 → Formality / Conformal LEC**에서 수집기가 만든
`signoff/commercial-lec/v1` JSON을 미리 보고 저장한다. 서버는 벤더 로그를 추측하지 않고
reference·implementation TOP, compare point 집계, 판정과 실패 목록의 모순을 검사한다.

```json
{
  "format": "signoff/commercial-lec/v1",
  "tool": "Synopsys Formality",
  "tool_version": "T-2025.06",
  "reference_top": "CHIP",
  "implementation_top": "CHIP",
  "status": "non_equivalent",
  "summary": {"reference_compare_points": 100, "implementation_compare_points": 100, "matched_points": 99, "failing_points": 1, "aborted_points": 0, "unreachable_points": 0},
  "failures": [{"kind": "non_equivalent", "name": "compare/M42", "severity": "critical", "reference_object": "r:/WORK/CHIP/M42", "implementation_object": "i:/WORK/CHIP/M42", "message": "Logic cone differs."}]
}
```

`tool`은 `Synopsys Formality` 또는 `Cadence Conformal`이다. 판정은 `equivalent`,
`non_equivalent`, `error`이며 equivalent 결과에는 실패 항목이나 failing/aborted point를 허용하지
않는다. 실패 kind는 `non_equivalent`, `unmapped`, `aborted`, `black_box`, `setup`이다.

API는 `POST /projects/{id}/imports/commercial-lec/preview`,
`POST /projects/{id}/imports/commercial-lec`, `GET /runs/{id}/lec-failures`다. 원본 SHA-256,
정규화된 집계·실패, 제출 신원을 불변 근거로 보존하고 실패를 차단 위반으로 만든다.

서명 없는 equivalent 보고서는 `incomplete`다. HMAC 증명이 setup, 양쪽 입력, 라이브러리, 제약,
compare point, 비교와 finding 전체 범위를 결합한 경우에만 clean 결과를 `passed`로 인정한다.
synthesis와 final 게이트는 LEC를 별도 필수 도메인으로 요구한다. 이 증명은 등록 수집기의 선언이며
벤더 서명, 실제 입력 파일이나 호스트 무결성을 증명하지 않는다. 가져오기·판정·탐색에는 AI가
개입하지 않는다.
