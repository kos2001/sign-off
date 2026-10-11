# OpenLane 2 플로우 결과 가져오기

프로젝트의 **보고서 가져오기 → OpenLane 2**에서 OpenLane 2 런의 지표 파일 하나로 타이밍(STA),
물리 검증(PV), LVS 런을 함께 만든다. 세 런은 같은 설계 리비전·스테이지·원본 SHA-256을 공유한다.
리비전마다 가져오면 **런 비교**에서 코너별 슬랙, 위반 수와 finding의 추가·해소를 비교할 수 있다.

## 입력 파일

- `runs/<tag>/final/metrics.json`: 정상 종료한 런의 최종 지표.
- 마지막 단계의 `state_out.json`: OpenLane은 사인오프 checker가 실패하면 `final/`을 쓰지 않는다.
  이 경우 마지막으로 실행된 단계 폴더의 `state_out.json`을 올리며, 그 안의 `metrics` 객체만 사용한다.

지표는 [METRICS2.1](https://github.com/ieee-ceda-datc/datc-rdf-Metrics4ML) 명명
(`category__metric[__modifier:value]`)을 따르는 평탄한 JSON 객체여야 한다. 2 MB, 20,000개 이하이며
중복 키, 중첩 값, `NaN`과 형식에 맞지 않는 이름은 거부한다. OpenLane이 경로가 없는 슬랙을
`Infinity`로 쓰는 경우는 받아들이되 "보고되지 않음"으로 기록하고 해당 지표 이름을 근거에 남긴다.

시간 값은 Liberty 시간 단위를 따른다(OpenSTA `time_sta_ui`). sky130·gf180은 ns, asap7 등은 ps이므로
가져올 때 단위를 선택한다. 저장 값은 ps로 변환한다. 전력은 W→mW, IR drop은 V→mV로 표시한다.

## 도메인과 finding

| 런 | 사용하는 지표 | 차단(error) | 경고(warning) |
|---|---|---|---|
| STA | `timing__{setup,hold}__{ws,tns}__corner:*`, `timing__{setup,hold}_vio__count__corner:*`, `design__max_{slew,cap,fanout}_violation__count[__corner:*]` | 코너별 WNS < 0 또는 위반 종점 > 0 | 코너별 max slew·cap·fanout 위반 |
| PV | `route__drc_errors`, `magic__drc_error__count`, `klayout__drc_error__count`, `magic__illegal_overlap__count`, `design__xor_difference__count`, `design__critical_disconnected_pin__count`, `design__power_grid_violation__count`, `antenna__violating__{nets,pins}` | 안테나를 제외한 각 개수 > 0 | 안테나 위반 넷·핀 |
| LVS | `design__lvs_error__count`와 세부 개수 | LVS 오류 > 0 | — |

파일에 지표가 없는 도메인은 런을 만들지 않는다. 코너별 개수가 없고 합계만 있으면 "all corners"
finding으로 남긴다. finding은 `openlane/<domain>/<check>/<corner>` 이름과 코너 위치를 가지므로
리비전 간 비교에서 같은 항목으로 대응된다.

판정 기준은 OpenLane 2 checker(`openlane/steps/checker.py`)의 기본값과 맞춘다. DRC·겹침·XOR·끊어진 핀·
PDN·LVS는 0 초과 시 플로우를 실패시키고, max slew·cap은 기본 경고이며, 안테나는 checker가 없다.
차이 한 가지: OpenLane의 sky130·gf180 기본값은 `*tt*` 코너의 setup·hold 위반만 실패로 보지만,
Sign-off Hub는 보고된 **모든 코너**의 음수 슬랙을 차단 finding으로 기록한다.

## 근거와 게이트

`POST /projects/{id}/imports/openlane-metrics/preview`와 `POST /projects/{id}/imports/openlane-metrics`
(편집자 이상)를 사용한다. 입력은 다른 가져오기와 같은 `import_id`, `stage`, `filename`,
`tool_version`(OpenLane 버전), `design_revision`, `scenario`(런 태그), `source_text`에
`time_unit`(`ns`·`ps`, 기본 `ns`)을 더한다. 응답은 `{"runs": [...]}`다. 같은 `import_id`의 재전송은
기존 런을 그대로 돌려주고, 내용이 다르면 409를 반환한다. 원본은 각 런의 근거로 보존되어
**원본 파일 다운로드**에서 SHA-256과 함께 받을 수 있고, 런 상태는 수동으로 바꿀 수 없다.

플로우 지표는 코너별 최악값과 개수의 요약이다. 제약, 코너 구성, 기생 성분, 경로·마커 상세와
파운드리 사인오프 룰덱 실행을 증명하지 않는다. 따라서 위반이 없어도 상태는 `incomplete`이며,
게이트는 "OpenLane 플로우 지표만으로는 전체 검증 범위 미확인"으로 차단을 유지한다. 최종 승인에는
OpenSTA 실행 또는 서명된 상용 도구 결과 등 범위가 증명된 근거가 필요하다. 수집기 자동 제출은
커버리지 증명이 있는 경로만 허용되므로 이 가져오기는 사람이 화면이나 API로 제출한다.
가져오기와 판정에는 AI가 개입하지 않는다.

## 참고

- OpenLane 2 지표 라이브러리와 checker: `chipfoundry/openlane2`의 `openlane/common/metrics/`,
  `openlane/steps/checker.py`, `openlane/flows/sequential.py`.
- 실제 sky130 런 지표를 테스트 픽스처로 사용한다(`backend/tests/fixtures/openlane/`, 출처: ppa-eda-agent
  참조 실험, MIT).
