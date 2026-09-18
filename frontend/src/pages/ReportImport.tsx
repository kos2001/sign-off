import { useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useParams } from 'react-router';
import { api, STAGES, STAGE_LABELS, type ReportImportInput, type ReportPreview, type KLayoutPreview } from '../api';
import { useAuth } from '../components/AuthProvider';

export default function ReportImport({ klayout = false, commercialSta = false, commercialDrc = false }: { klayout?: boolean; commercialSta?: boolean; commercialDrc?: boolean }) {
  const { id } = useParams();
  return <ImportForm key={`${id}-${klayout}-${commercialSta}-${commercialDrc}`} projectId={Number(id)} klayout={klayout} commercialSta={commercialSta} commercialDrc={commercialDrc} />;
}
function ImportForm({ projectId, klayout, commercialSta, commercialDrc }: { projectId: number; klayout: boolean; commercialSta: boolean; commercialDrc: boolean }) {
  const drc = klayout || commercialDrc;
  const auth = useAuth();
  const qc = useQueryClient();
  const project = useQuery({ queryKey: ['project', projectId], queryFn: () => api.getProject(projectId) });
  const [form, setForm] = useState<ReportImportInput>({ import_id: crypto.randomUUID(), stage: 'placement', filename: klayout ? 'drc.lyrdb' : commercialSta ? 'commercial-sta.json' : commercialDrc ? 'commercial-drc.json' : 'timing.json', tool_version: '', design_revision: '', scenario: '', source_text: '' });
  const [preview, setPreview] = useState<ReportPreview | KLayoutPreview | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState<number | null>(null);
  const fileVersion = useRef(0);
  function edit(patch: Partial<ReportImportInput>) {
    setForm(current => ({ ...current, ...patch, import_id: crypto.randomUUID() }));
    setPreview(null); setSaved(null); setError('');
  }
  if (project.isPending) return <p role="status">프로젝트 불러오는 중…</p>;
  if (project.isError) return <p role="alert">{project.error.message}</p>;
  if (!auth.can(projectId, 'editor')) return <p>보고서를 가져오려면 프로젝트 편집자 권한이 필요합니다.</p>;
  return <section className="max-w-3xl space-y-5">
    <header><Link className="text-sm underline" to={`/projects/${projectId}`}>{project.data.name}로 돌아가기</Link><h1 className="mt-3 text-xl font-bold">{klayout ? 'KLayout DRC 보고서 가져오기' : commercialDrc ? 'Calibre / Pegasus 마커 가져오기' : commercialSta ? 'PrimeTime / Tempus 경로 가져오기' : 'OpenSTA 보고서 가져오기'}</h1></header>
    <nav className="flex flex-wrap gap-3 text-sm" aria-label="보고서 형식"><Link className="underline" to={`/projects/${projectId}/import`}>OpenSTA</Link><Link className="underline" to={`/projects/${projectId}/import/commercial-sta`}>PrimeTime / Tempus</Link><Link className="underline" to={`/projects/${projectId}/import/klayout`}>KLayout DRC</Link><Link className="underline" to={`/projects/${projectId}/import/commercial-drc`}>Calibre / Pegasus</Link><Link className="underline" to={`/projects/${projectId}/import/commercial-emir`}>RedHawk / Voltus / Totem</Link><Link className="underline" to={`/projects/${projectId}/import/commercial-power`}>PrimePower / Joules / PowerArtist</Link></nav>
    <p className="text-sm text-[var(--text-secondary)]">{klayout ? "KLayout DRC 마커 데이터베이스(.lyrdb XML)를 사용하세요. 최대 2 MB, 마커 1,000개를 지원합니다. 셀 기준 좌표 원문을 보존하며 계층 좌표 변환은 하지 않습니다." : commercialDrc ? <>Calibre 또는 Pegasus 수집기가 만든 <code>signoff/commercial-drc-markers/v1</code> JSON을 사용하세요. 툴·버전·좌표 단위·심각도와 도형을 검증합니다.</> : commercialSta ? <>PrimeTime 또는 Tempus에서 수집한 경로를 <code>signoff/commercial-sta-paths/v1</code> JSON으로 내보내세요. 툴·버전·시간 단위와 경로 핀을 검증하며 최대 2 MB, 1,000개 경로를 지원합니다.</> : <>OpenSTA에서 <code>report_checks -format json</code>으로 내보낸 보고서를 사용하세요. 시간 값은 초 단위에서 ps로 변환합니다. 최대 2 MB, 1,000개 경로를 지원합니다.</>}</p>
    {drc && <p className="text-sm">PV 보고서 수집에는 에이전트가 개입하지 않습니다. 위반 승인·웨이버는 권한 있는 사용자가 처리합니다.</p>}
    <form className="space-y-4" onSubmit={async e => {
      e.preventDefault(); setPending(true); setError(''); setPreview(null);
      try { setPreview(await (klayout ? api.previewKLayout(projectId, form) : commercialDrc ? api.previewCommercialDrc(projectId, form) : commercialSta ? api.previewCommercialSta(projectId, form) : api.previewOpenSta(projectId, form))); }
      catch (error) { setError((error as Error).message); }
      finally { setPending(false); }
    }}>
      <fieldset disabled={pending} className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="text-sm">스테이지<select className="input mt-1 w-full" value={form.stage} onChange={e => edit({ stage: e.target.value as ReportImportInput['stage'] })}>{STAGES.map(stage => <option key={stage} value={stage}>{STAGE_LABELS[stage]}</option>)}</select></label>
          {(['filename', 'tool_version', 'design_revision', 'scenario'] as const).map(key => <label key={key} className="text-sm">{{ filename: '보고서 파일명', tool_version: klayout ? 'KLayout 버전' : commercialSta || commercialDrc ? '보고서에 기록된 툴 버전' : 'OpenSTA 버전', design_revision: '설계 리비전', scenario: drc ? '룰덱 / 실행 조건' : '시나리오 / 코너' }[key]}<input className="input mt-1 w-full" required maxLength={key === 'tool_version' ? 80 : 160} value={form[key]} onChange={e => edit({ [key]: e.target.value })} /></label>)}
        </div>
        <label className="block text-sm">{klayout ? "LYRDB 파일 선택" : "JSON 파일 선택"}<input className="mt-2 block w-full min-w-0 text-sm" type="file" accept={klayout ? ".lyrdb,.xml,application/xml" : ".json,application/json"} onChange={async e => {
          const file = e.target.files?.[0]; const version = ++fileVersion.current;
          if (!file) return;
          edit({ source_text: '' });
          if (file.size > 2_000_000) { setError('파일이 2 MB를 초과합니다.'); return; }
          setPending(true);
          try {
            const source = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(await file.arrayBuffer());
            if (version === fileVersion.current) edit({ source_text: source, filename: file.name });
          } catch { setError('UTF-8 보고서 파일을 읽을 수 없습니다.'); }
          finally { setPending(false); }
        }} /></label>
        <label className="block text-sm">{klayout ? "보고서 XML" : "보고서 JSON"}<textarea aria-label={klayout ? "보고서 XML" : "보고서 JSON"} className="input mt-1 w-full font-mono text-xs" rows={10} required maxLength={2_000_000} spellCheck={false} value={form.source_text} onChange={e => { fileVersion.current++; edit({ source_text: e.target.value }); }} /></label>
        <button className="btn btn-primary" disabled={pending || saved !== null}>{pending ? '처리 중…' : '가져오기 미리보기'}</button>
      </fieldset>
    </form>
    {error && <p role="alert" className="text-sm text-[var(--status-critical)]">{error}</p>}
    {saved !== null ? <p role="status">런 #{saved}에 보고서와 근거를 저장했습니다. <Link className="underline" to={`/projects/${projectId}`}>저장한 런 보기</Link> · {drc && <><Link className="underline" to={`/runs/${saved}/markers`}>DRC 마커 탐색</Link> · </>}{!drc && <><Link className="underline" to={`/runs/${saved}/paths`}>타이밍 경로 탐색</Link> · </>}<Link className="underline" to={`/projects/${projectId}/violations?domain=${drc ? "pv" : "sta"}`}>위반 검토</Link></p> : preview && <section aria-label="가져오기 미리보기" className="rounded-xl border border-[var(--border)] p-4 space-y-4">
      <h2 className="font-semibold">저장할 보고서</h2>
      {'items' in preview ? <>
        {preview.tool && <p className="text-sm">수집 툴: <strong>{preview.tool}</strong>{preview.tool_version ? ` · ${preview.tool_version}` : ''}</p>}
        <p>마커 {preview.metrics.reported_items}개 · 보고된 중복 발생 수 합계 {preview.metrics.reported_multiplicity}</p>
        <p>{commercialDrc ? '수집기가 기록한 심각도를 보존하지만 해결·승인으로 해석하지 않습니다.' : 'DRC 마커를 보수적으로 error 위반으로 등록합니다. 원본 형식에는 표준 심각도 필드가 없습니다. visited·waived 태그는 서비스의 해결·승인으로 반영하지 않습니다.'} 마커가 없더라도 전체 검증 범위 미확인으로 저장합니다.</p>
        <ul className="space-y-2">{preview.items.slice(0, 20).map(item => <li key={item.index} className="rounded-lg bg-[var(--surface-2)] p-3 text-xs break-words"><strong>#{item.index} · {item.category}</strong><p>셀: {item.cell || '전체 셀'} · 중복 발생 수: {item.multiplicity}{item.severity ? ` · 심각도: ${item.severity}` : ''}</p><pre className="whitespace-pre-wrap break-words">{item.values.join('\n')}</pre><p>원본 태그: {item.tags || '없음'}</p></li>)}</ul>
        {preview.items.length > 20 && <p>처음 20개 마커를 표시합니다. 저장 시 전체 {preview.items.length}개를 보존합니다.</p>}
      </> : <>
      {preview.tool && <p className="text-sm">수집 툴: <strong>{preview.tool}</strong>{preview.tool_version ? ` · ${preview.tool_version}` : ''}</p>}
      <p className="text-sm">경로 {preview.metrics.reported_paths}개 · 위반 {preview.metrics.violating_paths}개 · 제약 없음 {preview.metrics.unconstrained_paths}개</p>
      <p className="text-sm break-all">보고된 최악 슬랙: {preview.metrics.worst_reported_slack_ps === null ? '없음' : `${preview.metrics.worst_reported_slack_ps} ps`}</p>
      <p className="text-sm">{preview.status === 'failed' ? '위반이 있어 실패 상태로 저장합니다.' : '전체 검증 범위를 확인할 수 없어 검증 미완료로 저장합니다.'} 일부 경로만 포함될 수 있으므로 전체 설계의 WNS/TNS나 사인오프 통과로 해석하지 마세요.</p>
      <ul className="space-y-2">{preview.paths.slice(0, 20).map(path => <li key={path.index} className="rounded-lg bg-[var(--surface-2)] p-3 text-xs break-all"><strong>#{path.index} · {path.path_type} · {path.path_group}</strong><p>{path.startpoint} → {path.endpoint}</p><p>{path.slack_ps === null ? '제약 없음' : `${path.slack_ps} ps`}</p></li>)}</ul>
      {preview.paths.length > 20 && <p className="text-xs">처음 20개 경로를 표시합니다. 저장 시 전체 {preview.paths.length}개를 보존합니다.</p>}
      </>}
      <p className="text-xs break-all">원본 SHA-256: {preview.source_sha256}</p>
      <button className="btn btn-primary" disabled={pending} onClick={async () => {
        setPending(true); setError('');
        try {
          const run = await (klayout ? api.importKLayout(projectId, form) : commercialDrc ? api.importCommercialDrc(projectId, form) : commercialSta ? api.importCommercialSta(projectId, form) : api.importOpenSta(projectId, form)); setSaved(run.id);
          await Promise.all([qc.invalidateQueries({ queryKey: ['runs', projectId] }), qc.invalidateQueries({ queryKey: ['gate', projectId] }), qc.invalidateQueries({ queryKey: ['project-violations', projectId] })]);
        } catch (error) { setError((error as Error).message); }
        finally { setPending(false); }
      }}>{pending ? '저장 중…' : '런으로 저장'}</button>
    </section>}
  </section>;
}
