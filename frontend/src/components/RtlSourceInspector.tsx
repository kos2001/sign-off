import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, type RunEvidence } from '../api';
import { diagnosticLinkProblem, rtlDiagnostics, sourceMapping } from '../rtlDiagnostics';

const labels = { lint: '기본 린트', width: '폭 검사', synthesize: '합성' };

export function RtlSourceInspector({ evidence }: { evidence: RunEvidence }) {
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
      if (blob.size > 2 * 1024 * 1024) throw new Error('소스 탐색의 크기 제한을 초과했습니다.');
      const text = await blob.text();
      if (text !== evidence.source_text) throw new Error('실행 근거와 다운로드한 소스가 다릅니다. 근거를 다시 불러오세요.');
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
    : source.isSuccess && source.data !== evidence.source_text ? '실행 근거와 확인된 소스가 다릅니다. 원본을 다시 확인하세요.' : null;
  const start = Math.max(1, line - 10);
  const end = Math.min(mapping.lines.length, start + 39);
  const validInput = /^\d+$/.test(lineInput) && Number.isSafeInteger(Number(lineInput)) && Number(lineInput) >= 1 && Number(lineInput) <= mapping.lines.length;
  function jump(target: number) {
    setLine(target); setLineInput(String(target)); setOpened(true);
    if (source.isSuccess) { codeRef.current?.focus(); codeRef.current?.scrollIntoView({ block: 'nearest' }); }
  }
  return <section aria-label="RTL 진단과 소스 탐색" className="space-y-3 min-w-0">
    <h4 className="font-semibold">RTL 진단과 소스 탐색</h4>
    <p>저장된 도구 로그의 위치 진단입니다. 선택하면 원본 일치를 확인한 뒤 해당 줄을 표시합니다. 열 번호는 도구 표기를 유지하며 줄 단위로 이동합니다.</p>
    <p className="text-[var(--text-muted)]">지원 형식: Verilator 오류·경고 및 Yosys 파일:줄 진단. 연결되지 않는 진단과 전체 내용은 아래 원본 로그에서 확인하세요. 소스 조회는 읽기 전용이며 AI를 호출하지 않습니다.</p>
    {diagnostics.truncated && <p role="status">위치 진단은 최대 200개까지 표시합니다. 전체 진단은 원본 로그를 확인하세요.</p>}
    {!diagnostics.items.length ? <p>직접 연결할 위치 진단이 없습니다.</p> : <>
      <ol className="space-y-2" start={page * 10 + 1}>
        {diagnostics.items.slice(page * 10, (page + 1) * 10).map((item, index) => {
          const problem = diagnosticLinkProblem(item, mapping);
          return <li key={`${page}-${index}`} className="rounded-lg bg-[var(--surface-2)] p-2 min-w-0">
            <div className="flex flex-wrap items-center gap-2"><strong>{labels[item.tool]} · {item.severity}{item.code ? `-${item.code}` : ''}</strong>
              <button className="btn btn-ghost break-all whitespace-normal" disabled={!!problem} onClick={() => jump(item.line)}>{item.file}:{item.line}{item.column === null ? '' : `:${item.column}`} 줄 보기</button>
            </div>
            {problem && <p>{problem}</p>}
            <p className="whitespace-pre-wrap [overflow-wrap:anywhere]">{item.message}</p>
          </li>;
        })}
      </ol>
      <div className="flex flex-wrap items-center gap-2">
        <button className="btn btn-ghost" disabled={page === 0} onClick={() => setPage(page - 1)}>이전 진단</button>
        <span role="status">위치 진단 {page * 10 + 1}–{Math.min((page + 1) * 10, diagnostics.items.length)} / {diagnostics.items.length}</span>
        <button className="btn btn-ghost" disabled={(page + 1) * 10 >= diagnostics.items.length} onClick={() => setPage(page + 1)}>다음 진단</button>
      </div>
    </>}
    <button className="btn btn-ghost" disabled={!evidence.source_text} aria-expanded={opened} onClick={() => setOpened(!opened)}>번호가 있는 소스 {opened ? '접기' : '보기'}</button>
    {opened && (source.isPending ? <p role="status">원본 일치 확인 중…</p> : sourceError ? <p role="alert">{sourceError} <button className="btn btn-ghost" onClick={() => source.refetch()}>원본 다시 확인</button></p> : <div className="space-y-2">
      <p role="status">저장된 원본 일치 확인 · 읽기 전용 · 선택 {line}줄 / {mapping.lines.length}줄</p>
      {mapping.remapped && <p>`line 지시문이 있어 진단의 자동 줄 연결을 사용하지 않습니다. 아래는 저장된 파일의 실제 줄 번호입니다.</p>}
      <form className="flex flex-wrap items-center gap-2" onSubmit={event => { event.preventDefault(); if (validInput) jump(Number(lineInput)); }}>
        <label>줄 번호 <input className="input w-24" inputMode="numeric" value={lineInput} onChange={event => setLineInput(event.target.value)} /></label>
        <button className="btn btn-ghost" disabled={!validInput}>줄로 이동</button>
        <button type="button" className="btn btn-ghost" disabled={line <= 1} onClick={() => jump(Math.max(1, line - 30))}>이전 소스</button>
        <button type="button" className="btn btn-ghost" disabled={end >= mapping.lines.length} onClick={() => jump(Math.min(mapping.lines.length, line + 30))}>다음 소스</button>
      </form>
      <p>표시 {start}–{end}줄 · 전체 파일은 원본 다운로드에서 확인할 수 있습니다.</p>
      <pre ref={codeRef} tabIndex={0} aria-label={`RTL 소스 · 선택 ${line}줄`} className="max-h-96 max-w-full overflow-auto rounded-lg bg-[var(--surface-2)] p-3">
        {mapping.lines.slice(start - 1, end).map((text, offset) => <span key={start + offset} data-line={start + offset} aria-current={start + offset === line ? 'location' : undefined} className={`block min-w-max ${start + offset === line ? 'bg-[var(--seq-700)] border-l-2 border-[var(--series-1)]' : ''}`}><span className="inline-block w-12 select-none text-[var(--text-muted)]">{start + offset}</span>{text || ' '}</span>)}
      </pre>
    </div>)}
  </section>;
}
