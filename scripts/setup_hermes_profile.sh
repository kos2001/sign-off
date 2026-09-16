#!/usr/bin/env bash
# hermes 'sign-off' 프로파일 셋업 (api_server :8657)
#
# weekly-report-harness/scripts/setup_hermes_profile.sh 를 참조해 만들었다.
# 기본은 dry-run: 수행할 작업만 출력한다. 실제 적용은 --apply.
# 기존 ~/.hermes 설정을 건드리므로 적용 전 출력을 확인할 것.
set -euo pipefail

PROFILE=sign-off
PORT=8657
HERMES_PROFILE_DIR="$HOME/.hermes/profiles/$PROFILE"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SOUL_SRC="$REPO_DIR/backend/profiles/$PROFILE/SOUL.md"
APPLY=false
[ "${1:-}" = "--apply" ] && APPLY=true

say() { echo "[setup] $*"; }
run() { if $APPLY; then "$@"; else say "(dry-run) $*"; fi; }

if ! command -v hermes >/dev/null 2>&1; then
  say "ERROR: hermes CLI 를 찾을 수 없음. hermes-agent 설치 후 재실행." >&2
  exit 1
fi

# 1) 프로파일 생성
if [ -d "$HERMES_PROFILE_DIR" ]; then
  say "프로파일 존재: $HERMES_PROFILE_DIR (생성 생략)"
else
  run hermes profile create "$PROFILE"
fi

# 2) SOUL.md + 스킬 복사
#    sign-off-api        : 사인오프 REST API 사용법 (프로젝트/런/위반/게이트/스크리닝 분석)
#    sign-off-drc-rules  : DRC-XXX 룰 카탈로그 + shift-left 스테이지 게이트 매트릭스
#    스킬은 대화 모드에서만 로드된다 (api_server 경로는 도구·스킬을 실행하지 않는다).
#    SOUL.md 가 파이프라인(A1~A5, V 역할) 쪽 규율을 담는다.
run cp "$SOUL_SRC" "$HERMES_PROFILE_DIR/SOUL.md"
run mkdir -p "$HERMES_PROFILE_DIR/skills"
for skill in sign-off-api sign-off-drc-rules sign-off-evidence-review; do
  run cp -R "$REPO_DIR/backend/profiles/$PROFILE/skills/$skill" "$HERMES_PROFILE_DIR/skills/"
done

# 3) API 서버 키 생성 + 프로파일 .env 설정 (env 가 config.yaml 보다 우선)
KEY_LINE_FILE="$HERMES_PROFILE_DIR/.env"
if $APPLY; then
  if [ -f "$KEY_LINE_FILE" ] && grep -q "^API_SERVER_KEY=" "$KEY_LINE_FILE"; then
    say "API_SERVER_KEY 이미 설정됨 (유지)"
  else
    KEY=$(python3 -c "import secrets; print('so-'+secrets.token_hex(24))")
    {
      echo "API_SERVER_ENABLED=true"
      echo "API_SERVER_KEY=$KEY"
      echo "API_SERVER_PORT=$PORT"
      echo "API_SERVER_HOST=127.0.0.1"
    } >> "$KEY_LINE_FILE"
    chmod 600 "$KEY_LINE_FILE"
    say "API_SERVER_KEY 생성 완료 — backend/.env 의 SIGNOFF_LLM_API_KEY 에 같은 값을 넣을 것 (키는 화면에 출력하지 않음)"
  fi
else
  say "(dry-run) $KEY_LINE_FILE 에 API_SERVER_ENABLED/KEY/PORT($PORT)/HOST 추가"
fi

# 4) 게이트웨이 재시작 안내
say "다음 단계:"
say "  1. hermes -p $PROFILE gateway restart   # api_server :$PORT 기동"
say "  2. curl -s http://127.0.0.1:$PORT/health  # 확인"
say "  3. backend/.env 에 SIGNOFF_LLM_API_KEY=<위 키> 설정 (backend/.env.example 참고)"
say "  4. (선택) AIFde 게이트웨이(:8700) 업스트림 등록: cd ~/gitspace/AIFde && python3 <hermes-gateway skill>/scripts/build_env.py --gateway-dir ~/gitspace/AIFde"
$APPLY || say "실제 적용: $0 --apply"
