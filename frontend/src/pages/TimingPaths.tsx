import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Link, useParams, useSearchParams } from 'react-router';
import { api, STAGE_LABELS, type TimingPath } from '../api';
import { TimingGroups } from '../components/TimingGroups';
import { RunEvidencePanel } from '../components/RunEvidencePanel';

const outcomes = { all: '모든 경로', violated: '음수 슬랙', met: '0 이상 슬랙', unconstrained: '제약 없음' };
const sorts = { slack_asc: '슬랙 낮은 순', slack_desc: '슬랙 높은 순', report: '보고서 순서' };
function numberParam(value: string | null, maximum: number) { const n = Number(value); return Number.isInteger(n) && n >= 0 && n <= maximum ? n : 0; }
function validOption(value: string | null, choices: object, fallback: string) { return value && Object.hasOwn(choices, value) ? value : fallback; }
function ps(value: number | null) { return value === null ? '미보고 / 유효한 값 없음' : `${value} ps`; }
function deltaPs(value: number | null) { return ps(value === null ? null : Number(value.toPrecision(8))); }
function pathLabel(path: TimingPath) { return path.status === 'unconstrained' ? '제약 없음' : path.status === 'violated' ? '음수 슬랙' : '0 이상 슬랙'; }

export default function TimingPaths() {
  const runId = Number(useParams().runId);
  const [params, setParams] = useSearchParams();
  const q = (params.get('q') ?? '').slice(0, 200);
  const [search, setSearch] = useState(q);
  useEffect(() => setSearch(q), [q]);
  const slackMin = (params.get('slack_min_ps') ?? '').trim();
  const slackMax = (params.get('slack_max_ps') ?? '').trim();
  const [minimum, setMinimum] = useState(slackMin);
  const [maximum, setMaximum] = useState(slackMax);
  const [rangeError, setRangeError] = useState('');
  useEffect(() => { setMinimum(slackMin); setMaximum(slackMax); setRangeError(''); }, [slackMin, slackMax]);
  const selected = numberParam(params.get('selected'), 1000);
  const pointOffset = numberParam(params.get('point_offset'), 10000);
  const offset = numberParam(params.get('offset'), 1000);
  const pathGroup = params.get('path_group');
  const pathType = validOption(params.get('path_type'), { min: true, max: true }, '');
  const filters: Record<string, string> = { q, ...(pathGroup !== null ? { path_group: pathGroup } : {}), status: validOption(params.get('status'), outcomes, 'all'), sort: validOption(params.get('sort'), sorts, 'slack_asc'), offset: String(offset), limit: '25', ...(pathType ? { path_type: pathType } : {}), ...(slackMin ? { slack_min_ps: slackMin } : {}), ...(slackMax ? { slack_max_ps: slackMax } : {}) };
  const paths = useQuery({ queryKey: ['timing-paths', runId, filters], queryFn: () => api.timingPaths(runId, filters) });
  const download = useMutation({
    mutationFn: async ({ id, applied, format, total }: { id: number; applied: Record<string, string>; format: 'json' | 'csv'; total: number }) => {
      if (format === 'csv') return { run: { id }, total, format, content: '\ufeff' + (await api.exportTimingPathsCsv(id, applied)).replace(/^\ufeff/, ''), mime: 'text/csv;charset=utf-8' };
      const bundle = await api.exportTimingPaths(id, applied);
      return { run: bundle.run, total: bundle.total, format, content: JSON.stringify(bundle, null, 2), mime: 'application/json' };
    },
    onSuccess: bundle => {
      const url = URL.createObjectURL(new Blob([bundle.content], { type: bundle.mime }));
      const link = document.createElement('a');
      link.href = url;
      link.download = `run-${bundle.run.id}-timing-paths.${bundle.format}`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
  });
  const detail = useQuery({ queryKey: ['timing-path', runId, selected, pointOffset], queryFn: () => api.timingPath(runId, selected, pointOffset), enabled: selected > 0 && !!paths.data });
  const detailRegion = useRef<HTMLElement>(null);
  const hasPaths = !!paths.data;
  useEffect(() => {
    if (selected && hasPaths) {
      detailRegion.current?.focus({ preventScroll: true });
      detailRegion.current?.scrollIntoView({ block: 'start' });
    }
  }, [selected, hasPaths]);
  function change(key: string, value: string) {
    setParams(previous => {
      const next = new URLSearchParams(previous);
      if (value) next.set(key, value); else next.delete(key);
      if (key !== 'point_offset') next.delete('point_offset');
      if (key !== 'selected' && key !== 'point_offset') next.delete('selected');
      if (!['offset', 'selected', 'point_offset'].includes(key)) next.delete('offset');
      return next;
    });
  }
  function resetSearch() { setSearch(''); setMinimum(''); setMaximum(''); setRangeError(''); setParams({}); }
  function applySearch() {
    const lower = minimum.trim(), upper = maximum.trim();
    if ((lower && !Number.isFinite(Number(lower))) || (upper && !Number.isFinite(Number(upper)))) {
      setRangeError('슬랙 범위에는 유한한 숫자를 입력하세요.'); return;
    }
    if (lower && upper && Number(lower) > Number(upper)) {
      setRangeError('슬랙 하한은 상한보다 작거나 같아야 합니다.'); return;
    }
    setRangeError('');
    setParams(previous => {
      const next = new URLSearchParams(previous);
      for (const [key, value] of Object.entries({ q: search.trim(), slack_min_ps: lower, slack_max_ps: upper })) {
        if (value) next.set(key, value); else next.delete(key);
      }
      for (const key of ['offset', 'selected', 'point_offset']) next.delete(key);
      return next;
    });
  }
  if (paths.isPending) return <p role="status">타이밍 경로 불러오는 중…</p>;
  if (paths.isError) return <section className="space-y-3"><p role="alert">타이밍 경로를 불러오지 못했습니다: {paths.error.message}</p><button className="btn btn-ghost" onClick={() => void paths.refetch()}>다시 시도</button><button className="btn btn-ghost" onClick={resetSearch}>검색 초기화</button><Link className="btn btn-ghost" to="/">대시보드로</Link></section>;
  const data = paths.data;
  return <div className="space-y-5">
    <header className="space-y-2">
      <Link className="text-sm underline" to={`/projects/${data.run.project_id}`}>프로젝트로 돌아가기</Link>
      <h1 className="text-xl font-bold">타이밍 경로 · 런 #{runId}</h1>
      <p className="text-sm break-words">{STAGE_LABELS[data.run.stage]} · {data.metadata.filename} · {data.metadata.scenario} · 리비전 {data.design_revision}</p>
      <p className="text-sm text-[var(--text-secondary)]">보고서에 포함된 경로를 탐색합니다. 슬랙이 0 이상인 경로가 있어도 전체 STA 검증 통과를 의미하지 않습니다.</p>
      <RunEvidencePanel run={data.run} />
    </header>
    <TimingGroups key={runId} groups={data.groups} onSelect={(group, kind) => setParams({ path_group: group, path_type: kind })} />
    <section aria-label="경로 검색" className="rounded-xl border border-[var(--border)] p-4 space-y-4">
      <form className="space-y-3" onSubmit={e => { e.preventDefault(); applySearch(); }}>
        <label className="block min-w-0 text-sm">시작점 · 끝점 · 그룹 검색<input className="input mt-1 w-full" value={search} maxLength={200} onChange={e => setSearch(e.target.value)} /></label>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="min-w-0 text-sm">슬랙 하한 (ps)<input type="number" step="any" className="input mt-1 w-full" aria-describedby="slack-range-help" value={minimum} onChange={e => { setMinimum(e.target.value); setRangeError(''); }} /></label>
          <label className="min-w-0 text-sm">슬랙 상한 (ps)<input type="number" step="any" className="input mt-1 w-full" aria-describedby="slack-range-help" value={maximum} onChange={e => { setMaximum(e.target.value); setRangeError(''); }} /></label>
        </div>
        <p id="slack-range-help" className="text-xs text-[var(--text-secondary)]">빈칸은 제한 없음이며 경계값을 포함합니다. 범위를 지정하면 슬랙이 없는 경로는 제외됩니다. 입력 후 검색을 누르세요.</p>
        {rangeError && <p role="alert" className="text-sm text-[var(--status-critical)]">{rangeError}</p>}
        <button className="btn btn-primary">검색</button>
      </form>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className="text-sm">경로 유형<select aria-label="경로 유형" className="input mt-1 w-full" value={pathType} onChange={e => change('path_type', e.target.value)}><option value="">min / max 모두</option><option value="max">max</option><option value="min">min</option></select></label>
        <label className="text-sm">슬랙 조건<select aria-label="슬랙 조건" className="input mt-1 w-full" value={filters.status} onChange={e => change('status', e.target.value)}>{Object.entries(outcomes).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label className="text-sm">정렬<select aria-label="정렬" className="input mt-1 w-full" value={filters.sort} onChange={e => change('sort', e.target.value)}>{Object.entries(sorts).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      </div>
      <label className="block text-sm">정확한 경로 그룹<select aria-label="정확한 경로 그룹" className="input mt-1 w-full" value={pathGroup === null ? '' : JSON.stringify(pathGroup)} onChange={e => {
        setParams(previous => {
          const next = new URLSearchParams(previous);
          if (e.target.value) next.set('path_group', JSON.parse(e.target.value)); else next.delete('path_group');
          for (const key of ['offset', 'selected', 'point_offset']) next.delete(key);
          return next;
        });
      }}><option value="">모든 그룹</option>{[...new Set([...data.groups.map(group => group.path_group), ...(pathGroup !== null ? [pathGroup] : [])])].sort().map(group => <option key={group} value={JSON.stringify(group)}>{group || '(빈 그룹 이름)'}</option>)}</select></label>
      <p className="text-xs text-[var(--text-secondary)]">그룹은 대소문자를 포함해 정확히 일치하며 다른 검색 조건과 함께 적용됩니다.</p>
      <button className="btn btn-ghost" onClick={resetSearch}>검색 초기화</button>
    </section>
    <section aria-label="타이밍 경로 목록" className="space-y-3">
      <h2 className="font-semibold">검색 결과 {data.total}개 / 보고된 전체 {data.reported_total}개</h2>
      {(slackMin || slackMax) && <p className="text-sm break-all">적용된 슬랙 범위: {slackMin || '하한 없음'} ~ {slackMax || '상한 없음'} ps (경계 포함)</p>}
      <section aria-label="검색 결과 요약" className="rounded-xl border border-[var(--border)] p-4 space-y-3">
        <h3 className="font-semibold text-sm">검색 결과 요약</h3>
        <p className="text-xs text-[var(--text-secondary)]">페이지에 관계없이 적용된 검색 조건의 전체 경로를 집계합니다.</p>
        <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            { label: '음수 슬랙 경로', value: data.summary.violated_paths },
            { label: '0 이상 슬랙 경로', value: data.summary.met_paths },
            { label: '제약 없는 경로', value: data.summary.unconstrained_paths },
            { label: '최악 보고 슬랙', value: data.summary.worst_slack_ps === null ? '없음' : ps(data.summary.worst_slack_ps) },
          ].map(item => <div key={item.label} className="min-w-0 rounded-lg bg-[var(--surface-2)] p-3">
            <dt className="text-xs text-[var(--text-secondary)]">{item.label}</dt>
            <dd className="mt-1 text-lg font-semibold tabular-nums break-all">{item.value}</dd>
          </div>)}
        </dl>
      </section>
      <div className="space-y-2">
        <div className="flex flex-wrap gap-2">{(['json', 'csv'] as const).map(format => <button key={format} className="btn btn-ghost" disabled={download.isPending} onClick={() => {
          const applied = Object.fromEntries(Object.entries(filters).filter(([key]) => key !== 'offset' && key !== 'limit'));
          download.mutate({ id: runId, applied, format, total: data.total });
        }}>{download.isPending && download.variables.format === format ? '내보내는 중…' : `검색 결과 ${format.toUpperCase()} 내보내기`}</button>)}</div>
        <p className="text-xs text-[var(--text-secondary)]">적용된 검색 조건의 전체 경로와 원본 해시·리비전을 저장합니다. 페이지 밖의 결과도 포함합니다.</p>
        {download.isError && <p role="alert" className="text-sm text-[var(--status-critical)]">내보내지 못했습니다: {download.error.message}</p>}
        {download.isSuccess && <p role="status" className="text-sm">런 #{download.data.run.id}의 경로 {download.data.total}개를 {download.data.format === 'csv' ? 'CSV로' : 'JSON으로'} 내보냈습니다.</p>}
      </div>
      {data.items.length === 0 ? <p className="text-sm">{data.total ? '이 페이지에 경로가 없습니다.' : '조건에 맞는 경로가 없습니다.'} {offset > 0 && <button className="btn btn-ghost" onClick={() => change('offset', '0')}>첫 페이지</button>}</p> : <ul className="grid gap-3 lg:grid-cols-2">{data.items.map(path => <li key={path.index}>
        <button aria-current={selected === path.index ? 'true' : undefined} className={`w-full rounded-lg border p-3 text-left space-y-1 ${selected === path.index ? 'border-[var(--series-1)] bg-[var(--surface-2)]' : 'border-[var(--border)]'}`} onClick={() => change('selected', String(path.index))}>
          <span className="block font-semibold text-sm">경로 #{path.index} · {path.path_type} · {pathLabel(path)}</span>
          <span className="block text-xs break-all">{path.startpoint} → {path.endpoint}</span>
          <span className="block text-xs break-all">그룹 {path.path_group} · {path.slack_ps === null ? '슬랙 없음' : ps(path.slack_ps)}</span>
        </button>
      </li>)}</ul>}
      <nav aria-label="경로 페이지" className="flex flex-wrap items-center gap-3 text-sm"><button className="btn btn-ghost" disabled={offset === 0} onClick={() => change('offset', String(Math.max(0, offset - 25)))}>이전 페이지</button><span>{data.total && offset < data.total ? `${offset + 1}–${Math.min(offset + 25, data.total)}` : '0'} / {data.total}</span><button className="btn btn-ghost" disabled={offset + 25 >= data.total} onClick={() => change('offset', String(offset + 25))}>다음 페이지</button></nav>
    </section>
    {selected > 0 && <section ref={detailRegion} tabIndex={-1} aria-label="선택한 타이밍 경로" className="rounded-xl border border-[var(--border)] p-4 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-semibold">경로 #{selected} 상세</h2><button className="btn btn-ghost" onClick={() => change('selected', '')}>상세 닫기</button></div>
      {detail.isPending ? <p role="status">경로 상세 불러오는 중…</p> : detail.isError ? <p role="alert">{detail.error.message} <button className="btn btn-ghost" onClick={() => void detail.refetch()}>다시 시도</button></p> : <>
        <p className="text-sm break-all">{detail.data.path.startpoint} → {detail.data.path.endpoint}</p>
        <p className="text-sm break-words">시작 클록: {detail.data.source_clock ?? '미보고'} · 끝 클록: {detail.data.target_clock ?? '미보고'}</p>
        <p className="text-sm break-all">데이터 도착 시간: {ps(detail.data.arrival_ps)} · 요구 시간: {ps(detail.data.required_ps)} · 슬랙: {ps(detail.data.path.slack_ps)}</p>
        <p className="text-xs text-[var(--text-secondary)]">보고된 데이터 경로 핀 순서입니다. 도착 시간과 슬루는 원본의 초 단위를 ps로 변환했습니다. 미보고 값은 0으로 대체하지 않습니다.</p>
        <section aria-label="도착 시간 증가 구간" className="rounded-lg border border-[var(--border)] p-3 space-y-2">
          <h3 className="text-sm font-semibold">도착 시간 증가가 큰 구간 · 상위 5개</h3>
          <p className="text-xs text-[var(--text-secondary)]">현재 경로 전체의 인접 핀 {detail.data.arrival_delta_summary.total_pairs}구간 중 {detail.data.arrival_delta_summary.reported_pairs}구간 계산 가능. 두 핀의 보고된 도착 시간 차이이며, 개별 셀·넷 지연이나 원인을 분리한 값은 아닙니다. 차이는 최대 8자리 유효숫자로 표시합니다.</p>
          <ul className="space-y-2">{detail.data.arrival_delta_summary.largest_increases.map(pair => <li key={pair.to_index} className="text-xs break-all">
            <p title={`도착 시간 차이: ${ps(pair.delta_ps)}`}>#{pair.from_index} {pair.from_pin ?? '핀 미보고'} → #{pair.to_index} {pair.to_pin ?? '핀 미보고'} · +{deltaPs(pair.delta_ps)}</p>
            <button className="btn btn-ghost mt-1" onClick={() => change('point_offset', String(Math.floor((pair.to_index - 1) / 100) * 100))}>핀 #{pair.to_index} 페이지 보기</button>
          </li>)}</ul>
          {detail.data.arrival_delta_summary.largest_increases.length === 0 && <p className="text-xs">계산 가능한 양의 도착 시간 증가가 없습니다. 누락된 값은 지연이 없다는 뜻이 아닙니다.</p>}
        </section>
        <ol className="space-y-2">{detail.data.points.map(point => <li key={point.index} className="rounded-lg bg-[var(--surface-2)] p-3 text-xs space-y-1 break-all"><strong>{point.index}. {point.pin}</strong><p>셀: {point.cell ?? '미보고'} · 인스턴스: {point.instance ?? '미보고'}</p><p>넷: {point.net ?? '미보고'}</p><p>도착: {ps(point.arrival_ps)} · 슬루: {ps(point.slew_ps)}</p><p>직전 핀 대비: {point.index === 1 ? "시작 핀 · 비교 대상 없음" : deltaPs(point.arrival_delta_ps)}</p></li>)}</ol>
        <nav aria-label="핀 페이지" className="flex flex-wrap items-center gap-2 text-xs"><button className="btn btn-ghost" disabled={pointOffset === 0} onClick={() => change('point_offset', String(Math.max(0, pointOffset - 100)))}>이전 핀</button><span>전체 {detail.data.point_total}개 핀 · {pointOffset < detail.data.point_total ? `${pointOffset + 1}–${Math.min(pointOffset + 100, detail.data.point_total)}` : '0'}</span><button className="btn btn-ghost" disabled={pointOffset + 100 >= detail.data.point_total} onClick={() => change('point_offset', String(pointOffset + 100))}>다음 핀</button></nav>
      </>}
    </section>}
  </div>;
}
