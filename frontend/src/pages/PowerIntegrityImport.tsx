import { useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useParams } from 'react-router';
import { api, STAGES, STAGE_LABELS, type PowerIntegrityPreview, type ReportImportInput } from '../api';
import { useAuth } from '../components/AuthProvider';

export default function PowerIntegrityImport() {
  const projectId = Number(useParams().id); const auth = useAuth(); const qc = useQueryClient();
  const project = useQuery({ queryKey: ['project', projectId], queryFn: () => api.getProject(projectId) });
  const [form, setForm] = useState<ReportImportInput>({ import_id: crypto.randomUUID(), stage: 'routing',
    filename: 'commercial-emir.json', tool_version: '', design_revision: '', scenario: '', source_text: '' });
  const [preview, setPreview] = useState<PowerIntegrityPreview | null>(null); const [saved, setSaved] = useState<number | null>(null);
  const [pending, setPending] = useState(false); const [error, setError] = useState(''); const fileVersion = useRef(0);
  function edit(patch: Partial<ReportImportInput>) { setForm(current => ({ ...current, ...patch, import_id: crypto.randomUUID() })); setPreview(null); setSaved(null); setError(''); }
  if (project.isPending) return <p role="status">프로젝트 불러오는 중…</p>;
  if (project.isError) return <p role="alert">{project.error.message}</p>;
  if (!auth.can(projectId, 'editor')) return <p>보고서를 가져오려면 프로젝트 편집자 권한이 필요합니다.</p>;
  return <section className="max-w-3xl space-y-5">
    <header><Link className="text-sm underline" to={`/projects/${projectId}`}>{project.data.name}로 돌아가기</Link><h1 className="mt-3 text-xl font-bold">RedHawk-SC / Voltus / Totem 결과 가져오기</h1></header>
    <nav className="flex flex-wrap gap-3 text-sm" aria-label="보고서 형식"><Link className="underline" to={`/projects/${projectId}/import`}>STA / DRC 가져오기</Link><Link className="underline" to={`/projects/${projectId}/import/commercial-emir`}>상용 EM/IR</Link></nav>
    <p className="text-sm text-[var(--text-secondary)]">수집기가 만든 <code>signoff/commercial-power-integrity/v1</code> JSON을 사용하세요. 툴·버전·분석 종류·값·제한·단위·좌표를 검증합니다. 가져오기와 탐색에는 AI가 개입하지 않습니다.</p>
    <form className="space-y-4" onSubmit={async event => { event.preventDefault(); setPending(true); setError(''); setPreview(null); try { setPreview(await api.previewCommercialEmir(projectId, form)); } catch (reason) { setError((reason as Error).message); } finally { setPending(false); } }}>
      <fieldset disabled={pending} className="space-y-4"><div className="grid gap-4 sm:grid-cols-2">
        <label className="text-sm">스테이지<select className="input mt-1 w-full" value={form.stage} onChange={event => edit({ stage: event.target.value as ReportImportInput['stage'] })}>{STAGES.map(stage => <option key={stage} value={stage}>{STAGE_LABELS[stage]}</option>)}</select></label>
        {(['filename','tool_version','design_revision','scenario'] as const).map(key => <label key={key} className="text-sm">{{filename:'보고서 파일명',tool_version:'보고서에 기록된 툴 버전',design_revision:'설계 리비전',scenario:'모드 / 코너 / 전원 조건'}[key]}<input className="input mt-1 w-full" required maxLength={key === 'tool_version' ? 80 : 160} value={form[key]} onChange={event => edit({[key]:event.target.value})}/></label>)}
      </div><label className="block text-sm">JSON 파일 선택<input className="mt-2 block w-full text-sm" type="file" accept=".json,application/json" onChange={async event => { const file=event.target.files?.[0]; const version=++fileVersion.current; if(!file)return; edit({source_text:''}); if(file.size>2_000_000){setError('파일이 2 MB를 초과합니다.');return;} setPending(true); try { const source=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(await file.arrayBuffer()); if(version===fileVersion.current) edit({source_text:source,filename:file.name}); } catch { setError('UTF-8 보고서 파일을 읽을 수 없습니다.'); } finally { setPending(false); } }}/></label>
      <label className="block text-sm">보고서 JSON<textarea aria-label="보고서 JSON" className="input mt-1 w-full font-mono text-xs" rows={12} required maxLength={2_000_000} spellCheck={false} value={form.source_text} onChange={event => { fileVersion.current++; edit({source_text:event.target.value}); }}/></label>
      <button className="btn btn-primary" disabled={pending || saved !== null}>{pending?'처리 중…':'가져오기 미리보기'}</button></fieldset>
    </form>
    {error && <p role="alert" className="text-sm text-[var(--status-critical)]">{error}</p>}
    {saved !== null ? <p role="status">런 #{saved}에 원본 근거를 저장했습니다. <Link className="underline" to={`/runs/${saved}/power-integrity`}>EM/IR 핫스폿 탐색</Link> · <Link className="underline" to={`/projects/${projectId}/violations?domain=emir`}>위반 검토</Link></p> : preview && <section aria-label="가져오기 미리보기" className="rounded-xl border border-[var(--border)] p-4 space-y-3">
      <h2 className="font-semibold">저장할 전력 무결성 보고서</h2><p>수집 툴: <strong>{preview.tool}</strong> · {preview.tool_version}</p>
      <p>결과 {preview.metrics.reported_findings}개 · 제한 초과 {preview.metrics.violated_findings}개 · static IR {preview.metrics.static_ir_findings} · dynamic IR {preview.metrics.dynamic_ir_findings} · EM {preview.metrics.em_findings}</p>
      <p>제출된 결과만 보존하며 전체 rail·모드·벡터·추출 범위나 상용 툴 실행 진위를 증명하지 않습니다.</p>
      <ul className="space-y-2">{preview.items.slice(0,20).map(item => <li key={item.index} className="rounded-lg bg-[var(--surface-2)] p-3 text-xs break-words"><strong>#{item.index} · {item.analysis} · {item.check}</strong><p>{item.value} / 제한 {item.limit} {item.unit} · {item.violated?'초과':'범위 내'} · {item.severity}</p><p>{item.instance || item.net || '대상 미기록'} · ({item.x_um}, {item.y_um}) µm</p></li>)}</ul>
      <p className="text-xs break-all">원본 SHA-256: {preview.source_sha256}</p>
      <button className="btn btn-primary" disabled={pending} onClick={async()=>{setPending(true);setError('');try{const run=await api.importCommercialEmir(projectId,form);setSaved(run.id);await Promise.all([qc.invalidateQueries({queryKey:['runs',projectId]}),qc.invalidateQueries({queryKey:['gate',projectId]})]);}catch(reason){setError((reason as Error).message);}finally{setPending(false);}}}>{pending?'저장 중…':'런으로 저장'}</button>
    </section>}
  </section>;
}
