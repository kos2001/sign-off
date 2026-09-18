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
관리형 DB 기능 또는 `pg_basebackup`, `pg_dump` 등 PostgreSQL 도구로 구성하고 실제 복구 훈련을
별도로 수행한다. 현재 앱 시작 마이그레이션은 additive 변경만 지원하며, 열 삭제·대규모 데이터
변환·롤백 마이그레이션 프레임워크를 제공하지 않는다.
