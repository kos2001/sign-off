import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router';
import { api } from '../api';
import { useAuth } from '../components/AuthProvider';
import { securityActionKeys, securityActionLabel, securityEventDate } from '../securityEvents';
import { useLanguage } from '../components/LanguageProvider';

function localInput(value: string) {
  if (!value) return '';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '';
  const pad = (n: number, length = 2) => String(n).padStart(length, '0');
  return `${pad(date.getFullYear(), 4)}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}.${pad(date.getMilliseconds(), 3)}`;
}

export default function SecurityEvents() {
  const auth = useAuth();
  const { t } = useLanguage();
  const [params, setParams] = useSearchParams();
  const pendingParams = useRef(params);
  useEffect(() => { pendingParams.current = params; }, [params]);
  const subject = params.get('subject_username') ?? '';
  const [draft, setDraft] = useState(subject);
  useEffect(() => setDraft(subject), [subject]);
  const from = params.get('created_from') ?? '', before = params.get('created_before') ?? '';
  const [fromDraft, setFromDraft] = useState(() => localInput(from));
  const [beforeDraft, setBeforeDraft] = useState(() => localInput(before));
  const [periodError, setPeriodError] = useState('');
  useEffect(() => { setFromDraft(localInput(from)); setBeforeDraft(localInput(before)); setPeriodError(''); }, [from, before]);
  const filters: Record<string, string> = { limit: '25' };
  for (const key of ['subject_username', 'action', 'source', 'before_id', 'created_from', 'created_before']) {
    const value = params.get(key);
    if (value) filters[key] = value;
  }
  const allowed = auth.state.mode === 'required' && !!auth.state.user?.is_admin;
  const history = useQuery({ queryKey: ['admin-security-events', auth.state.user?.id, filters], queryFn: () => api.adminSecurityEvents(filters), enabled: allowed });
  function change(key: string, value: string) {
    // Preserve rapid consecutive filter edits before navigation rerenders.
    const next = new URLSearchParams(pendingParams.current);
    if (value) next.set(key, value); else next.delete(key);
    if (key !== 'before_id') next.delete('before_id');
    pendingParams.current = next;
    setParams(next);
  }
  function search() {
    const start = fromDraft ? new Date(fromDraft) : null, end = beforeDraft ? new Date(beforeDraft) : null;
    if ((start && !Number.isFinite(start.getTime())) || (end && !Number.isFinite(end.getTime()))) {
      setPeriodError(t('올바른 시각을 입력하세요.', 'Enter a valid time.')); return;
    }
    if (start && end && start >= end) { setPeriodError(t('종료 시각은 시작 시각보다 늦어야 합니다.', 'The end time must be later than the start time.')); return; }
    const next = new URLSearchParams(pendingParams.current);
    for (const [key, value] of Object.entries({ subject_username: draft.trim(), created_from: start?.toISOString() ?? '', created_before: end?.toISOString() ?? '' })) {
      if (value) next.set(key, value); else next.delete(key);
    }
    next.delete('before_id'); setPeriodError(''); pendingParams.current = next; setParams(next);
  }
  if (!allowed) return <p role="alert">{t('보안 이력 관리는 관리자 계정으로 로그인해야 사용할 수 있습니다.', 'Sign in with an administrator account to manage security events.')}</p>;
  return <div className="max-w-4xl space-y-5">
    <header><h1 className="text-xl font-bold">{t('보안 이력 관리', 'Security events')}</h1><p className="mt-2 text-sm text-[var(--text-secondary)]">{t('전체 계정·전역 작업과 로그인 실패 이력입니다. 실패한 로그인의 계정 이름은 요청자가 입력한 값이며 실행자 신원이 확인된 것은 아닙니다.', 'Actions across all accounts, global actions and failed sign-ins. The username on a failed sign-in is what the requester typed; the requester\'s identity is not verified.')}</p></header>
    <section aria-label={t('보안 이력 검색', 'Search security events')} className="rounded-xl border border-[var(--border)] p-4 space-y-3">
      <form className="space-y-3" onSubmit={e => { e.preventDefault(); search(); }}>
        <label className="block min-w-0 text-sm">{t('대상 계정 이름 (정확히)', 'Target username (exact)')}<input className="input mt-1 w-full" maxLength={64} value={draft} onChange={e => setDraft(e.target.value)} /></label>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="min-w-0 text-sm">{t('시작 시각 (포함)', 'Start time (inclusive)')}<input type="datetime-local" step="0.001" className="input mt-1 w-full" value={fromDraft} onChange={e => { setFromDraft(e.target.value); setPeriodError(''); }} /></label>
          <label className="min-w-0 text-sm">{t('종료 시각 (미포함)', 'End time (exclusive)')}<input type="datetime-local" step="0.001" className="input mt-1 w-full" value={beforeDraft} onChange={e => { setBeforeDraft(e.target.value); setPeriodError(''); }} /></label>
        </div>
        <p className="text-xs text-[var(--text-secondary)]">{t(`브라우저 시간대: ${Intl.DateTimeFormat().resolvedOptions().timeZone}. 빈칸은 제한 없음입니다. 입력 후 검색을 누르세요.`, `Browser time zone: ${Intl.DateTimeFormat().resolvedOptions().timeZone}. Leave a field blank for no limit. Press Search after entering values.`)}</p>
        {periodError && <p role="alert" className="text-sm text-[var(--status-critical)]">{periodError}</p>}
        <button className="btn btn-primary">{t('검색', 'Search')}</button>
      </form>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">{t('작업 종류', 'Action')}<select aria-label={t('작업 종류', 'Action')} className="input mt-1 w-full" value={filters.action ?? ''} onChange={e => change('action', e.target.value)}><option value="">{t('모든 작업', 'All actions')}</option>{securityActionKeys.map(key => <option key={key} value={key}>{securityActionLabel(key)}</option>)}</select></label>
        <label className="text-sm">{t('실행 경로', 'Source')}<select aria-label={t('실행 경로', 'Source')} className="input mt-1 w-full" value={filters.source ?? ''} onChange={e => change('source', e.target.value)}><option value="">{t('모두', 'All')}</option><option value="api">{t('서비스 API', 'Service API')}</option><option value="operator">{t('운영자 명령', 'Operator command')}</option></select></label>
      </div>
      <button className="btn btn-ghost" onClick={() => { setDraft(''); setFromDraft(''); setBeforeDraft(''); setPeriodError(''); pendingParams.current = new URLSearchParams(); setParams({}); }}>{t('검색 초기화', 'Reset search')}</button>
    </section>
    <section aria-label={t('전체 계정 보안 이력', 'Security events for all accounts')} className="space-y-3">
      <button className="btn btn-ghost" disabled={history.isFetching} onClick={() => { if (filters.before_id) change('before_id', ''); else void history.refetch(); }}>{t('최신 이력 보기', 'Show latest events')}</button>
      {history.isPending ? <p role="status">{t('이력을 불러오는 중…', 'Loading events…')}</p> : history.isError ? <p role="alert">{history.error.message} <button className="btn btn-ghost" onClick={() => void history.refetch()}>{t('다시 시도', 'Try again')}</button></p> : <>
        <p className="text-sm">{t(`표시된 이력 ${history.data.items.length}개`, `${history.data.items.length} ${history.data.items.length === 1 ? 'event' : 'events'} shown`)}</p>
        {history.data.items.length === 0 ? <p className="text-sm">{t('조건에 맞는 보안 이력이 없습니다.', 'No security events match these filters.')}</p> : <ol className="space-y-3">{history.data.items.map(event => <li key={event.id} className="rounded-xl border border-[var(--border)] p-4 space-y-1 text-sm break-all">
          <strong>{securityActionLabel(event.action)}</strong>
          <p>{t('대상', 'Target')}: {event.subject_username ?? t('전체 계정 (전역 작업)', 'All accounts (global action)')}</p>
          {event.action === 'login_failed' && event.subject_user_id === null && <p className="text-xs text-[var(--text-secondary)]">{t('입력된 이름 · 해당 시점에 등록된 계정 없음', 'Name as typed · no account with this name existed at the time')}</p>}
          <p>{t('실행', 'Performed by')}: {event.source === 'operator' ? t('로컬 운영자', 'Local operator') : event.actor_user_id === null ? t('인증되지 않은 요청', 'Unauthenticated request') : event.actor} · {event.source === 'operator' ? t('운영자 명령', 'Operator command') : t('서비스 API', 'Service API')}</p>
          <p className="text-xs text-[var(--text-secondary)]">{securityEventDate(event.created_at)} · {t('이력', 'Event')} #{event.id}</p>
          {event.revoked_sessions !== null && <p>{t(`종료한 세션 기록: ${event.revoked_sessions}개`, `Sessions ended: ${event.revoked_sessions}`)}</p>}
        </li>)}</ol>}
        {history.data.next_before_id !== null && <button className="btn btn-ghost" onClick={() => change('before_id', String(history.data.next_before_id))}>{t('이전 이력 보기', 'Show older events')}</button>}
      </>}
    </section>
  </div>;
}
