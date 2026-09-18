import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';

import { api, DOMAIN_LABELS, STAGE_LABELS } from '../api';
import { Card, Field, StatTile, StatusBadge } from '../components/ui';

function tone(status: string) {
  return status === 'passed' ? 'good' : status === 'failed' ? 'critical' : 'warning';
}

function gateReason(reason: string | null) {
  if (!reason) return '게이트 준비';
  if (reason === 'no run for this stage') return '필수 결과 없음';
  const latest = reason.match(/^latest run status is '([^']+)'$/);
  if (latest) return `최신 런 ${latest[1]}`;
  const blocking = reason.match(/^(\d+) open blocking violation/);
  if (blocking) return `미해결 차단 위반 ${blocking[1]}건`;
  const waiver = reason.match(/^(\d+) expired or out-of-scope waiver/);
  if (waiver) return `만료·범위 불일치 웨이버 ${waiver[1]}건`;
  const known: Record<string, string> = {
    'Captured verification coverage required; manual status is not evidence': '검증 범위 근거 필요',
    'Imported path report does not establish full STA coverage': 'STA 전체 범위 미확인',
    'Executed path sample does not establish full STA coverage': 'STA 전체 범위 미확인',
    'Trusted STA evidence targets an outdated scenario plan': '오래된 MMMC 계획 근거',
  };
  return known[reason] ?? reason;
}

export default function RevisionCoverage() {
  const projectId = Number(useParams().id);
  const [params, setParams] = useSearchParams();
  const selectedRevision = params.get('revision')?.trim() ?? '';
  const [revision, setRevision] = useState(selectedRevision);
  useEffect(() => setRevision(selectedRevision), [selectedRevision]);
  const project = useQuery({ queryKey: ['project', projectId], queryFn: () => api.getProject(projectId) });
  const revisions = useQuery({ queryKey: ['run-revisions', projectId], queryFn: () => api.runRevisions(projectId) });
  const coverage = useQuery({
    queryKey: ['revision-coverage', projectId, selectedRevision],
    queryFn: () => api.revisionCoverage(projectId, selectedRevision),
    enabled: selectedRevision.length > 0,
  });

  return <div className="space-y-5">
    <header className="space-y-2">
      <Link className="text-sm underline text-[var(--text-secondary)]" to={`/projects/${projectId}`}>← {project.data?.name ?? '프로젝트'} · 프로젝트 개요</Link>
      <h1 className="text-xl font-bold">리비전 검증 매트릭스</h1>
      <p className="text-sm text-[var(--text-muted)]">한 설계 리비전에 각 스테이지의 필수 도메인 런이 존재하는지 확인합니다.</p>
    </header>
    <Card title="설계 리비전" subtitle="저장된 리비전의 정확한 값으로 모든 스테이지와 도메인을 조회합니다.">
      <form className="flex flex-wrap items-end gap-3" onSubmit={event => { event.preventDefault(); if (revision.trim()) setParams({ revision: revision.trim() }); }}>
        <Field label="정확한 설계 리비전"><input className="input min-w-64" list="coverage-revisions" maxLength={160} required value={revision} onChange={event => setRevision(event.target.value)} placeholder="예: release-2026.09" /><datalist id="coverage-revisions">{(revisions.data?.items ?? []).map(item => <option key={item.design_revision} value={item.design_revision}>{item.run_count}개 런</option>)}</datalist></Field>
        <button className="btn btn-primary">매트릭스 조회</button>
      </form>
      {revisions.data && <p className="mt-2 text-xs text-[var(--text-muted)]">기록된 리비전 {revisions.data.total}개 · 미기록 런 {revisions.data.unlabeled_runs}개{revisions.data.total > revisions.data.items.length ? ' · 최근 100개 자동완성' : ''}</p>}
    </Card>
    {!selectedRevision && <Card><p className="text-sm">설계 리비전을 선택하면 검증 결과 존재 여부를 조회합니다.</p></Card>}
    {selectedRevision && coverage.isPending && <p role="status">리비전 매트릭스 불러오는 중…</p>}
    {selectedRevision && coverage.isError && <Card><p role="alert">{coverage.error.message}</p><button className="btn btn-ghost mt-3" onClick={() => void coverage.refetch()}>다시 시도</button></Card>}
    {coverage.data && <>
      <div className="grid gap-3 sm:grid-cols-3">
        <StatTile label="이 리비전의 런" value={coverage.data.total_runs} suffix="개" />
        <StatTile label="필수 도메인 결과" value={`${coverage.data.covered_required_cells} / ${coverage.data.required_cells}`} tone={coverage.data.covered_required_cells === coverage.data.required_cells ? 'good' : 'critical'} />
        <StatTile label="결과 누락" value={coverage.data.required_cells - coverage.data.covered_required_cells} tone={coverage.data.covered_required_cells === coverage.data.required_cells ? 'good' : 'critical'} />
      </div>
      {coverage.data.stages.map(stage => <Card key={stage.stage} title={STAGE_LABELS[stage.stage]} subtitle={`사인오프 계획 v${stage.plan_version} · 필수 결과 ${stage.covered_required_domains}/${stage.required_domains.length}`}>
        <div className="mb-3 flex flex-wrap items-center gap-2"><StatusBadge status={stage.ready ? 'good' : 'critical'} label={stage.ready ? '이 리비전 게이트 통과 가능' : '이 리비전 게이트 차단'} /><span className="text-xs text-[var(--text-muted)]">리비전 일관성: {stage.revision_status === 'consistent' ? '일치' : stage.revision_status === 'missing' ? '필수 결과 누락' : '불일치'}</span></div>
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{stage.cells.map(cell => <li key={cell.domain} className="rounded-lg border border-[var(--border)] p-3 space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2"><strong>{DOMAIN_LABELS[cell.domain]}</strong><StatusBadge status={cell.required ? cell.gate_ready ? 'good' : 'critical' : cell.latest_run ? tone(cell.latest_run.status) : 'neutral'} label={cell.required ? gateReason(cell.gate_reason) : cell.latest_run ? `계획 외 · ${cell.latest_run.status}` : '계획 외'} /></div>
          <p className="text-xs text-[var(--text-muted)]">{cell.required ? '필수 도메인' : '계획 외 기록'} · 기록 {cell.run_count}회</p>
          {cell.latest_run && <><p className="text-sm break-words">최신 런 #{cell.latest_run.id} · {cell.latest_run.tool} · 저장 상태 {cell.latest_run.status}</p><Link className="btn btn-ghost" to={`/runs/${cell.latest_run.id}`}>런 워크스페이스</Link></>}
        </li>)}</ul>
      </Card>)}
      <Card><p className="text-xs text-[var(--text-muted)]">리비전 게이트는 현재 프로젝트 계획과 해당 리비전의 최신 런만 사용해 커버리지 증명·위반·웨이버·MMMC 계획을 기존 게이트와 같은 규칙으로 평가합니다. 실제 승인·근거 동결은 프로젝트의 현재 최신 게이트에서 승인자가 별도로 수행하며 AI는 이 판정에 개입하지 않습니다.</p></Card>
    </>}
  </div>;
}
