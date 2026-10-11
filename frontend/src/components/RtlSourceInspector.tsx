import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, type RunEvidence } from '../api';
import { diagnosticLinkProblem, rtlDiagnostics, sourceMapping } from '../rtlDiagnostics';
import { tr, useLanguage } from './LanguageProvider';

const labels = { lint: () => tr('기본 린트', 'Basic lint'), width: () => tr('폭 검사', 'Width check'), synthesize: () => tr('합성', 'Synthesis') };

export function RtlSourceInspector({ evidence }: { evidence: RunEvidence }) {
  const { t } = useLanguage();
  const diagnostics = useMemo(() => rtlDiagnostics(evidence.result.tool_runs), [evidence.result.tool_runs]);
  const mapping = useMemo(() => sourceMapping(evidence.source_text), [evidence.source_text]);
  const [opened, setOpened] = useState(false);
  const [line, setLine] = useState(1);
  const [lineInput, setLineInput] = useState('1');
  const [page, setPage] = useState(0);
  const codeRef = useRef<HTMLPreElement>(null);
  const source = useQuery({
    queryKey: ['rtl-source-inspector', evidence.run_id, evidence.source_sha256],
    enabled: opened,
    queryFn: async () => {
      const blob = await api.runSource(evidence.run_id);
      if (blob.size > 2 * 1024 * 1024) throw new Error(tr('소스 탐색의 크기 제한을 초과했습니다.', 'The source exceeds the source browser size limit.'));
      const text = await blob.text();
      if (text !== evidence.source_text) throw new Error(tr('실행 근거와 다운로드한 소스가 다릅니다. 근거를 다시 불러오세요.', 'The downloaded source does not match the run evidence. Reload the evidence.'));
      return text;
    },
    retry: false,
  });
  useEffect(() => {
    if (opened && source.isSuccess) {
      codeRef.current?.focus();
      codeRef.current?.scrollIntoView({ block: 'nearest' });
    }
  }, [opened, line, source.isSuccess]);
  const sourceError = source.isError ? source.error.message
    : source.isSuccess && source.data !== evidence.source_text ? t('실행 근거와 확인된 소스가 다릅니다. 원본을 다시 확인하세요.', 'The verified source does not match the run evidence. Check the original again.') : null;
  const start = Math.max(1, line - 10);
  const end = Math.min(mapping.lines.length, start + 39);
  const validInput = /^\d+$/.test(lineInput) && Number.isSafeInteger(Number(lineInput)) && Number(lineInput) >= 1 && Number(lineInput) <= mapping.lines.length;
  function jump(target: number) {
    setLine(target); setLineInput(String(target)); setOpened(true);
    if (source.isSuccess) { codeRef.current?.focus(); codeRef.current?.scrollIntoView({ block: 'nearest' }); }
  }
  return <section aria-label={t('RTL 진단과 소스 탐색', 'RTL diagnostics and source browser')} className="space-y-3 min-w-0">
    <h4 className="font-semibold">{t('RTL 진단과 소스 탐색', 'RTL diagnostics and source browser')}</h4>
    <p>{t('저장된 도구 로그의 위치 진단입니다. 선택하면 원본 일치를 확인한 뒤 해당 줄을 표시합니다. 열 번호는 도구 표기를 유지하며 줄 단위로 이동합니다.', 'Location diagnostics from the stored tool logs. Selecting one verifies the source matches the original, then shows that line. Column numbers are kept as the tool reported them; navigation is by line.')}</p>
    <p className="text-[var(--text-muted)]">{t('지원 형식: Verilator 오류·경고 및 Yosys 파일:줄 진단. 연결되지 않는 진단과 전체 내용은 아래 원본 로그에서 확인하세요. 소스 조회는 읽기 전용이며 AI를 호출하지 않습니다.', 'Supported formats: Verilator errors and warnings, and Yosys file:line diagnostics. See the raw logs below for unlinked diagnostics and full output. Source viewing is read-only and does not call AI.')}</p>
    {diagnostics.truncated && <p role="status">{t('위치 진단은 최대 200개까지 표시합니다. 전체 진단은 원본 로그를 확인하세요.', 'Up to 200 location diagnostics are shown. See the raw logs for all diagnostics.')}</p>}
    {!diagnostics.items.length ? <p>{t('직접 연결할 위치 진단이 없습니다.', 'No location diagnostics to link directly.')}</p> : <>
      <ol className="space-y-2" start={page * 10 + 1}>
        {diagnostics.items.slice(page * 10, (page + 1) * 10).map((item, index) => {
          const problem = diagnosticLinkProblem(item, mapping);
          return <li key={`${page}-${index}`} className="rounded-lg bg-[var(--surface-2)] p-2 min-w-0">
            <div className="flex flex-wrap items-center gap-2"><strong>{labels[item.tool]()} · {item.severity}{item.code ? `-${item.code}` : ''}</strong>
              <button className="btn btn-ghost break-all whitespace-normal" disabled={!!problem} onClick={() => jump(item.line)}>{item.file}:{item.line}{item.column === null ? '' : `:${item.column}`} {t('줄 보기', '· Show line')}</button>
            </div>
            {problem && <p>{problem}</p>}
            <p className="whitespace-pre-wrap [overflow-wrap:anywhere]">{item.message}</p>
          </li>;
        })}
      </ol>
      <div className="flex flex-wrap items-center gap-2">
        <button className="btn btn-ghost" disabled={page === 0} onClick={() => setPage(page - 1)}>{t('이전 진단', 'Previous diagnostics')}</button>
        <span role="status">{t('위치 진단', 'Location diagnostics')} {page * 10 + 1}–{Math.min((page + 1) * 10, diagnostics.items.length)} / {diagnostics.items.length}</span>
        <button className="btn btn-ghost" disabled={(page + 1) * 10 >= diagnostics.items.length} onClick={() => setPage(page + 1)}>{t('다음 진단', 'Next diagnostics')}</button>
      </div>
    </>}
    <button className="btn btn-ghost" disabled={!evidence.source_text} aria-expanded={opened} onClick={() => setOpened(!opened)}>{opened ? t('번호가 있는 소스 접기', 'Hide numbered source') : t('번호가 있는 소스 보기', 'Show numbered source')}</button>
    {opened && (source.isPending ? <p role="status">{t('원본 일치 확인 중…', 'Verifying source against original…')}</p> : sourceError ? <p role="alert">{sourceError} <button className="btn btn-ghost" onClick={() => source.refetch()}>{t('원본 다시 확인', 'Verify again')}</button></p> : <div className="space-y-2">
      <p role="status">{t(`저장된 원본 일치 확인 · 읽기 전용 · 선택 ${line}줄 / ${mapping.lines.length}줄`, `Matches stored original · read-only · line ${line} of ${mapping.lines.length}`)}</p>
      {mapping.remapped && <p>{t('`line 지시문이 있어 진단의 자동 줄 연결을 사용하지 않습니다. 아래는 저장된 파일의 실제 줄 번호입니다.', 'The source contains `line directives, so diagnostics are not linked to lines automatically. Line numbers below are the actual lines of the stored file.')}</p>}
      <form className="flex flex-wrap items-center gap-2" onSubmit={event => { event.preventDefault(); if (validInput) jump(Number(lineInput)); }}>
        <label>{t('줄 번호', 'Line number')} <input className="input w-24" inputMode="numeric" value={lineInput} onChange={event => setLineInput(event.target.value)} /></label>
        <button className="btn btn-ghost" disabled={!validInput}>{t('줄로 이동', 'Go to line')}</button>
        <button type="button" className="btn btn-ghost" disabled={line <= 1} onClick={() => jump(Math.max(1, line - 30))}>{t('이전 소스', 'Previous lines')}</button>
        <button type="button" className="btn btn-ghost" disabled={end >= mapping.lines.length} onClick={() => jump(Math.min(mapping.lines.length, line + 30))}>{t('다음 소스', 'Next lines')}</button>
      </form>
      <p>{t(`표시 ${start}–${end}줄 · 전체 파일은 원본 다운로드에서 확인할 수 있습니다.`, `Showing lines ${start}–${end} · Download the original to see the full file.`)}</p>
      <pre ref={codeRef} tabIndex={0} aria-label={t(`RTL 소스 · 선택 ${line}줄`, `RTL source · line ${line} selected`)} className="max-h-96 max-w-full overflow-auto rounded-lg bg-[var(--surface-2)] p-3">
        {mapping.lines.slice(start - 1, end).map((text, offset) => <span key={start + offset} data-line={start + offset} aria-current={start + offset === line ? 'location' : undefined} className={`block min-w-max ${start + offset === line ? 'bg-[var(--seq-700)] border-l-2 border-[var(--series-1)]' : ''}`}><span className="inline-block w-12 select-none text-[var(--text-muted)]">{start + offset}</span>{text || ' '}</span>)}
      </pre>
    </div>)}
  </section>;
}
