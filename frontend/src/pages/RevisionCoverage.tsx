import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';

import { api, DOMAIN_LABELS, STAGE_LABELS } from '../api';
import { Card, Field, StatTile, StatusBadge } from '../components/ui';

function tone(status: string) {
  return status === 'passed' ? 'good' : status === 'failed' ? 'critical' : 'warning';
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
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{stage.cells.map(cell => <li key={cell.domain} className="rounded-lg border border-[var(--border)] p-3 space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2"><strong>{DOMAIN_LABELS[cell.domain]}</strong><StatusBadge status={cell.latest_run ? tone(cell.latest_run.status) : cell.required ? 'critical' : 'neutral'} label={cell.latest_run ? cell.latest_run.status : '결과 없음'} /></div>
          <p className="text-xs text-[var(--text-muted)]">{cell.required ? '필수 도메인' : '계획 외 기록'} · 기록 {cell.run_count}회</p>
          {cell.latest_run && <><p className="text-sm break-words">최신 런 #{cell.latest_run.id} · {cell.latest_run.tool}</p><Link className="btn btn-ghost" to={`/runs/${cell.latest_run.id}`}>런 워크스페이스</Link></>}
        </li>)}</ul>
      </Card>)}
      <Card><p className="text-xs text-[var(--text-muted)]">이 화면은 해당 리비전의 런 존재 여부와 저장 상태를 보여줍니다. 커버리지 증명·원본 무결성·위반·웨이버·MMMC 계획을 포함한 실제 통과 판단은 각 스테이지 게이트에서 수행하며 AI는 이 매트릭스 계산에 개입하지 않습니다.</p></Card>
    </>}
  </div>;
}
