export const securityActions: Record<string, string> = {
  login: '로그인', login_failed: '로그인 실패', logout: '로그아웃', password_changed: '비밀번호 변경',
  other_sessions_revoked: '다른 세션 종료', account_created: '계정 생성',
  admin_account_created: '관리자 계정 생성', password_reset: '운영자 비밀번호 재설정',
  account_disabled: '계정 비활성화', account_enabled: '계정 활성화',
  all_sessions_revoked: '전체 세션 종료',
};

export function securityEventDate(value: string) {
  return new Date(/[Zz]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`).toLocaleString();
}
