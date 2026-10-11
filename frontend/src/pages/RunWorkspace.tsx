import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useParams, useSearchParams } from 'react-router';

import { api, DOMAIN_LABELS, STAGE_LABELS, type RunStatus, type Severity, type ViolationStatus } from '../api';
import { useAuth } from '../components/AuthProvider';
import { EVIDENCE_LABELS, RunEvidencePanel } from '../components/RunEvidencePanel';
import { ViolationActions } from '../components/ViolationActions';
import { Card, StatusBadge } from '../components/ui';
import { formatDateTime, tr, useLanguage } from '../components/LanguageProvider';

const STATUS_LABELS: Record<ViolationStatus, string> = { get open() { return tr('미해결', 'Open'); }, get fixed() { return tr('수정 완료', 'Fixed'); }, get waived() { return tr('웨이버 승인', 'Waiver approved'); } };
const SEVERITY_LABELS: Record<Severity, string> = { get info() { return tr('정보', 'Info'); }, get warning() { return tr('경고', 'Warning'); }, get error() { return tr('오류', 'Error'); }, get critical() { return tr('치명적', 'Critical'); } };
const RUN_STATUS: Record<RunStatus, string> = { get running() { return tr('진행 중', 'Running'); }, get incomplete() { return tr('검증 미완료', 'Verification incomplete'); }, get passed() { return tr('통과', 'Passed'); }, get failed() { return tr('실패', 'Failed'); } };

function nonnegative(value: string | null, maximum: number) {
  const number = Number(value);
  return Number.isInteger(number) && number >= 0 && number <= maximum ? number : 0;
}

function option<T extends string>(value: string | null, values: readonly T[]): T | '' {
  return value && values.includes(value as T) ? value as T : '';
}

function metric(value: unknown) {
  if (value === null) return 'null';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
  const text = JSON.stringify(value);
  return text.length > 500 ? `${text.slice(0, 500)}…` : text;
}

export default function RunWorkspace() {
  const { t } = useLanguage();
  const runId = Number(useParams().runId);
  const validRun = Number.isSafeInteger(runId) && runId > 0;
  const [params, setParams] = useSearchParams();
  const q = (params.get('q') ?? '').slice(0, 200);
  const [search, setSearch] = useState(q);
  useEffect(() => setSearch(q), [q]);
  const status = option(params.get('status'), ['open', 'fixed', 'waived'] as const);
  const severity = option(params.get('severity'), ['info', 'warning', 'error', 'critical'] as const);
  const offset = nonnegative(params.get('offset'), 10000);
  const filters: Record<string, string> = {
    q, offset: String(offset), limit: '25',
    ...(status ? { status } : {}),
    ...(severity ? { severity } : {}),
  };
  const qc = useQueryClient();
  const run = useQuery({ queryKey: ['run', runId], queryFn: () => api.getRun(runId), enabled: validRun, retry: false });
  const findings = useQuery({ queryKey: ['run-violations-page', runId, filters], queryFn: () => api.runViolations(runId, filters), enabled: validRun && !!run.data, retry: false });
  const auth = useAuth();
  const update = useMutation({
    mutationFn: (next: 'passed' | 'failed') => api.updateRun(runId, next),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['run', runId] }); void qc.invalidateQueries({ queryKey: ['runs'] }); },
  });
  function apply(next: Partial<Record<'q' | 'status' | 'severity' | 'offset', string>>) {
    setParams(previous => {
      const value = new URLSearchParams(previous);
      for (const [key, item] of Object.entries(next)) item ? value.set(key, item) : value.delete(key);
      if (!Object.hasOwn(next, 'offset')) value.delete('offset');
      return value;
    });
  }
  if (!validRun) return <p role="alert">{t('유효한 런 번호가 아닙니다.', 'Not a valid run number.')} <Link className="underline" to="/">{t('대시보드로', 'Back to dashboard')}</Link></p>;
  if (run.isPending) return <p role="status">{t('런 워크스페이스 불러오는 중…', 'Loading run workspace…')}</p>;
  if (run.isError) return <section className="space-y-3"><p role="alert">{t('런을 불러오지 못했습니다', 'Could not load the run')}: {run.error.message}</p><button className="btn btn-ghost" onClick={() => void run.refetch()}>{t('다시 시도', 'Retry')}</button><Link className="btn btn-ghost" to="/">{t('대시보드로', 'Back to dashboard')}</Link></section>;
  const item = run.data;
  const metrics = Object.entries(item.metrics).slice(0, 100);
  const refreshFindings = () => { void qc.invalidateQueries({ queryKey: ['run-violations-page', runId] }); };
  return <div className="space-y-5">
    <header className="space-y-3">
      <Link className="text-sm underline" to={`/projects/${item.project_id}`}>{t('프로젝트로 돌아가기', 'Back to project')}</Link>
      <div className="flex flex-wrap items-center gap-3"><h1 className="text-xl font-bold">{t(`사인오프 런 #${item.id}`, `Sign-off run #${item.id}`)}</h1><StatusBadge status={item.status === 'passed' ? 'good' : item.status === 'failed' ? 'critical' : 'warning'} label={RUN_STATUS[item.status]} /></div>
      <p className="text-sm">{DOMAIN_LABELS[item.domain]} · {STAGE_LABELS[item.stage]} · {item.tool}</p>
      <p className="text-xs text-[var(--text-secondary)]">{t('생성', 'Created')} {formatDateTime(item.created_at)} · {EVIDENCE_LABELS[item.evidence_source]}</p>
      <div className="flex flex-wrap gap-2">
        {(item.evidence_source === 'opensta_report' || item.evidence_source === 'opensta_execution' || item.evidence_source === 'commercial_sta_report') && <Link className="btn btn-primary" to={`/runs/${item.id}/paths`}>{t('타이밍 경로 탐색', 'Explore timing paths')}</Link>}
        {(item.evidence_source === 'klayout_report' || item.evidence_source === 'commercial_drc_report') && <Link className="btn btn-primary" to={`/runs/${item.id}/markers`}>{t('DRC 마커 탐색', 'Explore DRC markers')}</Link>}
        {item.evidence_source === 'commercial_emir_report' && <Link className="btn btn-primary" to={`/runs/${item.id}/power-integrity`}>{t('EM/IR 핫스폿 탐색', 'Explore EM/IR hotspots')}</Link>}
        {item.evidence_source === 'commercial_power_report' && <Link className="btn btn-primary" to={`/runs/${item.id}/power-breakdown`}>{t('전력 계층 탐색', 'Explore power hierarchy')}</Link>}
        {item.evidence_source === 'commercial_thermal_report' && <Link className="btn btn-primary" to={`/runs/${item.id}/thermal-hotspots`}>{t('열 핫스폿 탐색', 'Explore thermal hotspots')}</Link>}
        {item.evidence_source === 'commercial_rtl_report' && <Link className="btn btn-primary" to={`/runs/${item.id}/rtl-regression`}>{t('RTL 회귀 탐색', 'Explore RTL regression')}</Link>}
        {item.evidence_source === 'commercial_lvs_report' && <Link className="btn btn-primary" to={`/runs/${item.id}/lvs-mismatches`}>{t('LVS 불일치 탐색', 'Explore LVS mismatches')}</Link>}
        {item.evidence_source === 'commercial_lec_report' && <Link className="btn btn-primary" to={`/runs/${item.id}/lec-failures`}>{t('LEC 실패 탐색', 'Explore LEC failures')}</Link>}
        {item.evidence_source === 'commercial_cdc_report' && <Link className="btn btn-primary" to={`/runs/${item.id}/cdc-findings`}>{t('CDC·RDC finding 탐색', 'Explore CDC·RDC findings')}</Link>}
        {item.evidence_source === 'commercial_dft_report' && <Link className="btn btn-primary" to={`/runs/${item.id}/dft-findings`}>{t('DFT finding 탐색', 'Explore DFT findings')}</Link>}
        {item.evidence_source === 'commercial_low_power_report' && <Link className="btn btn-primary" to={`/runs/${item.id}/low-power-findings`}>{t('저전력 finding 탐색', 'Explore low-power findings')}</Link>}
        {item.evidence_source === 'rtl_ladder' && <Link className="btn btn-primary" to={`/runs/${item.id}/structure`}>{t('합성 구조 탐색', 'Explore synthesized structure')}</Link>}
        <Link className="btn btn-ghost" to={`/projects/${item.project_id}/compare?candidate=${item.id}`}>{t('다른 런과 비교', 'Compare with another run')}</Link>
      </div>
    </header>

    <div className="grid gap-4 lg:grid-cols-2">
      <Card title={t('실행 근거', 'Run evidence')} subtitle={t('원본 입력, 해시, 실행 로그와 보존된 결과를 확인합니다.', 'Review source inputs, hashes, run logs, and preserved results.')}><RunEvidencePanel run={item} /></Card>
      <Card title={t('런 지표', 'Run metrics')} subtitle={t('툴 또는 가져온 보고서가 보존한 요약 값입니다.', 'Summary values preserved by the tool or imported report.')}>
        {metrics.length ? <dl className="grid gap-3 sm:grid-cols-2">{metrics.map(([name, value]) => <div key={name} className="min-w-0 rounded-lg bg-[var(--surface-2)] p-3"><dt className="text-xs text-[var(--text-secondary)] break-all">{name}</dt><dd className="mt-1 text-sm font-semibold break-all">{metric(value)}</dd></div>)}</dl> : <p className="text-sm">{t('보존된 런 지표가 없습니다.', 'No run metrics preserved.')}</p>}
        {Object.keys(item.metrics).length > 100 && <p className="mt-3 text-xs">{t('지표가 100개를 넘어 처음 100개만 표시합니다. 전체 값은 실행 근거 JSON에서 확인하세요.', 'There are more than 100 metrics; only the first 100 are shown. See the run evidence JSON for all values.')}</p>}
        {!item.result_locked && <div className="mt-4 space-y-2"><p className="text-xs text-[var(--text-secondary)]">{t('수동 런 상태 변경은 툴 실행이나 검증 근거를 만들지 않습니다.', 'Changing the run status manually does not create a tool run or verification evidence.')}</p><div className="flex gap-2"><button className="btn btn-ghost" disabled={!auth.can(item.project_id, 'editor') || update.isPending} onClick={() => update.mutate('passed')}>Pass</button><button className="btn btn-ghost" disabled={!auth.can(item.project_id, 'editor') || update.isPending} onClick={() => update.mutate('failed')}>Fail</button></div>{update.isError && <p role="alert">{update.error.message}</p>}</div>}
      </Card>
    </div>

    <Card title={t('위반 검토', 'Violation review')} subtitle={t('이 런의 위반을 필터링하고 처리 이력과 웨이버를 검토합니다.', 'Filter violations in this run and review their history and waivers.')}>
      {findings.isPending ? <p role="status">{t('위반 불러오는 중…', 'Loading violations…')}</p> : findings.isError ? <p role="alert">{t('위반을 불러오지 못했습니다', 'Could not load violations')}: {findings.error.message} <button className="btn btn-ghost" onClick={() => void findings.refetch()}>{t('다시 시도', 'Retry')}</button></p> : <div className="space-y-4">
        <dl aria-label={t('런 위반 요약', 'Run violation summary')} className="grid gap-3 grid-cols-2 lg:grid-cols-4">{([
          ['total', t('전체', 'Total'), findings.data.run_total], ['open', t('미해결', 'Open'), findings.data.status_counts.open], ['fixed', t('수정 완료', 'Fixed'), findings.data.status_counts.fixed], ['waived', t('웨이버', 'Waived'), findings.data.status_counts.waived],
        ] as const).map(([key, label, value]) => <div key={key} className="rounded-lg bg-[var(--surface-2)] p-3"><dt className="text-xs text-[var(--text-secondary)]">{label}</dt><dd className="text-lg font-semibold tabular-nums">{value}</dd></div>)}</dl>
        <form aria-label={t('런 위반 검색', 'Search run violations')} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" onSubmit={event => { event.preventDefault(); apply({ q: search.trim() }); }}>
          <label className="text-sm lg:col-span-2">{t('체크·위치·설명 검색', 'Search check, location, or description')}<input className="input mt-1 w-full" maxLength={200} value={search} onChange={event => setSearch(event.target.value)} /></label>
          <label className="text-sm">{t('상태', 'Status')}<select className="input mt-1 w-full" value={status} onChange={event => apply({ status: event.target.value })}><option value="">{t('모든 상태', 'All statuses')}</option>{Object.entries(STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label className="text-sm">{t('심각도', 'Severity')}<select className="input mt-1 w-full" value={severity} onChange={event => apply({ severity: event.target.value })}><option value="">{t('모든 심각도', 'All severities')}</option>{Object.entries(SEVERITY_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <div className="flex flex-wrap gap-2 lg:col-span-4"><button className="btn btn-primary">{t('검색', 'Search')}</button><button type="button" className="btn btn-ghost" onClick={() => { setSearch(''); setParams({}); }}>{t('초기화', 'Reset')}</button></div>
        </form>
        <p className="text-sm">{t('검색 결과', 'Results')} {findings.data.total} / {t('전체', 'total')} {findings.data.run_total}{t('건', '')}</p>
        {findings.data.items.length ? <ul className="space-y-3">{findings.data.items.map(violation => <li key={violation.id} className="rounded-lg border border-[var(--border)] p-3 space-y-3">
          <div className="flex flex-wrap items-center gap-2"><StatusBadge status={violation.severity === 'critical' ? 'critical' : violation.severity === 'error' ? 'serious' : violation.severity === 'warning' ? 'warning' : 'neutral'} label={SEVERITY_LABELS[violation.severity]} /><strong className="break-all">{violation.check_name}</strong><span className="text-xs break-all text-[var(--text-secondary)]">{violation.location ?? t('위치 미등록', 'No location')}</span></div>
          <ViolationActions violation={violation} projectId={item.project_id} onChange={refreshFindings} />
        </li>)}</ul> : <p className="text-sm">{t('조건에 맞는 위반이 없습니다.', 'No violations match these filters.')}</p>}
        <nav aria-label={t('위반 페이지', 'Violation pages')} className="flex flex-wrap items-center gap-3 text-sm"><button className="btn btn-ghost" disabled={offset === 0} onClick={() => apply({ offset: String(Math.max(0, offset - 25)) })}>{t('이전', 'Previous')}</button><span>{findings.data.total && offset < findings.data.total ? `${offset + 1}–${Math.min(offset + 25, findings.data.total)}` : '0'} / {findings.data.total}</span><button className="btn btn-ghost" disabled={offset + 25 >= findings.data.total} onClick={() => apply({ offset: String(offset + 25) })}>{t('다음', 'Next')}</button></nav>
      </div>}
    </Card>
  </div>;
}
