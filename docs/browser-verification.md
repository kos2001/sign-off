# 브라우저 통합 검증

`scripts/browser_review_check.mjs`는 실제 API에 합성 프로젝트를 생성합니다.
아래처럼 임시 DB를 사용하는 별도 백엔드로 실행하세요. 기존 운영 DB를 지정하지 마세요.
기존 사용자 데이터는 수정하지 않으며 테스트 프로젝트는 임시 DB에 남습니다.

## 서버

프로젝트 루트에서 터미널 두 개를 사용합니다.

```bash
# 터미널 1: 임시 DB 백엔드
SIGNOFF_QA_DIR=$(mktemp -d)
cd backend
SIGNOFF_DATABASE_URL="sqlite:///$SIGNOFF_QA_DIR/test.db" \
  .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 18000
```

```bash
# 터미널 2: 검증용 프런트엔드
cd frontend
BACKEND_PORT=18000 npm run dev -- --host 127.0.0.1 --port 15173 --strictPort
```

## 브라우저 검사

검증 스크립트는 Playwright 모듈을 사용합니다. 앱의 의존성과 분리해서 설치할 수 있습니다.

```bash
# 프로젝트 루트의 세 번째 터미널
npm install --prefix /tmp/signoff-browser-tools playwright@1.63.0
node /tmp/signoff-browser-tools/node_modules/playwright/cli.js install chromium
SIGNOFF_TEST_OUTPUT=/tmp/signoff-review-check \
  node scripts/browser_review_check.mjs /tmp/signoff-browser-tools/node_modules/playwright/index.mjs
```

브라우저 실행이 제한된 환경에서는 테스트용 Chromium 실행 권한이 필요합니다.
종료 시 `result: PASS`와 검증 항목 목록을 출력하고, 출력 디렉터리에
`desktop.png`, `mobile.png`, `comparison-desktop.png`, `comparison-mobile.png`, `evidence-desktop.png`, `evidence-mobile.png`,
`run-evidence.json`, `review-conflict.png`를 저장합니다. 두 서버는 Ctrl+C로 종료하세요.

검증 항목: 최신/과거 런 범위, 검색·필터·페이지 이동, URL 복원과 뒤로 가기,
선택 항목 복원, 취소 시 무변경, 웨이버 승인·재오픈·수정 완료·이력 보존,
모바일 폼과 메뉴, 가로 잘림, API 오류 복구, 브라우저 런타임 오류.
런 비교에서는 지표 차이, 차이 필터·페이지 이동, 기준 교환, URL 복원, 새 런 추가 후
대상 고정, 잠정 결과 갱신, 잘못된 실행 조합과 API 실패 복구, 모바일 배치도 확인합니다.

기본 테스트 주소는 `127.0.0.1:15173`(UI), `127.0.0.1:18000`(API)이며
`SIGNOFF_TEST_UI`, `SIGNOFF_TEST_API`로 변경할 수 있습니다. 스크립트는 호스트가
127.0.0.1이 아니면 실행을 거부합니다. 개발 서버에서 코드가 갱신되지 않으면
서버를 재시작한 뒤 다시 실행하세요.

RTL 검증에서는 실제 클린 예제를 스트리밍 실행해 incomplete 상태와 게이트 차단,
결과 수정 잠금, 리비전·원본 코드·단계별 근거 표시를 확인합니다. 내려받은 JSON의 소스와
SHA-256을 대조하고, 최종 판정 없이 끊긴 스트림의 오류 표시와 실행 중 표시 종료도 검사합니다.
Verilator/Yosys가 없어도 단계가 skip으로 기록되어 incomplete가 되어야 합니다.

동시 검토 검증은 브라우저 페이지 두 개에서 같은 위반을 열어 실행합니다. 한 검토자가
수정 완료 후 재오픈한 뒤 다른 검토자의 이전 버전 저장이 409인지, 사유가 남아 있는지,
이력을 확인한 뒤에만 새 버전으로 처리하는지 확인합니다. 상태 필터로 위반 행이 사라진
뒤에도 동일 탭에서 작성한 내용이 복원되는지 검사합니다.


## RTL 테스트벤치 브라우저 검증

위의 격리된 테스트 DB를 사용하는 백엔드 시작 명령에
`SIGNOFF_SIMULATION_MODE=trusted_local`을 추가합니다. Icarus (`iverilog`, `vvp`),
verilator와 yosys가 필요하며 신뢰된 로컬 테스트 소스만 사용합니다.

```sh
node scripts/browser_simulation_check.mjs /absolute/path/to/node_modules/playwright/index.mjs
```

이 스크립트는 별도 QA 프로젝트를 만들고 예제 테스트벤치의 성공·실패 실행,
게이트 차단, 과거 성공 결과 보존, 로그 표시, JSON 다운로드·SHA-256과 모바일 레이아웃을
확인합니다. 기본 산출물 경로는 `/private/tmp/signoff-simulation-check`입니다.
기존 `browser_review_check.mjs`는 테스트벤치 없는 실행이 계속 incomplete인지 검증합니다.
