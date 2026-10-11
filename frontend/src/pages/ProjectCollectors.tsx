import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useParams } from 'react-router';

import { api, type IssuedCollectorCredential } from '../api';
import { useAuth } from '../components/AuthProvider';
import { formatDateTime, tr, useLanguage } from '../components/LanguageProvider';
import { StatusBadge } from '../components/ui';

function dateFromEpoch(value: number) {
  return formatDateTime(value * 1000);
}

const statusLabel = {
  get active() { return tr('활성', 'Active'); },
  get expired() { return tr('만료', 'Expired'); },
  get revoked() { return tr('폐기', 'Revoked'); },
};

export default function ProjectCollectors() {
  const projectId = Number(useParams().id);
  const auth = useAuth();
  const { t } = useLanguage();
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
  if (!auth.can(projectId, 'owner')) return <p>{t('프로젝트 소유자 권한이 필요합니다.', 'Project owner permission is required.')} <Link className="underline" to={`/projects/${projectId}`}>{t('프로젝트로', 'Back to project')}</Link></p>;
  return <section className="max-w-4xl space-y-5">
    <header><Link className="text-sm underline" to={`/projects/${projectId}`}>{t('프로젝트로', 'Back to project')}</Link><h1 className="mt-2 text-xl font-bold">{t('수집기 자격증명', 'Collector credentials')}</h1></header>
    <p className="text-sm">{t('상용 EDA 자동 수집기에 프로젝트 범위의 만료형 Bearer 토큰을 발급합니다. AI는 발급·폐기 결정에 개입하지 않습니다.', 'Issues expiring, project-scoped Bearer tokens to automated commercial EDA collectors. AI takes no part in issue or revoke decisions.')}</p>
    <form className="flex flex-wrap items-end gap-3" onSubmit={event => { event.preventDefault(); create.mutate(); }}>
      <label className="text-sm">{t('자격증명 이름', 'Credential name')}<input className="input mt-1 block" required pattern="[a-z0-9][a-z0-9_.-]{0,63}" maxLength={64} value={name} onChange={event => setName(event.target.value)} placeholder="primetime-prod-2026q4" /></label>
      <label className="text-sm">{t('유효 일수', 'Valid for (days)')}<input className="input mt-1 block w-28" required type="number" min={1} max={3650} value={validDays} onChange={event => setValidDays(Number(event.target.value))} /></label>
      <button className="btn btn-primary" disabled={create.isPending || revoke.isPending}>{create.isPending ? t('발급 중…', 'Issuing…') : t('새 토큰 발급', 'Issue new token')}</button>
    </form>
    <p className="text-xs text-[var(--text-muted)]">{t('이름은 소문자·숫자로 시작하고 소문자, 숫자, 점, 밑줄, 하이픈만 사용합니다. 폐기한 이름은 감사 추적을 위해 다시 사용할 수 없습니다.', 'Names start with a lowercase letter or digit and use only lowercase letters, digits, dots, underscores and hyphens. Revoked names cannot be reused, to keep the audit trail intact.')}</p>
    {create.isError && <p role="alert">{create.error.message}</p>}
    {issued && <section className="rounded-lg border border-[var(--status-warning)] p-4 space-y-2" aria-label={t('새 수집기 토큰', 'New collector token')}>
      <h2 className="font-semibold">{t('지금 토큰을 비밀 저장소에 보관하세요', 'Store this token in your secret store now')}</h2>
      <p className="text-sm">{t('이 토큰은 이 화면에서 한 번만 표시되며 서버는 SHA-256 해시만 저장합니다.', 'This token is shown only once on this screen; the server stores only its SHA-256 hash.')}</p>
      <textarea className="input w-full font-mono text-xs" readOnly rows={2} value={issued.token} aria-label={t('발급된 수집기 토큰', 'Issued collector token')} />
      <button className="btn btn-ghost" onClick={async () => { await navigator.clipboard.writeText(issued.token); setCopied(true); }}>{copied ? t('복사됨', 'Copied') : t('토큰 복사', 'Copy token')}</button>
      <button className="btn btn-ghost ml-2" onClick={() => setIssued(null)}>{t('보관 완료', 'Stored')}</button>
    </section>}
    {(credentials.isPending || history.isPending) && <p role="status">{t('자격증명 불러오는 중…', 'Loading credentials…')}</p>}
    {(credentials.isError || history.isError || revoke.isError) && <p role="alert">{credentials.error?.message ?? history.error?.message ?? revoke.error?.message}</p>}
    {credentials.data && <section className="space-y-3" aria-label={t('수집기 자격증명 목록', 'Collector credential list')}><h2 className="font-semibold">{t('발급된 자격증명', 'Issued credentials')}</h2>
      {credentials.data.length === 0 ? <p className="text-sm">{t('발급된 자격증명이 없습니다.', 'No credentials issued.')}</p> : <ul className="space-y-2">{credentials.data.map(item => <li className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[var(--border)] p-3" key={item.id}>
        <div><p className="font-semibold">{item.name}</p><p className="text-xs text-[var(--text-muted)]">ID {item.id} · {t('만료', 'Expires')} {dateFromEpoch(item.expires_at)} · {t('최근 사용', 'Last used')} {item.last_used_at ? formatDateTime(item.last_used_at) : t('없음', 'Never')}</p></div>
        <div className="flex items-center gap-2"><StatusBadge status={item.status === 'active' ? 'good' : item.status === 'expired' ? 'warning' : 'neutral'} label={statusLabel[item.status]} />{item.status === 'active' && (revokeId === item.id ? <><button className="btn btn-primary" disabled={revoke.isPending} onClick={() => revoke.mutate(item.id)}>{revoke.isPending ? t('폐기 중…', 'Revoking…') : t('폐기 확인', 'Confirm revoke')}</button><button className="btn btn-ghost" disabled={revoke.isPending} onClick={() => setRevokeId(null)}>{t('취소', 'Cancel')}</button></> : <button className="btn btn-ghost" disabled={revoke.isPending} onClick={() => setRevokeId(item.id)}>{t('즉시 폐기', 'Revoke now')}</button>)}</div>
      </li>)}</ul>}
    </section>}
    {history.data && <section className="space-y-3 border-t border-[var(--border)] pt-5" aria-label={t('수집기 자격증명 감사 이력', 'Collector credential audit history')}><h2 className="font-semibold">{t('발급·폐기 감사 이력', 'Issue and revoke audit history')}</h2>
      <ol className="space-y-2">{history.data.pages.flatMap(page => page.items).map(item => <li className="rounded-lg bg-[var(--surface-1)] p-3 text-sm" key={item.id}><p className="font-medium">{item.credential_name} · {item.action === 'issued' ? t('발급', 'Issued') : t('폐기', 'Revoked')}</p><p className="text-xs text-[var(--text-muted)]">{item.actor} · {formatDateTime(item.created_at)} · {t('만료', 'Expires')} {dateFromEpoch(item.expires_at)}</p></li>)}</ol>
      {history.hasNextPage && <button className="btn btn-ghost" disabled={history.isFetchingNextPage} onClick={() => history.fetchNextPage()}>{history.isFetchingNextPage ? t('불러오는 중…', 'Loading…') : t('이전 이력 더 보기', 'Show earlier history')}</button>}
    </section>}
  </section>;
}
