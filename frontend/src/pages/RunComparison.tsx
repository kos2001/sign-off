import { useInfiniteQuery, useQueries, useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { api, DOMAIN_LABELS, STAGE_LABELS, type ComparisonKind, type SignoffRun, type Violation, type RunProvenance } from "../api";
import { Card, Field, StatusBadge } from "../components/ui";
import { EVIDENCE_LABELS, RunEvidencePanel } from "../components/RunEvidencePanel";
import { formatDateTime, tr, useLanguage } from "../components/LanguageProvider";

// Label tables are built at call time so they follow the active language.
function kindLabels(): Record<ComparisonKind, string> { return { new: tr("비교 대상에만 있음", "Only in candidate"), changed: tr("내용 변경", "Changed"), removed: tr("기준에만 있음", "Only in baseline"), unchanged: tr("동일", "Unchanged") }; }
function fieldLabels(): Record<string, string> { return { severity: tr("심각도", "Severity"), status: tr("처리 상태", "Status"), description: tr("설명", "Description"), waiver: tr("웨이버 근거", "Waiver rationale") }; }
function statusLabels() { return { open: tr("미해결", "Open"), waived: tr("웨이버 승인", "Waived"), fixed: tr("수정 완료", "Fixed") }; }
function provenanceFields(): [keyof RunProvenance, string][] {
  return [
    ['source', tr('근거 종류', 'Evidence type')], ['design_revision', tr('설계 리비전', 'Design revision')], ['scenario', tr('시나리오', 'Scenario')],
    ['tool_version', tr('툴 버전', 'Tool version')], ['coverage', tr('검증 범위', 'Coverage')], ['source_sha256', tr('원본 SHA-256', 'Source SHA-256')],
  ];
}

function provenanceText(key: keyof RunProvenance, value: string | null) {
  if (value === null) return tr('미등록', 'Not recorded');
  if (key === 'source') return EVIDENCE_LABELS[value as keyof typeof EVIDENCE_LABELS] ?? value;
  if (key === 'coverage' && value === 'reported_paths_only') return tr('보고된 경로만', 'Reported paths only');
  return value;
}

function date(value: string) {
  return formatDateTime(value);
}

function runLabel(run: SignoffRun) {
  return `#${run.id} · ${DOMAIN_LABELS[run.domain]} / ${STAGE_LABELS[run.stage]} · ${run.tool} · ${date(run.created_at)}`;
}

function valueText(value: unknown, present: boolean) {
  if (!present) return tr("미등록", "Not recorded");
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function Evidence({ title, violation }: { title: string; violation: Violation | null }) {
  const { t } = useLanguage();
  return <div className="min-w-0 rounded-lg bg-[var(--surface-2)] p-3 text-xs">
    <h3 className="mb-2 font-semibold">{title}{violation ? t(` · 위반 #${violation.id}`, ` · Violation #${violation.id}`) : ""}</h3>
    {violation ? <div className="space-y-2">
      <p>{violation.severity} · {statusLabels()[violation.status]}</p>
      <p className="whitespace-pre-wrap break-words">{violation.description ?? t("설명 미등록", "No description")}</p>
      {violation.waiver && <p className="whitespace-pre-wrap break-words">{t('승인 근거', 'Approval rationale')}: {violation.waiver.reason} · {violation.waiver.approved_by}</p>}
    </div> : <p className="text-[var(--text-muted)]">{t('대응하는 기록 없음', 'No matching record')}</p>}
  </div>;
}

export default function RunComparison() {
  const { t } = useLanguage();
  const labels = kindLabels();
  const projectId = Number(useParams().id);
  const [params, setParams] = useSearchParams();
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => api.getProject(projectId) });
  const runs = useInfiniteQuery({
    queryKey: ['comparison-runs', projectId],
    queryFn: ({ pageParam }) => api.runPage(projectId, { beforeId: pageParam, limit: 100 }),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: page => page.next_before_id ?? undefined,
    enabled: !!project.data,
  });
  const requestedIds = [...new Set(['baseline', 'candidate'].map(key => Number(params.get(key)))
    .filter(id => Number.isSafeInteger(id) && id > 0))];
  const requestedRuns = useQueries({ queries: requestedIds.map(id => ({
    queryKey: ['run', id], queryFn: () => api.getRun(id), enabled: !!project.data,
  })) });
  const requestedRunsPending = requestedRuns.some(query => query.isPending);
  const requestedRunsError = requestedRuns.find(query => query.isError)?.error;
  const loaded = [...(runs.data?.pages.flatMap(page => page.items) ?? []),
    ...requestedRuns.flatMap(query => query.data?.project_id === projectId ? [query.data] : [])];
  const ordered = [...new Map(loaded.map(run => [run.id, run])).values()]
    .sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id - a.id);
  const compatible = (a: SignoffRun, b: SignoffRun) => a.id !== b.id && a.domain === b.domain && a.stage === b.stage;
  const candidates = ordered.filter(run => ordered.some(other => compatible(run, other)));
  const candidateId = params.has("candidate") ? Number(params.get("candidate")) : candidates[0]?.id;
  const candidate = ordered.find(run => run.id === candidateId);
  const baselines = candidate ? ordered.filter(run => compatible(run, candidate)) : [];
  const baselineId = params.has("baseline") ? Number(params.get("baseline")) : baselines[0]?.id;
  const baseline = ordered.find(run => run.id === baselineId);
  const valid = !!baseline && !!candidate && compatible(baseline, candidate);
  const rawKind = params.get("kind") ?? "all";
  const kind = Object.hasOwn(labels, rawKind) ? rawKind : "all";
  const rawOffset = Number(params.get("offset") ?? 0);
  const offset = Number.isSafeInteger(rawOffset) && rawOffset >= 0 && rawOffset <= 2_147_483_647 ? rawOffset : 0;
  // Persist concrete run IDs so a shared link cannot silently select a newer run.
  useEffect(() => {
    if (!valid || (params.has("candidate") && params.has("baseline"))) return;
    setParams(previous => {
      const next = new URLSearchParams(previous);
      next.set("candidate", String(candidateId));
      next.set("baseline", String(baselineId));
      return next;
    }, { replace: true });
  }, [valid, candidateId, baselineId, params, setParams]);
  const comparison = useQuery({
    queryKey: ["run-comparison", projectId, baselineId, candidateId, kind, offset],
    queryFn: () => api.compareRuns(projectId, baselineId!, candidateId!, kind, offset),
    enabled: valid,
  });
  function update(key: string, value: string) {
    setParams(previous => {
      const next = new URLSearchParams(previous);
      next.set(key, value);
      if (key !== "offset") next.delete("offset");
      if (key === "candidate" || key === "baseline") next.delete("kind");
      if (key === "candidate") next.delete("baseline");
      return next;
    });
  }
  if (project.isPending) return <p role="status">{t('프로젝트 불러오는 중…', 'Loading project…')}</p>;
  if (project.isError) return <p role="alert">{project.error.message} <Link className="underline" to="/">{t('대시보드로', 'Go to dashboard')}</Link></p>;
  return <div className="space-y-5">
    <header className="space-y-2">
      <Link className="text-sm underline text-[var(--text-secondary)]" to={`/projects/${projectId}`}>← {project.data.name} · {t('프로젝트 개요', 'Project overview')}</Link>
      <h1 className="text-xl font-bold">{t('런 비교', 'Run comparison')}</h1>
      <p className="text-sm text-[var(--text-muted)]">{t('같은 도메인·단계의 두 실행에서 지표와 위반 기록이 어떻게 달라졌는지 확인합니다.', 'See how metrics and violations changed between two runs of the same domain and stage.')}</p>
    </header>
    <Card title={t('비교할 실행', 'Runs to compare')} subtitle={t('기준 → 비교 대상 순서입니다. 선택한 실행과 조회 조건은 URL에 보존됩니다.', 'Ordered baseline → candidate. The selected runs and filters are kept in the URL.')}>
      {runs.isPending || requestedRunsPending ? <p role="status">{t('런 불러오는 중…', 'Loading runs…')}</p> : runs.isError || requestedRunsError ? <p role="alert">{runs.error?.message ?? requestedRunsError?.message} <button className="btn btn-ghost" onClick={() => runs.refetch()}>{t('다시 시도', 'Retry')}</button></p> : candidates.length === 0 ? <p className="text-sm">{t('같은 도메인·단계의 런이 두 개 이상 필요합니다.', 'At least two runs of the same domain and stage are needed.')} <Link className="underline" to={`/projects/${projectId}`}>{t('프로젝트에서 런 생성', 'Create a run in the project')}</Link></p> : <>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t('기준 런', 'Baseline run')}><select className="input w-full min-w-0" value={baselineId ?? ""} onChange={e => update("baseline", e.target.value)}>
            {!baselines.some(run => run.id === baselineId) && <option value={baselineId ?? ""}>{t('유효한 기준 런을 선택하세요', 'Select a valid baseline run')}</option>}
            {baselines.map(run => <option key={run.id} value={run.id}>{runLabel(run)}</option>)}
          </select></Field>
          <Field label={t('비교 대상 런', 'Candidate run')}><select className="input w-full min-w-0" value={candidateId ?? ""} onChange={e => update("candidate", e.target.value)}>
            {!candidates.some(run => run.id === candidateId) && <option value={candidateId ?? ""}>{t('유효한 비교 대상 런을 선택하세요', 'Select a valid candidate run')}</option>}
            {candidates.map(run => <option key={run.id} value={run.id}>{runLabel(run)}</option>)}
          </select></Field>
        </div>
        <div className="mt-3 flex gap-2">
          <button className="btn btn-ghost" disabled={!valid} onClick={() => setParams({ baseline: String(candidateId), candidate: String(baselineId), kind })}>{t('기준과 대상 바꾸기', 'Swap baseline and candidate')}</button>
          <button className="btn btn-ghost" disabled={!valid || comparison.isFetching} onClick={() => comparison.refetch()}>{t('비교 새로고침', 'Refresh comparison')}</button>
        </div>
        {!valid && <p role="alert" className="mt-3 text-sm">{t('링크의 실행 조합을 비교할 수 없습니다. 같은 도메인·단계의 서로 다른 런을 선택하세요.', 'The runs in this link cannot be compared. Select two different runs of the same domain and stage.')}</p>}
      </>}
      {runs.hasNextPage && <button className="btn btn-ghost mt-3" disabled={runs.isFetchingNextPage} onClick={() => runs.fetchNextPage()}>{runs.isFetchingNextPage ? t('이전 런 불러오는 중…', 'Loading earlier runs…') : t('이전 런 더 보기', 'Show earlier runs')}</button>}
    </Card>
    {valid && (comparison.isPending ? <p role="status">{t('비교 결과 불러오는 중…', 'Loading comparison…')}</p> : comparison.isError ? <Card><p role="alert">{comparison.error.message}</p><button className="btn btn-ghost mt-3" onClick={() => comparison.refetch()}>{t('다시 시도', 'Retry')}</button></Card> : <>
      <div className="grid gap-3 sm:grid-cols-2">
        {[{ title: t("기준", "Baseline"), run: comparison.data.baseline_run }, { title: t("비교 대상", "Candidate"), run: comparison.data.candidate_run }].map(({ title, run }) => <Card key={title} title={`${title} · run #${run.id}`}>
          <p className="text-sm break-words">{run.tool} · {DOMAIN_LABELS[run.domain]} / {STAGE_LABELS[run.stage]}</p>
          <div className="mt-2 flex flex-wrap gap-2 text-xs"><StatusBadge status={run.status === "passed" ? "good" : (run.status === "running" || run.status === "incomplete") ? "warning" : "critical"} label={run.status} /><span>{date(run.created_at)}</span></div>
          <RunEvidencePanel key={run.id} run={run} />
        </Card>)}
      </div>
      {comparison.data.partial && <p role="status" className="rounded-lg border border-[var(--status-warning)] p-3 text-sm">{t('검증 중이거나 검증 범위가 제한된 런이 포함된 잠정 비교입니다. 전체 설계의 변화를 증명하지 않습니다. 가져온 보고서는 선택 조건·코너·룰덱도 실행 근거에서 확인하세요.', 'This is a provisional comparison that includes runs still being verified or with limited coverage. It does not prove how the whole design changed. For imported reports, also check the selection criteria, corners and rule deck in the run evidence.')}</p>}
      {comparison.data.different_tools && <p className="text-sm text-[var(--text-secondary)]">{t('두 런의 툴이 다릅니다. 규칙·단위·분석 설정이 같은지 원본 결과에서 확인하세요.', 'The two runs used different tools. Check the original results to confirm the rules, units and analysis settings match.')}</p>}
      <Card title={t('분석 조건과 원본 근거', 'Analysis conditions and source evidence')} subtitle={t('리비전·시나리오·툴 버전은 제출 시 입력된 식별자입니다. 같은 문자열도 설계·제약·코너 설정의 일치를 보증하지 않습니다.', 'Revision, scenario and tool version are identifiers entered at submission. Matching strings do not guarantee matching design, constraint or corner settings.')}>
        <section aria-label={t('분석 조건 비교', 'Analysis condition comparison')} className="space-y-3">
          {provenanceFields().map(([key, label]) => {
            const before = comparison.data.baseline_provenance[key], after = comparison.data.candidate_provenance[key];
            const relation = before === null || after === null ? t('정보 부족', 'Insufficient information') : before === after ? t('동일 기록', 'Same record') : t('서로 다름', 'Different');
            return <div key={key} className="hairline-t py-3" role="group" aria-label={label}>
              <div className="flex flex-wrap justify-between gap-2 text-sm"><h3 className="font-semibold">{label}</h3><span>{relation}</span></div>
              <div className="mt-2 grid gap-3 sm:grid-cols-2">{[{ title: t('기준', 'Baseline'), value: before }, { title: t('비교 대상', 'Candidate'), value: after }].map(side => <div key={side.title} className="min-w-0 rounded-lg bg-[var(--surface-2)] p-3 text-xs"><p className="mb-1 text-[var(--text-muted)]">{side.title}</p><p className="whitespace-pre-wrap break-all">{provenanceText(key, side.value)}</p></div>)}</div>
            </div>;
          })}
          <p className="text-xs text-[var(--text-secondary)]">{t('원본 해시는 저장된 입력의 바이트를 비교합니다. 같은 보고서라도 입력한 시나리오가 다를 수 있습니다. 각 런의 실행 근거에서 원본을 확인하세요.', 'Source hashes compare the bytes of the stored inputs. The same report may have been submitted with different scenarios. Check the source in each run\'s evidence.')}</p>
        </section>
      </Card>
      <Card title={t('지표 비교', 'Metric comparison')} subtitle={t('차이 = 비교 대상 − 기준. 값의 증가·감소만으로 개선 여부를 판정하지 않습니다.', 'Difference = candidate − baseline. An increase or decrease alone does not indicate improvement.')}>
        {comparison.data.metrics.length === 0 ? <p className="text-sm text-[var(--text-muted)]">{t('등록된 지표가 없습니다.', 'No metrics recorded.')}</p> : <div className="space-y-2">{comparison.data.metrics.map(metric => <div key={metric.name} className="hairline-t py-3">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold break-all">{metric.name}</h3><span className="text-xs text-[var(--text-secondary)]">{metric.delta !== null ? t(`차이 ${metric.delta > 0 ? "+" : ""}${metric.delta}`, `Difference ${metric.delta > 0 ? "+" : ""}${metric.delta}`) : metric.changed ? t("변경됨", "Changed") : t("동일", "Unchanged")}</span></div>
          <div className="grid min-w-0 gap-3 sm:grid-cols-2">{[{ title: t("기준", "Baseline"), value: metric.baseline, present: metric.baseline_present }, { title: t("비교 대상", "Candidate"), value: metric.candidate, present: metric.candidate_present }].map(side => <div key={side.title} className="min-w-0 text-xs"><p className="mb-1 text-[var(--text-muted)]">{side.title}</p><pre className="max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-[var(--surface-2)] p-2">{valueText(side.value, side.present)}</pre></div>)}</div>
        </div>)}</div>}
      </Card>
      <Card title={t('위반 차이', 'Violation differences')} subtitle={t('체크 이름과 위치가 같은 기록을 대응시킵니다. 기준에만 있는 기록도 수정 완료를 뜻하지 않으며, 처리 상태는 변경하지 않습니다.', 'Records with the same check name and location are matched. A record only in the baseline does not mean it was fixed, and statuses are not changed.')}>
        <div className="mb-4 flex flex-wrap gap-2" aria-label={t('차이 유형 필터', 'Difference type filter')}>
          <button className={`btn ${kind === "all" ? "btn-primary" : "btn-ghost"}`} aria-pressed={kind === "all"} onClick={() => update("kind", "all")}>{t('전체', 'All')} {Object.values(comparison.data.summary).reduce((a, b) => a + b, 0)}</button>
          {(Object.keys(labels) as ComparisonKind[]).map(key => <button key={key} className={`btn ${kind === key ? "btn-primary" : "btn-ghost"}`} aria-pressed={kind === key} onClick={() => update("kind", key)}>{labels[key]} {comparison.data.summary[key]}</button>)}
        </div>
        <div className="space-y-3">{comparison.data.items.map(item => {
          const violation = (item.candidate ?? item.baseline)!;
          return <article key={`${item.baseline?.id ?? "-"}:${item.candidate?.id ?? "-"}`} className="rounded-lg border border-[var(--border)] p-3">
            <div className="mb-2 flex flex-wrap items-center gap-2"><StatusBadge status={item.kind === "new" ? "warning" : "neutral"} label={labels[item.kind]} /><h3 className="text-sm font-semibold break-all">{violation.check_name}</h3></div>
            <p className="mb-3 text-xs text-[var(--text-secondary)] break-all">{violation.location ?? t("위치 미등록", "No location recorded")}</p>
            {item.changed_fields.length > 0 && <p className="mb-2 text-xs">{t('변경 항목', 'Changed fields')}: {item.changed_fields.map(name => fieldLabels()[name] ?? name).join(", ")}</p>}
            {item.ambiguous_match && <p className="mb-2 text-xs text-[var(--status-warning)]">{t('같은 체크·위치에 중복 기록이 있습니다. 동일 내용부터 대응시킨 결과이므로 개별 항목의 연속성은 원본에서 확인하세요.', 'There are duplicate records for the same check and location. Identical records were matched first, so confirm the continuity of individual items in the source.')}</p>}
            <div className="grid gap-3 sm:grid-cols-2"><Evidence title={t('기준', 'Baseline')} violation={item.baseline} /><Evidence title={t('비교 대상', 'Candidate')} violation={item.candidate} /></div>
          </article>;
        })}</div>
        {comparison.data.items.length === 0 && <p className="py-4 text-sm">{t('현재 조건 또는 페이지에 표시할 차이가 없습니다.', 'No differences to show for these conditions or this page.')}</p>}
        <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-xs">
          <p role="status">{comparison.data.items.length ? `${offset + 1}–${offset + comparison.data.items.length}` : "0"} / {t(`${comparison.data.total}건`, `${comparison.data.total} items`)}</p>
          <div className="flex flex-wrap gap-2">{offset > 0 && <button className="btn btn-ghost" onClick={() => update("offset", "0")}>{t('첫 페이지', 'First page')}</button>}<button className="btn btn-ghost" disabled={offset === 0} onClick={() => update("offset", String(Math.max(0, offset - 25)))}>{t('이전', 'Previous')}</button><button className="btn btn-ghost" disabled={offset + 25 >= comparison.data.total} onClick={() => update("offset", String(offset + 25))}>{t('다음', 'Next')}</button></div>
        </div>
      </Card>
    </>)}
  </div>;
}
