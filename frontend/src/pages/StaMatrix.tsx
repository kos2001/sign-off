import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';

import { api, STAGES, STAGE_LABELS, type Stage } from '../api';
import { Card, Field, StatTile, StatusBadge } from '../components/ui';
import { useAuth } from '../components/AuthProvider';
import { formatDateTime, tr, useLanguage } from '../components/LanguageProvider';

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

function coverageLabels() {
  return {
    recorded: tr('실행됨', 'Run'), missing: tr('실행 누락', 'Run missing'), parasitics_missing: tr('SPEF 누락', 'SPEF missing'), unplanned: tr('계획 외', 'Unplanned'),
  };
}

export default function StaMatrix() {
  const { t } = useLanguage();
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
      <Link className="text-sm underline text-[var(--text-secondary)]" to={`/projects/${projectId}`}>← {project.data?.name ?? t('프로젝트', 'Project')} · {t('프로젝트 개요', 'Project overview')}</Link>
      <h1 className="text-xl font-bold">{t('STA 시나리오 매트릭스', 'STA scenario matrix')}</h1>
      <p className="text-sm text-[var(--text-muted)]">{t('같은 설계 리비전과 단계에서 서버가 실행한 OpenSTA 시나리오의 최신 결과를 비교합니다.', 'Compares the latest results of OpenSTA scenarios run by the server for the same design revision and stage.')}</p>
    </header>
    <Card title={t('조회 범위', 'Scope')} subtitle={t('시나리오 이름별 최신 실행을 표시하며, 이전 실행 수를 함께 보존합니다.', 'Shows the latest run for each scenario name and keeps the count of earlier runs.')}>
      <form className="flex flex-wrap items-end gap-3" onSubmit={apply}>
        <Field label={t('스테이지', 'Stage')}><select className="input" value={stage} onChange={event => setStage(event.target.value as Stage)}>{STAGES.map(value => <option key={value} value={value}>{STAGE_LABELS[value]}</option>)}</select></Field>
        <Field label={t('설계 리비전', 'Design revision')}><input className="input min-w-64" maxLength={160} required value={revision} onChange={event => setRevision(event.target.value)} placeholder={t('예: release-2026.09', 'e.g. release-2026.09')} /></Field>
        <button className="btn btn-primary">{t('매트릭스 조회', 'Load matrix')}</button>
      </form>
    </Card>
    <Card title={t(`${STAGE_LABELS[selectedStage]} 기대 시나리오`, `${STAGE_LABELS[selectedStage]} expected scenarios`)} subtitle={t('승인자가 필수 코너·모드와 post-route SPEF 요구를 버전형 계획으로 관리합니다.', 'Approvers manage required corners, modes and post-route SPEF requirements as a versioned plan.')}>
      {definitions.isPending ? <p role="status">{t('시나리오 설정 불러오는 중…', 'Loading scenario settings…')}</p> : definitions.isError ? <p role="alert">{definitions.error.message}</p> : <div className="space-y-3">
        <p className="text-xs text-[var(--text-muted)]">{t('계획', 'Plan')} v{definitions.data.version} · {definitions.data.source === 'versioned' ? `${definitions.data.updated_by} · ${definitions.data.reason}` : t('기존 정의 · 다음 저장부터 변경 이력 보존', 'Legacy definition · change history is kept from the next save')}</p>
        {draft.map((item, index) => <div className="flex flex-wrap items-center gap-3" key={index}>
          <input aria-label={t(`시나리오 ${index + 1} 이름`, `Scenario ${index + 1} name`)} className="input min-w-64 flex-1" maxLength={160} disabled={!auth.can(projectId, 'approver')} value={item.name} onChange={event => setDraft(rows => rows.map((row, i) => i === index ? { ...row, name: event.target.value } : row))} placeholder={t('예: slow-setup-functional', 'e.g. slow-setup-functional')} />
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" disabled={!auth.can(projectId, 'approver')} checked={item.require_spef} onChange={event => setDraft(rows => rows.map((row, i) => i === index ? { ...row, require_spef: event.target.checked } : row))} />{t('SPEF 필수', 'SPEF required')}</label>
          {auth.can(projectId, 'approver') && <button className="btn btn-ghost" onClick={() => setDraft(rows => rows.filter((_, i) => i !== index))}>{t('삭제', 'Delete')}</button>}
        </div>)}
        {draft.length === 0 && <p className="text-sm text-[var(--text-muted)]">{t('정의된 기대 시나리오가 없습니다. 이 상태에서는 실행 기록을 계획 외로 표시합니다.', 'No expected scenarios are defined. Until they are, recorded runs are shown as unplanned.')}</p>}
        {auth.can(projectId, 'approver') && <><Field label={t('계획 변경 사유', 'Reason for plan change')}><textarea className="input w-full" rows={2} maxLength={4000} value={planReason} onChange={event => setPlanReason(event.target.value)} /></Field><div className="flex flex-wrap gap-2"><button className="btn btn-ghost" disabled={draft.length >= 100} onClick={() => setDraft(rows => [...rows, { name: '', require_spef: false }])}>{t('시나리오 추가', 'Add scenario')}</button><button className="btn btn-primary" disabled={saveDefinitions.isPending || !draft.length || !planReason.trim() || draft.some(item => !item.name.trim())} onClick={() => saveDefinitions.mutate()}>{saveDefinitions.isPending ? t('저장 중…', 'Saving…') : t(`계획 v${definitions.data.version + 1} 저장`, `Save plan v${definitions.data.version + 1}`)}</button></div></>}
        {saveDefinitions.isError && <p role="alert">{saveDefinitions.error.message}</p>}
        {saveDefinitions.isSuccess && <p role="status">{t('기대 시나리오 세트를 저장했습니다.', 'Expected scenario set saved.')}</p>}
        {planHistory.data?.items.length ? <details className="rounded-lg border border-[var(--border)] p-3">
          <summary className="cursor-pointer text-sm font-semibold">{t('최근 계획 변경 이력', 'Recent plan changes')}</summary>
          <ol className="mt-3 space-y-2 text-sm">{planHistory.data.items.map(item => <li className="hairline-b pb-2" key={item.version}>
            <span className="font-semibold">v{item.version}</span> · {item.updated_by} · {t(`${item.scenarios.length}개 시나리오`, `${item.scenarios.length} scenarios`)}
            <span className="block text-xs text-[var(--text-muted)]">{item.reason} · {item.created_at ? formatDateTime(item.created_at) : t('시각 미상', 'Time unknown')}</span>
          </li>)}</ol>
          {planHistory.data.next_before_id && <p className="mt-2 text-xs text-[var(--text-muted)]">{t('이전 이력은 API 커서로 조회할 수 있습니다.', 'Earlier history is available through the API cursor.')}</p>}
        </details> : null}
      </div>}
    </Card>
    {!selectedRevision && <Card><p className="text-sm">{t('설계 리비전을 입력하면 기록된 시나리오를 조회합니다.', 'Enter a design revision to load its recorded scenarios.')}</p></Card>}
    {selectedRevision && matrix.isPending && <p role="status">{t('시나리오 매트릭스 불러오는 중…', 'Loading scenario matrix…')}</p>}
    {selectedRevision && matrix.isError && <Card><p role="alert">{matrix.error.message}</p><button className="btn btn-ghost mt-3" onClick={() => matrix.refetch()}>{t('다시 시도', 'Retry')}</button></Card>}
    {matrix.data && <>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <StatTile label={t('기대 / 실행', 'Expected / run')} value={`${matrix.data.summary.expected_scenario_count} / ${matrix.data.summary.recorded_expected_scenarios}`} tone={matrix.data.summary.scenario_coverage_complete ? 'good' : undefined} />
        <StatTile label={t('실행 누락', 'Runs missing')} value={matrix.data.summary.missing_scenarios} tone={matrix.data.summary.missing_scenarios ? 'critical' : 'good'} />
        <StatTile label={t('SPEF 요구 누락', 'SPEF requirement gaps')} value={matrix.data.summary.parasitic_requirement_gaps} tone={matrix.data.summary.parasitic_requirement_gaps ? 'critical' : 'good'} />
        <StatTile label={t('실패', 'Failed')} value={matrix.data.summary.failed_scenarios} tone={matrix.data.summary.failed_scenarios ? 'critical' : 'good'} />
        <StatTile label={t('최악 보고 슬랙', 'Worst reported slack')} value={matrix.data.summary.worst_reported_slack_ps ?? '—'} suffix={matrix.data.summary.worst_reported_slack_ps === null ? undefined : 'ps'} />
      </div>
      <Card title={`${STAGE_LABELS[matrix.data.stage]} · ${matrix.data.design_revision}`} subtitle={t('표시 값은 각 시나리오의 최신 서버 실행 결과입니다.', 'Values are from the latest server run of each scenario.')}>
        <div className="overflow-x-auto"><table className="w-full text-left text-sm">
          <thead><tr className="hairline-b"><th className="px-2 py-3">{t('시나리오', 'Scenario')}</th><th className="px-2 py-3">{t('커버리지', 'Coverage')}</th><th className="px-2 py-3">{t('상태', 'Status')}</th><th className="px-2 py-3">WNS</th><th className="px-2 py-3">{t('위반 / 보고 / 미제약', 'Violating / reported / unconstrained')}</th><th className="px-2 py-3">{t('기생 성분', 'Parasitics')}</th><th className="px-2 py-3">{t('실행 근거', 'Run evidence')}</th></tr></thead>
          <tbody>{matrix.data.scenarios.map(row => <tr className="hairline-b" key={row.scenario}>
            <td className="px-2 py-3 font-semibold break-all">{row.scenario}<p className="mt-1 text-xs font-normal text-[var(--text-muted)]">{t(`기록 ${row.run_count}회`, `${row.run_count} recorded runs`)}</p></td>
            <td className="px-2 py-3"><StatusBadge status={row.coverage_state === 'recorded' ? 'good' : row.coverage_state === 'unplanned' ? 'neutral' : 'critical'} label={coverageLabels()[row.coverage_state]} /></td>
            <td className="px-2 py-3">{row.status ? <StatusBadge status={tone(row.status)} label={row.status} /> : '—'}</td>
            <td className="px-2 py-3 whitespace-nowrap">{slack(row.metrics)}</td>
            <td className="px-2 py-3 whitespace-nowrap">{metric(row.metrics, 'violating_paths')} / {metric(row.metrics, 'reported_paths')} / {metric(row.metrics, 'unconstrained_paths')}</td>
            <td className="px-2 py-3">{row.parasitics === 'spef' ? 'SPEF' : row.parasitics === 'none' ? t('미적용', 'Not applied') : '—'}{row.require_spef && <span className="block text-xs text-[var(--text-muted)]">{t('필수', 'Required')}</span>}</td>
            <td className="px-2 py-3">{row.run_id ? <><Link className="underline" to={`/runs/${row.run_id}`}>run #{row.run_id}</Link><span className="block text-xs text-[var(--text-muted)]">{row.tool_version}</span><Link className="text-xs underline" to={`/runs/${row.run_id}/paths`}>{t('경로 표본', 'Path samples')}</Link></> : '—'}</td>
          </tr>)}</tbody>
        </table></div>
        {matrix.data.scenarios.length === 0 && <p className="py-4 text-sm">{t('이 범위에 서버 OpenSTA 실행 기록이 없습니다.', 'No server OpenSTA runs are recorded for this scope.')}</p>}
      </Card>
      <Card title={t('범위와 에이전트 개입', 'Scope and agent involvement')}>
        <p className="text-sm">{t('이 화면과 집계 API에는 AI 에이전트가 개입하지 않습니다. 저장된 OpenSTA 실행 근거를 읽기 전용으로 집계합니다.', 'No AI agent is involved in this screen or its summary API. It aggregates stored OpenSTA run evidence read-only.')}</p>
        <p className="mt-2 text-xs text-[var(--text-muted)]">{t('기대 세트와 최신 실행을 비교해 누락을 표시합니다. 타이밍 수치는 보고된 경로 표본만 포함하므로 전체 사인오프 커버리지는 별도로 확인해야 합니다.', 'Missing scenarios are flagged by comparing the expected set with the latest runs. Timing figures cover only the reported path samples, so full sign-off coverage must be checked separately.')}</p>
      </Card>
    </>}
  </div>;
}
