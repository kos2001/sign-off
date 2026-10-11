import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Link, useParams, useSearchParams } from 'react-router';
import { api, STAGE_LABELS, type TimingPath, type TimingSection } from '../api';
import { TimingGroups } from '../components/TimingGroups';
import { RunEvidencePanel } from '../components/RunEvidencePanel';
import { tr, useLanguage } from '../components/LanguageProvider';

// Label tables are built at render time so they follow the active language.
function sectionLabels(): Record<TimingSection, string> { return { data: tr('데이터 경로', 'Data path'), source_clock: tr('시작 클록 경로', 'Launch clock path'), target_clock: tr('끝 클록 경로', 'Capture clock path') }; }
function outcomeLabels() { return { all: tr('모든 경로', 'All paths'), violated: tr('음수 슬랙', 'Negative slack'), met: tr('0 이상 슬랙', 'Zero or positive slack'), unconstrained: tr('제약 없음', 'Unconstrained') }; }
function sortLabels() { return { slack_asc: tr('슬랙 낮은 순', 'Lowest slack first'), slack_desc: tr('슬랙 높은 순', 'Highest slack first'), report: tr('보고서 순서', 'Report order') }; }
function numberParam(value: string | null, maximum: number) { const n = Number(value); return Number.isInteger(n) && n >= 0 && n <= maximum ? n : 0; }
function validOption(value: string | null, choices: object, fallback: string) { return value && Object.hasOwn(choices, value) ? value : fallback; }
function ps(value: number | null) { return value === null ? tr('미보고 / 유효한 값 없음', 'Not reported / no valid value') : `${Number(value.toPrecision(12))} ps`; }
function deltaPs(value: number | null) { return ps(value === null ? null : Number(value.toPrecision(8))); }
function pathLabel(path: TimingPath) { return path.status === 'unconstrained' ? tr('제약 없음', 'Unconstrained') : path.status === 'violated' ? tr('음수 슬랙', 'Negative slack') : tr('0 이상 슬랙', 'Zero or positive slack'); }

export default function TimingPaths() {
  const { t } = useLanguage();
  const sections = sectionLabels();
  const outcomes = outcomeLabels();
  const sorts = sortLabels();
  const notReported = t('미보고', 'Not reported');
  const emptyGroupName = t('(빈 그룹 이름)', '(empty group name)');
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
  const section = validOption(params.get('section'), sections, 'data') as TimingSection;
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
  const detail = useQuery({ queryKey: ['timing-path', runId, selected, pointOffset, section], queryFn: () => api.timingPath(runId, selected, pointOffset, section), enabled: selected > 0 && !!paths.data });
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
      if (key !== 'selected' && key !== 'point_offset' && key !== 'section') next.delete('selected');
      if (!['offset', 'selected', 'point_offset', 'section'].includes(key)) next.delete('offset');
      return next;
    });
  }
  function resetSearch() { setSearch(''); setMinimum(''); setMaximum(''); setRangeError(''); setParams({}); }
  function applySearch() {
    const lower = minimum.trim(), upper = maximum.trim();
    if ((lower && !Number.isFinite(Number(lower))) || (upper && !Number.isFinite(Number(upper)))) {
      setRangeError(t('슬랙 범위에는 유한한 숫자를 입력하세요.', 'Enter finite numbers for the slack range.')); return;
    }
    if (lower && upper && Number(lower) > Number(upper)) {
      setRangeError(t('슬랙 하한은 상한보다 작거나 같아야 합니다.', 'The slack minimum must be less than or equal to the maximum.')); return;
    }
    setRangeError('');
    setParams(previous => {
      const next = new URLSearchParams(previous);
      for (const [key, value] of Object.entries({ q: search.trim(), slack_min_ps: lower, slack_max_ps: upper })) {
        if (value) next.set(key, value); else next.delete(key);
      }
      for (const key of ['offset', 'selected', 'point_offset', 'section']) next.delete(key);
      return next;
    });
  }
  if (paths.isPending) return <p role="status">{t('타이밍 경로 불러오는 중…', 'Loading timing paths…')}</p>;
  if (paths.isError) return <section className="space-y-3"><p role="alert">{t('타이밍 경로를 불러오지 못했습니다', 'Could not load timing paths')}: {paths.error.message}</p><button className="btn btn-ghost" onClick={() => void paths.refetch()}>{t('다시 시도', 'Retry')}</button><button className="btn btn-ghost" onClick={resetSearch}>{t('검색 초기화', 'Reset search')}</button><Link className="btn btn-ghost" to="/">{t('대시보드로', 'Go to dashboard')}</Link></section>;
  const data = paths.data;
  return <div className="space-y-5">
    <header className="space-y-2">
      <Link className="text-sm underline" to={`/projects/${data.run.project_id}`}>{t('프로젝트로 돌아가기', 'Back to project')}</Link>
      <h1 className="text-xl font-bold">{t('타이밍 경로', 'Timing paths')} · {t('런', 'Run')} #{runId}</h1>
      <p className="text-sm break-words">{STAGE_LABELS[data.run.stage]} · {data.metadata.filename} · {data.metadata.scenario} · {t('리비전', 'Revision')} {data.design_revision}</p>
      <p className="text-sm text-[var(--text-secondary)]">{t('보고서에 포함된 경로를 탐색합니다. 슬랙이 0 이상인 경로가 있어도 전체 STA 검증 통과를 의미하지 않습니다.', 'Explore the paths included in the report. Paths with zero or positive slack do not mean the full STA check passed.')}</p>
      <RunEvidencePanel run={data.run} />
    </header>
    <TimingGroups key={runId} groups={data.groups} onSelect={(group, kind) => setParams({ path_group: group, path_type: kind })} />
    <section aria-label={t('경로 검색', 'Path search')} className="rounded-xl border border-[var(--border)] p-4 space-y-4">
      <form className="space-y-3" onSubmit={e => { e.preventDefault(); applySearch(); }}>
        <label className="block min-w-0 text-sm">{t('시작점 · 끝점 · 그룹 검색', 'Search startpoint · endpoint · group')}<input className="input mt-1 w-full" value={search} maxLength={200} onChange={e => setSearch(e.target.value)} /></label>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="min-w-0 text-sm">{t('슬랙 하한 (ps)', 'Slack minimum (ps)')}<input type="number" step="any" className="input mt-1 w-full" aria-describedby="slack-range-help" value={minimum} onChange={e => { setMinimum(e.target.value); setRangeError(''); }} /></label>
          <label className="min-w-0 text-sm">{t('슬랙 상한 (ps)', 'Slack maximum (ps)')}<input type="number" step="any" className="input mt-1 w-full" aria-describedby="slack-range-help" value={maximum} onChange={e => { setMaximum(e.target.value); setRangeError(''); }} /></label>
        </div>
        <p id="slack-range-help" className="text-xs text-[var(--text-secondary)]">{t('빈칸은 제한 없음이며 경계값을 포함합니다. 범위를 지정하면 슬랙이 없는 경로는 제외됩니다. 입력 후 검색을 누르세요.', 'Leave blank for no limit; bounds are inclusive. Setting a range excludes paths without slack. Press Search after entering values.')}</p>
        {rangeError && <p role="alert" className="text-sm text-[var(--status-critical)]">{rangeError}</p>}
        <button className="btn btn-primary">{t('검색', 'Search')}</button>
      </form>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className="text-sm">{t('경로 유형', 'Path type')}<select aria-label={t('경로 유형', 'Path type')} className="input mt-1 w-full" value={pathType} onChange={e => change('path_type', e.target.value)}><option value="">{t('min / max 모두', 'Both min / max')}</option><option value="max">max</option><option value="min">min</option></select></label>
        <label className="text-sm">{t('슬랙 조건', 'Slack condition')}<select aria-label={t('슬랙 조건', 'Slack condition')} className="input mt-1 w-full" value={filters.status} onChange={e => change('status', e.target.value)}>{Object.entries(outcomes).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label className="text-sm">{t('정렬', 'Sort')}<select aria-label={t('정렬', 'Sort')} className="input mt-1 w-full" value={filters.sort} onChange={e => change('sort', e.target.value)}>{Object.entries(sorts).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      </div>
      <label className="block text-sm">{t('정확한 경로 그룹', 'Exact path group')}<select aria-label={t('정확한 경로 그룹', 'Exact path group')} className="input mt-1 w-full" value={pathGroup === null ? '' : JSON.stringify(pathGroup)} onChange={e => {
        setParams(previous => {
          const next = new URLSearchParams(previous);
          if (e.target.value) next.set('path_group', JSON.parse(e.target.value)); else next.delete('path_group');
          for (const key of ['offset', 'selected', 'point_offset', 'section']) next.delete(key);
          return next;
        });
      }}><option value="">{t('모든 그룹', 'All groups')}</option>{[...new Set([...data.groups.map(group => group.path_group), ...(pathGroup !== null ? [pathGroup] : [])])].sort().map(group => <option key={group} value={JSON.stringify(group)}>{group || emptyGroupName}</option>)}</select></label>
      <p className="text-xs text-[var(--text-secondary)]">{t('그룹은 대소문자를 포함해 정확히 일치하며 다른 검색 조건과 함께 적용됩니다.', 'The group must match exactly, including case, and is combined with the other search conditions.')}</p>
      <button className="btn btn-ghost" onClick={resetSearch}>{t('검색 초기화', 'Reset search')}</button>
    </section>
    <section aria-label={t('타이밍 경로 목록', 'Timing path list')} className="space-y-3">
      <h2 className="font-semibold">{t(`검색 결과 ${data.total}개 / 보고된 전체 ${data.reported_total}개`, `${data.total} results / ${data.reported_total} reported in total`)}</h2>
      {(slackMin || slackMax) && <p className="text-sm break-all">{t('적용된 슬랙 범위', 'Applied slack range')}: {slackMin || t('하한 없음', 'no minimum')} ~ {slackMax || t('상한 없음', 'no maximum')} ps ({t('경계 포함', 'inclusive')})</p>}
      <section aria-label={t('검색 결과 요약', 'Search result summary')} className="rounded-xl border border-[var(--border)] p-4 space-y-3">
        <h3 className="font-semibold text-sm">{t('검색 결과 요약', 'Search result summary')}</h3>
        <p className="text-xs text-[var(--text-secondary)]">{t('페이지에 관계없이 적용된 검색 조건의 전체 경로를 집계합니다.', 'Counts all paths matching the applied search, across every page.')}</p>
        <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            { label: t('음수 슬랙 경로', 'Negative-slack paths'), value: data.summary.violated_paths },
            { label: t('0 이상 슬랙 경로', 'Zero-or-positive-slack paths'), value: data.summary.met_paths },
            { label: t('제약 없는 경로', 'Unconstrained paths'), value: data.summary.unconstrained_paths },
            { label: t('최악 보고 슬랙', 'Worst reported slack'), value: data.summary.worst_slack_ps === null ? t('없음', 'None') : ps(data.summary.worst_slack_ps) },
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
        }}>{download.isPending && download.variables.format === format ? t('내보내는 중…', 'Exporting…') : t(`검색 결과 ${format.toUpperCase()} 내보내기`, `Export results as ${format.toUpperCase()}`)}</button>)}</div>
        <p className="text-xs text-[var(--text-secondary)]">{t('적용된 검색 조건의 전체 경로와 원본 해시·리비전을 저장합니다. 페이지 밖의 결과도 포함합니다.', 'Saves every path matching the applied search, with the source hash and revision. Results beyond this page are included.')}</p>
        {download.isError && <p role="alert" className="text-sm text-[var(--status-critical)]">{t('내보내지 못했습니다', 'Export failed')}: {download.error.message}</p>}
        {download.isSuccess && <p role="status" className="text-sm">{t(`런 #${download.data.run.id}의 경로 ${download.data.total}개를 ${download.data.format === 'csv' ? 'CSV로' : 'JSON으로'} 내보냈습니다.`, `Exported ${download.data.total} paths from run #${download.data.run.id} as ${download.data.format === 'csv' ? 'CSV' : 'JSON'}.`)}</p>}
      </div>
      {data.items.length === 0 ? <p className="text-sm">{data.total ? t('이 페이지에 경로가 없습니다.', 'No paths on this page.') : t('조건에 맞는 경로가 없습니다.', 'No paths match these conditions.')} {offset > 0 && <button className="btn btn-ghost" onClick={() => change('offset', '0')}>{t('첫 페이지', 'First page')}</button>}</p> : <ul className="grid gap-3 lg:grid-cols-2">{data.items.map(path => <li key={path.index}>
        <button aria-current={selected === path.index ? 'true' : undefined} className={`w-full rounded-lg border p-3 text-left space-y-1 ${selected === path.index ? 'border-[var(--series-1)] bg-[var(--surface-2)]' : 'border-[var(--border)]'}`} onClick={() => change('selected', String(path.index))}>
          <span className="block font-semibold text-sm">{t('경로', 'Path')} #{path.index} · {path.path_type} · {pathLabel(path)}</span>
          <span className="block text-xs break-all">{path.startpoint} → {path.endpoint}</span>
          <span className="block text-xs break-all">{t('그룹', 'Group')} {path.path_group} · {path.slack_ps === null ? t('슬랙 없음', 'No slack') : ps(path.slack_ps)}</span>
        </button>
      </li>)}</ul>}
      <nav aria-label={t('경로 페이지', 'Path pages')} className="flex flex-wrap items-center gap-3 text-sm"><button className="btn btn-ghost" disabled={offset === 0} onClick={() => change('offset', String(Math.max(0, offset - 25)))}>{t('이전 페이지', 'Previous page')}</button><span>{data.total && offset < data.total ? `${offset + 1}–${Math.min(offset + 25, data.total)}` : '0'} / {data.total}</span><button className="btn btn-ghost" disabled={offset + 25 >= data.total} onClick={() => change('offset', String(offset + 25))}>{t('다음 페이지', 'Next page')}</button></nav>
    </section>
    {selected > 0 && <section ref={detailRegion} tabIndex={-1} aria-label={t('선택한 타이밍 경로', 'Selected timing path')} className="rounded-xl border border-[var(--border)] p-4 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-semibold">{t(`경로 #${selected} 상세`, `Path #${selected} details`)}</h2><button className="btn btn-ghost" onClick={() => change('selected', '')}>{t('상세 닫기', 'Close details')}</button></div>
      {detail.isPending ? <p role="status">{t('경로 상세 불러오는 중…', 'Loading path details…')}</p> : detail.isError ? <p role="alert">{detail.error.message} <button className="btn btn-ghost" onClick={() => void detail.refetch()}>{t('다시 시도', 'Retry')}</button></p> : <>
        <p className="text-sm break-all">{detail.data.path.startpoint} → {detail.data.path.endpoint}</p>
        <p className="text-sm break-words">{t('시작 클록', 'Launch clock')}: {detail.data.source_clock ?? notReported} · {t('끝 클록', 'Capture clock')}: {detail.data.target_clock ?? notReported}</p>
        <p className="text-sm break-all">{t('데이터 도착 시간', 'Data arrival time')}: {ps(detail.data.arrival_ps)} · {t('요구 시간', 'Required time')}: {ps(detail.data.required_ps)} · {t('슬랙', 'Slack')}: {ps(detail.data.path.slack_ps)}</p>
        <section aria-label={t('타이밍 계산 항목', 'Timing check terms')} className="rounded-lg bg-[var(--surface-2)] p-3 space-y-3">
          <h3 className="text-sm font-semibold">{t('타이밍 계산 항목 · 원본 보고 값', 'Timing check terms · values as reported')}</h3>
          <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 text-xs">
            {[
              [t('시작 클록 에지', 'Launch clock edge'), detail.data.source_clock_edge ?? notReported],
              [t('끝 클록 에지', 'Capture clock edge'), detail.data.target_clock_edge ?? notReported],
              [t('공통 클록 경로 비관 보정 (CRPR)', 'Clock reconvergence pessimism removal (CRPR)'), ps(detail.data.check_terms.crpr_ps)],
              [t('검사 마진 (margin)', 'Check margin (margin)'), ps(detail.data.check_terms.margin_ps)],
              [t('경로 마진 (path_margin)', 'Path margin (path_margin)'), ps(detail.data.check_terms.path_margin_ps)],
              [t('경로 지연 제약 (path_delay)', 'Path delay constraint (path_delay)'), ps(detail.data.check_terms.path_delay_ps)],
              [t('다중 주기 배수', 'Multicycle multiplier'), detail.data.check_terms.multi_cycle_path ?? t('미보고 / 유효한 값 없음', 'Not reported / no valid value')],
            ].map(([label, value]) => <div key={label} className="min-w-0"><dt className="text-[var(--text-secondary)]">{label}</dt><dd className="mt-1 break-all font-medium">{value}</dd></div>)}
          </dl>
          <p className="text-xs text-[var(--text-secondary)]">{t('보고된 항목만 표시합니다. 제약 파일 전체나 항목 간 부호·적용 순서는 이 보고서만으로 복원하지 않습니다. 슬랙을 재계산하거나 AI를 호출하지 않습니다.', 'Only reported terms are shown. The full constraint file, and the signs or order in which terms apply, are not reconstructed from this report alone. Slack is not recalculated and no AI is called.')}</p>
        </section>
        <nav aria-label={t('타이밍 경로 구간', 'Timing path sections')} className="flex flex-wrap gap-2">{(Object.keys(sections) as TimingSection[]).map(name => <button key={name} aria-current={section === name ? 'true' : undefined} className={`btn ${section === name ? 'btn-primary' : 'btn-ghost'}`} onClick={() => change('section', name)}>{sections[name]} · {detail.data.sections[name].reported ? t(`${detail.data.sections[name].point_total}개 핀`, `${detail.data.sections[name].point_total} pins`) : notReported}</button>)}</nav>
        <h3 className="font-semibold">{sections[section]}</h3>
        <p className="text-xs text-[var(--text-secondary)]">{t('선택한 구간의 보고된 핀 순서입니다. 도착 시간과 슬루는 초에서 ps로 변환합니다. 클록 간 도착 시간 차이를 스큐로 추정하지 않으며, 미보고 값은 0으로 대체하지 않습니다.', 'Pins in the selected section, in reported order. Arrival times and slews are converted from seconds to ps. Arrival differences between clocks are not treated as skew, and unreported values are not replaced with 0.')}</p>
        {!detail.data.section_reported && <p role="status" className="text-sm">{t(`이 보고서에는 ${sections[section]}가 없습니다. 클록 지연이 0이거나 문제가 없다는 뜻은 아닙니다.`, `This report has no ${sections[section].toLowerCase()}. That does not mean the clock latency is zero or that there is no problem.`)}</p>}
        {detail.data.section_reported && detail.data.point_total === 0 && <p role="status" className="text-sm">{t(`${sections[section]}가 빈 목록으로 보고되었습니다.`, `The ${sections[section].toLowerCase()} was reported as an empty list.`)}</p>}
        <section aria-label={t('도착 시간 증가 구간', 'Arrival time increases')} className="rounded-lg border border-[var(--border)] p-3 space-y-2">
          <h3 className="text-sm font-semibold">{t('도착 시간 증가가 큰 구간 · 상위 5개', 'Largest arrival time increases · top 5')}</h3>
          <p className="text-xs text-[var(--text-secondary)]">{t(`선택한 구간 전체의 인접 핀 ${detail.data.arrival_delta_summary.total_pairs}구간 중 ${detail.data.arrival_delta_summary.reported_pairs}구간 계산 가능.`, `${detail.data.arrival_delta_summary.reported_pairs} of ${detail.data.arrival_delta_summary.total_pairs} adjacent pin pairs in the selected section can be computed.`)} {t('두 핀의 보고된 도착 시간 차이이며, 개별 셀·넷 지연이나 원인을 분리한 값은 아닙니다. 차이는 최대 8자리 유효숫자로 표시합니다.', 'Each value is the difference between the two pins\' reported arrival times, not an isolated cell or net delay or a root cause. Differences are shown with up to 8 significant digits.')}</p>
          <ul className="space-y-2">{detail.data.arrival_delta_summary.largest_increases.map(pair => <li key={pair.to_index} className="text-xs break-all">
            <p title={`${t('도착 시간 차이', 'Arrival time difference')}: ${ps(pair.delta_ps)}`}>#{pair.from_index} {pair.from_pin ?? t('핀 미보고', 'Pin not reported')} → #{pair.to_index} {pair.to_pin ?? t('핀 미보고', 'Pin not reported')} · +{deltaPs(pair.delta_ps)}</p>
            <button className="btn btn-ghost mt-1" onClick={() => change('point_offset', String(Math.floor((pair.to_index - 1) / 100) * 100))}>{t(`핀 #${pair.to_index} 페이지 보기`, `View page with pin #${pair.to_index}`)}</button>
          </li>)}</ul>
          {detail.data.arrival_delta_summary.largest_increases.length === 0 && <p className="text-xs">{t('계산 가능한 양의 도착 시간 증가가 없습니다. 누락된 값은 지연이 없다는 뜻이 아닙니다.', 'No positive arrival time increase can be computed. Missing values do not mean there is no delay.')}</p>}
        </section>
        <ol className="space-y-2">{detail.data.points.map(point => <li key={point.index} className="rounded-lg bg-[var(--surface-2)] p-3 text-xs space-y-1 break-all"><strong>{point.index}. {point.pin}</strong><p>{t('셀', 'Cell')}: {point.cell ?? notReported} · {t('인스턴스', 'Instance')}: {point.instance ?? notReported}</p><p>{t('넷', 'Net')}: {point.net ?? notReported}</p><p>{t('도착', 'Arrival')}: {ps(point.arrival_ps)} · {t('슬루', 'Slew')}: {ps(point.slew_ps)}</p><p>{t('직전 핀 대비', 'Change from previous pin')}: {point.index === 1 ? t("시작 핀 · 비교 대상 없음", 'First pin · nothing to compare') : deltaPs(point.arrival_delta_ps)}</p></li>)}</ol>
        <nav aria-label={t('핀 페이지', 'Pin pages')} className="flex flex-wrap items-center gap-2 text-xs"><button className="btn btn-ghost" disabled={pointOffset === 0} onClick={() => change('point_offset', String(Math.max(0, pointOffset - 100)))}>{t('이전 핀', 'Previous pins')}</button><span>{t(`전체 ${detail.data.point_total}개 핀`, `${detail.data.point_total} pins total`)} · {pointOffset < detail.data.point_total ? `${pointOffset + 1}–${Math.min(pointOffset + 100, detail.data.point_total)}` : '0'}</span><button className="btn btn-ghost" disabled={pointOffset + 100 >= detail.data.point_total} onClick={() => change('point_offset', String(pointOffset + 100))}>{t('다음 핀', 'Next pins')}</button></nav>
      </>}
    </section>}
  </div>;
}
