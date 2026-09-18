# 상용 EDA 수집기 요청 생성

`backend/scripts/create_coverage_import.py`는 상용 보고서를 서버와 같은 파서로 먼저 검증하고,
원본 SHA-256과 모든 요청 바인딩을 계산한 뒤 `signoff/coverage-attestation/v1` HMAC을 생성한다.
출력은 해당 가져오기 API에 그대로 제출할 수 있는 JSON 요청이다.

## 준비

수집기 호스트에 저장소의 `backend` 코드와 잠긴 Python 의존성을 설치한다. 서버에 등록한 키의
비밀값은 명령행 인수나 파일에 넣지 않고 환경변수로 주입한다. 명령행은 프로세스 목록과 셸
이력에 남을 수 있기 때문이다.

```sh
cd backend
export SIGNOFF_COLLECTOR_HMAC_SECRET='비밀 관리 시스템이 주입한 32바이트 이상의 값'
```

claim 파일은 해당 도메인의 [정확한 claim 집합](coverage-attestation.md)을 한 번씩 포함하고,
수집기가 실제 실행 로그와 입력 목록을 확인한 항목만 `true`여야 한다. 누락, 추가, `false`, 숫자
또는 문자열 값은 거부된다. 예를 들어 STA 파일은 다음과 같다.

```json
{
  "tool_run_completed": true,
  "modes_corners_complete": true,
  "constraints_validated": true,
  "parasitics_requirement_satisfied": true,
  "findings_complete": true,
  "unconstrained_paths_zero": true
}
```

## 요청 생성과 제출

```sh
PYTHONPATH=. .venv/bin/python scripts/create_coverage_import.py \
  --domain sta \
  --report /collector/out/primetime-paths.json \
  --claims-file /collector/out/sta-claims.json \
  --project-id 42 \
  --stage final \
  --design-revision release-2026.09 \
  --scenario all-signoff-views \
  --tool-version T-2025.06 \
  --key-id sta-collector-2026q3 \
  --output /collector/out/signoff-import.json

curl --fail-with-body \
  -H 'Content-Type: application/json' \
  --data-binary @/collector/out/signoff-import.json \
  https://signoff.example/projects/42/imports/commercial-sta
```

`--domain`은 `sta`, `pv`, `emir`, `glitch_power`, `thermal`, `rtl` 중 하나다. 제출 URL은 각각
`commercial-sta`, `commercial-drc`, `commercial-emir`, `commercial-power`,
`commercial-thermal`, `commercial-rtl`이다. 기본 유효 시간은 1시간이며
`--valid-for-seconds`로 1초부터 7일까지 지정할 수 있다.

CLI는 UTF-8 원본 바이트, 툴과 버전, claim 집합을 검증한 후 요청을 생성한다. `--output` 파일은
같은 디렉터리에서 완성한 뒤 권한 `0600`으로 원자 게시하며 기존 파일을 덮어쓰지 않는다.
출력에는 서명과 원본 보고서가 포함되지만 비밀키는 포함되지 않는다. `--output`을 생략하면
표준 출력으로 보낸다. 같은 네트워크 요청을 안전하게 재시도하려면 생성된 파일을 그대로 다시
제출한다. 새로 생성하면 새 `import_id`가 생긴다.

이 도구는 claim의 철자와 서명을 검증하지만 실제 상용 툴을 실행하거나 라이선스·호스트 무결성을
증명하지 않는다. 수집기 자동화는 툴 종료 코드, 입력 manifest, 모드/코너 목록과 커버리지 보고서를
확인한 뒤 claim 파일을 만들어야 한다.
