# 사인오프 결정과 근거 동결

상용 사인오프에서는 분석 결과와 사람의 최종 결정을 같은 시점의 근거에 묶어야 한다.
프로젝트 화면의 **사람의 사인오프 결정**은 현재 스테이지 게이트와 원본 보고서를 다시
검증하고, 결정·사유·결정자와 정확한 ZIP 바이트를 데이터베이스에 불변 기록한다.

## 결정 규칙

- `approver` 이상만 승인 또는 차단 결정을 만들 수 있다. viewer는 기록과 패키지를 조회할 수 있다.
- `approved`는 현재 게이트의 `ready`가 참이고 해당 스테이지의 릴리스 후보 리비전이 고정됐으며,
  게이트의 공통 리비전과 고정된 후보가 정확히 일치할 때만 허용한다. 조건을 충족하지 않으면
  409이며 기록을 만들지 않는다.
- 승인자는 `GET /projects/{project_id}/signoff-releases/review?stage=final`로 현재 근거를 검토하고
  응답의 `evidence_snapshot_sha256`을 승인 요청의 `expected_evidence_sha256`으로 제출한다. 승인
  패키지를 다시 만든 결과가 다르면 서버는 409로 거부해 변경된 근거의 의도하지 않은 승인을 막는다.
- `rejected`는 차단 또는 준비된 게이트 모두에 사용할 수 있다. 근거 부족 자체를 감사 기록으로 남길 수 있다.
- 로그인 모드에서는 요청 본문으로 결정자 이름을 받지 않고 세션의 사용자 ID와 이름을 저장한다.
- 결정 생성과 판정에는 Hermes 또는 다른 AI 모델이 개입하지 않는다.
- 새 결정은 동결한 게이트와 선택 런·메트릭·원본 해시·위반·웨이버 상태의 정규화 SHA-256을
  결정 해시에 직접 결합한다. 조회 시 두 스냅샷 해시를 다시 검증하고 현재 근거와 비교한다.

## 현재성 상태

결정 응답의 `lifecycle_status`는 과거 결정을 현재 승인으로 오해하지 않도록 다음 상태를 제공한다.

- `current`: 같은 스테이지의 최신 결정이며 현재 런·웨이버·사인오프 계획이 동결 근거와 같다.
- `evidence_changed`: 최신 결정이지만 현재 게이트 근거가 달라 새 검토와 결정이 필요하다.
- `superseded_by_decision`: 같은 스테이지에 더 최근 결정이 있다.
- `legacy_unbound`: 게이트 스냅샷 해시 도입 전 기록이라 현재성을 암호학적으로 비교할 수 없다.

웨이버 만료만으로도 현재 게이트 판정이 바뀌므로 기존 결정은 `evidence_changed`가 된다. 화면은
결정 자체의 승인/차단과 현재성 상태를 별도 배지로 표시한다. AI는 현재성을 변경하거나 재승인하지 않는다.

## API

`POST /projects/{project_id}/signoff-releases`

```json
{"stage":"final","decision":"approved","reason":"all evidence reviewed","expected_evidence_sha256":"64-character lowercase SHA-256"}
```

서버는 현재 최신 런을 다시 선택하고 `signoff/evidence-package/v1` 패키지를 만든 뒤 다음을
함께 저장한다.

- 스테이지와 승인/차단 결정, 사유, 결정자 계정과 시각
- 공통 설계 리비전과 전체 게이트 스냅샷
- `manifest.json`, ZIP 전체, 결정 메타데이터의 SHA-256 및 바이트 수
- 게이트 및 전체 근거 스냅샷 SHA-256과 현재성 상태
- 다운로드했던 것과 동일한 ZIP 바이트

목록은 `GET /projects/{project_id}/signoff-releases`로 최신순 25개를 조회한다.
`before_id`와 최대 100의 `limit`으로 과거 기록을 이어서 읽는다. 개별 메타데이터는
`GET /projects/{project_id}/signoff-releases/{release_id}`, 보관 ZIP은 끝에 `/package`를
붙여 내려받는다. 조회할 때 결정 메타데이터의 정규화 SHA-256을, 다운로드 때 ZIP SHA-256도
다시 계산하며 불일치하면 409를 반환한다.

기록 수정·삭제 API는 제공하지 않는다. 보관 ZIP은 원본 보고서의 저장 SHA를 생성 시점에
재검증하지만 벤더의 디지털 서명, 실제 툴 실행 진위 또는 설계 입력 동일성을 대신하지 않는다.
