# PostgreSQL 운영

운영 PostgreSQL은 psycopg 3 드라이버를 사용한다. 백엔드를 시작하기 전에 연결 문자열을 설정한다.

```bash
export SIGNOFF_DATABASE_URL='postgresql+psycopg://signoff:password@db.example/signoff'
```

서비스 시작 시 `initialize_schema`가 PostgreSQL advisory transaction lock을 획득해 여러 API 워커의
동시 초기화를 직렬화한다. 기존 native `domain`·`runstatus` enum을 현재 값으로 확장하고 커밋한 뒤,
누락된 테이블·인덱스·컬럼을 additive 방식으로 추가한다. 기존 행은 다시 쓰지 않는다. 새 설치와
축소된 레거시 enum 및 프로젝트 테이블의 동시·반복 업그레이드는 PostgreSQL 17 CI에서 검증한다.

검증 스크립트는 전용 DB 안에 임시 스키마를 만들고 종료 시 삭제하므로 다른 스키마를 변경하지 않는다.

```bash
SIGNOFF_POSTGRES_TEST_URL='postgresql+psycopg://signoff:password@localhost/signoff' \
  PYTHONPATH=. .venv/bin/python scripts/check_postgres_migrations.py
```

스크립트는 테스트 자격증명이 있는 검증 DB에서만 실행한다. 임시 스키마 생성·삭제 권한이 필요하다.
CI는 PostgreSQL 이미지도 digest로 고정한다.

SQLite용 `app.backup` 명령은 PostgreSQL에 사용할 수 없다. 운영 백업·시점 복구·복제·장애 조치는
관리형 DB 기능 또는 PostgreSQL 도구로 구성한다. 현재 앱 시작 마이그레이션은 additive 변경만
지원하며, 열 삭제·대규모 데이터 변환·롤백 마이그레이션 프레임워크를 제공하지 않는다.

## 백업과 복구 훈련

`pg_dump` 클라이언트는 서버와 같은 major 버전 또는 더 새로운 버전을 사용한다. 비밀번호를 명령행
인수에 넣지 말고 `.pgpass`, `PGPASSFILE` 또는 secret manager가 주입한 `PGPASSWORD`를 사용한다.
custom archive는 PostgreSQL 자체 암호화 형식이 아니므로 접근 제한, 별도 저장소 암호화, 보존 정책과
SHA-256 체크섬을 함께 운영한다.

```bash
umask 077
archive="signoff-$(date -u +%Y%m%dT%H%M%SZ).dump"
pg_dump --dbname=signoff --format=custom --compress=6 \
  --no-owner --no-privileges --file="$archive"
pg_restore --list "$archive" >/dev/null
sha256sum "$archive" >"$archive.sha256"
```

복원 훈련은 운영 DB를 덮어쓰지 않고 별도 격리 DB에서 수행한다. 복원 중 애플리케이션을 연결하지
않고, 완료 후 같은 버전의 API로 `/ready`, 프로젝트·최근 런·위반/웨이버·감사 결정과 원본 근거
다운로드를 확인한다. 시점 복구를 사용한다면 목표 시각 직전과 직후의 알려진 트랜잭션도 확인한다.
검증을 마친 격리 DB는 민감한 설계 데이터를 포함하므로 즉시 제거한다.

CI의 `scripts/check_postgres_backup.py`는 전용 검증 DB 안에 무작위 스키마를 만들고 대표 사인오프
근거를 저장한 다음 실제 `pg_dump`로 내보낸다. 원본 스키마를 삭제하고 `pg_restore`한 뒤 다음을
검증하고 스키마를 제거한다.

- 모든 앱 테이블·열과 테이블별 행 수
- 중첩 JSON 지표, enum, Unicode 원문과 바이너리 승인 패키지의 정확한 값
- 복원된 primary-key sequence의 다음 쓰기와 외래키 강제
- archive 비어 있지 않음과 restore 단일 트랜잭션

```bash
SIGNOFF_POSTGRES_TEST_URL='postgresql+psycopg://signoff:password@localhost/signoff' \
  PYTHONPATH=. .venv/bin/python scripts/check_postgres_backup.py
```

이 검증은 synthetic 스키마의 논리 백업 복구를 증명한다. 운영 데이터 전체의 백업 성공, WAL 기반
시점 복구, 저장소 복제, 키 관리, RPO/RTO 또는 장애 조치를 대신하지 않는다. 운영 복구 훈련은 실제
백업 산출물과 격리된 동일 규모 환경에서 정기적으로 수행한다.
