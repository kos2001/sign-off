# 버전형 STA 시나리오 계획

상용 MMMC 타이밍 사인오프에서는 어떤 mode/corner가 필수인지 결과 수집 전에 고정해야 한다.
프로젝트의 **STA 시나리오 매트릭스**에서 단계별 시나리오 이름과 SPEF 요구를 관리한다.

- `approver` 이상만 변경할 수 있으며 변경 사유가 필수다.
- 각 저장은 `expected_version`을 검사하고 append-only 새 버전으로 남는다. 동시 변경은 409다.
- 현재 계획은 `GET /projects/{id}/sta-scenario-plan/{stage}`, 이력은 끝에 `/history`를 붙여 조회한다.
- 기존 정의는 버전 0 `legacy`로 읽고, 첫 저장부터 버전 1의 감사 기록을 만든다.

신뢰된 상용 STA 수집기는 서명된 coverage attestation의 `scenario_plan_version`에 현재 계획 버전을
넣어야 한다. 서버는 가져오기 시 현재 버전과 일치하는지 검사한다. 계획이 나중에 바뀌면 이전 STA
런은 보존되지만 게이트에서 `Trusted STA evidence targets an outdated scenario plan`으로 차단된다.
새 계획 범위를 실행하고 새 증명을 제출해야 다시 준비 완료가 된다.

수집기 CLI에는 STA 요청일 때 `--scenario-plan-version <version>`을 사용한다. 버전 0 기존 계획은
필드를 생략할 수 있다. 계획 버전과 `modes_corners_complete=true` 서명은 수집기 선언을 서버 계획에
결합하지만, 실제 벤더 툴 실행 진위를 독립적으로 증명하지는 않는다. 계획 변경·게이트 비교에는 AI가
개입하지 않는다.
