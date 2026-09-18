import { useInfiniteQuery, useQueries, useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { api, DOMAIN_LABELS, STAGE_LABELS, type ComparisonKind, type SignoffRun, type Violation, type RunProvenance } from "../api";
import { Card, Field, StatusBadge } from "../components/ui";
import { EVIDENCE_LABELS, RunEvidencePanel } from "../components/RunEvidencePanel";

const labels: Record<ComparisonKind, string> = { new: "비교 대상에만 있음", changed: "내용 변경", removed: "기준에만 있음", unchanged: "동일" };
const fieldLabels: Record<string, string> = { severity: "심각도", status: "처리 상태", description: "설명", waiver: "웨이버 근거" };
const statusLabels = { open: "미해결", waived: "웨이버 승인", fixed: "수정 완료" };
const provenanceFields: [keyof RunProvenance, string][] = [
  ['source', '근거 종류'], ['design_revision', '설계 리비전'], ['scenario', '시나리오'],
  ['tool_version', '툴 버전'], ['coverage', '검증 범위'], ['source_sha256', '원본 SHA-256'],
];

function provenanceText(key: keyof RunProvenance, value: string | null) {
  if (value === null) return '미등록';
  if (key === 'source') return EVIDENCE_LABELS[value as keyof typeof EVIDENCE_LABELS] ?? value;
  if (key === 'coverage' && value === 'reported_paths_only') return '보고된 경로만';
  return value;
}

function date(value: string) {
  return new Date(/[Zz]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`).toLocaleString();
}

function runLabel(run: SignoffRun) {
  return `#${run.id} · ${DOMAIN_LABELS[run.domain]} / ${STAGE_LABELS[run.stage]} · ${run.tool} · ${date(run.created_at)}`;
}

function valueText(value: unknown, present: boolean) {
  if (!present) return "미등록";
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function Evidence({ title, violation }: { title: string; violation: Violation | null }) {
  return <div className="min-w-0 rounded-lg bg-[var(--surface-2)] p-3 text-xs">
    <h3 className="mb-2 font-semibold">{title}{violation ? ` · 위반 #${violation.id}` : ""}</h3>
    {violation ? <div className="space-y-2">
      <p>{violation.severity} · {statusLabels[violation.status]}</p>
      <p className="whitespace-pre-wrap break-words">{violation.description ?? "설명 미등록"}</p>
      {violation.waiver && <p className="whitespace-pre-wrap break-words">승인 근거: {violation.waiver.reason} · {violation.waiver.approved_by}</p>}
    </div> : <p className="text-[var(--text-muted)]">대응하는 기록 없음</p>}
  </div>;
}

export default function RunComparison() {
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
  if (project.isPending) return <p role="status">프로젝트 불러오는 중…</p>;
  if (project.isError) return <p role="alert">{project.error.message} <Link className="underline" to="/">대시보드로</Link></p>;
  return <div className="space-y-5">
    <header className="space-y-2">
      <Link className="text-sm underline text-[var(--text-secondary)]" to={`/projects/${projectId}`}>← {project.data.name} · 프로젝트 개요</Link>
      <h1 className="text-xl font-bold">런 비교</h1>
      <p className="text-sm text-[var(--text-muted)]">같은 도메인·단계의 두 실행에서 지표와 위반 기록이 어떻게 달라졌는지 확인합니다.</p>
    </header>
    <Card title="비교할 실행" subtitle="기준 → 비교 대상 순서입니다. 선택한 실행과 조회 조건은 URL에 보존됩니다.">
      {runs.isPending || requestedRunsPending ? <p role="status">런 불러오는 중…</p> : runs.isError || requestedRunsError ? <p role="alert">{runs.error?.message ?? requestedRunsError?.message} <button className="btn btn-ghost" onClick={() => runs.refetch()}>다시 시도</button></p> : candidates.length === 0 ? <p className="text-sm">같은 도메인·단계의 런이 두 개 이상 필요합니다. <Link className="underline" to={`/projects/${projectId}`}>프로젝트에서 런 생성</Link></p> : <>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="기준 런"><select className="input w-full min-w-0" value={baselineId ?? ""} onChange={e => update("baseline", e.target.value)}>
            {!baselines.some(run => run.id === baselineId) && <option value={baselineId ?? ""}>유효한 기준 런을 선택하세요</option>}
            {baselines.map(run => <option key={run.id} value={run.id}>{runLabel(run)}</option>)}
          </select></Field>
          <Field label="비교 대상 런"><select className="input w-full min-w-0" value={candidateId ?? ""} onChange={e => update("candidate", e.target.value)}>
            {!candidates.some(run => run.id === candidateId) && <option value={candidateId ?? ""}>유효한 비교 대상 런을 선택하세요</option>}
            {candidates.map(run => <option key={run.id} value={run.id}>{runLabel(run)}</option>)}
          </select></Field>
        </div>
        <div className="mt-3 flex gap-2">
          <button className="btn btn-ghost" disabled={!valid} onClick={() => setParams({ baseline: String(candidateId), candidate: String(baselineId), kind })}>기준과 대상 바꾸기</button>
          <button className="btn btn-ghost" disabled={!valid || comparison.isFetching} onClick={() => comparison.refetch()}>비교 새로고침</button>
        </div>
        {!valid && <p role="alert" className="mt-3 text-sm">링크의 실행 조합을 비교할 수 없습니다. 같은 도메인·단계의 서로 다른 런을 선택하세요.</p>}
      </>}
      {runs.hasNextPage && <button className="btn btn-ghost mt-3" disabled={runs.isFetchingNextPage} onClick={() => runs.fetchNextPage()}>{runs.isFetchingNextPage ? '이전 런 불러오는 중…' : '이전 런 더 보기'}</button>}
    </Card>
    {valid && (comparison.isPending ? <p role="status">비교 결과 불러오는 중…</p> : comparison.isError ? <Card><p role="alert">{comparison.error.message}</p><button className="btn btn-ghost mt-3" onClick={() => comparison.refetch()}>다시 시도</button></Card> : <>
      <div className="grid gap-3 sm:grid-cols-2">
        {[{ title: "기준", run: comparison.data.baseline_run }, { title: "비교 대상", run: comparison.data.candidate_run }].map(({ title, run }) => <Card key={title} title={`${title} · run #${run.id}`}>
          <p className="text-sm break-words">{run.tool} · {DOMAIN_LABELS[run.domain]} / {STAGE_LABELS[run.stage]}</p>
          <div className="mt-2 flex flex-wrap gap-2 text-xs"><StatusBadge status={run.status === "passed" ? "good" : (run.status === "running" || run.status === "incomplete") ? "warning" : "critical"} label={run.status} /><span>{date(run.created_at)}</span></div>
          <RunEvidencePanel key={run.id} run={run} />
        </Card>)}
      </div>
      {comparison.data.partial && <p role="status" className="rounded-lg border border-[var(--status-warning)] p-3 text-sm">검증 중이거나 검증 범위가 제한된 런이 포함된 잠정 비교입니다. 전체 설계의 변화를 증명하지 않습니다. 가져온 보고서는 선택 조건·코너·룰덱도 실행 근거에서 확인하세요.</p>}
      {comparison.data.different_tools && <p className="text-sm text-[var(--text-secondary)]">두 런의 툴이 다릅니다. 규칙·단위·분석 설정이 같은지 원본 결과에서 확인하세요.</p>}
      <Card title="분석 조건과 원본 근거" subtitle="리비전·시나리오·툴 버전은 제출 시 입력된 식별자입니다. 같은 문자열도 설계·제약·코너 설정의 일치를 보증하지 않습니다.">
        <section aria-label="분석 조건 비교" className="space-y-3">
          {provenanceFields.map(([key, label]) => {
            const before = comparison.data.baseline_provenance[key], after = comparison.data.candidate_provenance[key];
            const relation = before === null || after === null ? '정보 부족' : before === after ? '동일 기록' : '서로 다름';
            return <div key={key} className="hairline-t py-3" role="group" aria-label={label}>
              <div className="flex flex-wrap justify-between gap-2 text-sm"><h3 className="font-semibold">{label}</h3><span>{relation}</span></div>
              <div className="mt-2 grid gap-3 sm:grid-cols-2">{[{ title: '기준', value: before }, { title: '비교 대상', value: after }].map(side => <div key={side.title} className="min-w-0 rounded-lg bg-[var(--surface-2)] p-3 text-xs"><p className="mb-1 text-[var(--text-muted)]">{side.title}</p><p className="whitespace-pre-wrap break-all">{provenanceText(key, side.value)}</p></div>)}</div>
            </div>;
          })}
          <p className="text-xs text-[var(--text-secondary)]">원본 해시는 저장된 입력의 바이트를 비교합니다. 같은 보고서라도 입력한 시나리오가 다를 수 있습니다. 각 런의 실행 근거에서 원본을 확인하세요.</p>
        </section>
      </Card>
      <Card title="지표 비교" subtitle="차이 = 비교 대상 − 기준. 값의 증가·감소만으로 개선 여부를 판정하지 않습니다.">
        {comparison.data.metrics.length === 0 ? <p className="text-sm text-[var(--text-muted)]">등록된 지표가 없습니다.</p> : <div className="space-y-2">{comparison.data.metrics.map(metric => <div key={metric.name} className="hairline-t py-3">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold break-all">{metric.name}</h3><span className="text-xs text-[var(--text-secondary)]">{metric.delta !== null ? `차이 ${metric.delta > 0 ? "+" : ""}${metric.delta}` : metric.changed ? "변경됨" : "동일"}</span></div>
          <div className="grid min-w-0 gap-3 sm:grid-cols-2">{[{ title: "기준", value: metric.baseline, present: metric.baseline_present }, { title: "비교 대상", value: metric.candidate, present: metric.candidate_present }].map(side => <div key={side.title} className="min-w-0 text-xs"><p className="mb-1 text-[var(--text-muted)]">{side.title}</p><pre className="max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-[var(--surface-2)] p-2">{valueText(side.value, side.present)}</pre></div>)}</div>
        </div>)}</div>}
      </Card>
      <Card title="위반 차이" subtitle="체크 이름과 위치가 같은 기록을 대응시킵니다. 기준에만 있는 기록도 수정 완료를 뜻하지 않으며, 처리 상태는 변경하지 않습니다.">
        <div className="mb-4 flex flex-wrap gap-2" aria-label="차이 유형 필터">
          <button className={`btn ${kind === "all" ? "btn-primary" : "btn-ghost"}`} aria-pressed={kind === "all"} onClick={() => update("kind", "all")}>전체 {Object.values(comparison.data.summary).reduce((a, b) => a + b, 0)}</button>
          {(Object.keys(labels) as ComparisonKind[]).map(key => <button key={key} className={`btn ${kind === key ? "btn-primary" : "btn-ghost"}`} aria-pressed={kind === key} onClick={() => update("kind", key)}>{labels[key]} {comparison.data.summary[key]}</button>)}
        </div>
        <div className="space-y-3">{comparison.data.items.map(item => {
          const violation = (item.candidate ?? item.baseline)!;
          return <article key={`${item.baseline?.id ?? "-"}:${item.candidate?.id ?? "-"}`} className="rounded-lg border border-[var(--border)] p-3">
            <div className="mb-2 flex flex-wrap items-center gap-2"><StatusBadge status={item.kind === "new" ? "warning" : "neutral"} label={labels[item.kind]} /><h3 className="text-sm font-semibold break-all">{violation.check_name}</h3></div>
            <p className="mb-3 text-xs text-[var(--text-secondary)] break-all">{violation.location ?? "위치 미등록"}</p>
            {item.changed_fields.length > 0 && <p className="mb-2 text-xs">변경 항목: {item.changed_fields.map(name => fieldLabels[name] ?? name).join(", ")}</p>}
            {item.ambiguous_match && <p className="mb-2 text-xs text-[var(--status-warning)]">같은 체크·위치에 중복 기록이 있습니다. 동일 내용부터 대응시킨 결과이므로 개별 항목의 연속성은 원본에서 확인하세요.</p>}
            <div className="grid gap-3 sm:grid-cols-2"><Evidence title="기준" violation={item.baseline} /><Evidence title="비교 대상" violation={item.candidate} /></div>
          </article>;
        })}</div>
        {comparison.data.items.length === 0 && <p className="py-4 text-sm">현재 조건 또는 페이지에 표시할 차이가 없습니다.</p>}
        <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-xs">
          <p role="status">{comparison.data.items.length ? `${offset + 1}–${offset + comparison.data.items.length}` : "0"} / {comparison.data.total}건</p>
          <div className="flex flex-wrap gap-2">{offset > 0 && <button className="btn btn-ghost" onClick={() => update("offset", "0")}>첫 페이지</button>}<button className="btn btn-ghost" disabled={offset === 0} onClick={() => update("offset", String(Math.max(0, offset - 25)))}>이전</button><button className="btn btn-ghost" disabled={offset + 25 >= comparison.data.total} onClick={() => update("offset", String(offset + 25))}>다음</button></div>
        </div>
      </Card>
    </>)}
  </div>;
}
