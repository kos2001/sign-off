# Celsius / Icepak / Calibre 3DSTACK 열 결과 가져오기

`signoff/commercial-thermal/v1` JSON으로 상용 열 해석 핫스폿을 가져옵니다.

```json
{"format":"signoff/commercial-thermal/v1","tool":"Cadence Celsius","tool_version":"23.1","temperature_unit":"K","coordinate_unit":"mm","top_cell":"CHIP","hotspots":[{"component":"CPU","layer":"die0","temperature":383.15,"limit":378.15,"severity":"critical","x":1.5,"y":2.0,"z":0.1}]}
```

- 툴은 `Cadence Celsius`, `Ansys Icepak`, `Siemens Calibre 3DSTACK` 중 하나입니다.
- 온도 단위는 `C` 또는 `K`이며 °C로 정규화합니다. 절대영도 미만을 거부합니다.
- 좌표 단위는 `um` 또는 `mm`이며 µm로 정규화합니다. Z는 생략하면 0입니다.
- 온도가 제한을 초과하면 제출된 심각도의 위반을 만듭니다. 최대 5,000개, 원본 최대 2 MB입니다.

원본·SHA-256·툴 버전·설계 리비전·경계/전력 조건을 보존합니다. 핫스폿 화면은 XY 상대 위치와
Z 높이, 온도와 제한을 표시합니다. 제출된 점은 전체 재료 물성, 경계 조건, 전력 맵, 패키지,
냉각·유동 및 과도 해석 범위를 증명하지 않습니다. 깨끗한 결과도 `incomplete`이며 게이트를
통과하지 않습니다. 가져오기·계산·탐색에는 AI가 개입하지 않습니다.

## 신뢰된 전체 범위

운영자가 등록한 수집기는 가져오기 요청에 `signoff/coverage-attestation/v1`을 함께 보낼 수
있습니다. 서버는 프로젝트·스테이지·리비전·툴·시나리오·원본 SHA-256과 재료, 경계 조건,
전력 맵, 패키지 적층, 해석 범위, 메시 수렴 및 finding 완전성 claim의 HMAC 서명을 검증합니다.
유효한 증명과 제한 초과 0건이 함께 확인될 때만 런을 `passed`로 저장하고 열 게이트 근거로
사용합니다. 상세 계약은 [수집기 커버리지 증명](coverage-attestation.md)을 참고하세요.

API는 `POST /projects/{id}/imports/commercial-thermal/preview`,
`POST /projects/{id}/imports/commercial-thermal`, `GET /runs/{id}/thermal-hotspots`입니다.
