import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useParams, useSearchParams } from 'react-router';

import { api, DOMAIN_LABELS, STAGE_LABELS, type RunStatus, type Severity, type ViolationStatus } from '../api';
import { useAuth } from '../components/AuthProvider';
import { EVIDENCE_LABELS, RunEvidencePanel } from '../components/RunEvidencePanel';
import { ViolationActions } from '../components/ViolationActions';
import { Card, StatusBadge } from '../components/ui';

const STATUS_LABELS: Record<ViolationStatus, string> = { open: '미해결', fixed: '수정 완료', waived: '웨이버 승인' };
const SEVERITY_LABELS: Record<Severity, string> = { info: '정보', warning: '경고', error: '오류', critical: '치명적' };
const RUN_STATUS: Record<RunStatus, string> = { running: '진행 중', incomplete: '검증 미완료', passed: '통과', failed: '실패' };

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
  if (!validRun) return <p role="alert">유효한 런 번호가 아닙니다. <Link className="underline" to="/">대시보드로</Link></p>;
  if (run.isPending) return <p role="status">런 워크스페이스 불러오는 중…</p>;
  if (run.isError) return <section className="space-y-3"><p role="alert">런을 불러오지 못했습니다: {run.error.message}</p><button className="btn btn-ghost" onClick={() => void run.refetch()}>다시 시도</button><Link className="btn btn-ghost" to="/">대시보드로</Link></section>;
  const item = run.data;
  const metrics = Object.entries(item.metrics).slice(0, 100);
  const refreshFindings = () => { void qc.invalidateQueries({ queryKey: ['run-violations-page', runId] }); };
  return <div className="space-y-5">
    <header className="space-y-3">
      <Link className="text-sm underline" to={`/projects/${item.project_id}`}>프로젝트로 돌아가기</Link>
      <div className="flex flex-wrap items-center gap-3"><h1 className="text-xl font-bold">사인오프 런 #{item.id}</h1><StatusBadge status={item.status === 'passed' ? 'good' : item.status === 'failed' ? 'critical' : 'warning'} label={RUN_STATUS[item.status]} /></div>
      <p className="text-sm">{DOMAIN_LABELS[item.domain]} · {STAGE_LABELS[item.stage]} · {item.tool}</p>
      <p className="text-xs text-[var(--text-secondary)]">생성 {new Date(item.created_at).toLocaleString()} · {EVIDENCE_LABELS[item.evidence_source]}</p>
      <div className="flex flex-wrap gap-2">
        {(item.evidence_source === 'opensta_report' || item.evidence_source === 'opensta_execution' || item.evidence_source === 'commercial_sta_report') && <Link className="btn btn-primary" to={`/runs/${item.id}/paths`}>타이밍 경로 탐색</Link>}
        {(item.evidence_source === 'klayout_report' || item.evidence_source === 'commercial_drc_report') && <Link className="btn btn-primary" to={`/runs/${item.id}/markers`}>DRC 마커 탐색</Link>}
        {item.evidence_source === 'commercial_emir_report' && <Link className="btn btn-primary" to={`/runs/${item.id}/power-integrity`}>EM/IR 핫스폿 탐색</Link>}
        {item.evidence_source === 'commercial_power_report' && <Link className="btn btn-primary" to={`/runs/${item.id}/power-breakdown`}>전력 계층 탐색</Link>}
        {item.evidence_source === 'commercial_thermal_report' && <Link className="btn btn-primary" to={`/runs/${item.id}/thermal-hotspots`}>열 핫스폿 탐색</Link>}
        {item.evidence_source === 'rtl_ladder' && <Link className="btn btn-primary" to={`/runs/${item.id}/structure`}>합성 구조 탐색</Link>}
        <Link className="btn btn-ghost" to={`/projects/${item.project_id}/compare?candidate=${item.id}`}>다른 런과 비교</Link>
      </div>
    </header>

    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="실행 근거" subtitle="원본 입력, 해시, 실행 로그와 보존된 결과를 확인합니다."><RunEvidencePanel run={item} /></Card>
      <Card title="런 지표" subtitle="툴 또는 가져온 보고서가 보존한 요약 값입니다.">
        {metrics.length ? <dl className="grid gap-3 sm:grid-cols-2">{metrics.map(([name, value]) => <div key={name} className="min-w-0 rounded-lg bg-[var(--surface-2)] p-3"><dt className="text-xs text-[var(--text-secondary)] break-all">{name}</dt><dd className="mt-1 text-sm font-semibold break-all">{metric(value)}</dd></div>)}</dl> : <p className="text-sm">보존된 런 지표가 없습니다.</p>}
        {Object.keys(item.metrics).length > 100 && <p className="mt-3 text-xs">지표가 100개를 넘어 처음 100개만 표시합니다. 전체 값은 실행 근거 JSON에서 확인하세요.</p>}
        {!item.result_locked && <div className="mt-4 space-y-2"><p className="text-xs text-[var(--text-secondary)]">수동 런 상태 변경은 툴 실행이나 검증 근거를 만들지 않습니다.</p><div className="flex gap-2"><button className="btn btn-ghost" disabled={!auth.can(item.project_id, 'editor') || update.isPending} onClick={() => update.mutate('passed')}>Pass</button><button className="btn btn-ghost" disabled={!auth.can(item.project_id, 'editor') || update.isPending} onClick={() => update.mutate('failed')}>Fail</button></div>{update.isError && <p role="alert">{update.error.message}</p>}</div>}
      </Card>
    </div>

    <Card title="위반 검토" subtitle="이 런의 위반을 필터링하고 처리 이력과 웨이버를 검토합니다.">
      {findings.isPending ? <p role="status">위반 불러오는 중…</p> : findings.isError ? <p role="alert">위반을 불러오지 못했습니다: {findings.error.message} <button className="btn btn-ghost" onClick={() => void findings.refetch()}>다시 시도</button></p> : <div className="space-y-4">
        <dl aria-label="런 위반 요약" className="grid gap-3 grid-cols-2 lg:grid-cols-4">{([
          ['전체', findings.data.run_total], ['미해결', findings.data.status_counts.open], ['수정 완료', findings.data.status_counts.fixed], ['웨이버', findings.data.status_counts.waived],
        ] as const).map(([label, value]) => <div key={label} className="rounded-lg bg-[var(--surface-2)] p-3"><dt className="text-xs text-[var(--text-secondary)]">{label}</dt><dd className="text-lg font-semibold tabular-nums">{value}</dd></div>)}</dl>
        <form aria-label="런 위반 검색" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" onSubmit={event => { event.preventDefault(); apply({ q: search.trim() }); }}>
          <label className="text-sm lg:col-span-2">체크·위치·설명 검색<input className="input mt-1 w-full" maxLength={200} value={search} onChange={event => setSearch(event.target.value)} /></label>
          <label className="text-sm">상태<select className="input mt-1 w-full" value={status} onChange={event => apply({ status: event.target.value })}><option value="">모든 상태</option>{Object.entries(STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label className="text-sm">심각도<select className="input mt-1 w-full" value={severity} onChange={event => apply({ severity: event.target.value })}><option value="">모든 심각도</option>{Object.entries(SEVERITY_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <div className="flex flex-wrap gap-2 lg:col-span-4"><button className="btn btn-primary">검색</button><button type="button" className="btn btn-ghost" onClick={() => { setSearch(''); setParams({}); }}>초기화</button></div>
        </form>
        <p className="text-sm">검색 결과 {findings.data.total} / 전체 {findings.data.run_total}건</p>
        {findings.data.items.length ? <ul className="space-y-3">{findings.data.items.map(violation => <li key={violation.id} className="rounded-lg border border-[var(--border)] p-3 space-y-3">
          <div className="flex flex-wrap items-center gap-2"><StatusBadge status={violation.severity === 'critical' ? 'critical' : violation.severity === 'error' ? 'serious' : violation.severity === 'warning' ? 'warning' : 'neutral'} label={SEVERITY_LABELS[violation.severity]} /><strong className="break-all">{violation.check_name}</strong><span className="text-xs break-all text-[var(--text-secondary)]">{violation.location ?? '위치 미등록'}</span></div>
          <ViolationActions violation={violation} projectId={item.project_id} onChange={refreshFindings} />
        </li>)}</ul> : <p className="text-sm">조건에 맞는 위반이 없습니다.</p>}
        <nav aria-label="위반 페이지" className="flex flex-wrap items-center gap-3 text-sm"><button className="btn btn-ghost" disabled={offset === 0} onClick={() => apply({ offset: String(Math.max(0, offset - 25)) })}>이전</button><span>{findings.data.total && offset < findings.data.total ? `${offset + 1}–${Math.min(offset + 25, findings.data.total)}` : '0'} / {findings.data.total}</span><button className="btn btn-ghost" disabled={offset + 25 >= findings.data.total} onClick={() => apply({ offset: String(offset + 25) })}>다음</button></nav>
      </div>}
    </Card>
  </div>;
}
