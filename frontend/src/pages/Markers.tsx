import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useParams, useSearchParams } from 'react-router';
import { api } from '../api';
import { MarkerGeometryViewer } from '../components/MarkerGeometryViewer';
import { MarkerViolationReview } from '../components/MarkerViolationReview';
import { RunEvidencePanel } from '../components/RunEvidencePanel';
import { useLanguage } from '../components/LanguageProvider';

function index(value: string | null) { const n = Number(value); return Number.isInteger(n) && n >= 0 && n <= 1000 ? n : 0; }
export default function Markers() {
  const { t } = useLanguage();
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
  if (list.isPending) return <p role="status">{t('마커 불러오는 중…', 'Loading markers…')}</p>;
  if (list.isError) return <p role="alert">{list.error.message} <button className="btn btn-ghost" onClick={() => void list.refetch()}>{t('다시 시도', 'Try again')}</button></p>;
  const data = list.data;
  const item = detail.data?.item;
  const geometry = detail.data?.geometry;
  return <section className="max-w-6xl space-y-5">
    <header className="space-y-2"><Link className="underline" to={`/projects/${data.run.project_id}`}>{t('프로젝트로 돌아가기', 'Back to project')}</Link><h1 className="text-xl font-bold">{t(`DRC 마커 탐색 · 런 #${runId}`, `DRC marker explorer · run #${runId}`)}</h1></header>
    <p>{t('보관된 마커를 탐색합니다. 도형은 보고된 셀 좌표의 미리보기이며 실제 레이아웃이나 전체 DRC 검증 결과가 아닙니다. 조회에는 AI가 개입하지 않습니다. 연결된 위반의 상태 변경은 아래 별도 검토 절차로 처리합니다.', 'Browse archived markers. Shapes preview the reported cell geometry and are not the actual layout or a full DRC verification result. No AI is involved in browsing. Status changes for linked violations go through the separate review below.')}</p>
    <RunEvidencePanel key={runId} run={data.run} />
    <form className="flex flex-wrap gap-2" onSubmit={event => { event.preventDefault(); change('q', search || null); }}>
      <label className="flex-1 min-w-0">{t('마커 검색', 'Search markers')}<input className="input w-full" value={search} maxLength={200} onChange={event => setSearch(event.target.value)} placeholder={t('규칙·셀·값·태그·댓글', 'Rule · cell · value · tag · comment')} /></label>
      <button className="btn btn-primary self-end">{t('검색', 'Search')}</button>
    </form>
    <div className="grid gap-3 sm:grid-cols-2">{(['category', 'cell'] as const).map(key => <label className="min-w-0" key={key}>{key === 'category' ? t('규칙 분류', 'Rule category') : t('셀', 'Cell')}<select aria-label={key === "category" ? t("규칙 분류", "Rule category") : t("셀", "Cell")} className="input w-full" value={params.has(key) ? JSON.stringify(params.get(key)) : 'all'} onChange={event => change(key, event.target.value === 'all' ? null : JSON.parse(event.target.value))}>
      <option value="all">{t('전체', 'All')}</option>{(key === 'category' ? data.categories : data.cells).map(option => <option key={option.value} value={JSON.stringify(option.value)}>{option.value || t('전체 셀 마커', 'All-cell markers')} ({option.count})</option>)}
    </select></label>)}</div>
    <p className="text-sm text-[var(--text-muted)]">{t('필터 괄호의 개수는 전체 보고서 기준입니다. 목록은 보고서 순서이며 중복 마커를 합치지 않습니다.', 'Counts in parentheses cover the whole report. The list follows report order and does not merge duplicate markers.')}</p>
    <p role="status">{t(`검색 결과 ${data.total} / 보고된 마커 ${data.reported_total}개 · 검색 결과의 중복 발생 수 합계 ${data.matched_multiplicity}`, `${data.total} results / ${data.reported_total} reported markers · total multiplicity in results ${data.matched_multiplicity}`)}</p>
    {!data.total && <p>{t('조건에 맞는 마커가 없습니다. 검색 조건을 변경하세요.', 'No markers match. Change the search filters.')}</p>}
    <ul className="grid gap-2 sm:grid-cols-2">{data.items.map(marker => <li key={marker.index}><button className="btn btn-ghost block w-full text-left whitespace-normal break-words" aria-pressed={selected === marker.index} onClick={() => change('selected', String(marker.index))}>{t('마커', 'Marker')} #{marker.index} · {marker.category}<br />{t('셀', 'Cell')}: {marker.cell || t('전체 셀', 'All cells')} · {t('중복 발생 수', 'Multiplicity')}: {marker.multiplicity}</button></li>)}</ul>
    <div className="flex flex-wrap gap-2"><button className="btn btn-ghost" disabled={offset === 0} onClick={() => change('offset', String(Math.max(0, offset-25)))}>{t('이전 마커', 'Previous markers')}</button><button className="btn btn-ghost" disabled={offset+25 >= data.total} onClick={() => change('offset', String(offset+25))}>{t('다음 마커', 'Next markers')}</button></div>
    {selected > 0 && <section aria-label={t('DRC 마커 상세', 'DRC marker details')} ref={detailRegion} tabIndex={-1} className="rounded-xl border border-[var(--border)] p-4 space-y-3">
      {detail.isPending ? <p role="status">{t('마커 상세 불러오는 중…', 'Loading marker details…')}</p> : detail.isError ? <p role="alert">{detail.error.message} <button className="btn btn-ghost" onClick={() => void detail.refetch()}>{t('상세 다시 시도', 'Retry details')}</button></p> : item && geometry && <>
        <h2 className="font-semibold break-words">{t('마커', 'Marker')} #{item.index} · {item.category}</h2><p>{t('셀', 'Cell')}: {item.cell || t('전체 셀', 'All cells')} · {t('보고된 중복 발생 수', 'Reported multiplicity')}: {item.multiplicity}</p>
        <p>{t('현재 검색과 독립적으로 선택한 원본 마커입니다. 좌표 단위 µm, X는 오른쪽·Y는 위쪽입니다. 셀 계층 변환을 적용하지 않습니다.', 'This is the source marker you selected, independent of the current search. Coordinates are in µm, with X to the right and Y up. Cell hierarchy transforms are not applied.')}</p>
        {geometry.shapes.length > 0 ? <MarkerGeometryViewer key={`${runId}-${selected}`} geometry={geometry} index={item.index} /> : <p>{t('표시 가능한 기하 값이 없습니다. 아래 원문을 확인하세요.', 'No geometry values can be displayed. Check the raw values below.')}</p>}
        {geometry.bounds_um && <p className="break-words">{t('전체 도형 범위 (µm)', 'Overall shape bounds (µm)')}: X {geometry.bounds_um.xmin} ~ {geometry.bounds_um.xmax} · Y {geometry.bounds_um.ymin} ~ {geometry.bounds_um.ymax}</p>}
        <p>{t(`도형으로 표시한 값 ${geometry.rendered_values} / ${item.values.length}개. box·edge·edge-pair·polygon을 지원하며 레이아웃 배경은 포함하지 않습니다.`, `${geometry.rendered_values} of ${item.values.length} values drawn as shapes. box, edge, edge-pair and polygon are supported; the layout background is not included.`)}</p>
        {!!geometry.unrendered_values.length && <p>{t(`표시하지 않은 값 번호: ${geometry.unrendered_values.join(', ')}. 텍스트·미지원 형식·범위 초과 값은 원문으로 확인하세요.`, `Values not drawn: ${geometry.unrendered_values.join(', ')}. Check text, unsupported formats and out-of-range values in the raw values.`)}</p>}
        <p className="break-words">{t('원본 태그', 'Source tags')}: {item.tags || t('없음', 'None')} · {t('서비스 승인 상태가 아닙니다.', 'Not a service approval status.')}</p><p className="whitespace-pre-wrap break-words">{t('댓글', 'Comment')}: {item.comment || t('없음', 'None')}</p>
        <ol className="space-y-2">{item.values.map((value, i) => <li key={i} className="rounded bg-[var(--surface-2)] p-2"><strong>{t('값', 'Value')} #{i+1}</strong><pre className="whitespace-pre-wrap break-words">{value}</pre></li>)}</ol>
        <MarkerViolationReview key={`${runId}-${selected}`} runId={runId} projectId={data.run.project_id} matches={detail.data!.violation_matches} onChange={() => { void detail.refetch(); }} />
      </>}
    </section>}
  </section>;
}
