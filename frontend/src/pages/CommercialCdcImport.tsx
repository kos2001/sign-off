import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useParams } from 'react-router';
import { api, STAGES, STAGE_LABELS, type CdcPreview, type ReportImportInput } from '../api';
import { useAuth } from '../components/AuthProvider';
import { useLanguage } from '../components/LanguageProvider';

export default function CommercialCdcImport() {
  const projectId = Number(useParams().id), auth = useAuth(), queryClient = useQueryClient();
  const { t } = useLanguage();
  const project = useQuery({ queryKey: ['project', projectId], queryFn: () => api.getProject(projectId) });
  const [form, setForm] = useState<ReportImportInput>({ import_id: crypto.randomUUID(), stage: 'rtl',
    filename: 'commercial-cdc.json', tool_version: '', design_revision: '', scenario: '', source_text: '' });
  const [attestationText, setAttestationText] = useState('');
  const [preview, setPreview] = useState<CdcPreview | null>(null), [saved, setSaved] = useState<number | null>(null);
  const [pending, setPending] = useState(false), [error, setError] = useState('');
  function edit(change: Partial<ReportImportInput>) { setForm(current => ({ ...current, ...change, import_id: crypto.randomUUID() })); setPreview(null); setSaved(null); setError(''); }
  function requestForm(): ReportImportInput { if (!attestationText.trim()) return form; try { const value = JSON.parse(attestationText) as unknown; if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(); return { ...form, coverage_attestation: value as ReportImportInput['coverage_attestation'] }; } catch { throw new Error(t('커버리지 증명은 JSON 객체여야 합니다.', 'The coverage attestation must be a JSON object.')); } }
  if (project.isPending) return <p>{t('프로젝트 불러오는 중…', 'Loading project…')}</p>;
  if (project.isError) return <p role="alert">{project.error.message}</p>;
  if (!auth.can(projectId, 'editor')) return <p>{t('편집자 권한이 필요합니다.', 'Editor permission is required.')}</p>;
  return <section className="max-w-3xl space-y-5"><header><Link className="underline" to={`/projects/${projectId}`}>{t(`${project.data.name}로 돌아가기`, `Back to ${project.data.name}`)}</Link><h1 className="mt-2 text-xl font-bold">{t('VC SpyGlass / Jasper CDC·RDC 결과 가져오기', 'Import VC SpyGlass / Jasper CDC/RDC results')}</h1></header>
    <p><code>signoff/commercial-cdc-rdc/v1</code> {t('JSON의 TOP, clock/reset domain 집계와 CDC·RDC finding을 검증합니다. AI는 개입하지 않습니다.', 'JSON is checked for the TOP, clock/reset domain totals and CDC/RDC findings. No AI is involved.')}</p>
    <form className="space-y-4" onSubmit={async event => { event.preventDefault(); setPending(true); setError(''); try { setPreview(await api.previewCommercialCdc(projectId, requestForm())); } catch (reason) { setError((reason as Error).message); } finally { setPending(false); } }}><fieldset disabled={pending} className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2"><label>{t('스테이지', 'Stage')}<select className="input w-full" value={form.stage} onChange={event => edit({ stage: event.target.value as ReportImportInput['stage'] })}>{STAGES.map(stage => <option key={stage} value={stage}>{STAGE_LABELS[stage]}</option>)}</select></label>
      {(['filename', 'tool_version', 'design_revision', 'scenario'] as const).map(key => <label key={key}>{{ filename: t('보고서 파일명', 'Report filename'), tool_version: t('보고서에 기록된 툴 버전', 'Tool version recorded in report'), design_revision: t('설계 리비전', 'Design revision'), scenario: t('CDC/RDC 제약 / 분석 구성', 'CDC/RDC constraints / analysis setup') }[key]}<input className="input w-full" required value={form[key]} onChange={event => edit({ [key]: event.target.value })}/></label>)}</div>
      <label className="block">{t('보고서 JSON', 'Report JSON')}<textarea aria-label={t('보고서 JSON', 'Report JSON')} className="input mt-1 w-full font-mono text-xs" rows={14} required value={form.source_text} onChange={event => edit({ source_text: event.target.value })}/></label>
      <label className="block">{t('수집기 커버리지 증명 JSON (선택)', 'Collector coverage attestation JSON (optional)')}<textarea aria-label={t('수집기 커버리지 증명 JSON', 'Collector coverage attestation JSON')} className="input mt-1 w-full font-mono text-xs" rows={8} value={attestationText} onChange={event => { setAttestationText(event.target.value); setPreview(null); setSaved(null); setError(''); }}/></label>
      <p className="text-sm text-[var(--text-muted)]">{t('등록된 수집기의 서명이 있으면 clock/reset·제약·계층·구조/기능 분석·CDC/RDC·finding 전체 범위를 검증합니다.', 'With a registered collector signature, full coverage of clocks/resets, constraints, hierarchy, structural/functional analysis, CDC/RDC and findings is verified.')}</p><button className="btn btn-primary">{pending ? t('처리 중…', 'Processing…') : t('가져오기 미리보기', 'Preview import')}</button>
    </fieldset></form>{error && <p role="alert">{error}</p>}
    {saved ? <p role="status">{t(`런 #${saved} 저장 완료`, `Saved as run #${saved}`)} · <Link className="underline" to={`/runs/${saved}/cdc-findings`}>{t('CDC·RDC finding 탐색', 'Explore CDC/RDC findings')}</Link></p> : preview && <section aria-label={t('가져오기 미리보기', 'Import preview')} className="rounded-xl border p-4 space-y-3"><h2 className="font-semibold">{preview.tool} · {preview.tool_version}</h2><p>{t('판정', 'Verdict')} {preview.cdc_status} · TOP {preview.top}</p><p>Clock domain {preview.summary.clock_domains} · Reset domain {preview.summary.reset_domains} · {t(`finding ${preview.items.length}개`, `${preview.items.length} findings`)}</p>{preview.coverage_attestation?.verified ? <p className="font-semibold">{t('신뢰된 수집기 서명과 전체 CDC·RDC 범위를 검증했습니다.', 'Verified the trusted collector signature and full CDC/RDC coverage.')}</p> : <p>{t('제출된 결과만으로 전체 CDC·RDC 분석 범위를 증명하지 않습니다.', 'The submitted results alone do not prove full CDC/RDC analysis coverage.')}</p>}<ul>{preview.items.slice(0, 20).map(item => <li key={item.index}>{item.kind} · {item.name} · {item.severity}</li>)}</ul><p className="break-all text-xs">{t('원본 SHA-256', 'Source SHA-256')}: {preview.source_sha256}</p><button className="btn btn-primary" disabled={pending} onClick={async () => { setPending(true); setError(''); try { const run = await api.importCommercialCdc(projectId, requestForm()); setSaved(run.id); await queryClient.invalidateQueries({ queryKey: ['runs', projectId] }); } catch (reason) { setError((reason as Error).message); } finally { setPending(false); } }}>{t('런으로 저장', 'Save as run')}</button></section>}
  </section>;
}
