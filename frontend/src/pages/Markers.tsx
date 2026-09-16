import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useParams, useSearchParams } from 'react-router';
import { api } from '../api';
import { MarkerViolationReview } from '../components/MarkerViolationReview';
import { RunEvidencePanel } from '../components/RunEvidencePanel';

function index(value: string | null) { const n = Number(value); return Number.isInteger(n) && n >= 0 && n <= 1000 ? n : 0; }
export default function Markers() {
  const runId = Number(useParams().runId);
  const [params, setParams] = useSearchParams();
  const q = (params.get('q') ?? '').slice(0, 200);
  const [search, setSearch] = useState(q);
  useEffect(() => setSearch(q), [q]);
  const offset = index(params.get('offset'));
  const selected = index(params.get('selected'));
  const filters = { q, offset: String(offset), limit: '25',
    ...(params.has('category') ? { category: params.get('category')!.slice(0, 2000) } : {}),
    ...(params.has('cell') ? { cell: params.get('cell')!.slice(0, 200) } : {}) };
  const list = useQuery({ queryKey: ['markers', runId, filters], queryFn: () => api.markers(runId, filters) });
  const detail = useQuery({ queryKey: ['marker', runId, selected], queryFn: () => api.marker(runId, selected), enabled: selected > 0 && !!list.data, refetchInterval: selected > 0 ? 5000 : false });
  const detailRegion = useRef<HTMLElement>(null);
  const hasDetail = !!detail.data;
  useEffect(() => { if (selected && hasDetail) { detailRegion.current?.focus({ preventScroll: true }); detailRegion.current?.scrollIntoView({ block: 'start' }); } }, [selected, hasDetail, runId]);
  function change(key: string, value: string | null) {
    setParams(previous => {
      const next = new URLSearchParams(previous);
      if (value === null) next.delete(key); else next.set(key, value);
      if (key !== 'selected') next.delete('selected');
      if (key !== 'offset' && key !== 'selected') next.delete('offset');
      return next;
    });
  }
  if (list.isPending) return <p role="status">마커 불러오는 중…</p>;
  if (list.isError) return <p role="alert">{list.error.message} <button className="btn btn-ghost" onClick={() => void list.refetch()}>다시 시도</button></p>;
  const data = list.data;
  const item = detail.data?.item;
  const geometry = detail.data?.geometry;
  return <section className="max-w-6xl space-y-5">
    <header className="space-y-2"><Link className="underline" to={`/projects/${data.run.project_id}`}>프로젝트로 돌아가기</Link><h1 className="text-xl font-bold">DRC 마커 탐색 · 런 #{runId}</h1></header>
    <p>보관된 마커를 탐색합니다. 도형은 보고된 셀 좌표의 미리보기이며 실제 레이아웃이나 전체 DRC 검증 결과가 아닙니다. 조회에는 AI가 개입하지 않습니다. 연결된 위반의 상태 변경은 아래 별도 검토 절차로 처리합니다.</p>
    <RunEvidencePanel key={runId} run={data.run} />
    <form className="flex flex-wrap gap-2" onSubmit={event => { event.preventDefault(); change('q', search || null); }}>
      <label className="flex-1 min-w-0">마커 검색<input className="input w-full" value={search} maxLength={200} onChange={event => setSearch(event.target.value)} placeholder="규칙·셀·값·태그·댓글" /></label>
      <button className="btn btn-primary self-end">검색</button>
    </form>
    <div className="grid gap-3 sm:grid-cols-2">{(['category', 'cell'] as const).map(key => <label className="min-w-0" key={key}>{key === 'category' ? '규칙 분류' : '셀'}<select aria-label={key === "category" ? "규칙 분류" : "셀"} className="input w-full" value={params.has(key) ? JSON.stringify(params.get(key)) : 'all'} onChange={event => change(key, event.target.value === 'all' ? null : JSON.parse(event.target.value))}>
      <option value="all">전체</option>{(key === 'category' ? data.categories : data.cells).map(option => <option key={option.value} value={JSON.stringify(option.value)}>{option.value || '전체 셀 마커'} ({option.count})</option>)}
    </select></label>)}</div>
    <p className="text-sm text-[var(--text-muted)]">필터 괄호의 개수는 전체 보고서 기준입니다. 목록은 보고서 순서이며 중복 마커를 합치지 않습니다.</p>
    <p role="status">검색 결과 {data.total} / 보고된 마커 {data.reported_total}개 · 검색 결과의 중복 발생 수 합계 {data.matched_multiplicity}</p>
    {!data.total && <p>조건에 맞는 마커가 없습니다. 검색 조건을 변경하세요.</p>}
    <ul className="grid gap-2 sm:grid-cols-2">{data.items.map(marker => <li key={marker.index}><button className="btn btn-ghost block w-full text-left whitespace-normal break-words" aria-pressed={selected === marker.index} onClick={() => change('selected', String(marker.index))}>마커 #{marker.index} · {marker.category}<br />셀: {marker.cell || '전체 셀'} · 중복 발생 수: {marker.multiplicity}</button></li>)}</ul>
    <div className="flex flex-wrap gap-2"><button className="btn btn-ghost" disabled={offset === 0} onClick={() => change('offset', String(Math.max(0, offset-25)))}>이전 마커</button><button className="btn btn-ghost" disabled={offset+25 >= data.total} onClick={() => change('offset', String(offset+25))}>다음 마커</button></div>
    {selected > 0 && <section aria-label="DRC 마커 상세" ref={detailRegion} tabIndex={-1} className="rounded-xl border border-[var(--border)] p-4 space-y-3">
      {detail.isPending ? <p role="status">마커 상세 불러오는 중…</p> : detail.isError ? <p role="alert">{detail.error.message} <button className="btn btn-ghost" onClick={() => void detail.refetch()}>상세 다시 시도</button></p> : item && geometry && <>
        <h2 className="font-semibold break-words">마커 #{item.index} · {item.category}</h2><p>셀: {item.cell || '전체 셀'} · 보고된 중복 발생 수: {item.multiplicity}</p>
        <p>현재 검색과 독립적으로 선택한 원본 마커입니다. 좌표 단위 µm, X는 오른쪽·Y는 위쪽입니다. 셀 계층 변환을 적용하지 않습니다.</p>
        {geometry.shapes.length > 0 ? <svg role="img" aria-label={`마커 #${item.index} 셀 좌표 미리보기`} viewBox="0 0 200 200" className="w-full max-w-md aspect-square border border-[var(--border)] bg-[var(--surface-2)]">
          <title>선택한 마커의 셀 좌표 도형 · µm</title>
          {geometry.shapes.map(shape => <g key={shape.value_index}>
            <path d={shape.contours.map(contour => contour.map((point, i) => `${i ? 'L' : 'M'} ${point[0]} ${point[1]}`).join(' ') + (shape.closed ? ' Z' : '')).join(' ')} fill={shape.closed ? 'var(--series-1)' : 'none'} fillOpacity={0.15} fillRule="evenodd" stroke="var(--series-1)" strokeWidth={1.5} />
            {!shape.closed && shape.contours.flatMap((contour, ci) => contour.map((point, pi) => <circle key={`${ci}-${pi}`} cx={point[0]} cy={point[1]} r={2} fill="var(--series-1)" />))}
            {shape.closed && shape.contours.flat().every(point => point[0] === shape.contours[0][0][0] && point[1] === shape.contours[0][0][1]) && <circle cx={shape.contours[0][0][0]} cy={shape.contours[0][0][1]} r={2} fill="var(--series-1)" />}
          </g>)}
        </svg> : <p>표시 가능한 기하 값이 없습니다. 아래 원문을 확인하세요.</p>}
        {geometry.bounds_um && <p className="break-words">표시 범위 (µm): X {geometry.bounds_um.xmin} ~ {geometry.bounds_um.xmax} · Y {geometry.bounds_um.ymin} ~ {geometry.bounds_um.ymax}</p>}
        <p>도형으로 표시한 값 {geometry.rendered_values} / {item.values.length}개. box·edge·edge-pair·polygon을 지원하며 레이아웃 배경은 포함하지 않습니다.</p>
        {!!geometry.unrendered_values.length && <p>표시하지 않은 값 번호: {geometry.unrendered_values.join(', ')}. 텍스트·미지원 형식·범위 초과 값은 원문으로 확인하세요.</p>}
        <p className="break-words">원본 태그: {item.tags || '없음'} · 서비스 승인 상태가 아닙니다.</p><p className="whitespace-pre-wrap break-words">댓글: {item.comment || '없음'}</p>
        <ol className="space-y-2">{item.values.map((value, i) => <li key={i} className="rounded bg-[var(--surface-2)] p-2"><strong>값 #{i+1}</strong><pre className="whitespace-pre-wrap break-words">{value}</pre></li>)}</ol>
        <MarkerViolationReview key={`${runId}-${selected}`} runId={runId} projectId={data.run.project_id} matches={detail.data!.violation_matches} onChange={() => { void detail.refetch(); }} />
      </>}
    </section>}
  </section>;
}
