# KLayout DRC 보고서 가져오기

프로젝트 → 보고서 가져오기 → **KLayout DRC 보고서 가져오기**에서 `.lyrdb` XML을
미리 보고 PV 런으로 저장한다. KLayout의 [공식 RDB 형식](https://www.klayout.de/staging/rdb_format.html)을
기준으로 마커의 셀 참조·분류 경로·값 문자열·multiplicity·태그·방문 표시·댓글을 읽는다.
기하 값은 보고된 셀 문맥의 마이크로미터 좌표 문자열로 보존한다. 계층 변환이나 레이아웃
오버레이를 계산하지 않으며 분류 경로와 셀 참조도 원문 그대로 보존한다.

## API와 저장

- `POST /projects/{project_id}/imports/klayout/preview`: 저장 전 해석 결과.
- `POST /projects/{project_id}/imports/klayout`: `domain=pv`, `tool=KLayout DRC` 런 저장.
- 기존 OpenSTA와 같은 본문 필드: UUID `import_id`, `stage`, `filename`, `tool_version`,
  `design_revision`, `scenario`, `source_text`. scenario에는 룰덱/실행 조건 식별자를 입력한다.
- editor 이상과 CSRF(required 모드)를 요구한다. 같은 import_id/내용은 같은 런을 반환하고
  다른 내용이나 다른 보고서 형식에 같은 키를 재사용하면 충돌로 거절한다.
- 원본 UTF-8 텍스트·SHA-256·파서 버전·메타데이터·제출자를 RunEvidence에 보존한다.
  기존 SQLite 백업/복원 대상 테이블을 사용하며 새 DB 테이블은 필요 없다.

소스 타입은 `klayout_report`이며 저장된 결과·메트릭은 기존 실행 근거와 같이 읽기 전용이다.
원본은 `GET /runs/{id}/evidence/source`에서 해시 검증 후 `.lyrdb`로 받을 수 있다.
근거 JSON과 게이트 내보내기에도 보관 결과가 포함된다. DRC 가져오기에는 AI를 호출하지 않는다.
이 보고서에 대한 자동/저장 AI 검토 역할은 아직 연결하지 않았다.

## 해석 정책

보고서 형식에 표준 심각도 필드가 없으므로 **제출된 DRC 마커를 보수적으로 error 위반으로
등록한다**. 이 정책을 미리보기에서 표시한다. 각 마커는 한 위반이며 multiplicity는 별도
발생 수로 보존한다. 동일 마커가 반복되면 삭제하거나 하나로 합치지 않는다.
분류·셀·값으로 만든 지문은 중복을 포함하는 기존 런 비교에 사용한다.

visited 및 waived 태그는 서비스의 fixed/waived 상태나 승인으로 자동 변환하지 않는다.
처음에는 open이며, 변경은 기존 권한·웨이버·이력 절차를 따른다.
마커가 있으면 failed, 없으면 incomplete다. 마커 파일만으로 룰덱 실행 완전성·전체 레이어
검사·툴 실행 진위가 증명되지는 않는다. 웨이버 후에도 전체 DRC 게이트를 열지 않는다.
비교 화면에서도 제한된 근거의 잠정 비교로 표시한다.

## 입력 한도

2,000,000 UTF-8 바이트, 마커 1,000개, 마커당 값 100개(각 20,000자),
XML 깊이 32 및 요소 50,000개로 제한한다. multiplicity는 0–1,000,000,000 정수다.
DTD/엔티티 선언은 거절하며 외부 XML 자원을 읽지 않는다. 잘못된 구조·중복 필드·지원 범위
초과는 422이며 기록하지 않는다. 이미지·셀 계층·분류 정의 등은 원본에 보존하고 실행하지 않는다.

## 실제 툴 검증

`scripts/generate_klayout_fixture.py`는 KLayout Python 0.30.12로 0.1 × 0.1 µm 도형에
0.15 µm 최소 폭 검사를 실행한다. 생성된 2개 edge-pair 마커가
`backend/tests/fixtures/klayout-width.lyrdb`에 보존되어 있다. 이는 합성된 테스트 도형이며
파운드리 룰덱 검증 결과는 아니다. 테스트 도구는 별도 임시 경로에 설치했고 서비스 의존성은 변경하지 않았다.

전체 백엔드 668개 통과(1개 건너뜀), 프런트엔드 빌드 통과.
`scripts/browser_klayout_import_check.mjs`로 임시 인증 DB에서 미리보기·저장·잘못된 XML 거절,
결과 잠금·게이트 범위 표시·원본 바이트 일치·320/390/1440px 배치를 확인했다.
원본 BOM/CRLF 보존, 태그와 승인 분리, 중복 마커, 권한·동일 요청 및 크기/구조 제한도 검사한다.

저장 후 [DRC 마커 탐색](marker-exploration.md)에서 규칙·셀 검색과 셀 좌표 기하 미리보기를 사용할 수 있다.
