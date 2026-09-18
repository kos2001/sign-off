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
기록으로 유지하고 새 헤드를 다음 체크포인트로 보관한다. 이 기능은 공개키 전자서명을 제공하지 않으며,
체크포인트의 신뢰성은 외부 저장소의 접근 통제와 보존 정책에 의존한다. 원장 생성과 검증에는 AI가
개입하지 않는다.
