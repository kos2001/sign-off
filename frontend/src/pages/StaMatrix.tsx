import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';

import { api, STAGES, STAGE_LABELS, type Stage } from '../api';
import { Card, Field, StatTile, StatusBadge } from '../components/ui';
import { useAuth } from '../components/AuthProvider';

function metric(metrics: Record<string, unknown>, name: string) {
  const value = metrics[name];
  return typeof value === 'number' && Number.isFinite(value) ? value : '—';
}

function slack(metrics: Record<string, unknown>) {
  const value = metric(metrics, 'worst_reported_slack_ps');
  return typeof value === 'number' ? `${value} ps` : value;
}

function tone(status: string) {
  return status === 'passed' ? 'good' : status === 'failed' ? 'critical' : 'warning';
}

const coverageLabels = {
  recorded: '실행됨', missing: '실행 누락', parasitics_missing: 'SPEF 누락', unplanned: '계획 외',
};

export default function StaMatrix() {
  const { id } = useParams();
  const projectId = Number(id);
  const auth = useAuth();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const initialStage = STAGES.includes(params.get('stage') as Stage) ? params.get('stage') as Stage : 'routing';
  const [stage, setStage] = useState<Stage>(initialStage);
  const [revision, setRevision] = useState(params.get('revision') ?? '');
  const selectedRevision = params.get('revision')?.trim() ?? '';
  const selectedStage = STAGES.includes(params.get('stage') as Stage) ? params.get('stage') as Stage : stage;
  const project = useQuery({ queryKey: ['project', projectId], queryFn: () => api.getProject(projectId) });
  const definitions = useQuery({
    queryKey: ['sta-scenarios', projectId, selectedStage],
    queryFn: () => api.staScenarioPlan(projectId, selectedStage),
    enabled: Number.isSafeInteger(projectId) && projectId > 0,
  });
  const planHistory = useQuery({
    queryKey: ['sta-scenario-plan-history', projectId, selectedStage],
    queryFn: () => api.staScenarioPlanHistory(projectId, selectedStage),
    enabled: Number.isSafeInteger(projectId) && projectId > 0,
  });
  const [draft, setDraft] = useState<{ name: string; require_spef: boolean }[]>([]);
  const [planReason, setPlanReason] = useState('');
  useEffect(() => {
    if (definitions.data) {
      setDraft(definitions.data.scenarios.map(({ name, require_spef }) => ({ name, require_spef })));
      setPlanReason('');
    }
  }, [definitions.data]);
  const saveDefinitions = useMutation({
    mutationFn: () => api.replaceStaScenarios(projectId, selectedStage,
      { scenarios: draft.map(item => ({ ...item, name: item.name.trim() })).filter(item => item.name),
        expected_version: definitions.data!.version, reason: planReason.trim() }),
    onSuccess: async () => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['sta-scenarios', projectId, selectedStage] }),
        qc.invalidateQueries({ queryKey: ['sta-scenario-plan-history', projectId, selectedStage] }),
        qc.invalidateQueries({ queryKey: ['sta-matrix', projectId, selectedStage] }),
      ]);
    },
  });
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
    <Card title={`${STAGE_LABELS[selectedStage]} 기대 시나리오`} subtitle="승인자가 필수 코너·모드와 post-route SPEF 요구를 버전형 계획으로 관리합니다.">
      {definitions.isPending ? <p role="status">시나리오 설정 불러오는 중…</p> : definitions.isError ? <p role="alert">{definitions.error.message}</p> : <div className="space-y-3">
        <p className="text-xs text-[var(--text-muted)]">계획 v{definitions.data.version} · {definitions.data.source === 'versioned' ? `${definitions.data.updated_by} · ${definitions.data.reason}` : '기존 정의 · 다음 저장부터 변경 이력 보존'}</p>
        {draft.map((item, index) => <div className="flex flex-wrap items-center gap-3" key={index}>
          <input aria-label={`시나리오 ${index + 1} 이름`} className="input min-w-64 flex-1" maxLength={160} disabled={!auth.can(projectId, 'approver')} value={item.name} onChange={event => setDraft(rows => rows.map((row, i) => i === index ? { ...row, name: event.target.value } : row))} placeholder="예: slow-setup-functional" />
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" disabled={!auth.can(projectId, 'approver')} checked={item.require_spef} onChange={event => setDraft(rows => rows.map((row, i) => i === index ? { ...row, require_spef: event.target.checked } : row))} />SPEF 필수</label>
          {auth.can(projectId, 'approver') && <button className="btn btn-ghost" onClick={() => setDraft(rows => rows.filter((_, i) => i !== index))}>삭제</button>}
        </div>)}
        {draft.length === 0 && <p className="text-sm text-[var(--text-muted)]">정의된 기대 시나리오가 없습니다. 이 상태에서는 실행 기록을 계획 외로 표시합니다.</p>}
        {auth.can(projectId, 'approver') && <><Field label="계획 변경 사유"><textarea className="input w-full" rows={2} maxLength={4000} value={planReason} onChange={event => setPlanReason(event.target.value)} /></Field><div className="flex flex-wrap gap-2"><button className="btn btn-ghost" disabled={draft.length >= 100} onClick={() => setDraft(rows => [...rows, { name: '', require_spef: false }])}>시나리오 추가</button><button className="btn btn-primary" disabled={saveDefinitions.isPending || !draft.length || !planReason.trim() || draft.some(item => !item.name.trim())} onClick={() => saveDefinitions.mutate()}>{saveDefinitions.isPending ? '저장 중…' : `계획 v${definitions.data.version + 1} 저장`}</button></div></>}
        {saveDefinitions.isError && <p role="alert">{saveDefinitions.error.message}</p>}
        {saveDefinitions.isSuccess && <p role="status">기대 시나리오 세트를 저장했습니다.</p>}
        {planHistory.data?.items.length ? <details className="rounded-lg border border-[var(--border)] p-3">
          <summary className="cursor-pointer text-sm font-semibold">최근 계획 변경 이력</summary>
          <ol className="mt-3 space-y-2 text-sm">{planHistory.data.items.map(item => <li className="hairline-b pb-2" key={item.version}>
            <span className="font-semibold">v{item.version}</span> · {item.updated_by} · {item.scenarios.length}개 시나리오
            <span className="block text-xs text-[var(--text-muted)]">{item.reason} · {item.created_at ? new Date(item.created_at).toLocaleString('ko-KR') : '시각 미상'}</span>
          </li>)}</ol>
          {planHistory.data.next_before_id && <p className="mt-2 text-xs text-[var(--text-muted)]">이전 이력은 API 커서로 조회할 수 있습니다.</p>}
        </details> : null}
      </div>}
    </Card>
    {!selectedRevision && <Card><p className="text-sm">설계 리비전을 입력하면 기록된 시나리오를 조회합니다.</p></Card>}
    {selectedRevision && matrix.isPending && <p role="status">시나리오 매트릭스 불러오는 중…</p>}
    {selectedRevision && matrix.isError && <Card><p role="alert">{matrix.error.message}</p><button className="btn btn-ghost mt-3" onClick={() => matrix.refetch()}>다시 시도</button></Card>}
    {matrix.data && <>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <StatTile label="기대 / 실행" value={`${matrix.data.summary.expected_scenario_count} / ${matrix.data.summary.recorded_expected_scenarios}`} tone={matrix.data.summary.scenario_coverage_complete ? 'good' : undefined} />
        <StatTile label="실행 누락" value={matrix.data.summary.missing_scenarios} tone={matrix.data.summary.missing_scenarios ? 'critical' : 'good'} />
        <StatTile label="SPEF 요구 누락" value={matrix.data.summary.parasitic_requirement_gaps} tone={matrix.data.summary.parasitic_requirement_gaps ? 'critical' : 'good'} />
        <StatTile label="실패" value={matrix.data.summary.failed_scenarios} tone={matrix.data.summary.failed_scenarios ? 'critical' : 'good'} />
        <StatTile label="최악 보고 슬랙" value={matrix.data.summary.worst_reported_slack_ps ?? '—'} suffix={matrix.data.summary.worst_reported_slack_ps === null ? undefined : 'ps'} />
      </div>
      <Card title={`${STAGE_LABELS[matrix.data.stage]} · ${matrix.data.design_revision}`} subtitle="표시 값은 각 시나리오의 최신 서버 실행 결과입니다.">
        <div className="overflow-x-auto"><table className="w-full text-left text-sm">
          <thead><tr className="hairline-b"><th className="px-2 py-3">시나리오</th><th className="px-2 py-3">커버리지</th><th className="px-2 py-3">상태</th><th className="px-2 py-3">WNS</th><th className="px-2 py-3">위반 / 보고 / 미제약</th><th className="px-2 py-3">기생 성분</th><th className="px-2 py-3">실행 근거</th></tr></thead>
          <tbody>{matrix.data.scenarios.map(row => <tr className="hairline-b" key={row.scenario}>
            <td className="px-2 py-3 font-semibold break-all">{row.scenario}<p className="mt-1 text-xs font-normal text-[var(--text-muted)]">기록 {row.run_count}회</p></td>
            <td className="px-2 py-3"><StatusBadge status={row.coverage_state === 'recorded' ? 'good' : row.coverage_state === 'unplanned' ? 'neutral' : 'critical'} label={coverageLabels[row.coverage_state]} /></td>
            <td className="px-2 py-3">{row.status ? <StatusBadge status={tone(row.status)} label={row.status} /> : '—'}</td>
            <td className="px-2 py-3 whitespace-nowrap">{slack(row.metrics)}</td>
            <td className="px-2 py-3 whitespace-nowrap">{metric(row.metrics, 'violating_paths')} / {metric(row.metrics, 'reported_paths')} / {metric(row.metrics, 'unconstrained_paths')}</td>
            <td className="px-2 py-3">{row.parasitics === 'spef' ? 'SPEF' : row.parasitics === 'none' ? '미적용' : '—'}{row.require_spef && <span className="block text-xs text-[var(--text-muted)]">필수</span>}</td>
            <td className="px-2 py-3">{row.run_id ? <><Link className="underline" to={`/runs/${row.run_id}`}>run #{row.run_id}</Link><span className="block text-xs text-[var(--text-muted)]">{row.tool_version}</span><Link className="text-xs underline" to={`/runs/${row.run_id}/paths`}>경로 표본</Link></> : '—'}</td>
          </tr>)}</tbody>
        </table></div>
        {matrix.data.scenarios.length === 0 && <p className="py-4 text-sm">이 범위에 서버 OpenSTA 실행 기록이 없습니다.</p>}
      </Card>
      <Card title="범위와 에이전트 개입">
        <p className="text-sm">이 화면과 집계 API에는 AI 에이전트가 개입하지 않습니다. 저장된 OpenSTA 실행 근거를 읽기 전용으로 집계합니다.</p>
        <p className="mt-2 text-xs text-[var(--text-muted)]">기대 세트와 최신 실행을 비교해 누락을 표시합니다. 타이밍 수치는 보고된 경로 표본만 포함하므로 전체 사인오프 커버리지는 별도로 확인해야 합니다.</p>
      </Card>
    </>}
  </div>;
}
