import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';

import { api, STAGES, STAGE_LABELS, type Stage } from '../api';
import { Card, Field, StatTile, StatusBadge } from '../components/ui';

function metric(metrics: Record<string, unknown>, name: string) {
  const value = metrics[name];
  return typeof value === 'number' && Number.isFinite(value) ? value : '—';
}

function tone(status: string) {
  return status === 'passed' ? 'good' : status === 'failed' ? 'critical' : 'warning';
}

export default function StaMatrix() {
  const { id } = useParams();
  const projectId = Number(id);
  const [params, setParams] = useSearchParams();
  const initialStage = STAGES.includes(params.get('stage') as Stage) ? params.get('stage') as Stage : 'routing';
  const [stage, setStage] = useState<Stage>(initialStage);
  const [revision, setRevision] = useState(params.get('revision') ?? '');
  const selectedRevision = params.get('revision')?.trim() ?? '';
  const selectedStage = STAGES.includes(params.get('stage') as Stage) ? params.get('stage') as Stage : stage;
  const project = useQuery({ queryKey: ['project', projectId], queryFn: () => api.getProject(projectId) });
  const matrix = useQuery({
    queryKey: ['sta-matrix', projectId, selectedStage, selectedRevision],
    queryFn: () => api.staMatrix(projectId, selectedStage, selectedRevision),
    enabled: Number.isSafeInteger(projectId) && projectId > 0 && selectedRevision.length > 0,
  });
  function apply(event: React.FormEvent) {
    event.preventDefault();
    if (revision.trim()) setParams({ stage, revision: revision.trim() });
  }

  return <div className="space-y-5">
    <header className="space-y-2">
      <Link className="text-sm underline text-[var(--text-secondary)]" to={`/projects/${projectId}`}>← {project.data?.name ?? '프로젝트'} · 프로젝트 개요</Link>
      <h1 className="text-xl font-bold">STA 시나리오 매트릭스</h1>
      <p className="text-sm text-[var(--text-muted)]">같은 설계 리비전과 단계에서 서버가 실행한 OpenSTA 시나리오의 최신 결과를 비교합니다.</p>
    </header>
    <Card title="조회 범위" subtitle="시나리오 이름별 최신 실행을 표시하며, 이전 실행 수를 함께 보존합니다.">
      <form className="flex flex-wrap items-end gap-3" onSubmit={apply}>
        <Field label="스테이지"><select className="input" value={stage} onChange={event => setStage(event.target.value as Stage)}>{STAGES.map(value => <option key={value} value={value}>{STAGE_LABELS[value]}</option>)}</select></Field>
        <Field label="설계 리비전"><input className="input min-w-64" maxLength={160} required value={revision} onChange={event => setRevision(event.target.value)} placeholder="예: release-2026.09" /></Field>
        <button className="btn btn-primary">매트릭스 조회</button>
      </form>
    </Card>
    {!selectedRevision && <Card><p className="text-sm">설계 리비전을 입력하면 기록된 시나리오를 조회합니다.</p></Card>}
    {selectedRevision && matrix.isPending && <p role="status">시나리오 매트릭스 불러오는 중…</p>}
    {selectedRevision && matrix.isError && <Card><p role="alert">{matrix.error.message}</p><button className="btn btn-ghost mt-3" onClick={() => matrix.refetch()}>다시 시도</button></Card>}
    {matrix.data && <>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <StatTile label="기록된 시나리오" value={matrix.data.summary.scenario_count} />
        <StatTile label="실패" value={matrix.data.summary.failed_scenarios} tone={matrix.data.summary.failed_scenarios ? 'critical' : 'good'} />
        <StatTile label="미완료" value={matrix.data.summary.incomplete_scenarios} />
        <StatTile label="위반 경로 표본" value={matrix.data.summary.total_violating_paths} />
        <StatTile label="최악 보고 슬랙" value={matrix.data.summary.worst_reported_slack_ps ?? '—'} suffix={matrix.data.summary.worst_reported_slack_ps === null ? undefined : 'ps'} />
      </div>
      <Card title={`${STAGE_LABELS[matrix.data.stage]} · ${matrix.data.design_revision}`} subtitle="표시 값은 각 시나리오의 최신 서버 실행 결과입니다.">
        <div className="overflow-x-auto"><table className="w-full text-left text-sm">
          <thead><tr className="hairline-b"><th className="px-2 py-3">시나리오</th><th className="px-2 py-3">상태</th><th className="px-2 py-3">WNS</th><th className="px-2 py-3">위반 / 보고 / 미제약</th><th className="px-2 py-3">기생 성분</th><th className="px-2 py-3">실행 근거</th></tr></thead>
          <tbody>{matrix.data.scenarios.map(row => <tr className="hairline-b" key={row.scenario}>
            <td className="px-2 py-3 font-semibold break-all">{row.scenario}<p className="mt-1 text-xs font-normal text-[var(--text-muted)]">기록 {row.run_count}회</p></td>
            <td className="px-2 py-3"><StatusBadge status={tone(row.status)} label={row.status} /></td>
            <td className="px-2 py-3 whitespace-nowrap">{metric(row.metrics, 'worst_reported_slack_ps')} ps</td>
            <td className="px-2 py-3 whitespace-nowrap">{metric(row.metrics, 'violating_paths')} / {metric(row.metrics, 'reported_paths')} / {metric(row.metrics, 'unconstrained_paths')}</td>
            <td className="px-2 py-3">{row.parasitics === 'spef' ? 'SPEF' : '미적용'}</td>
            <td className="px-2 py-3"><Link className="underline" to={`/runs/${row.run_id}`}>run #{row.run_id}</Link><span className="block text-xs text-[var(--text-muted)]">{row.tool_version}</span><Link className="text-xs underline" to={`/runs/${row.run_id}/paths`}>경로 표본</Link></td>
          </tr>)}</tbody>
        </table></div>
        {matrix.data.scenarios.length === 0 && <p className="py-4 text-sm">이 범위에 서버 OpenSTA 실행 기록이 없습니다.</p>}
      </Card>
      <Card title="범위와 에이전트 개입">
        <p className="text-sm">이 화면과 집계 API에는 AI 에이전트가 개입하지 않습니다. 저장된 OpenSTA 실행 근거를 읽기 전용으로 집계합니다.</p>
        <p className="mt-2 text-xs text-[var(--text-muted)]">최신 실행 / 기록된 시나리오 / 보고된 경로 표본만 포함합니다. 예상 코너·모드가 모두 실행되었는지와 전체 사인오프 커버리지는 별도로 확인해야 합니다.</p>
      </Card>
    </>}
  </div>;
}
