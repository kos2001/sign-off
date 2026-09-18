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

인증이 필요한 서버에는 프로젝트 전용 API 자격증명을 운영자가 발급한다. 토큰은 생성 응답에서
한 번만 표시되며 DB에는 SHA-256만 저장된다.

```sh
cd backend
PYTHONPATH=. .venv/bin/python -m app.collectors create 42 primetime-prod --valid-days 90
export SIGNOFF_COLLECTOR_API_TOKEN='위 명령이 한 번 표시한 soct_ 토큰'

# 비밀값 없이 상태 확인 및 즉시 폐기
PYTHONPATH=. .venv/bin/python -m app.collectors list 42
PYTHONPATH=. .venv/bin/python -m app.collectors revoke 42 primetime-prod
```

API 토큰은 전송자를 인증하고 HMAC 키는 보고서와 전체 실행 범위 claim을 결합한다. 서로 다른
비밀값을 사용한다. API 토큰은 지정 프로젝트의 열한 `commercial-*` 저장 POST와 읽기 전용 수집기
컨텍스트 조회에만 사용할 수 있고 일반 조회, 미리보기, 위반 처리, 게이트 승인에는 사용할 수 없다. 만료·폐기 또는 다른 프로젝트의
토큰은 일반적인 401로 거부된다. 머신 제출은 coverage attestation이 없는 요청도 거부하므로
서비스 자격증명만으로 서명 없는 최신 런을 만들어 게이트를 방해할 수 없다.

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

실행 전에 현재 단계의 계약을 조회한다. 응답은 게이트가 요구하는 도메인과 각 도메인의 정확한 claim,
제출 경로, 사인오프 계획 버전, STA 시나리오 계획 버전·mode/corner·SPEF 요구를 제공한다. 수집기는
응답에 없는 도메인을 게이트 필수 항목으로 추측하지 않고, STA 요청에는 반환된
`sta_scenario_plan.version`을 사용한다.

```sh
curl --fail-with-body \
  -H "Authorization: Bearer $SIGNOFF_COLLECTOR_API_TOKEN" \
  https://signoff.example/projects/42/collector-context/final \
  > /collector/out/signoff-context.json
```

이 조회는 프로젝트 범위의 현재 설정만 반환하고 런·위반·결정 데이터는 노출하지 않는다. 계획이 조회
후 변경되는 경합은 저장 API가 계획 버전 불일치로 다시 차단하므로 컨텍스트를 새로 읽고 재실행한다.

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
  -H "Authorization: Bearer $SIGNOFF_COLLECTOR_API_TOKEN" \
  -H 'Content-Type: application/json' \
  --data-binary @/collector/out/signoff-import.json \
  https://signoff.example/projects/42/imports/commercial-sta
```

`--domain`은 `sta`, `cdc`, `pv`, `lvs`, `lec`, `dft`, `low_power`, `emir`, `glitch_power`, `thermal`, `rtl` 중 하나다. 제출 URL은 각각
`commercial-sta`, `commercial-cdc`, `commercial-drc`, `commercial-lvs`, `commercial-lec`, `commercial-dft`, `commercial-low-power`, `commercial-emir`, `commercial-power`,
`commercial-thermal`, `commercial-rtl`이다. 기본 유효 시간은 1시간이며
`--valid-for-seconds`로 1초부터 7일까지 지정할 수 있다.
STA 도메인에서는 `--scenario-plan-version`에 컨텍스트가 반환한 현재 계획 버전을 지정한다.
서버는 이 값을 HMAC 서명과 함께 검증하며 현재 계획과 다르면 저장을 거부한다.

CLI는 UTF-8 원본 바이트, 툴과 버전, claim 집합을 검증한 후 요청을 생성한다. `--output` 파일은
같은 디렉터리에서 완성한 뒤 권한 `0600`으로 원자 게시하며 기존 파일을 덮어쓰지 않는다.
출력에는 서명과 원본 보고서가 포함되지만 비밀키는 포함되지 않는다. `--output`을 생략하면
표준 출력으로 보낸다. 같은 네트워크 요청을 안전하게 재시도하려면 생성된 파일을 그대로 다시
제출한다. 새로 생성하면 새 `import_id`가 생긴다.

이 도구는 claim의 철자와 서명을 검증하지만 실제 상용 툴을 실행하거나 라이선스·호스트 무결성을
증명하지 않는다. 수집기 자동화는 툴 종료 코드, 입력 manifest, 모드/코너 목록과 커버리지 보고서를
확인한 뒤 claim 파일을 만들어야 한다.

운영 전송은 HTTPS를 사용하고 HMAC 키와 API 토큰을 서로 분리된 비밀 항목으로 관리한다. 저장된
실행 근거에는 사용자 대신 `collector_id`와 이름이 기록되며 API 토큰과 HMAC 비밀값은 기록되지
않는다. 키 교체 시 새 이름으로 자격증명을 발급하고 수집기를 전환한 뒤 이전 이름을 폐기한다.
