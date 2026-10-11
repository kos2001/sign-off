import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useParams } from 'react-router';
import { api, DOMAIN_LABELS, STAGES, STAGE_LABELS, type OpenLaneImportInput, type OpenLanePreview, type RunStatus, type SignoffRun } from '../api';
import { useAuth } from '../components/AuthProvider';
import { useLanguage } from '../components/LanguageProvider';
import { OpenLaneDesignSummary, OpenLaneDomainSummary } from '../components/OpenLaneSummary';
import { StatusBadge } from '../components/ui';

const MAX_BYTES = 2_000_000;

function RunBadge({ status }: { status: RunStatus }) {
  const { t } = useLanguage();
  const badge = { passed: ['good', t('통과', 'Passed')], failed: ['critical', t('실패', 'Failed')],
    incomplete: ['warning', t('검증 미완료', 'Incomplete')], running: ['warning', t('진행 중', 'Running')] } as const;
  return <StatusBadge status={badge[status][0]} label={badge[status][1]}/>;
}

export default function OpenLaneImport() {
  const projectId = Number(useParams().id), auth = useAuth(), queryClient = useQueryClient();
  const { t } = useLanguage();
  const project = useQuery({ queryKey: ['project', projectId], queryFn: () => api.getProject(projectId) });
  const [form, setForm] = useState<OpenLaneImportInput>({ import_id: crypto.randomUUID(), stage: 'routing',
    filename: 'metrics.json', tool_version: '', design_revision: '', scenario: '', source_text: '', time_unit: 'ns' });
  const [preview, setPreview] = useState<OpenLanePreview | null>(null), [saved, setSaved] = useState<SignoffRun[] | null>(null);
  const [pending, setPending] = useState(false), [error, setError] = useState('');
  function edit(change: Partial<OpenLaneImportInput>) {
    setForm(current => ({ ...current, ...change, import_id: crypto.randomUUID() })); setPreview(null); setSaved(null); setError('');
  }
  async function readFile(file: File | undefined) {
    if (!file) return;
    if (file.size > MAX_BYTES) { setError(t('파일이 2 MB를 넘습니다.', 'The file is larger than 2 MB.')); return; }
    edit({ filename: file.name.slice(0, 160), source_text: await file.text() });
  }
  if (project.isPending) return <p>{t('프로젝트 불러오는 중…', 'Loading project…')}</p>;
  if (project.isError) return <p role="alert">{project.error.message}</p>;
  if (!auth.can(projectId, 'editor')) return <p>{t('편집자 권한이 필요합니다.', 'Editor permission is required.')}</p>;
  const labels = { filename: t('파일명', 'Filename'), tool_version: t('OpenLane 버전', 'OpenLane version'),
    design_revision: t('설계 리비전', 'Design revision'), scenario: t('런 태그 / 설정', 'Run tag / configuration') };
  return <section className="max-w-4xl space-y-5">
    <header><Link className="underline" to={`/projects/${projectId}`}>{t(`${project.data.name}로 돌아가기`, `Back to ${project.data.name}`)}</Link>
      <h1 className="mt-2 text-xl font-bold">{t('OpenLane 2 플로우 결과 가져오기', 'Import OpenLane 2 flow results')}</h1></header>
    <p>{t('OpenLane 2 런의 ', 'Upload ')}<code>final/metrics.json</code>{t('을 올리세요. 사인오프 검사에서 실패해 ', ' from an OpenLane 2 run. If the run stopped on a sign-off checker and has no ')}<code>final/</code>{t(' 폴더가 없으면 마지막 단계의 ', ' folder, use the last step\'s ')}<code>state_out.json</code>{t('을 사용합니다. 한 번에 타이밍(STA), 물리 검증(DRC·안테나·XOR·PDN), LVS 런을 만들고 같은 설계 리비전에 연결합니다. AI는 개입하지 않습니다.', '. One upload creates timing (STA), physical verification (DRC, antenna, XOR, PDN) and LVS runs on the same design revision. No AI is involved.')}</p>
    <form className="space-y-4" onSubmit={async event => {
      event.preventDefault(); setPending(true); setError('');
      try { setPreview(await api.previewOpenLaneMetrics(projectId, form)); } catch (reason) { setError((reason as Error).message); } finally { setPending(false); }
    }}><fieldset disabled={pending} className="space-y-4">
      <label className="block">{t('metrics.json 또는 state_out.json 파일', 'metrics.json or state_out.json file')}
        <input className="mt-1 block w-full text-sm" type="file" accept=".json,application/json" onChange={event => void readFile(event.target.files?.[0])}/></label>
      <div className="grid gap-4 sm:grid-cols-2">
        <label>{t('스테이지', 'Stage')}<select className="input w-full" value={form.stage} onChange={event => edit({ stage: event.target.value as OpenLaneImportInput['stage'] })}>{STAGES.map(stage => <option key={stage} value={stage}>{STAGE_LABELS[stage]}</option>)}</select></label>
        <label>{t('시간 단위 (Liberty)', 'Time unit (Liberty)')}<select className="input w-full" value={form.time_unit} onChange={event => edit({ time_unit: event.target.value as OpenLaneImportInput['time_unit'] })}>
          <option value="ns">{t('ns · sky130, gf180', 'ns · sky130, gf180')}</option><option value="ps">{t('ps · asap7 등', 'ps · asap7 and similar')}</option></select></label>
        {(['filename', 'tool_version', 'design_revision', 'scenario'] as const).map(key => <label key={key}>{labels[key]}
          <input className="input w-full" required value={form[key]} placeholder={key === 'tool_version' ? '2.3.10' : key === 'scenario' ? 'RUN_2026-10-11_aes' : undefined} onChange={event => edit({ [key]: event.target.value })}/></label>)}
      </div>
      <label className="block">{t('지표 JSON', 'Metrics JSON')}<textarea aria-label={t('지표 JSON', 'Metrics JSON')} className="input mt-1 w-full font-mono text-xs" rows={10} required value={form.source_text} onChange={event => edit({ source_text: event.target.value })}/></label>
      <button className="btn btn-primary">{pending ? t('처리 중…', 'Processing…') : t('가져오기 미리보기', 'Preview import')}</button>
    </fieldset></form>
    {error && <p role="alert">{error}</p>}
    {saved ? <section role="status" aria-label={t('저장된 런', 'Saved runs')} className="rounded-xl border p-4 space-y-2">
      <h2 className="font-semibold">{t(`런 ${saved.length}개 저장 완료`, `Saved ${saved.length} run${saved.length === 1 ? '' : 's'}`)}</h2>
      <ul className="space-y-1">{saved.map(run => <li key={run.id} className="flex flex-wrap items-center gap-2">
        <Link className="underline" to={`/runs/${run.id}`}>{t(`런 #${run.id}`, `Run #${run.id}`)} · {DOMAIN_LABELS[run.domain]}</Link><RunBadge status={run.status}/></li>)}</ul>
      <p className="text-sm text-[var(--text-muted)]">{t('서명된 커버리지 증명이 없으므로 게이트는 이 근거만으로 통과하지 않습니다. 이전 리비전과의 변화는 런 비교에서 확인하세요.', 'Without a signed coverage attestation, the gate does not pass on this evidence alone. Use run comparison to see changes from an earlier revision.')}</p>
      <Link className="btn btn-ghost" to={`/projects/${projectId}/compare`}>{t('런 비교 열기', 'Open run comparison')}</Link>
    </section> : preview && <section aria-label={t('가져오기 미리보기', 'Import preview')} className="rounded-xl border p-4 space-y-4">
      <h2 className="font-semibold">{preview.tool} · {form.tool_version} · {preview.source_format}</h2>
      <p className="text-sm">{t(`지표 ${preview.metric_count}개 · 시간 단위 ${preview.time_unit}`, `${preview.metric_count} metrics · time unit ${preview.time_unit}`)}</p>
      {preview.non_finite_metrics.length > 0 && <p className="text-sm text-[var(--status-warning)]">{t('무한대 값은 보고되지 않은 값으로 처리합니다', 'Infinite values are treated as not reported')}: {preview.non_finite_metrics.join(', ')}</p>}
      <OpenLaneDesignSummary summary={preview.design_summary}/>
      {preview.domains.map(domain => <section key={domain.domain} className="space-y-2 border-t pt-3" aria-label={DOMAIN_LABELS[domain.domain]}>
        <h3 className="flex items-center gap-2 font-semibold">{DOMAIN_LABELS[domain.domain]}<RunBadge status={domain.status}/></h3>
        <OpenLaneDomainSummary result={domain}/>
      </section>)}
      <button className="btn btn-primary" disabled={pending} onClick={async () => {
        setPending(true); setError('');
        try {
          const result = await api.importOpenLaneMetrics(projectId, form); setSaved(result.runs);
          await queryClient.invalidateQueries({ queryKey: ['project', projectId] });
          await queryClient.invalidateQueries({ queryKey: ['runs', projectId] });
        } catch (reason) { setError((reason as Error).message); } finally { setPending(false); }
      }}>{t(`런 ${preview.domains.length}개로 저장`, `Save as ${preview.domains.length} run${preview.domains.length === 1 ? '' : 's'}`)}</button>
    </section>}
  </section>;
}
