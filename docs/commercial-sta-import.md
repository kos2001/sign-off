# PrimeTime / Tempus 경로 가져오기

프로젝트의 **보고서 가져오기 → PrimeTime / Tempus**에서 상용 STA 경로를 미리 본 뒤
불변 실행 근거로 저장합니다. 사람이 읽는 `report_timing` 텍스트는 툴 버전과 출력 옵션에 따라
열 구성이 달라질 수 있어 직접 추측하지 않습니다. 수집 스크립트가 아래의 명시적 JSON 계약으로
변환해야 하며, 서버는 모든 경로와 핀을 검증한 뒤 하나라도 잘못되면 전체 가져오기를 거부합니다.

## `signoff/commercial-sta-paths/v1`

```json
{
  "format": "signoff/commercial-sta-paths/v1",
  "tool": "Synopsys PrimeTime",
  "tool_version": "T-2025.06",
  "time_unit": "ns",
  "paths": [
    {
      "check_type": "setup",
      "path_type": "max",
      "path_group": "core_clk",
      "startpoint": "u_launch/Q",
      "endpoint": "u_capture/D",
      "slack": -0.025,
      "source_clock": "core_clk",
      "target_clock": "core_clk",
      "data_arrival_time": 0.8,
      "required_time": 0.775,
      "points": [
        {"pin": "u_launch/Q", "arrival": 0.1, "slew": 0.02},
        {"pin": "u_buf/Y", "cell": "BUF", "net": "n1", "arrival": 0.4},
        {"pin": "u_capture/D", "arrival": 0.8}
      ]
    }
  ]
}
```

- `tool`은 `Synopsys PrimeTime` 또는 `Cadence Tempus`입니다.
- `tool_version`은 수집한 툴의 실제 버전이며 화면 입력과 정확히 일치해야 합니다.
- `time_unit`은 `s`, `ns`, `ps`, `fs` 중 하나이고 모든 시간 값에 공통 적용됩니다.
- `path_type`은 `min` 또는 `max`입니다. `slack`은 유한 숫자이며 제약 없는 경로만 `null`입니다.
- `points`는 1~10,000개이며 첫째·마지막 `pin`이 `startpoint`·`endpoint`와 일치해야 합니다.
- 선택적으로 `instance`, `cell`, `net`, `arrival`, `slew`, `source_clock_points`,
  `target_clock_points`, `source_clock`, `source_clock_edge`, `target_clock`, `target_clock_edge`,
  `crpr`, `margin`, `path_margin`, `path_delay`, `data_arrival_time`, `required_time`,
  `multi_cycle_path`를 보존합니다.
- UTF-8 원본은 최대 2,000,000바이트, 전체 경로는 최대 1,000개입니다. 중복 JSON 키,
  NaN/Infinity, 숫자 범람, 제어 문자, 잘린 경로는 허용하지 않습니다.

## 저장 결과와 한계

원본 바이트와 SHA-256, 툴·버전·시나리오·설계 리비전, 정규화한 경로와 업로드 계정을
보존합니다. 음수 슬랙은 error 위반, `null` 슬랙은 unconstrained warning으로 등록합니다.
경로와 그룹을 검색·필터·내보내고 핀별 도착 시간 변화를 탐색할 수 있습니다.

이 계약은 수집된 경로만 증명합니다. 전체 경로 수, 모든 코너·모드, 제약 적용, SI/OCV 설정,
분산 실행 완료나 벤더 라이선스 상태를 증명하지 않으므로 위반이 없어도 상태는 `incomplete`입니다.
수집과 저장에는 AI가 개입하지 않습니다. 저장 후 A2 검토를 사용자가 요청할 때만 제한된 경로
스냅샷을 Hermes에 전달합니다.

API는 `POST /projects/{id}/imports/commercial-sta/preview`와
`POST /projects/{id}/imports/commercial-sta`입니다. 요청 본문과 UUID 기반 재시도 규약은
[OpenSTA 보고서 가져오기](report-import.md#api와-재시도)와 같습니다.
