# SQLite 백업과 복구

백엔드 디렉터리에서 실행합니다. 실행 중인 서비스의 SQLite DB를 온라인 스냅샷으로
백업하며 WAL의 커밋된 데이터도 포함합니다. 프로젝트, 실행, 위반, 웨이버,
검토 이력, 변경 버전, RTL 원본 및 실행 근거를 함께 보존합니다.

## 백업

```sh
cd backend
mkdir -p /secure/backups
.venv/bin/python -m app.backup create \
  --database /absolute/path/signoff.db \
  --output /secure/backups/signoff-20260915.zip
.venv/bin/python -m app.backup verify \
  --backup /secure/backups/signoff-20260915.zip
```

실제 운영 DB 경로는 서비스의 `SIGNOFF_DATABASE_URL`에서 확인합니다.
출력 디렉터리는 미리 만들어야 하며 파일명은 매번 새 이름을 사용합니다.
`--timeout 120`은 스냅샷 복사 단계의 제한 시간(초)이며 전체 검증 시간 제한은 아닙니다.
성공 시 JSON과 종료 코드 0, 실패 시 표준 오류와 종료 코드 1을 반환합니다.
백업 실패 시 완성되지 않은 아카이브를 출력 경로에 게시하지 않습니다.

아카이브는 압축하지 않은 ZIP이며 `database.sqlite`, `manifest.json` 두 파일로 구성됩니다.
검증은 SHA-256, 크기, SQLite 무결성, 외래 키와 고아 레코드, 필수 스키마,
전체 사용자 테이블의 행 수를 확인합니다. 해시는 손상 검사이며 서명이나 암호화가 아닙니다.
복원 전에 메타데이터가 UTF-8 JSON인지 검사하며, 중복 필드(테이블별 행 수 내부 포함),
비유한 수, 잘못된 해시·시각·크기를 거절합니다. 행 수는 0 이상의 정수만 허용하므로
`true`나 `1.0`을 정수 `1`로 대신할 수 없습니다. 생성 시각에는 시간대가 있어야 합니다.
메타데이터 검증 실패 시 DB 내용을 추출하거나 복원 대상 파일을 게시하지 않습니다.
백업에는 RTL 소스와 검토 정보가 포함되므로 접근을 제한하고 암호화된 별도 저장소에 보관합니다.
생성 파일 권한은 0600입니다. 실행 파일, 환경 설정, 외부 툴 및 외부 파일은 포함하지 않습니다.

## 새 경로로 복원하고 전환

```sh
.venv/bin/python -m app.backup restore \
  --backup /secure/backups/signoff-20260915.zip \
  --database /absolute/path/recovered-signoff.db
```

1. 별도 경로에서 먼저 복원 연습을 수행합니다. 대상 파일과 `-wal`, `-shm`, `-journal`
   보조 파일이 없어야 하며 다른 프로세스가 대상 경로를 사용해서는 안 됩니다.
2. 전환할 때 모든 서비스 쓰기 프로세스를 중지합니다. 현재 DB도 별도 백업합니다.
3. 새 경로로 복원하고 JSON의 테이블별 행 수를 백업 기록과 비교합니다.
4. 계정 인증을 사용하는 DB라면 새 DB를 가리키는 환경에서 `python -m app.accounts revoke-sessions`를
   먼저 실행하여 백업에 남은 과거 세션을 폐기합니다.
5. `SIGNOFF_DATABASE_URL=sqlite:////absolute/path/recovered-signoff.db`로 설정하고
   해당 스키마와 호환되는 백엔드를 시작합니다. 복원 명령은 마이그레이션을 실행하지 않으며
   앱 시작 시 기존 초기화 절차가 적용됩니다.
6. 프로젝트, 최근 실행, 위반 상태/버전, 검토 이력, RTL 원본 근거와 게이트를 확인합니다.
   확인 후 트래픽을 연결합니다.
7. 전환 실패 시 새 서비스를 중지하고 기존 DB 경로로 설정을 되돌립니다.
   복원 후 발생한 새 쓰기는 기존 DB로 자동 병합되지 않습니다.

자동 덮어쓰기와 `--force` 옵션은 없습니다. 오래된 백업으로 복구하면 스냅샷 이후의
변경은 포함되지 않습니다. 백업 주기·보존 기간·복구 시간 목표는 운영자가 정하고,
별도 저장소 복제와 정기 복원 훈련을 운영 작업에 추가해야 합니다.

이 명령은 SQLite 전용입니다. PostgreSQL은 해당 DB의 백업·복구 도구와 별도 검증이 필요합니다.
