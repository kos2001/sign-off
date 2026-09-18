# PrimePower / Joules / PowerArtist 전력 결과 가져오기

상용 전력 분석의 총전력, 내부·스위칭·누설·글리치 전력과 계층별 기여도를
`signoff/commercial-power/v1` JSON으로 가져옵니다. 서버는 벤더 텍스트를 추측하지 않습니다.

```json
{
  "format": "signoff/commercial-power/v1",
  "tool": "Synopsys PrimePower",
  "tool_version": "T-2025.06",
  "power_unit": "uW",
  "glitch_share_limit": 0.2,
  "summary": {"total_power": 1000, "internal_power": 200, "switching_power": 700, "leakage_power": 100, "glitch_power": 250},
  "hierarchy": [
    {"path": "TOP/u_cpu", "total_power": 600, "internal_power": 100, "switching_power": 450, "leakage_power": 50, "glitch_power": 150}
  ]
}
```

- `tool`은 `Synopsys PrimePower`, `Cadence Joules`, `Ansys PowerArtist` 중 하나입니다.
- `power_unit`은 `W`, `mW`, `uW`이며 서버는 mW로 정규화합니다.
- 총전력은 내부+스위칭+누설과 1 ppm 안에서 같아야 하고 글리치 전력은 스위칭 전력을 넘을 수 없습니다.
- `glitch_share_limit`은 0~1입니다. 서버가 글리치/총전력을 다시 계산하고 초과한 TOP과 계층을 위반으로 만듭니다.
- 계층 경로는 중복될 수 없으며 최대 5,000개, UTF-8 원본은 최대 2 MB입니다.

원본과 SHA-256, 툴·버전·시나리오·설계 리비전을 보존합니다. 전력 계층 화면에서 총전력 또는
글리치 비중으로 정렬하고 제한 초과 여부로 필터합니다. 제출된 요약은 전체 벡터·활동도·모드,
라이브러리·기생성분·전압·온도 조건이나 툴 실행 진위를 증명하지 않습니다. 결과가 깨끗해도
`incomplete`이며 게이트를 통과하지 않습니다. 가져오기·계산·탐색에는 AI가 개입하지 않습니다.

API는 `POST /projects/{id}/imports/commercial-power/preview`,
`POST /projects/{id}/imports/commercial-power`, `GET /runs/{id}/power-breakdown`입니다.
