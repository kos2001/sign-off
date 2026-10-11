import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useParams, useSearchParams } from 'react-router';
import { api, type StructureBit } from '../api';
import { tr, useLanguage } from '../components/LanguageProvider';

function bitLabel(bit: StructureBit) { return typeof bit === 'number' ? tr(`신호 #${bit}`, `Signal #${bit}`) : tr(`상수 ${bit}`, `Constant ${bit}`); }
function pageNumber(value: string | null, total: number) {
  const page = Number(value);
  return Number.isSafeInteger(page) && page >= 0 ? Math.min(page, Math.max(0, Math.ceil(total / 20) - 1)) : 0;
}

function BitVector({ values, choose }: { values: StructureBit[]; choose: (bit: StructureBit) => void }) {
  const { t } = useLanguage();
  const [page, setPage] = useState(0);
  useEffect(() => setPage(0), [values]);
  return <details><summary className="cursor-pointer">{t(`${values.length}비트 연결 보기`, `View ${values.length}-bit connections`)}</summary><div className="mt-2 space-y-2">
    <div className="flex flex-wrap gap-1">{values.slice(page * 32, (page + 1) * 32).map((bit, index) => <button key={index} className="btn btn-ghost" onClick={() => choose(bit)}>{page * 32 + index}: {bitLabel(bit)}</button>)}</div>
    {values.length > 32 && <div className="flex flex-wrap gap-2"><button className="btn btn-ghost" disabled={!page} onClick={() => setPage(page - 1)}>{t('이전 비트', 'Previous bits')}</button><span>{page * 32}–{Math.min(values.length, (page + 1) * 32) - 1}</span><button className="btn btn-ghost" disabled={(page + 1) * 32 >= values.length} onClick={() => setPage(page + 1)}>{t('다음 비트', 'Next bits')}</button></div>}
  </div></details>;
}

export default function DesignStructure() {
  const { t } = useLanguage();
  const runId = Number(useParams().runId);
  const [params, setParams] = useSearchParams();
  const validId = Number.isSafeInteger(runId) && runId > 0;
  const result = useQuery({ queryKey: ['run-structure', runId], queryFn: () => api.runStructure(runId), enabled: validId, retry: false });
  const moduleName = params.get('module') ?? result.data?.top_module ?? '';
  const modules = useMemo(() => new Map(Object.entries(result.data?.design.modules ?? {})), [result.data]);
  const module = modules.get(moduleName);
  const cells = useMemo(() => new Map(Object.entries(module?.cells ?? {})), [module]);
  const q = (params.get('q') ?? '').slice(0, 200);
  const [search, setSearch] = useState(q);
  useEffect(() => setSearch(q), [q]);
  const filtered = useMemo(() => [...cells].filter(([name, cell]) => `${name} ${cell.type}`.toLowerCase().includes(q.toLowerCase())), [cells, q]);
  const page = pageNumber(params.get('page'), filtered.length);
  const selectedName = params.get('cell');
  const cell = selectedName === null ? undefined : cells.get(selectedName);
  const ports = Object.entries(module?.ports ?? {});
  const portPage = pageNumber(params.get('ports'), ports.length);
  let signal: StructureBit | undefined;
  try {
    const value: unknown = JSON.parse(params.get('signal') ?? 'null');
    if (typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 || typeof value === 'string' && ['0','1','x','z'].includes(value)) signal = value as StructureBit;
  } catch { /* Invalid locations stay unselected. */ }
  const connections = useMemo(() => {
    if (!module || signal === undefined) return [];
    const matches: { owner: string | null; port: string; direction: string }[] = [];
    for (const [name, port] of Object.entries(module.ports)) if (port.bits.includes(signal)) matches.push({ owner: null, port: name, direction: port.direction });
    for (const [name, instance] of Object.entries(module.cells)) for (const [port, bits] of Object.entries(instance.connections)) if (bits.includes(signal)) matches.push({ owner: name, port, direction: instance.port_directions[port] });
    return matches;
  }, [module, signal]);
  const aliases = useMemo(() => signal === undefined ? [] : Object.entries(module?.netnames ?? {}).filter(([, net]) => net.bits.includes(signal)).map(([name]) => name), [module, signal]);
  const connectionPage = pageNumber(params.get('connections'), connections.length);
  const aliasPage = pageNumber(params.get('aliases'), aliases.length);
  const cellPorts = Object.entries(cell?.connections ?? {});
  const cellPortPage = pageNumber(params.get('cell_ports'), cellPorts.length);
  const cellRegion = useRef<HTMLElement>(null);
  const signalRegion = useRef<HTMLElement>(null);
  useEffect(() => { if (selectedName !== null && result.data) { cellRegion.current?.focus(); cellRegion.current?.scrollIntoView({ block: 'start' }); } }, [selectedName, moduleName, result.data]);
  useEffect(() => { if (signal !== undefined && result.data) { signalRegion.current?.focus(); signalRegion.current?.scrollIntoView({ block: 'start' }); } }, [signal, moduleName, result.data]);

  function update(values: Record<string, string | null>) {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(values)) value === null ? next.delete(key) : next.set(key, value);
    setParams(next);
  }
  function chooseModule(name: string) { setParams({ module: name }); }
  function chooseCell(name: string, keepSignal = false) {
    update({ cell: name, cell_ports: null, ...(keepSignal ? {} : { signal: null, connections: null }) });
    if (selectedName === name) { cellRegion.current?.focus(); cellRegion.current?.scrollIntoView({ block: 'start' }); }
  }
  function chooseSignal(bit: StructureBit) {
    update({ signal: JSON.stringify(bit), connections: null, aliases: null });
    if (signal === bit) { signalRegion.current?.focus(); signalRegion.current?.scrollIntoView({ block: 'start' }); }
  }
  function bits(values: StructureBit[]) {
    return <BitVector values={values} choose={chooseSignal} />;
  }
  function pager(key: string, current: number, total: number) {
    return <div className="mt-3 flex flex-wrap items-center gap-2">
      <button className="btn btn-ghost" disabled={!current} onClick={() => update({ [key]: String(current - 1) })}>{t('이전', 'Previous')}</button>
      <span>{total ? current * 20 + 1 : 0}–{Math.min((current + 1) * 20, total)} / {total}</span>
      <button className="btn btn-ghost" disabled={(current + 1) * 20 >= total} onClick={() => update({ [key]: String(current + 1) })}>{t('다음', 'Next')}</button>
    </div>;
  }
  if (!validId) return <p role="alert">{t('올바른 런 번호가 필요합니다.', 'A valid run number is required.')}</p>;
  if (result.isPending) return <p role="status">{t('합성 구조와 원본 일치 확인 중…', 'Verifying synthesized structure against the original…')}</p>;
  if (result.isError) return <div role="alert">{result.error.message} <button className="btn btn-ghost" onClick={() => result.refetch()}>{t('다시 시도', 'Retry')}</button></div>;
  return <div className="space-y-5 text-sm min-w-0">
    <header className="space-y-2">
      <Link className="text-[var(--series-1)]" to={`/projects/${result.data.project_id}`}>{t('프로젝트로 돌아가기', 'Back to project')}</Link>
      <h1 className="text-xl font-semibold">{t(`런 #${runId} · 합성 구조 탐색`, `Run #${runId} · Synthesized structure explorer`)}</h1>
      <p>{t('Yosys 합성 결과의 모듈 정의와 연결입니다. 반복 인스턴스는 같은 모듈 정의로 이동합니다. 배치 좌표·타이밍 분석이나 전체 사인오프 완료를 나타내지 않습니다.', 'Module definitions and connectivity from Yosys synthesis. Repeated instances lead to the same module definition. This does not represent placement coordinates, timing analysis, or completion of full sign-off.')}</p>
      <p>{t('읽기 전용 · 원본과 구조 무결성 확인 · AI 개입 없음', 'Read-only · Source and structure integrity verified · No AI involvement')}</p>
      <p className="break-all text-xs text-[var(--text-muted)]">{t('구조 SHA-256', 'Structure SHA-256')}: {result.data.structure_sha256}</p>
    </header>
    <section className="card p-4 space-y-3 min-w-0" aria-label={t('모듈 선택', 'Module selection')}>
      <label className="block">{t('모듈 정의', 'Module definitions')} ({modules.size}) <select className="input w-full" value={moduleName} onChange={event => chooseModule(event.target.value)}>
        {!modules.has(moduleName) && <option value={moduleName}>{t('찾을 수 없는 모듈', 'Module not found')}: {moduleName}</option>}
        {[...modules.keys()].map(name => <option key={name} value={name}>{name}{name === result.data.top_module ? t(' · 최상위', ' · top') : ''}</option>)}
      </select></label>
      <button className="btn btn-ghost" onClick={() => chooseModule(result.data.top_module)}>{t('최상위 모듈로 이동', 'Go to top module')}</button>
      {module && <p className="break-all">{moduleName} · {t(`포트 ${ports.length}개 · 직접 인스턴스/셀 ${cells.size}개`, `${ports.length} ports · ${cells.size} direct instances/cells`)}</p>}
    </section>
    {!module ? <p role="alert">{t('선택한 모듈 정의가 없습니다.', 'The selected module definition does not exist.')}</p> : <>
      <section className="card p-4 space-y-3 min-w-0" aria-label={t('모듈 포트', 'Module ports')}>
        <h2 className="font-semibold">{t('모듈 포트', 'Module ports')}</h2>
        <p className="text-xs text-[var(--text-muted)]">{t('신호 ID는 현재 모듈 정의 안에서만 유효합니다. 연결 벡터의 0번은 최하위 비트이며 원래 선언의 첨자와 다를 수 있습니다.', 'Signal IDs are valid only within the current module definition. Index 0 of a connection vector is the least significant bit and may differ from the original declared index.')}</p>
        {ports.slice(portPage * 20, (portPage + 1) * 20).map(([name, port]) => <div key={name} className="border-b border-[var(--border)] pb-2"><strong className="break-all">{name}</strong> · {port.direction}{bits(port.bits)}</div>)}
        {pager('ports', portPage, ports.length)}
      </section>
      <section className="card p-4 space-y-3 min-w-0" aria-label={t('셀 목록', 'Cell list')}>
        <h2 className="font-semibold">{t('셀과 하위 모듈 인스턴스', 'Cells and submodule instances')}</h2>
        <form className="flex flex-wrap gap-2" onSubmit={event => { event.preventDefault(); update({ q: search || null, page: null }); }}>
          <input className="input min-w-0 flex-1" aria-label={t('셀 이름 또는 종류 검색', 'Search cell name or type')} maxLength={200} value={search} onChange={event => setSearch(event.target.value)} />
          <button className="btn btn-ghost">{t('검색', 'Search')}</button>
        </form>
        {filtered.slice(page * 20, (page + 1) * 20).map(([name, item]) => <div key={name} className="border-b border-[var(--border)] pb-2">
          <button className="btn btn-ghost max-w-full break-all whitespace-normal text-left" onClick={() => chooseCell(name)}>{name}</button>
          <p className="break-all text-xs">{item.type} · {modules.has(item.type) ? t('하위 모듈', 'Submodule') : t('일반 합성 셀', 'Synthesized primitive cell')}</p>
        </div>)}
        {!filtered.length && <p>{t('일치하는 셀이 없습니다.', 'No matching cells.')}</p>}
        {pager('page', page, filtered.length)}
      </section>
      {selectedName !== null && <section className="card p-4 space-y-3 min-w-0" aria-label={t('선택 셀', 'Selected cell')} ref={cellRegion} tabIndex={-1}>
        <h2 className="font-semibold break-all">{t('선택 셀', 'Selected cell')}: {selectedName}</h2>
        {!cell ? <p role="alert">{t('현재 모듈에 해당 셀이 없습니다.', 'This cell does not exist in the current module.')}</p> : <>
          <p className="break-all">{t('종류', 'Type')}: {cell.type}</p>
          {modules.has(cell.type) && <button className="btn btn-ghost" onClick={() => chooseModule(cell.type)}>{t('하위 모듈 정의 보기', 'View submodule definition')}</button>}
          {cellPorts.slice(cellPortPage * 20, (cellPortPage + 1) * 20).map(([name, vector]) => <div key={name} className="border-b border-[var(--border)] pb-2"><strong className="break-all">{name}</strong> · {cell.port_directions[name]}{bits(vector)}</div>)}
          {pager('cell_ports', cellPortPage, cellPorts.length)}
        </>}
      </section>}
      {signal !== undefined && <section className="card p-4 space-y-3 min-w-0" aria-label={t('선택 신호 연결', 'Selected signal connections')} ref={signalRegion} tabIndex={-1}>
        <h2 className="font-semibold">{bitLabel(signal)} · {t('현재 모듈의 연결', 'Connections in current module')}</h2>
        <details><summary className="cursor-pointer">{t(`같은 비트를 포함한 신호 이름 ${aliases.length}개`, `${aliases.length} signal names containing this bit`)}</summary><div className="max-h-48 overflow-auto break-all">{aliases.slice(aliasPage * 20, (aliasPage + 1) * 20).map(name => <p key={name}>{name}</p>)}</div>{pager('aliases', aliasPage, aliases.length)}</details>
        <p className="text-xs">{t('방향은 각 포트 기준입니다. 모듈 입력은 내부로 값을 공급합니다. 상수 선택은 같은 상수 값의 사용 위치를 표시합니다.', 'Direction is relative to each port. Module inputs drive values into the module. Selecting a constant shows where that constant value is used.')}</p>
        {connections.slice(connectionPage * 20, (connectionPage + 1) * 20).map((item, index) => <div key={index} className="border-b border-[var(--border)] pb-2">
          {item.owner === null ? <strong>{t('모듈 포트', 'Module port')}</strong> : <button className="btn btn-ghost max-w-full break-all whitespace-normal" onClick={() => item.owner !== null && chooseCell(item.owner, true)}>{item.owner}</button>}
          <p className="break-all">{item.port} · {item.direction}</p>
        </div>)}
        {!connections.length && <p>{t('이 신호 ID에 연결된 포트가 없습니다.', 'No ports are connected to this signal ID.')}</p>}
        {pager('connections', connectionPage, connections.length)}
      </section>}
    </>}
  </div>;
}
