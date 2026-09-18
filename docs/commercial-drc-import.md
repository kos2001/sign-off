# Calibre / Pegasus DRC 마커 가져오기

프로젝트의 **보고서 가져오기 → Calibre / Pegasus**에서 상용 DRC 마커를 미리 보고 불변
실행 근거로 저장합니다. 벤더별 텍스트나 RDB 문법을 서버가 추측하지 않습니다. 수집기가 아래
JSON 계약으로 변환해야 하며, 잘못된 마커가 하나라도 있으면 전체 가져오기를 거부합니다.

## `signoff/commercial-drc-markers/v1`

```json
{
  "format": "signoff/commercial-drc-markers/v1",
  "tool": "Siemens Calibre nmDRC",
  "tool_version": "2025.2_18.11",
  "coordinate_unit": "nm",
  "top_cell": "CHIP",
  "rule_deck": "foundry-deck-7nm-r42",
  "markers": [
    {
      "rule": "M1.SPACING.1",
      "cell": "CORE",
      "severity": "critical",
      "multiplicity": 2,
      "message": "M1 spacing below minimum",
      "shapes": [
        {"type": "box", "points": [[1500, 2000], [1600, 2100]]}
      ]
    },
    {
      "rule": "VIA1.ENC.2",
      "cell": "",
      "severity": "warning",
      "shapes": [
        {"type": "polygon", "contours": [
          [[0, 0], [100, 0], [100, 100], [0, 100]],
          [[20, 20], [40, 20], [40, 40]]
        ]}
      ]
    }
  ]
}
```

- `tool`은 `Siemens Calibre nmDRC` 또는 `Cadence Pegasus`입니다.
- `tool_version`은 수집한 툴의 실제 버전이며 화면 입력과 정확히 일치해야 합니다.
- `coordinate_unit`은 `um` 또는 `nm`입니다. 서버는 탐색용 도형을 µm로 정규화합니다.
- `top_cell`과 각 `rule`은 필수입니다. `cell`은 최상위 문맥이면 빈 문자열일 수 있습니다.
- `severity`는 `info`, `warning`, `error`, `critical` 중 하나이며 위반에 그대로 보존합니다.
- `multiplicity`는 기본 1인 양의 정수입니다. 같은 원본 발생을 자동으로 여러 위반 행으로
  펼치지 않고 보고 수량으로 보존합니다.
- `box`와 `edge`는 정확히 두 점, `polygon`은 3점 이상인 하나 이상의 `contours`를 사용합니다.
  첫 contour는 외곽선이고 나머지는 원본 수집기가 기록한 내부 contour입니다.
- 보고서는 UTF-8 최대 2,000,000바이트, 마커 1,000개, 마커별 도형 100개와 점 2,000개입니다.
  중복 JSON 키, NaN/Infinity, 범위 밖 좌표, 잘린 도형은 허용하지 않습니다.

## 저장 결과와 한계

원본 바이트와 SHA-256, 툴·버전·룰덱 조건·설계 리비전, 규칙·셀·심각도·도형과 업로드
계정을 보존합니다. 마커를 규칙과 셀로 검색하고 원본 셀 좌표에서 확대해 보며 연결된 위반을
검토할 수 있습니다. 원본 심각도는 해결, 승인 또는 웨이버가 아니며 권한 있는 사용자의 처리
이력과 분리됩니다.

이 계약은 제출된 마커만 증명합니다. 룰덱 파일과 해시, 레이어 매핑, 전체 셀 계층, 실행 완료,
라이선스 상태, DRC clean 여부를 증명하지 않습니다. 마커가 없어도 런은 `incomplete`이고 이
근거만으로 PV 게이트를 통과하지 않습니다. 좌표에는 계층 변환을 적용하지 않습니다. 수집,
저장, 탐색과 위반 생성에는 AI가 개입하지 않습니다.

API는 `POST /projects/{id}/imports/commercial-drc/preview`와
`POST /projects/{id}/imports/commercial-drc`입니다. 요청 본문과 UUID 기반 재시도 규약은
[OpenSTA 보고서 가져오기](report-import.md#api와-재시도)와 같습니다.
