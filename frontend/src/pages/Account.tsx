import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { securityActionLabel, securityEventDate } from '../securityEvents';
import { useAuth } from "../components/AuthProvider";
import { formatDateTime, tr, useLanguage } from '../components/LanguageProvider';

const errors: Record<string, () => string> = {
  "current password is incorrect": () => tr("현재 비밀번호가 일치하지 않습니다.", "The current password is incorrect."),
  "new password must differ from current password": () => tr("새 비밀번호는 현재 비밀번호와 달라야 합니다.", "The new password must differ from the current password."),
  "too many login attempts; try again in five minutes": () => tr("시도 횟수를 초과했습니다. 5분 뒤 다시 시도하세요.", "Too many attempts. Try again in five minutes."),
  "account changed; sign in again before changing the password": () => tr("계정 정보가 변경되었습니다. 다시 로그인한 뒤 시도하세요.", "Your account has changed. Sign in again, then try again."),
};
export default function Account() {
  const auth = useAuth();
  const { t } = useLanguage();
  const qc = useQueryClient();
  const [current, setCurrent] = useState("");
  const [replacement, setReplacement] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  if (!auth.state.user) return <p>{t("계정 설정은 로그인 모드에서 사용할 수 있습니다.", "Account settings are available only when sign-in is enabled.")}</p>;
  return <section className="max-w-lg space-y-5">
    <header><h1 className="text-xl font-bold">{t("계정 설정", "Account settings")}</h1><p className="mt-2 text-sm">{t("로그인 계정", "Signed in as")}: {auth.state.user.username}</p></header>
    <form className="rounded-xl border border-[var(--border)] p-5 space-y-4" onSubmit={async e => {
      e.preventDefault(); setError(""); setDone(false);
      if (replacement !== confirmation) { setError(t("새 비밀번호 확인이 일치하지 않습니다.", "The new password confirmation does not match.")); return; }
      setPending(true);
      try { await auth.changePassword(current, replacement); setCurrent(""); setReplacement(""); setConfirmation(""); setDone(true); await Promise.all([qc.invalidateQueries({ queryKey: ['auth-sessions'] }), qc.invalidateQueries({ queryKey: ['account-security-events'] })]); }
      catch (error) { const message = (error as Error).message; setError(errors[message]?.() ?? message); setCurrent(""); }
      finally { setPending(false); }
    }}>
      <h2 className="font-semibold">{t("비밀번호 변경", "Change password")}</h2>
      <p className="text-sm text-[var(--text-secondary)]">{t("변경 후 현재 브라우저는 로그인 상태를 유지하고, 다른 브라우저와 기기의 로그인은 종료됩니다.", "After the change, this browser stays signed in and sessions on other browsers and devices are signed out.")}</p>
      <input type="text" autoComplete="username" value={auth.state.user.username} readOnly hidden />
      <label className="block text-sm">{t("현재 비밀번호", "Current password")}<input className="input w-full mt-1" type="password" required maxLength={256} autoComplete="current-password" value={current} onChange={e => setCurrent(e.target.value)} disabled={pending} /></label>
      <label className="block text-sm">{t("새 비밀번호", "New password")}<input className="input w-full mt-1" type="password" required minLength={15} maxLength={256} autoComplete="new-password" value={replacement} onChange={e => setReplacement(e.target.value)} disabled={pending} aria-describedby="password-length" /></label>
      <p id="password-length" className="text-xs text-[var(--text-secondary)]">{t("15–256자로 입력하세요. 기억하기 쉬운 긴 문장을 사용할 수 있습니다.", "Use 15–256 characters. A long, memorable sentence works well.")}</p>
      <label className="block text-sm">{t("새 비밀번호 확인", "Confirm new password")}<input className="input w-full mt-1" type="password" required minLength={15} maxLength={256} autoComplete="new-password" value={confirmation} onChange={e => setConfirmation(e.target.value)} disabled={pending} /></label>
      {error && <p role="alert" className="text-sm text-[var(--status-critical)]">{error}</p>}
      {done && <p role="status" className="text-sm">{t("비밀번호를 변경했습니다. 다른 로그인 세션도 종료했습니다.", "Password changed. Your other sessions have been signed out.")}</p>}
      <button className="btn btn-primary" disabled={pending}>{pending ? t("변경 중…", "Changing…") : t("비밀번호 변경", "Change password")}</button>
    </form>
    <SessionPanel userId={auth.state.user.id} disabled={pending} />
    <SecurityHistory userId={auth.state.user.id} />
  </section>;
}

function SessionPanel({ userId, disabled }: { userId: number; disabled: boolean }) {
  const { t } = useLanguage();
  const qc = useQueryClient();
  const [offset, setOffset] = useState(0);
  const sessions = useQuery({ queryKey: ['auth-sessions', userId, offset], queryFn: () => api.authSessions(offset), refetchInterval: 60000 });
  const revoke = useMutation({ mutationFn: api.revokeOtherSessions, onSuccess: async () => {
    setOffset(0); await Promise.all([qc.invalidateQueries({ queryKey: ['auth-sessions', userId] }), qc.invalidateQueries({ queryKey: ['account-security-events', userId] })]);
  } });
  return <section aria-label={t("로그인 세션", "Sign-in sessions")} className="rounded-xl border border-[var(--border)] p-5 space-y-4">
    <h2 className="font-semibold">{t("로그인 세션", "Sign-in sessions")}</h2>
    <p className="text-sm text-[var(--text-secondary)]">{t("현재 세션을 유지하면서 다른 로그인을 종료할 수 있습니다. 종료된 세션은 다음 요청부터 다시 로그인해야 합니다. 기기 이름과 위치는 수집하지 않습니다.", "You can sign out other sessions while keeping this one. An ended session must sign in again on its next request. Device names and locations are not collected.")}</p>
    {sessions.isPending ? <p role="status">{t("세션을 불러오는 중…", "Loading sessions…")}</p> : sessions.isError ? <p role="alert">{sessions.error.message} <button className="btn btn-ghost" onClick={() => void sessions.refetch()}>{t("다시 시도", "Try again")}</button></p> : <>
      <p className="text-sm">{t(`활성 세션 ${sessions.data.total}개`, `${sessions.data.total} active ${sessions.data.total === 1 ? 'session' : 'sessions'}`)}</p>
      <ul className="space-y-2">{sessions.data.items.map(session => <li key={session.id} className="rounded-lg bg-[var(--surface-2)] p-3 text-sm break-words">
        <strong>{session.current ? t('현재 세션', 'This session') : t(`다른 세션 #${session.id}`, `Other session #${session.id}`)}</strong>
        <p className="mt-1 text-xs text-[var(--text-secondary)]">{t("만료", "Expires")}: {formatDateTime(session.expires_at * 1000)}</p>
      </li>)}</ul>
      {offset > 0 && sessions.data.items.length === 0 && <p className="text-sm">{t("이 페이지에 활성 세션이 없습니다.", "No active sessions on this page.")}</p>}
      {(offset > 0 || sessions.data.total > 25) && <nav aria-label={t("세션 페이지", "Session pages")} className="flex flex-wrap items-center gap-2">
        <button className="btn btn-ghost" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>{t("이전 세션", "Previous sessions")}</button>
        <button className="btn btn-ghost" disabled={offset + 25 >= sessions.data.total} onClick={() => setOffset(offset + 25)}>{t("다음 세션", "Next sessions")}</button>
        {offset > 0 && <button className="btn btn-ghost" onClick={() => setOffset(0)}>{t("첫 페이지", "First page")}</button>}
      </nav>}
    </>}
    {revoke.isError && <p role="alert" className="text-sm text-[var(--status-critical)]">{t("세션을 종료하지 못했습니다", "Could not end sessions")}: {revoke.error.message}</p>}
    {revoke.isSuccess && <p role="status" className="text-sm">{t(`다른 활성 세션 ${revoke.data.revoked}개를 종료했습니다.`, `Ended ${revoke.data.revoked} other active ${revoke.data.revoked === 1 ? 'session' : 'sessions'}.`)}</p>}
    <button className="btn btn-ghost" disabled={disabled || revoke.isPending || !sessions.data || sessions.data.total <= 1} onClick={() => revoke.mutate()}>{revoke.isPending ? t('종료 중…', 'Ending…') : t('다른 세션 모두 종료', 'Sign out all other sessions')}</button>
  </section>;
}

function SecurityHistory({ userId }: { userId: number }) {
  const { t } = useLanguage();
  const [before, setBefore] = useState<number | null>(null);
  const history = useQuery({ queryKey: ['account-security-events', userId, before], queryFn: () => api.securityEvents(before) });
  return <section aria-label={t("계정 보안 이력", "Account security events")} className="rounded-xl border border-[var(--border)] p-5 space-y-4">
    <h2 className="font-semibold">{t("계정 보안 이력", "Account security events")}</h2>
    <p className="text-sm text-[var(--text-secondary)]">{t("본인 계정의 작업과 로그인 실패 이력입니다. 로그인 실패는 이 계정 이름으로 시도된 요청이며 본인의 행동을 뜻하지 않습니다. 최신순으로 25개씩 표시합니다.", "Actions on your account and failed sign-ins. A failed sign-in is a request made with this username and does not mean you made it. Shown newest first, 25 at a time.")}</p>
    <button className="btn btn-ghost" disabled={history.isFetching} onClick={() => { if (before === null) void history.refetch(); else setBefore(null); }}>{t("최신 이력 보기", "Show latest events")}</button>
    {history.isPending ? <p role="status">{t("이력을 불러오는 중…", "Loading events…")}</p> : history.isError ? <p role="alert">{history.error.message} <button className="btn btn-ghost" onClick={() => void history.refetch()}>{t("다시 시도", "Try again")}</button></p> : <>
      {history.data.items.length === 0 ? <p className="text-sm">{t("표시할 보안 이력이 없습니다.", "No security events to show.")}</p> : <ol className="space-y-3">{history.data.items.map(event => <li key={event.id} className="rounded-lg bg-[var(--surface-2)] p-3 text-sm break-words">
        <strong>{securityActionLabel(event.action)}</strong>
        <p className="mt-1 text-xs text-[var(--text-secondary)]">{securityEventDate(event.created_at)}</p>
        <p className="mt-1 text-xs">{t("실행", "Performed by")}: {event.source === 'operator' ? t('로컬 운영자', 'Local operator') : event.actor_user_id === null ? t('인증되지 않은 요청', 'Unauthenticated request') : event.actor}</p>
        {event.revoked_sessions !== null && <p className="mt-1 text-xs">{t(`종료한 세션 기록: ${event.revoked_sessions}개`, `Sessions ended: ${event.revoked_sessions}`)}</p>}
      </li>)}</ol>}
      {history.data.next_before_id !== null && <button className="btn btn-ghost" onClick={() => setBefore(history.data.next_before_id)}>{t("이전 이력 보기", "Show older events")}</button>}
    </>}
  </section>;
}
