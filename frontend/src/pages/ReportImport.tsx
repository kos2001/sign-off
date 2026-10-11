import { useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useParams } from 'react-router';
import { api, STAGES, STAGE_LABELS, type ReportImportInput, type ReportPreview, type KLayoutPreview } from '../api';
import { useAuth } from '../components/AuthProvider';
import { useLanguage } from '../components/LanguageProvider';

export default function ReportImport({ klayout = false, commercialSta = false, commercialDrc = false }: { klayout?: boolean; commercialSta?: boolean; commercialDrc?: boolean }) {
  const { id } = useParams();
  return <ImportForm key={`${id}-${klayout}-${commercialSta}-${commercialDrc}`} projectId={Number(id)} klayout={klayout} commercialSta={commercialSta} commercialDrc={commercialDrc} />;
}
function ImportForm({ projectId, klayout, commercialSta, commercialDrc }: { projectId: number; klayout: boolean; commercialSta: boolean; commercialDrc: boolean }) {
  const { t } = useLanguage();
  const drc = klayout || commercialDrc;
  const trustedAttestation = commercialSta || commercialDrc;
  const auth = useAuth();
  const qc = useQueryClient();
  const project = useQuery({ queryKey: ['project', projectId], queryFn: () => api.getProject(projectId) });
  const [form, setForm] = useState<ReportImportInput>({ import_id: crypto.randomUUID(), stage: 'placement', filename: klayout ? 'drc.lyrdb' : commercialSta ? 'commercial-sta.json' : commercialDrc ? 'commercial-drc.json' : 'timing.json', tool_version: '', design_revision: '', scenario: '', source_text: '' });
  const [preview, setPreview] = useState<ReportPreview | KLayoutPreview | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState<number | null>(null);
  const [attestationText, setAttestationText] = useState('');
  const fileVersion = useRef(0);
  function edit(patch: Partial<ReportImportInput>) {
    setForm(current => ({ ...current, ...patch, import_id: crypto.randomUUID() }));
    setPreview(null); setSaved(null); setError('');
  }
  function requestForm(): ReportImportInput {
    if (!trustedAttestation || !attestationText.trim()) return form;
    try {
      const parsed = JSON.parse(attestationText) as unknown;
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error();
      return { ...form, coverage_attestation: parsed as ReportImportInput['coverage_attestation'] };
    } catch {
      throw new Error(t('커버리지 증명은 JSON 객체여야 합니다.', 'The coverage attestation must be a JSON object.'));
    }
  }
  if (project.isPending) return <p role="status">{t('프로젝트 불러오는 중…', 'Loading project…')}</p>;
  if (project.isError) return <p role="alert">{project.error.message}</p>;
  if (!auth.can(projectId, 'editor')) return <p>{t('보고서를 가져오려면 프로젝트 편집자 권한이 필요합니다.', 'You need project editor permission to import reports.')}</p>;
  return <section className="max-w-3xl space-y-5">
    <header><Link className="text-sm underline" to={`/projects/${projectId}`}>{t(`${project.data.name}로 돌아가기`, `Back to ${project.data.name}`)}</Link><h1 className="mt-3 text-xl font-bold">{klayout ? t('KLayout DRC 보고서 가져오기', 'Import KLayout DRC report') : commercialDrc ? t('Calibre / Pegasus 마커 가져오기', 'Import Calibre / Pegasus markers') : commercialSta ? t('PrimeTime / Tempus 경로 가져오기', 'Import PrimeTime / Tempus paths') : t('OpenSTA 보고서 가져오기', 'Import OpenSTA report')}</h1></header>
    <nav className="flex flex-wrap gap-3 text-sm" aria-label={t('보고서 형식', 'Report format')}><Link className="underline" to={`/projects/${projectId}/import`}>OpenSTA</Link><Link className="underline" to={`/projects/${projectId}/import/commercial-rtl`}>VCS / Xcelium</Link><Link className="underline" to={`/projects/${projectId}/import/commercial-cdc`}>VC SpyGlass / Jasper CDC·RDC</Link><Link className="underline" to={`/projects/${projectId}/import/commercial-dft`}>TestMAX / Tessent / Modus DFT</Link><Link className="underline" to={`/projects/${projectId}/import/commercial-low-power`}>VC LP / Conformal Low Power</Link><Link className="underline" to={`/projects/${projectId}/import/commercial-sta`}>PrimeTime / Tempus</Link><Link className="underline" to={`/projects/${projectId}/import/klayout`}>KLayout DRC</Link><Link className="underline" to={`/projects/${projectId}/import/commercial-drc`}>Calibre / Pegasus DRC</Link><Link className="underline" to={`/projects/${projectId}/import/commercial-lvs`}>Calibre / Pegasus LVS</Link><Link className="underline" to={`/projects/${projectId}/import/commercial-lec`}>Formality / Conformal LEC</Link><Link className="underline" to={`/projects/${projectId}/import/commercial-emir`}>RedHawk / Voltus / Totem</Link><Link className="underline" to={`/projects/${projectId}/import/commercial-power`}>PrimePower / Joules / PowerArtist</Link><Link className="underline" to={`/projects/${projectId}/import/commercial-thermal`}>Celsius / Icepak / 3DSTACK</Link></nav>
    <p className="text-sm text-[var(--text-secondary)]">{klayout ? t("KLayout DRC 마커 데이터베이스(.lyrdb XML)를 사용하세요. 최대 2 MB, 마커 1,000개를 지원합니다. 셀 기준 좌표 원문을 보존하며 계층 좌표 변환은 하지 않습니다.", "Use a KLayout DRC marker database (.lyrdb XML). Up to 2 MB and 1,000 markers are supported. Cell-relative coordinates are kept as is, with no hierarchical transform.") : commercialDrc ? <>{t('Calibre 또는 Pegasus 수집기가 만든', 'Use')} <code>signoff/commercial-drc-markers/v1</code> {t('JSON을 사용하세요. 툴·버전·좌표 단위·심각도와 도형을 검증합니다.', 'JSON produced by a Calibre or Pegasus collector. Tool, version, coordinate unit, severity and shapes are validated.')}</> : commercialSta ? <>{t('PrimeTime 또는 Tempus에서 수집한 경로를', 'Export paths collected from PrimeTime or Tempus as')} <code>signoff/commercial-sta-paths/v1</code> {t('JSON으로 내보내세요. 툴·버전·시간 단위와 경로 핀을 검증하며 최대 2 MB, 1,000개 경로를 지원합니다.', 'JSON. Tool, version, time unit and path pins are validated; up to 2 MB and 1,000 paths are supported.')}</> : <>{t('OpenSTA에서', 'Use a report exported from OpenSTA with')} <code>report_checks -format json</code>{t('으로 내보낸 보고서를 사용하세요. 시간 값은 초 단위에서 ps로 변환합니다. 최대 2 MB, 1,000개 경로를 지원합니다.', '. Time values are converted from seconds to ps. Up to 2 MB and 1,000 paths are supported.')}</>}</p>
    {drc && <p className="text-sm">{t('PV 보고서 수집에는 에이전트가 개입하지 않습니다. 위반 승인·웨이버는 권한 있는 사용자가 처리합니다.', 'No agent is involved in collecting PV reports. Violation approvals and waivers are handled by authorized users.')}</p>}
    <form className="space-y-4" onSubmit={async e => {
      e.preventDefault(); setPending(true); setError(''); setPreview(null);
      try { const body = requestForm(); setPreview(await (klayout ? api.previewKLayout(projectId, body) : commercialDrc ? api.previewCommercialDrc(projectId, body) : commercialSta ? api.previewCommercialSta(projectId, body) : api.previewOpenSta(projectId, body))); }
      catch (error) { setError((error as Error).message); }
      finally { setPending(false); }
    }}>
      <fieldset disabled={pending} className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="text-sm">{t('스테이지', 'Stage')}<select className="input mt-1 w-full" value={form.stage} onChange={e => edit({ stage: e.target.value as ReportImportInput['stage'] })}>{STAGES.map(stage => <option key={stage} value={stage}>{STAGE_LABELS[stage]}</option>)}</select></label>
          {(['filename', 'tool_version', 'design_revision', 'scenario'] as const).map(key => <label key={key} className="text-sm">{{ filename: t('보고서 파일명', 'Report file name'), tool_version: klayout ? t('KLayout 버전', 'KLayout version') : commercialSta || commercialDrc ? t('보고서에 기록된 툴 버전', 'Tool version recorded in the report') : t('OpenSTA 버전', 'OpenSTA version'), design_revision: t('설계 리비전', 'Design revision'), scenario: drc ? t('룰덱 / 실행 조건', 'Rule deck / run conditions') : t('시나리오 / 코너', 'Scenario / corner') }[key]}<input className="input mt-1 w-full" required maxLength={key === 'tool_version' ? 80 : 160} value={form[key]} onChange={e => edit({ [key]: e.target.value })} /></label>)}
        </div>
        <label className="block text-sm">{klayout ? t("LYRDB 파일 선택", "Choose LYRDB file") : t("JSON 파일 선택", "Choose JSON file")}<input className="mt-2 block w-full min-w-0 text-sm" type="file" accept={klayout ? ".lyrdb,.xml,application/xml" : ".json,application/json"} onChange={async e => {
          const file = e.target.files?.[0]; const version = ++fileVersion.current;
          if (!file) return;
          edit({ source_text: '' });
          if (file.size > 2_000_000) { setError(t('파일이 2 MB를 초과합니다.', 'The file exceeds 2 MB.')); return; }
          setPending(true);
          try {
            const source = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(await file.arrayBuffer());
            if (version === fileVersion.current) edit({ source_text: source, filename: file.name });
          } catch { setError(t('UTF-8 보고서 파일을 읽을 수 없습니다.', 'Could not read the report file as UTF-8.')); }
          finally { setPending(false); }
        }} /></label>
        <label className="block text-sm">{klayout ? t("보고서 XML", "Report XML") : t("보고서 JSON", "Report JSON")}<textarea aria-label={klayout ? t("보고서 XML", "Report XML") : t("보고서 JSON", "Report JSON")} className="input mt-1 w-full font-mono text-xs" rows={10} required maxLength={2_000_000} spellCheck={false} value={form.source_text} onChange={e => { fileVersion.current++; edit({ source_text: e.target.value }); }} /></label>
        {trustedAttestation && <label className="block text-sm">{t('신뢰된 수집기 커버리지 증명 (선택)', 'Trusted collector coverage attestation (optional)')}<textarea aria-label={t('커버리지 증명 JSON', 'Coverage attestation JSON')} className="input mt-1 w-full font-mono text-xs" rows={7} spellCheck={false} value={attestationText} onChange={e => { setAttestationText(e.target.value); setPreview(null); setSaved(null); setError(''); }} placeholder='{"format":"signoff/coverage-attestation/v1", ...}' /><span className="mt-1 block text-xs text-[var(--text-muted)]">{t(`서버에 등록된 수집기 키로 서명된 증명만 전체 ${commercialDrc ? 'DRC' : 'STA'} 실행 범위로 인정합니다. 일반 보고서는 계속 부분 근거로 저장됩니다.`, `Only attestations signed with a collector key registered on the server count as full ${commercialDrc ? 'DRC' : 'STA'} run coverage. Regular reports are still saved as partial evidence.`)}</span></label>}
        <button className="btn btn-primary" disabled={pending || saved !== null}>{pending ? t('처리 중…', 'Processing…') : t('가져오기 미리보기', 'Preview import')}</button>
      </fieldset>
    </form>
    {error && <p role="alert" className="text-sm text-[var(--status-critical)]">{error}</p>}
    {saved !== null ? <p role="status">{t(`런 #${saved}에 보고서와 근거를 저장했습니다.`, `Saved the report and evidence to run #${saved}.`)} <Link className="underline" to={`/projects/${projectId}`}>{t('저장한 런 보기', 'View saved run')}</Link> · {drc && <><Link className="underline" to={`/runs/${saved}/markers`}>{t('DRC 마커 탐색', 'Explore DRC markers')}</Link> · </>}{!drc && <><Link className="underline" to={`/runs/${saved}/paths`}>{t('타이밍 경로 탐색', 'Explore timing paths')}</Link> · </>}<Link className="underline" to={`/projects/${projectId}/violations?domain=${drc ? "pv" : "sta"}`}>{t('위반 검토', 'Review violations')}</Link></p> : preview && <section aria-label={t('가져오기 미리보기', 'Import preview')} className="rounded-xl border border-[var(--border)] p-4 space-y-4">
      <h2 className="font-semibold">{t('저장할 보고서', 'Report to save')}</h2>
      {'items' in preview ? <>
        {preview.tool && <p className="text-sm">{t('수집 툴', 'Collector tool')}: <strong>{preview.tool}</strong>{preview.tool_version ? ` · ${preview.tool_version}` : ''}</p>}
        <p>{t(`마커 ${preview.metrics.reported_items}개 · 보고된 중복 발생 수 합계 ${preview.metrics.reported_multiplicity}`, `${preview.metrics.reported_items} markers · total reported multiplicity ${preview.metrics.reported_multiplicity}`)}</p>
        <p>{commercialDrc ? t('수집기가 기록한 심각도를 보존하지만 해결·승인으로 해석하지 않습니다.', 'The severity recorded by the collector is kept but not read as resolution or approval.') : t('DRC 마커를 보수적으로 error 위반으로 등록합니다. 원본 형식에는 표준 심각도 필드가 없습니다. visited·waived 태그는 서비스의 해결·승인으로 반영하지 않습니다.', 'DRC markers are conservatively registered as error violations because the source format has no standard severity field. visited and waived tags are not applied as resolution or approval in the service.')} {preview.coverage_attestation?.verified ? t('서명된 범위와 차단 마커를 함께 판정합니다.', 'The signed coverage and blocking markers are evaluated together.') : t('마커가 없더라도 전체 검증 범위 미확인으로 저장합니다.', 'Even with no markers, the run is saved with full verification coverage unconfirmed.')}</p>
        {preview.coverage_attestation?.verified && <p className="font-semibold">{t('신뢰된 수집기 서명과 전체 DRC 범위 선언을 검증했습니다. 차단 마커가 없으면 통과 상태로 저장합니다.', 'Verified the trusted collector signature and the full DRC coverage declaration. With no blocking markers, the run is saved as passed.')}</p>}
        <ul className="space-y-2">{preview.items.slice(0, 20).map(item => <li key={item.index} className="rounded-lg bg-[var(--surface-2)] p-3 text-xs break-words"><strong>#{item.index} · {item.category}</strong><p>{t('셀', 'Cell')}: {item.cell || t('전체 셀', 'All cells')} · {t('중복 발생 수', 'Multiplicity')}: {item.multiplicity}{item.severity ? t(` · 심각도: ${item.severity}`, ` · Severity: ${item.severity}`) : ''}</p><pre className="whitespace-pre-wrap break-words">{item.values.join('\n')}</pre><p>{t('원본 태그', 'Source tags')}: {item.tags || t('없음', 'None')}</p></li>)}</ul>
        {preview.items.length > 20 && <p>{t(`처음 20개 마커를 표시합니다. 저장 시 전체 ${preview.items.length}개를 보존합니다.`, `Showing the first 20 markers. All ${preview.items.length} are kept when saved.`)}</p>}
      </> : <>
      {preview.tool && <p className="text-sm">{t('수집 툴', 'Collector tool')}: <strong>{preview.tool}</strong>{preview.tool_version ? ` · ${preview.tool_version}` : ''}</p>}
      <p className="text-sm">{t(`경로 ${preview.metrics.reported_paths}개 · 위반 ${preview.metrics.violating_paths}개 · 제약 없음 ${preview.metrics.unconstrained_paths}개`, `${preview.metrics.reported_paths} paths · ${preview.metrics.violating_paths} violating · ${preview.metrics.unconstrained_paths} unconstrained`)}</p>
      <p className="text-sm break-all">{t('보고된 최악 슬랙', 'Worst reported slack')}: {preview.metrics.worst_reported_slack_ps === null ? t('없음', 'None') : `${preview.metrics.worst_reported_slack_ps} ps`}</p>
      {preview.coverage_attestation?.verified && <p className="text-sm font-semibold">{t('신뢰된 수집기 서명과 전체 STA 범위 선언을 검증했습니다.', 'Verified the trusted collector signature and the full STA coverage declaration.')}</p>}
      <p className="text-sm">{preview.status === 'failed' ? t('위반이 있어 실패 상태로 저장합니다.', 'Saved as failed because there are violations.') : preview.coverage_attestation?.verified ? t('서명된 전체 범위에서 보고된 위반과 제약 누락이 없어 통과 상태로 저장합니다.', 'Saved as passed: no violations or missing constraints were reported within the signed full coverage.') : t('전체 검증 범위를 확인할 수 없어 검증 미완료로 저장합니다.', 'Saved as incomplete because full verification coverage cannot be confirmed.')} {!preview.coverage_attestation?.verified && t('일부 경로만 포함될 수 있으므로 전체 설계의 WNS/TNS나 사인오프 통과로 해석하지 마세요.', 'Only some paths may be included, so do not read this as full-design WNS/TNS or a sign-off pass.')}</p>
      <ul className="space-y-2">{preview.paths.slice(0, 20).map(path => <li key={path.index} className="rounded-lg bg-[var(--surface-2)] p-3 text-xs break-all"><strong>#{path.index} · {path.path_type} · {path.path_group}</strong><p>{path.startpoint} → {path.endpoint}</p><p>{path.slack_ps === null ? t('제약 없음', 'Unconstrained') : `${path.slack_ps} ps`}</p></li>)}</ul>
      {preview.paths.length > 20 && <p className="text-xs">{t(`처음 20개 경로를 표시합니다. 저장 시 전체 ${preview.paths.length}개를 보존합니다.`, `Showing the first 20 paths. All ${preview.paths.length} are kept when saved.`)}</p>}
      </>}
      <p className="text-xs break-all">{t('원본 SHA-256', 'Source SHA-256')}: {preview.source_sha256}</p>
      <button className="btn btn-primary" disabled={pending} onClick={async () => {
        setPending(true); setError('');
        try {
          const body = requestForm(); const run = await (klayout ? api.importKLayout(projectId, body) : commercialDrc ? api.importCommercialDrc(projectId, body) : commercialSta ? api.importCommercialSta(projectId, body) : api.importOpenSta(projectId, body)); setSaved(run.id);
          await Promise.all([qc.invalidateQueries({ queryKey: ['runs', projectId] }), qc.invalidateQueries({ queryKey: ['gate', projectId] }), qc.invalidateQueries({ queryKey: ['project-violations', projectId] })]);
        } catch (error) { setError((error as Error).message); }
        finally { setPending(false); }
      }}>{pending ? t('저장 중…', 'Saving…') : t('런으로 저장', 'Save as run')}</button>
    </section>}
  </section>;
}
