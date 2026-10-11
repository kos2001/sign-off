import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';

import { api, DOMAIN_LABELS, STAGE_LABELS } from '../api';
import { tr, useLanguage } from '../components/LanguageProvider';
import { Card, Field, StatTile, StatusBadge } from '../components/ui';

function tone(status: string) {
  return status === 'passed' ? 'good' : status === 'failed' ? 'critical' : 'warning';
}

function gateReason(reason: string | null) {
  if (!reason) return tr('게이트 준비', 'Gate ready');
  if (reason === 'no run for this stage') return tr('필수 결과 없음', 'Required result missing');
  const latest = reason.match(/^latest run status is '([^']+)'$/);
  if (latest) return tr(`최신 런 ${latest[1]}`, `Latest run ${latest[1]}`);
  const blocking = reason.match(/^(\d+) open blocking violation/);
  if (blocking) return tr(`미해결 차단 위반 ${blocking[1]}건`, `${blocking[1]} open blocking violation(s)`);
  const waiver = reason.match(/^(\d+) expired or out-of-scope waiver/);
  if (waiver) return tr(`만료·범위 불일치 웨이버 ${waiver[1]}건`, `${waiver[1]} expired or out-of-scope waiver(s)`);
  const known: Record<string, string> = {
    'Captured verification coverage required; manual status is not evidence': tr('검증 범위 근거 필요', 'Coverage evidence required'),
    'Imported path report does not establish full STA coverage': tr('STA 전체 범위 미확인', 'Full STA coverage not established'),
    'Executed path sample does not establish full STA coverage': tr('STA 전체 범위 미확인', 'Full STA coverage not established'),
    'Imported OpenLane flow metrics do not establish full sign-off coverage': tr('OpenLane 플로우 지표만으로는 전체 검증 범위 미확인', 'OpenLane flow metrics alone do not establish full coverage'),
    'Trusted STA evidence targets an outdated scenario plan': tr('오래된 MMMC 계획 근거', 'Evidence targets an outdated MMMC plan'),
  };
  return known[reason] ?? reason;
}

export default function RevisionCoverage() {
  const { t } = useLanguage();
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
      <Link className="text-sm underline text-[var(--text-secondary)]" to={`/projects/${projectId}`}>← {project.data?.name ?? t('프로젝트', 'Project')} · {t('프로젝트 개요', 'Project overview')}</Link>
      <h1 className="text-xl font-bold">{t('리비전 검증 매트릭스', 'Revision verification matrix')}</h1>
      <p className="text-sm text-[var(--text-muted)]">{t('한 설계 리비전에 각 스테이지의 필수 도메인 런이 존재하는지 확인합니다.', 'Checks whether each stage\'s required domain runs exist for one design revision.')}</p>
    </header>
    <Card title={t('설계 리비전', 'Design revision')} subtitle={t('저장된 리비전의 정확한 값으로 모든 스테이지와 도메인을 조회합니다.', 'Looks up every stage and domain by the exact stored revision value.')}>
      <form className="flex flex-wrap items-end gap-3" onSubmit={event => { event.preventDefault(); if (revision.trim()) setParams({ revision: revision.trim() }); }}>
        <Field label={t('정확한 설계 리비전', 'Exact design revision')}><input className="input min-w-64" list="coverage-revisions" maxLength={160} required value={revision} onChange={event => setRevision(event.target.value)} placeholder={t('예: release-2026.09', 'e.g. release-2026.09')} /><datalist id="coverage-revisions">{(revisions.data?.items ?? []).map(item => <option key={item.design_revision} value={item.design_revision}>{t(`${item.run_count}개 런`, `${item.run_count} runs`)}</option>)}</datalist></Field>
        <button className="btn btn-primary">{t('매트릭스 조회', 'Load matrix')}</button>
      </form>
      {revisions.data && <p className="mt-2 text-xs text-[var(--text-muted)]">{t(`기록된 리비전 ${revisions.data.total}개 · 미기록 런 ${revisions.data.unlabeled_runs}개`, `${revisions.data.total} recorded revisions · ${revisions.data.unlabeled_runs} runs without a revision`)}{revisions.data.total > revisions.data.items.length ? t(' · 최근 100개 자동완성', ' · Autocomplete shows the latest 100') : ''}</p>}
    </Card>
    {!selectedRevision && <Card><p className="text-sm">{t('설계 리비전을 선택하면 검증 결과 존재 여부를 조회합니다.', 'Select a design revision to check which verification results exist.')}</p></Card>}
    {selectedRevision && coverage.isPending && <p role="status">{t('리비전 매트릭스 불러오는 중…', 'Loading revision matrix…')}</p>}
    {selectedRevision && coverage.isError && <Card><p role="alert">{coverage.error.message}</p><button className="btn btn-ghost mt-3" onClick={() => void coverage.refetch()}>{t('다시 시도', 'Retry')}</button></Card>}
    {coverage.data && <>
      <div className="grid gap-3 sm:grid-cols-3">
        <StatTile label={t('이 리비전의 런', 'Runs in this revision')} value={coverage.data.total_runs} suffix={t('개', '')} />
        <StatTile label={t('필수 도메인 결과', 'Required domain results')} value={`${coverage.data.covered_required_cells} / ${coverage.data.required_cells}`} tone={coverage.data.covered_required_cells === coverage.data.required_cells ? 'good' : 'critical'} />
        <StatTile label={t('결과 누락', 'Missing results')} value={coverage.data.required_cells - coverage.data.covered_required_cells} tone={coverage.data.covered_required_cells === coverage.data.required_cells ? 'good' : 'critical'} />
      </div>
      {coverage.data.stages.map(stage => <Card key={stage.stage} title={STAGE_LABELS[stage.stage]} subtitle={t(`사인오프 계획 v${stage.plan_version} · 필수 결과 ${stage.covered_required_domains}/${stage.required_domains.length}`, `Sign-off plan v${stage.plan_version} · Required results ${stage.covered_required_domains}/${stage.required_domains.length}`)}>
        <div className="mb-3 flex flex-wrap items-center gap-2"><StatusBadge status={stage.ready ? 'good' : 'critical'} label={stage.ready ? t('이 리비전 게이트 통과 가능', 'Gate can pass for this revision') : t('이 리비전 게이트 차단', 'Gate blocked for this revision')} /><span className="text-xs text-[var(--text-muted)]">{t('리비전 일관성', 'Revision consistency')}: {stage.revision_status === 'consistent' ? t('일치', 'Consistent') : stage.revision_status === 'missing' ? t('필수 결과 누락', 'Required results missing') : t('불일치', 'Inconsistent')}</span></div>
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{stage.cells.map(cell => <li key={cell.domain} className="rounded-lg border border-[var(--border)] p-3 space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2"><strong>{DOMAIN_LABELS[cell.domain]}</strong><StatusBadge status={cell.required ? cell.gate_ready ? 'good' : 'critical' : cell.latest_run ? tone(cell.latest_run.status) : 'neutral'} label={cell.required ? gateReason(cell.gate_reason) : cell.latest_run ? t(`계획 외 · ${cell.latest_run.status}`, `Not in plan · ${cell.latest_run.status}`) : t('계획 외', 'Not in plan')} /></div>
          <p className="text-xs text-[var(--text-muted)]">{cell.required ? t('필수 도메인', 'Required domain') : t('계획 외 기록', 'Recorded outside plan')} · {t(`기록 ${cell.run_count}회`, `${cell.run_count} recorded`)}</p>
          {cell.latest_run && <><p className="text-sm break-words">{t('최신 런', 'Latest run')} #{cell.latest_run.id} · {cell.latest_run.tool} · {t('저장 상태', 'Stored status')} {cell.latest_run.status}</p><Link className="btn btn-ghost" to={`/runs/${cell.latest_run.id}`}>{t('런 워크스페이스', 'Run workspace')}</Link></>}
        </li>)}</ul>
      </Card>)}
      <Card><p className="text-xs text-[var(--text-muted)]">{t('리비전 게이트는 현재 프로젝트 계획과 해당 리비전의 최신 런만 사용해 커버리지 증명·위반·웨이버·MMMC 계획을 기존 게이트와 같은 규칙으로 평가합니다. 실제 승인·근거 동결은 프로젝트의 현재 최신 게이트에서 승인자가 별도로 수행하며 AI는 이 판정에 개입하지 않습니다.', 'The revision gate uses only the current project plan and that revision\'s latest runs, and evaluates coverage proof, violations, waivers and the MMMC plan with the same rules as the regular gate. Actual approval and evidence freezing are done separately by an approver on the project\'s current gate; AI takes no part in this decision.')}</p></Card>
    </>}
  </div>;
}
