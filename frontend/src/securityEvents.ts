import { formatDateTime, tr } from './components/LanguageProvider';

const securityActionLabels: Record<string, () => string> = {
  login: () => tr('로그인', 'Sign in'), login_failed: () => tr('로그인 실패', 'Failed sign-in'), logout: () => tr('로그아웃', 'Sign out'), password_changed: () => tr('비밀번호 변경', 'Password changed'),
  other_sessions_revoked: () => tr('다른 세션 종료', 'Other sessions ended'), account_created: () => tr('계정 생성', 'Account created'),
  admin_account_created: () => tr('관리자 계정 생성', 'Administrator account created'), password_reset: () => tr('운영자 비밀번호 재설정', 'Password reset by operator'),
  account_disabled: () => tr('계정 비활성화', 'Account disabled'), account_enabled: () => tr('계정 활성화', 'Account enabled'),
  all_sessions_revoked: () => tr('전체 세션 종료', 'All sessions ended'),
  release_confirmation_failed: () => tr('사인오프 비밀번호 확인 실패', 'Sign-off password confirmation failed'),
};

/** Action keys sent to and received from the backend, in display order. */
export const securityActionKeys = Object.keys(securityActionLabels);

/** Localized label for a security event action; unknown actions are shown as-is. */
export function securityActionLabel(action: string) {
  return securityActionLabels[action]?.() ?? action;
}

export function securityEventDate(value: string) {
  return formatDateTime(value);
}
