# 백엔드 의존성 재현

Python 3.11을 기준으로 `backend/requirements.in`에 직접 의존성을 선언하고,
`backend/requirements.txt`에 전이 의존성까지 정확한 버전과 배포 파일 SHA-256을 고정합니다.
현재 검증된 환경의 버전을 유지하면서 운영체제별 조건부 패키지도 포함했습니다.
일반 설치에서는 `.in`을 직접 설치하지 않습니다.

```sh
cd backend
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python --require-hashes -r requirements.txt
uv pip check --python .venv/bin/python
.venv/bin/python scripts/check_dependencies.py
.venv/bin/python -m pytest -q
```

pip을 사용하는 별도 가상환경에서는 `python -m pip install --require-hashes -r requirements.txt`와
`python -m pip check`를 사용합니다. CI와 RTL Dockerfile도 해시 검증 설치 및 호환성 확인을 수행합니다.
패키지 버전이 같아도 파일 해시가 다르면 설치를 거절합니다. 기존 환경의 불필요한 패키지를 제거하는
명령은 아니므로 재현 확인은 새 가상환경에서 수행하세요.

`check_dependencies.py`는 현재 플랫폼의 직접 선언이 잠금 버전을 허용하는지, 활성 잠금 패키지가
모두 같은 버전으로 설치되어 있는지 확인합니다. 직접 패키지 누락, 불충분한 잠금 버전,
설치 누락/버전 변경, 해시 누락 및 정확하지 않은 버전 고정은 실패합니다. CI와 두 Docker 빌드에서도 실행합니다.
일반 패키지명·버전 조건·환경 마커를 지원하며 URL, extras, 다른 파일 포함 등 지원하지 않는
선언 문법은 명시적으로 거절합니다. 이런 형식이 필요하면 검사기를 함께 확장해야 합니다.
의존성 전체 해결은 설치 도구와 `pip check`가 담당하며 이 검사는 잠금 파일의 최신 버전 여부나
현재 플랫폼에서 비활성인 패키지의 실제 설치를 검증하지 않습니다.

`anyio`는 TLS 호스트명 검증과 프로세스 실행 관련 보안 수정이 포함된 4.14.2 이상을 요구합니다.
현재 Starlette 1.3.1이 4.15에서 deprecated 된 별칭을 사용하므로 경고 없는 검증 조합인 4.14.x로
상한을 두며, Starlette가 새 API로 전환되면 두 패키지를 함께 갱신합니다.

`cryptography`의 Ed25519 구현은 사람의 사인오프 결정 공개키 서명과 오프라인 원장 검증에 사용합니다.
private 키 원문은 DB·원장·로그에 저장하지 않으며 dependency 잠금에는 cffi/pycparser를 포함합니다.

## 의도적인 갱신

직접 의존성을 바꿀 때 `.in`을 편집하고 잠금 파일을 함께 갱신합니다. 아래 명령은
새 버전을 선택하므로 별도 작업 변경으로 검토하고 새 환경/컨테이너에서 검증합니다.

```sh
cd backend
uv pip compile requirements.in --universal --python-version 3.11 \
  --generate-hashes --no-annotate --no-header --upgrade --output-file requirements.txt
```

특정 버전 유지가 필요하면 임시 제약 파일을 `--constraints`로 지정할 수 있습니다.
해시를 오류 회피 목적으로 직접 고치지 말고 변경된 버전과 배포 파일을 검토하세요.
`.in`과 잠금 파일은 자기 개선 루프의 변경 보호 대상입니다.

## 검증 범위

macOS ARM64의 새 Python 3.11 환경에서 설치/호환성 및 전체 백엔드 검사를 수행합니다.
Linux ARM64 컨테이너에서도 같은 잠금 파일로 pip 해시 검증 설치와 실제 RTL 툴 검사를 수행합니다.
잘못된 해시를 가진 임시 요구사항은 빈 환경에서 설치가 거절되는지도 확인합니다.
CI는 고정 digest PostgreSQL 17 컨테이너와 psycopg 3 드라이버를 사용해 격리된 스키마에서 신규 설치,
레거시 enum·프로젝트 업그레이드, 동시·반복 초기화와 새 enum 값 저장을 실행합니다.

이 파일은 Python 패키지를 고정합니다. 운영체제의 apt 저장소·EDA 패키지 버전, 설치 도구 자체,
다른 CPU/운영체제의 실제 실행 검증까지 고정하거나 증명하지 않습니다. Docker 기본 이미지 digest는
Dockerfile에서 별도로 고정하며, 원격 CI 실행 결과는 별도로 확인해야 합니다.
