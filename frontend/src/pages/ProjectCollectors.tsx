import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useParams } from 'react-router';

import { api, type IssuedCollectorCredential } from '../api';
import { useAuth } from '../components/AuthProvider';
import { StatusBadge } from '../components/ui';

function dateFromEpoch(value: number) {
  return new Date(value * 1000).toLocaleString('ko-KR');
}

const statusLabel = { active: '활성', expired: '만료', revoked: '폐기' };

export default function ProjectCollectors() {
  const projectId = Number(useParams().id);
  const auth = useAuth();
  const qc = useQueryClient();
  const [name, setName] = useState('');
  const [validDays, setValidDays] = useState(90);
  const [issued, setIssued] = useState<IssuedCollectorCredential | null>(null);
  const [copied, setCopied] = useState(false);
  const [revokeId, setRevokeId] = useState<number | null>(null);
  const credentials = useQuery({
    queryKey: ['collectors', projectId], queryFn: () => api.collectors(projectId),
    enabled: auth.can(projectId, 'owner'),
  });
  const history = useInfiniteQuery({
    queryKey: ['collector-history', projectId],
    queryFn: ({ pageParam }) => api.collectorHistory(projectId, pageParam),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: page => page.next_before_id ?? undefined,
    enabled: auth.can(projectId, 'owner'),
  });
  const refresh = async () => {
    await Promise.all([
      qc.invalidateQueries({ queryKey: ['collectors', projectId] }),
      qc.invalidateQueries({ queryKey: ['collector-history', projectId] }),
    ]);
  };
  const create = useMutation({
    mutationFn: () => api.createCollector(projectId, name.trim(), validDays),
    onSuccess: async value => { setIssued(value); setCopied(false); setName(''); await refresh(); },
  });
  const revoke = useMutation({ mutationFn: (id: number) => api.revokeCollector(projectId, id), onSuccess: async () => { setRevokeId(null); await refresh(); } });
  if (!auth.can(projectId, 'owner')) return <p>프로젝트 소유자 권한이 필요합니다. <Link className="underline" to={`/projects/${projectId}`}>프로젝트로</Link></p>;
  return <section className="max-w-4xl space-y-5">
    <header><Link className="text-sm underline" to={`/projects/${projectId}`}>프로젝트로</Link><h1 className="mt-2 text-xl font-bold">수집기 자격증명</h1></header>
    <p className="text-sm">상용 EDA 자동 수집기에 프로젝트 범위의 만료형 Bearer 토큰을 발급합니다. AI는 발급·폐기 결정에 개입하지 않습니다.</p>
    <form className="flex flex-wrap items-end gap-3" onSubmit={event => { event.preventDefault(); create.mutate(); }}>
      <label className="text-sm">자격증명 이름<input className="input mt-1 block" required pattern="[a-z0-9][a-z0-9_.-]{0,63}" maxLength={64} value={name} onChange={event => setName(event.target.value)} placeholder="primetime-prod-2026q4" /></label>
      <label className="text-sm">유효 일수<input className="input mt-1 block w-28" required type="number" min={1} max={3650} value={validDays} onChange={event => setValidDays(Number(event.target.value))} /></label>
      <button className="btn btn-primary" disabled={create.isPending || revoke.isPending}>{create.isPending ? '발급 중…' : '새 토큰 발급'}</button>
    </form>
    <p className="text-xs text-[var(--text-muted)]">이름은 소문자·숫자로 시작하고 소문자, 숫자, 점, 밑줄, 하이픈만 사용합니다. 폐기한 이름은 감사 추적을 위해 다시 사용할 수 없습니다.</p>
    {create.isError && <p role="alert">{create.error.message}</p>}
    {issued && <section className="rounded-lg border border-[var(--status-warning)] p-4 space-y-2" aria-label="새 수집기 토큰">
      <h2 className="font-semibold">지금 토큰을 비밀 저장소에 보관하세요</h2>
      <p className="text-sm">이 토큰은 이 화면에서 한 번만 표시되며 서버는 SHA-256 해시만 저장합니다.</p>
      <textarea className="input w-full font-mono text-xs" readOnly rows={2} value={issued.token} aria-label="발급된 수집기 토큰" />
      <button className="btn btn-ghost" onClick={async () => { await navigator.clipboard.writeText(issued.token); setCopied(true); }}>{copied ? '복사됨' : '토큰 복사'}</button>
      <button className="btn btn-ghost ml-2" onClick={() => setIssued(null)}>보관 완료</button>
    </section>}
    {(credentials.isPending || history.isPending) && <p role="status">자격증명 불러오는 중…</p>}
    {(credentials.isError || history.isError || revoke.isError) && <p role="alert">{credentials.error?.message ?? history.error?.message ?? revoke.error?.message}</p>}
    {credentials.data && <section className="space-y-3" aria-label="수집기 자격증명 목록"><h2 className="font-semibold">발급된 자격증명</h2>
      {credentials.data.length === 0 ? <p className="text-sm">발급된 자격증명이 없습니다.</p> : <ul className="space-y-2">{credentials.data.map(item => <li className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[var(--border)] p-3" key={item.id}>
        <div><p className="font-semibold">{item.name}</p><p className="text-xs text-[var(--text-muted)]">ID {item.id} · 만료 {dateFromEpoch(item.expires_at)} · 최근 사용 {item.last_used_at ? new Date(item.last_used_at).toLocaleString('ko-KR') : '없음'}</p></div>
        <div className="flex items-center gap-2"><StatusBadge status={item.status === 'active' ? 'good' : item.status === 'expired' ? 'warning' : 'neutral'} label={statusLabel[item.status]} />{item.status === 'active' && (revokeId === item.id ? <><button className="btn btn-primary" disabled={revoke.isPending} onClick={() => revoke.mutate(item.id)}>{revoke.isPending ? '폐기 중…' : '폐기 확인'}</button><button className="btn btn-ghost" disabled={revoke.isPending} onClick={() => setRevokeId(null)}>취소</button></> : <button className="btn btn-ghost" disabled={revoke.isPending} onClick={() => setRevokeId(item.id)}>즉시 폐기</button>)}</div>
      </li>)}</ul>}
    </section>}
    {history.data && <section className="space-y-3 border-t border-[var(--border)] pt-5" aria-label="수집기 자격증명 감사 이력"><h2 className="font-semibold">발급·폐기 감사 이력</h2>
      <ol className="space-y-2">{history.data.pages.flatMap(page => page.items).map(item => <li className="rounded-lg bg-[var(--surface-1)] p-3 text-sm" key={item.id}><p className="font-medium">{item.credential_name} · {item.action === 'issued' ? '발급' : '폐기'}</p><p className="text-xs text-[var(--text-muted)]">{item.actor} · {new Date(item.created_at).toLocaleString('ko-KR')} · 만료 {dateFromEpoch(item.expires_at)}</p></li>)}</ol>
      {history.hasNextPage && <button className="btn btn-ghost" disabled={history.isFetchingNextPage} onClick={() => history.fetchNextPage()}>{history.isFetchingNextPage ? '불러오는 중…' : '이전 이력 더 보기'}</button>}
    </section>}
  </section>;
}
