import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { api, DOMAIN_LABELS, STAGE_LABELS, type ViolationFilters } from "../api";
import { ViolationActions } from "../components/ViolationActions";
import { Card, Field, StatTile, StatusBadge } from "../components/ui";

const statuses = { open: "미해결", fixed: "수정 완료", waived: "웨이버 승인" };
const severities = { critical: "Critical", error: "Error", warning: "Warning", info: "Info" };
const sorts = { severity: "심각도 높은 순", newest: "최근 등록순", oldest: "오래된 순" };

function option(value: string | null, choices: object, fallback = "") {
  return value && Object.hasOwn(choices, value) ? value : fallback;
}

function Filter({ label, value, choices, onChange }: {
  label: string; value: string; choices: Record<string, string>; onChange: (value: string) => void;
}) {
  return <Field label={label}><select className="input" value={value} onChange={e => onChange(e.target.value)}>
    {Object.entries(choices).map(([key, text]) => <option key={key} value={key}>{text}</option>)}
  </select></Field>;
}

export default function Violations() {
  const projectId = Number(useParams().id);
  const [params, setParams] = useSearchParams();
  const qc = useQueryClient();
  const offset = Number(params.get("offset") ?? 0);
  const filters: ViolationFilters = {
    q: (params.get("q") ?? "").slice(0, 200),
    status: option(params.get("status"), statuses),
    severity: option(params.get("severity"), severities),
    domain: option(params.get("domain"), DOMAIN_LABELS),
    stage: option(params.get("stage"), STAGE_LABELS),
    latest_only: params.get("latest_only") !== "false",
    sort: option(params.get("sort"), sorts, "severity"),
    offset: Number.isSafeInteger(offset) && offset >= 0 ? offset : 0,
    limit: [25, 50, 100].includes(Number(params.get("limit"))) ? Number(params.get("limit")) : 25,
  };
  const [search, setSearch] = useState(filters.q);
  useEffect(() => setSearch(filters.q), [filters.q]);
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => api.getProject(projectId) });
  const issues = useQuery({
    queryKey: ["project-violations", projectId, filters],
    queryFn: () => api.projectViolations(projectId, filters),
    enabled: !!project.data,
  });
  const download = useMutation({
    mutationFn: ({ id, applied }: { id: number; applied: ViolationFilters }) => api.exportViolations(id, applied),
    onSuccess: ({ bundle, content }) => {
      const url = URL.createObjectURL(new Blob([content], { type: 'application/json' }));
      const link = document.createElement('a');
      link.href = url;
      link.download = `project-${bundle.project_id}-violations.json`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
  });
  function setFilter(key: string, value: string) {
    setParams(previous => {
      const next = new URLSearchParams(previous);
      if (value) next.set(key, value); else next.delete(key);
      if (key !== "selected") next.delete("selected");
      if (key !== "offset" && key !== "selected") next.delete("offset");
      return next;
    });
  }
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["project-violations", projectId] });
    qc.invalidateQueries({ queryKey: ["violations"] });
    qc.invalidateQueries({ queryKey: ["gate", projectId] });
  };
  const selected = issues.data?.items.find(v => String(v.id) === params.get("selected"));
  if (project.isPending) return <p role="status">프로젝트 불러오는 중…</p>;
  if (project.isError) return <p role="alert">{project.error.message} <Link to="/" className="underline">대시보드로</Link></p>;
  return <div className="space-y-5">
    <header className="space-y-2">
      <Link className="text-sm text-[var(--text-secondary)] underline" to={`/projects/${projectId}`}>← {project.data.name} · 프로젝트 개요</Link>
      <h1 className="text-xl font-bold">위반 검토</h1>
      <p className="text-sm text-[var(--text-muted)]">도메인을 가로질러 위반을 찾고, 근거를 남기며 처리합니다. 검색 조건과 선택한 항목은 URL에 저장됩니다.</p>
    </header>
    <Card title="검색 및 필터" actions={<button className="btn btn-ghost" onClick={() => { setSearch(""); setParams({}); }}>초기화</button>}>
      <form className="mb-4 flex flex-wrap items-end gap-2" onSubmit={e => { e.preventDefault(); setFilter("q", search.trim()); }}>
        <div className="min-w-0 flex-1"><Field label="체크 이름 · 위치 · 설명 · 툴 검색"><input className="input w-full" maxLength={200} value={search} placeholder="예: setup, u_core, Calibre" onChange={e => setSearch(e.target.value)} /></Field></div>
        <button className="btn btn-primary">검색</button>
      </form>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
        <Filter label="상태" value={filters.status} choices={{ "": "모든 상태", ...statuses }} onChange={value => setFilter("status", value)} />
        <Filter label="심각도" value={filters.severity} choices={{ "": "모든 심각도", ...severities }} onChange={value => setFilter("severity", value)} />
        <Filter label="도메인" value={filters.domain} choices={{ "": "모든 도메인", ...DOMAIN_LABELS }} onChange={value => setFilter("domain", value)} />
        <Filter label="스테이지" value={filters.stage} choices={{ "": "모든 스테이지", ...STAGE_LABELS }} onChange={value => setFilter("stage", value)} />
        <Filter label="실행 범위" value={String(filters.latest_only)} choices={{ true: "단계·도메인별 최신 런", false: "과거 런 포함" }} onChange={value => setFilter("latest_only", value)} />
        <Filter label="정렬" value={filters.sort} choices={sorts} onChange={value => setFilter("sort", value)} />
      </div>
      <p className="mt-3 text-xs text-[var(--text-muted)]">{filters.latest_only ? "각 단계·도메인의 최신 런만 조회합니다. 실행 중인 런에는 아직 위반이 등록되지 않았을 수 있습니다." : "과거 런의 위반도 포함합니다. 과거 위반의 처리 상태는 최신 런의 게이트 판정과 별개입니다."} 위반이 없다는 것만으로 게이트 통과를 의미하지는 않습니다.</p>
    </Card>
    {issues.isPending ? <p role="status">위반 불러오는 중…</p> : issues.isError ? <Card><p role="alert">위반을 불러오지 못했습니다: {issues.error.message}</p><button className="btn btn-ghost mt-3" onClick={() => issues.refetch()}>다시 시도</button></Card> : <>
      <div className="grid grid-cols-2 gap-3" aria-live="polite">
        <StatTile label="검색 결과" value={issues.data.total} suffix="건" />
        <StatTile label="검색 결과 중 미해결 Error / Critical" value={issues.data.open_blocking} suffix="건" tone={issues.data.open_blocking ? "critical" : undefined} />
      </div>
      <Card title="검토 목록" actions={<button className="btn btn-ghost" disabled={issues.isFetching} onClick={refresh}>{issues.isFetching ? "갱신 중…" : "새로고침"}</button>}>
        <section aria-label="위반 내보내기" className="mb-4 space-y-2">
          <button className="btn btn-ghost" disabled={download.isPending} onClick={() => download.mutate({ id: projectId, applied: { ...filters } })}>{download.isPending ? '내보내는 중…' : '검색 결과 JSON 내보내기'}</button>
          <p className="text-xs text-[var(--text-muted)]">적용된 조건의 전체 위반과 런·웨이버 정보를 저장합니다. 최대 10,000건·8 MiB이며 페이지 밖의 결과도 포함합니다.</p>
          {download.isError && <p role="alert" className="text-sm text-[var(--status-critical)]">내보내지 못했습니다: {download.error.message}</p>}
          {download.isSuccess && <p role="status" className="text-sm">프로젝트 #{download.data.bundle.project_id}의 위반 {download.data.bundle.total}건을 JSON으로 내보냈습니다.</p>}
        </section>
        {issues.data.items.length === 0 ? <div className="py-6 text-sm text-[var(--text-secondary)]">
          <p>{issues.data.total > 0 ? "이 페이지에는 항목이 없습니다. 첫 페이지로 이동하세요." : "조건에 맞는 위반이 없습니다. 검색 조건이나 실행 범위를 변경해 보세요."}</p>
          {filters.offset > 0 && <button className="btn btn-ghost mt-3" onClick={() => setFilter("offset", "0")}>첫 페이지</button>}
        </div> : <div className="overflow-x-auto">
          <table className="violation-table w-full text-left text-xs">
            <caption className="sr-only">프로젝트 위반 검색 결과. 체크 이름 버튼으로 상세 검토를 엽니다.</caption>
            <thead className="text-[var(--text-muted)]"><tr>{["체크 · 위치", "심각도", "상태", "도메인 · 단계", "실행"].map(label => <th scope="col" className="px-2 py-3 whitespace-nowrap" key={label}>{label}</th>)}</tr></thead>
            <tbody>{issues.data.items.map(v => <Fragment key={v.id}><tr className={`hairline-t ${selected?.id === v.id ? "bg-[var(--surface-2)]" : ""}`}>
              <td className="px-2 py-3 min-w-44 max-w-64"><button className="text-left text-[var(--series-1)] font-semibold underline break-all" aria-label={`위반 #${v.id} 검토: ${v.check_name}`} aria-expanded={selected?.id === v.id} onClick={() => setFilter("selected", selected?.id === v.id ? "" : String(v.id))}>{v.check_name}</button><p className="mt-1 truncate text-[var(--text-muted)]" title={v.location ?? ""}>{v.location ?? "위치 미등록"}</p></td>
              <td data-label="심각도" className="px-2 py-3"><StatusBadge status={v.severity === "critical" ? "critical" : v.severity === "error" ? "serious" : v.severity === "warning" ? "warning" : "neutral"} label={severities[v.severity]} /></td>
              <td data-label="상태" className="px-2 py-3 whitespace-nowrap">{statuses[v.status]}</td>
              <td data-label="도메인 · 단계" className="px-2 py-3 whitespace-nowrap">{DOMAIN_LABELS[v.run.domain]}<br /><span className="text-[var(--text-muted)]">{STAGE_LABELS[v.run.stage]}</span></td>
              <td data-label="실행" className="px-2 py-3 min-w-28">#{v.run_id} · {v.run.status}<p className="text-[var(--text-muted)] break-all">{v.run.tool}</p></td>
            </tr>
              {selected?.id === v.id && <tr className="violation-detail"><td colSpan={5} className="p-4 bg-[var(--surface-2)]">
                <section aria-label={`위반 #${v.id} 상세 검토`} className="space-y-3">
                  <div className="flex items-center justify-between gap-2"><h3 className="font-semibold">위반 #{v.id} 상세 검토</h3><button className="btn btn-ghost" onClick={() => setFilter("selected", "")}>검토 닫기</button></div>
                  <p className="text-xs text-[var(--text-secondary)] break-all">{v.location ?? "위치 미등록"}</p>
                  <ViolationActions key={v.id} violation={v} onChange={refresh} />
                </section>
              </td></tr>}
            </Fragment>)}</tbody>
          </table>
        </div>}
        <div className="hairline-t mt-3 flex flex-wrap items-center justify-between gap-3 pt-3">
          <p className="text-xs" role="status">{issues.data.items.length ? `${filters.offset + 1}–${filters.offset + issues.data.items.length}` : "0"} / {issues.data.total}건</p>
          <div className="flex flex-wrap items-end gap-2">
            <Filter label="페이지 크기" value={String(filters.limit)} choices={{ 25: "25건", 50: "50건", 100: "100건" }} onChange={value => setFilter("limit", value)} />
            <button className="btn btn-ghost" disabled={filters.offset === 0} onClick={() => setFilter("offset", String(Math.max(0, filters.offset - filters.limit)))}>이전</button>
            <button className="btn btn-ghost" disabled={filters.offset + filters.limit >= issues.data.total} onClick={() => setFilter("offset", String(filters.offset + filters.limit))}>다음</button>
          </div>
        </div>
      </Card>
      {params.has("selected") && !selected && <p role="status" className="text-sm">선택한 위반이 현재 페이지 또는 검색 조건에 없습니다.</p>}
    </>}
  </div>;
}
