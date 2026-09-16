import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router';
import { api } from '../api';
import { useAuth } from '../components/AuthProvider';
import { securityActions, securityEventDate } from '../securityEvents';

function localInput(value: string) {
  if (!value) return '';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '';
  const pad = (n: number, length = 2) => String(n).padStart(length, '0');
  return `${pad(date.getFullYear(), 4)}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}.${pad(date.getMilliseconds(), 3)}`;
}

export default function SecurityEvents() {
  const auth = useAuth();
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
      setPeriodError('올바른 시각을 입력하세요.'); return;
    }
    if (start && end && start >= end) { setPeriodError('종료 시각은 시작 시각보다 늦어야 합니다.'); return; }
    const next = new URLSearchParams(pendingParams.current);
    for (const [key, value] of Object.entries({ subject_username: draft.trim(), created_from: start?.toISOString() ?? '', created_before: end?.toISOString() ?? '' })) {
      if (value) next.set(key, value); else next.delete(key);
    }
    next.delete('before_id'); setPeriodError(''); pendingParams.current = next; setParams(next);
  }
  if (!allowed) return <p role="alert">보안 이력 관리는 관리자 계정으로 로그인해야 사용할 수 있습니다.</p>;
  return <div className="max-w-4xl space-y-5">
    <header><h1 className="text-xl font-bold">보안 이력 관리</h1><p className="mt-2 text-sm text-[var(--text-secondary)]">전체 계정·전역 작업과 로그인 실패 이력입니다. 실패한 로그인의 계정 이름은 요청자가 입력한 값이며 실행자 신원이 확인된 것은 아닙니다.</p></header>
    <section aria-label="보안 이력 검색" className="rounded-xl border border-[var(--border)] p-4 space-y-3">
      <form className="space-y-3" onSubmit={e => { e.preventDefault(); search(); }}>
        <label className="block min-w-0 text-sm">대상 계정 이름 (정확히)<input className="input mt-1 w-full" maxLength={64} value={draft} onChange={e => setDraft(e.target.value)} /></label>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="min-w-0 text-sm">시작 시각 (포함)<input type="datetime-local" step="0.001" className="input mt-1 w-full" value={fromDraft} onChange={e => { setFromDraft(e.target.value); setPeriodError(''); }} /></label>
          <label className="min-w-0 text-sm">종료 시각 (미포함)<input type="datetime-local" step="0.001" className="input mt-1 w-full" value={beforeDraft} onChange={e => { setBeforeDraft(e.target.value); setPeriodError(''); }} /></label>
        </div>
        <p className="text-xs text-[var(--text-secondary)]">브라우저 시간대: {Intl.DateTimeFormat().resolvedOptions().timeZone}. 빈칸은 제한 없음입니다. 입력 후 검색을 누르세요.</p>
        {periodError && <p role="alert" className="text-sm text-[var(--status-critical)]">{periodError}</p>}
        <button className="btn btn-primary">검색</button>
      </form>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">작업 종류<select aria-label="작업 종류" className="input mt-1 w-full" value={filters.action ?? ''} onChange={e => change('action', e.target.value)}><option value="">모든 작업</option>{Object.entries(securityActions).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <label className="text-sm">실행 경로<select aria-label="실행 경로" className="input mt-1 w-full" value={filters.source ?? ''} onChange={e => change('source', e.target.value)}><option value="">모두</option><option value="api">서비스 API</option><option value="operator">운영자 명령</option></select></label>
      </div>
      <button className="btn btn-ghost" onClick={() => { setDraft(''); setFromDraft(''); setBeforeDraft(''); setPeriodError(''); pendingParams.current = new URLSearchParams(); setParams({}); }}>검색 초기화</button>
    </section>
    <section aria-label="전체 계정 보안 이력" className="space-y-3">
      <button className="btn btn-ghost" disabled={history.isFetching} onClick={() => { if (filters.before_id) change('before_id', ''); else void history.refetch(); }}>최신 이력 보기</button>
      {history.isPending ? <p role="status">이력을 불러오는 중…</p> : history.isError ? <p role="alert">{history.error.message} <button className="btn btn-ghost" onClick={() => void history.refetch()}>다시 시도</button></p> : <>
        <p className="text-sm">표시된 이력 {history.data.items.length}개</p>
        {history.data.items.length === 0 ? <p className="text-sm">조건에 맞는 보안 이력이 없습니다.</p> : <ol className="space-y-3">{history.data.items.map(event => <li key={event.id} className="rounded-xl border border-[var(--border)] p-4 space-y-1 text-sm break-all">
          <strong>{securityActions[event.action] ?? event.action}</strong>
          <p>대상: {event.subject_username ?? '전체 계정 (전역 작업)'}</p>
          {event.action === 'login_failed' && event.subject_user_id === null && <p className="text-xs text-[var(--text-secondary)]">입력된 이름 · 해당 시점에 등록된 계정 없음</p>}
          <p>실행: {event.source === 'operator' ? '로컬 운영자' : event.actor_user_id === null ? '인증되지 않은 요청' : event.actor} · {event.source === 'operator' ? '운영자 명령' : '서비스 API'}</p>
          <p className="text-xs text-[var(--text-secondary)]">{securityEventDate(event.created_at)} · 이력 #{event.id}</p>
          {event.revoked_sessions !== null && <p>종료한 세션 기록: {event.revoked_sessions}개</p>}
        </li>)}</ol>}
        {history.data.next_before_id !== null && <button className="btn btn-ghost" onClick={() => change('before_id', String(history.data.next_before_id))}>이전 이력 보기</button>}
      </>}
    </section>
  </div>;
}
