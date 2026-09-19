# 휴대용 결정 감사 원장

프로젝트 화면의 **검증 가능한 감사 원장 내보내기** 또는
`GET /projects/{project_id}/signoff-releases/audit/export`로 결정 원장을 받는다. 파일은 결정 사유와
결정자, 근거·패키지 해시, 생성 시각, 이전 결정 연결 및 현재 체인 헤드를 포함한다. 원본 보고서나
ZIP 패키지는 포함하지 않는다.
인증 필수 모드에서 만들어진 결정은 비밀번호 값 없이 `credential_confirmed_at`만 서명 필드로
포함해 결정 시점의 자격 증명 재확인 사실도 오프라인에서 검증한다.

백엔드 디렉터리에서 서버와 데이터베이스를 사용하지 않고 검증할 수 있다.

```bash
.venv/bin/python -m app.release_ledger verify \
  --ledger project-1-decision-ledger.json
```

성공하면 결정 수, 기능 도입 전 비연결 결정 수, 연결된 결정 수와 헤드를 JSON으로 출력한다. 결정
필드 변조, 순서 변경, 중간 삭제, 파일 자체의 헤드와 마지막 결정 불일치, 중복 JSON 키와 지원하지
않는 필드는 실패로 처리하고 종료 코드 1을 반환한다.

## Ed25519 공개키 서명

운영 배포에서는 결정 서명 키를 생성하고 private 파일을 secret manager에서 읽기 전용으로 주입한다.

```bash
umask 077
.venv/bin/python -m app.release_signing generate \
  --private-key /secure/signoff-release-private.key \
  --public-key /secure/signoff-release-public.key
export SIGNOFF_RELEASE_SIGNING_PRIVATE_KEY_FILE=/run/secrets/signoff-release-private.key
export SIGNOFF_RELEASE_SIGNING_REQUIRED=1
```

private 파일은 0600으로 새로 만들며 기존 파일을 덮어쓰지 않는다. 서버는 시작할 때 키 형식과
`SIGNOFF_RELEASE_SIGNING_REQUIRED`의 `0|1` 값을 검사한다. required가 1인데 키가 없거나 읽을 수
없으면 시작하지 않는다. 환경 변수 `SIGNOFF_RELEASE_SIGNING_PRIVATE_KEY`로 43자 base64url 원문을
직접 주입할 수도 있지만 파일 설정과 동시에 사용할 수 없다. 프로세스 환경 노출을 줄이려면 secret
파일을 권장한다.

키가 설정된 뒤 생성한 결정은 `decision_sha256`에 domain-separated Ed25519 서명을 추가한다. 원장은
서명 버전, key ID(SHA-256), 공개키와 서명을 포함하며 서버의 목록·상세·감사 API도 내장 공개키로
서명을 검사한다. 기존 결정은 nullable 미서명 기록으로 그대로 유지한다. 화면은 내장 공개키 서명
검증 여부를 결정마다 표시한다. 키를 교체하면 재시작 이후 새 결정만 새 키로 서명되며, 과거 public
파일도 계속 보관한다.

원장 안의 공개키는 파일과 함께 바꿀 수 있으므로 그 자체로 신뢰 기준이 아니다. public 파일을 서비스와
분리된 경로로 배포하고 강제 검증한다. 키 교체가 있었다면 옵션을 반복한다.

```bash
.venv/bin/python -m app.release_ledger verify \
  --ledger project-1-decision-ledger.json \
  --trusted-public-key /audit/signoff-release-public-2026q3.key \
  --trusted-public-key /audit/signoff-release-public-2026q4.key \
  --require-trusted-signatures
```

서명 도입 전에 결정 42건이 존재했다면 외부 변경 관리 기록에 그 개수를 보존하고
`--allow-unsigned-prefix-count 42`를 함께 사용한다. 그 선행 구간 이후 미서명 또는 신뢰 목록 밖 키로 서명한
결정은 실패한다. 성공 출력의 `signed_decision_count`와 `trusted_signature_count`가 기대한 범위와
일치하는지도 보관한다.

공개키 서명은 DB만 수정한 공격자가 결정 내용이나 이전 체인 연결을 다시 만드는 것을 막는다. private
키를 읽거나 API 프로세스를 제어한 공격, 키 폐기 정책, 마지막 결정과 헤드를 함께 삭제하는 공격을
해결하지 않는다. private 키 접근 감사와 교체는 secret manager에서 운영하고, 마지막 삭제 탐지는
아래 외부 체크포인트를 함께 사용한다.

## 외부 체크포인트

원장 파일만 가진 검증은 파일 안의 체인 일관성을 증명한다. 원장과 헤드를 함께 다시 작성하는 공격을
구분하려면 신뢰한 시점의 `X-Signoff-Decision-Chain-Head` 응답 헤더 또는 원장
`chain_head_sha256`을 서비스와 분리된 변경 불가 저장소에 보관한다. 이후 원장은 이 값과 함께 검증한다.

```bash
.venv/bin/python -m app.release_ledger verify \
  --ledger project-1-decision-ledger.json \
  --expected-head 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

`--expected-head`와 원장 헤드가 다르면 실패한다. 새 결정이 추가된 뒤에는 이전 원장과 헤드를 감사
기록으로 유지하고 새 헤드를 다음 체크포인트로 보관한다. 체크포인트의 신뢰성은 외부 저장소의 접근
통제와 보존 정책에 의존한다. 공개키 서명과 외부 head 검증 모두 원장 생성·검증에 AI를 사용하지 않는다.
