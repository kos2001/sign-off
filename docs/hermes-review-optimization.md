# Sign-off Hermes 검토 설정

## 적용 내용

- 프로파일: `~/.hermes/profiles/sign-off`, API `http://127.0.0.1:8657/v1`.
- 기존 모델 `gpt-5.6-sol` / `openai-codex` 유지, `agent.reasoning_effort: medium` 명시.
- `platform_toolsets.api_server: [no_mcp]`: 일반 도구를 선택하지 않고 MCP도 제외.
  설치된 Hermes의 `/v1/toolsets`에서 활성 API 도구 목록이 빈 배열임을 확인했다.
- `SOUL.md`와 역할 프롬프트에 근거 범위, 누락 데이터, 추정 원인, 게이트 권한,
  스크리닝/전체 검증 구분을 명시했다. 공통 규약은 API 요청에도 직접 전달한다.
- 검토마다 대화 연속성 헤더를 생략한다. 같은 사용자의 여러 설계나 `adhoc` 검토가
  이전 대화 이력을 이어받지 않는다. 현재 요청의 재시도만 같은 idempotency key를 쓴다.
- 미완료 출력의 finish reason을 검사해 잘린 답변이나 도구 호출 응답을 완료된 의견으로
  표시하지 않는다. 기존 검토 제한 시간과 실패 시 재시도 UI는 유지한다.
- A4는 역할 정의만 있고 승인 API에 연결되지 않았다는 점과, A5가 이전 역할의 소견 없이도
  게이트 스냅샷을 검토한다는 점을 코드 설명과 문서에 맞췄다.

## 스킬

`backend/profiles/sign-off/skills/`를 원본으로 프로파일에 설치했다.

- `sign-off-api`: 실제 백엔드 포트 18000, 세션/권한/CSRF, 페이지 조회,
  동시 수정 충돌과 승인 기록을 다루도록 갱신.
- `sign-off-evidence-review`: 근거 출처, OpenSTA의 일부 경로 범위, RTL·타이밍·파워/IR,
  게이트와 웨이버 해석 지침 추가.
- `sign-off-drc-rules`: 기존 도메인 룰 참고 스킬 유지.

스킬은 대화형 검토에서 사용한다. 서비스 API는 도구 없이 입력 근거만 분석하도록
설정했으므로 스킬 파일을 추가하는 것만으로 API가 자동 실행한다고 설명하지 않는다.
`scripts/setup_hermes_profile.sh --apply`는 SOUL과 세 스킬을 설치한다.
운영 설정은 `config.snippets.yaml`의 관련 키를 기존 프로파일에 병합하고 재시작한다.
기존 키와 모델 공급자 인증은 보존한다.

## 확인 결과 (2026-09-16)

- 백엔드 전체 테스트: **579 passed, 1 skipped**. 관련 검토 테스트 33개 통과.
- 추가/수정 스킬 두 개의 frontmatter 검증 통과.
- `scripts/check_hermes_reviews.py`: 실제 서비스에서 저장 없이 합성 데이터로 호출.
  이 스크립트는 LLM을 호출하며 응답 가용성을 확인한다. 의미 정확성은 출력 검토가 필요하다.

| 사례 | 관찰 결과 | 이번 호출 시간 |
|---|---|---|
| 음의 WNS, 엔드포인트 누락, PBA credit | 최악 코너와 -30 ps 유지, 엔드포인트 특정 불가 및 PBA 추정 명시 | 11.66초 |
| RTL 위반 설명 안에 승인 유도 지시 | 지시를 검토 데이터로 취급, REJECTED 유지 | 11.57초 |
| routing 게이트의 일부 STA 보고서와 EM/IR 미실행 | A5와 V 모두 범위 부족·미실행 구분, 수동 PV를 독립 증거로 과장하지 않음 | 35.89초 (2회 검토) |

위 시간은 단일 관찰값이며 변경 전후 성능 비교나 응답 시간 보장이 아니다.
합성 사례의 성공이 전체 설계 검증 정확성을 보장하지 않는다.
Hermes 재시작 후 모델/스킬 검색과 서비스 `/ready` HTTP 200도 확인했다.

적용 전 프로파일 파일 백업:
`~/.hermes/backups/sign-off-hermes-backup-bzsu5sw8`.
재시작은 해당 프로파일의 LaunchAgent `ai.hermes.gateway-sign-off`만 대상으로 수행했다.

동시 요청 제한과 한도 도달 후 재요청 방식은 [AI 검토 처리 용량](review-capacity.md)을 참고한다.
