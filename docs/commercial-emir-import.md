# RedHawk-SC / Voltus / Totem EM/IR 결과 가져오기

프로젝트의 **보고서 가져오기 → 상용 EM/IR**에서 전압 강하와 전류 밀도 결과를 미리 본 뒤
불변 실행 근거로 저장합니다. 벤더별 텍스트를 서버가 추측하지 않습니다. 수집기가 아래 JSON
계약으로 변환해야 하며, 잘못된 결과가 하나라도 있으면 전체 가져오기를 거부합니다.

## `signoff/commercial-power-integrity/v1`

```json
{
  "format": "signoff/commercial-power-integrity/v1",
  "tool": "Ansys RedHawk-SC",
  "tool_version": "2025 R1",
  "coordinate_unit": "nm",
  "top_cell": "CHIP",
  "findings": [
    {
      "analysis": "static_ir",
      "metric": "voltage_drop",
      "check": "VDD max drop",
      "severity": "critical",
      "value": 0.085,
      "limit": 0.075,
      "unit": "V",
      "x": 1500,
      "y": 2000,
      "instance": "u_core/u_cpu",
      "net": "VDD",
      "layer": "M8",
      "message": "Static rail drop exceeds the submitted limit"
    },
    {
      "analysis": "em",
      "metric": "current_density",
      "check": "M4 signal EM",
      "severity": "warning",
      "value": 0.8,
      "limit": 1.0,
      "unit": "mA/um2",
      "x": 500,
      "y": 600,
      "net": "n42",
      "layer": "M4"
    }
  ]
}
```

- `tool`은 `Ansys RedHawk-SC`, `Cadence Voltus`, `Ansys Totem` 중 하나입니다.
- `tool_version`은 실제 수집 버전이며 화면 입력과 정확히 일치해야 합니다.
- `coordinate_unit`은 `um` 또는 `nm`이며 탐색 좌표는 µm로 정규화됩니다.
- `analysis`는 `static_ir`, `dynamic_ir`, `em` 중 하나입니다.
- static/dynamic IR은 `metric=voltage_drop`과 `V`, `mV`, `uV` 단위를 사용합니다. EM은
  `metric=current_density`와 `A/um2`, `mA/um2`를 사용합니다. 한 결과의 `value`와 `limit`는
  같은 단위입니다. 서버는 전압 강하를 mV, 전류 밀도를 A/µm²로 정규화합니다.
- `value > limit`이면 제한 초과입니다. 서버가 제출된 별도 pass 플래그를 신뢰하지 않고 다시 계산합니다.
- `severity`는 `info`, `warning`, `error`, `critical` 중 하나입니다. 제한 초과 결과만 위반으로
  생성하며 제출된 심각도는 승인이나 웨이버가 아닙니다.
- `instance`, `net`, `layer`, `message`는 선택 항목입니다. 좌표와 `check`는 필수입니다.
- UTF-8 원본은 최대 2,000,000바이트, 결과는 최대 5,000개입니다. 중복 JSON 키,
  NaN/Infinity, 음수 측정값·제한, 범위 밖 좌표는 허용하지 않습니다.

## 탐색과 한계

EM/IR 핫스폿 화면은 분석 종류·측정 항목·제한 초과 여부로 필터하고 현재 페이지의 상대 위치를
표시합니다. 원본 값·제한·좌표·인스턴스·넷·레이어와 연결된 위반을 상세에서 확인합니다.
위치 그림은 레이아웃 배경, 라우팅 형상, 전원망 또는 계층 변환을 포함하지 않습니다.

커버리지 증명이 없는 이 계약은 제출된 결과만 증명합니다. 전체 rail·모드·벡터, 전원망 추출, 패키지 모델, 온도,
활동도, EM 수명 모델, 분산 실행 완료나 라이선스 상태를 증명하지 않습니다. 결과가 없어도 런은
`incomplete`이며 이 근거만으로 EM/IR 게이트를 통과하지 않습니다. 가져오기, 제한 비교,
위반 생성과 탐색에는 AI가 개입하지 않습니다.

API는 `POST /projects/{id}/imports/commercial-emir/preview`,
`POST /projects/{id}/imports/commercial-emir`, `GET /runs/{id}/power-integrity-findings`입니다.
요청 본문과 UUID 기반 재시도 규약은 [OpenSTA 보고서 가져오기](report-import.md#api와-재시도)와 같습니다.

## 신뢰된 수집기의 전체 범위 증명

선택 필드 `coverage_attestation`에 서버 등록 키로 서명한 증명을 첨부할 수 있습니다. 증명은
`domain: "emir"`와 `tool_run_completed`, `rail_coverage_complete`,
`modes_corners_complete`, `activity_vectors_complete`, `extraction_complete`,
`checks_complete`, `findings_complete`를 정확히 포함하고 모두 `true`여야 합니다.

유효한 증명과 함께 제한 초과 finding이 0건인 경우에만 `passed`로 저장하고 EM/IR 게이트
근거로 인정합니다. 제한 안의 finding은 원본 그대로 보존합니다. 공통 키·만료·정규화·서명
규칙은 [수집기 커버리지 증명](coverage-attestation.md)을 참고하세요.
