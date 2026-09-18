import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";

import type { RunStatus } from "../api";
import { api } from "../api";
import { RunStatusBar } from "../components/charts";
import { Card, Field, StatTile } from "../components/ui";

export default function Dashboard() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const appliedSearch = params.get('q')?.trim() ?? '';
  const rawSort = params.get('sort');
  const sort = rawSort === 'oldest' || rawSort === 'name' ? rawSort : 'newest';
  const rawLifecycle = params.get('lifecycle');
  const lifecycle = rawLifecycle === 'archived' || rawLifecycle === 'all' ? rawLifecycle : 'active';
  const rawPage = Number(params.get('page'));
  const page = Number.isSafeInteger(rawPage) && rawPage > 0 ? rawPage : 1;
  const pageSize = 24;
  const [search, setSearch] = useState(appliedSearch);
  const projects = useQuery({
    queryKey: ['project-summary-page', appliedSearch, sort, lifecycle, page],
    queryFn: () => api.projectSummaryPage({ q: appliedSearch || undefined, sort, lifecycle, offset: (page - 1) * pageSize, limit: pageSize }),
  });
  const [form, setForm] = useState({ name: "", process_node: "", foundry: "" });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setSearch(appliedSearch), [appliedSearch]);
  useEffect(() => {
    if (projects.data && projects.data.total > 0 && projects.data.offset >= projects.data.total) {
      setParams(current => { const next = new URLSearchParams(current); next.set('page', String(Math.ceil(projects.data!.total / pageSize))); return next; }, { replace: true });
    }
  }, [projects.data, setParams]);

  const create = useMutation({
    mutationFn: api.createProject,
    onSuccess: () => {
      setForm({ name: "", process_node: "", foundry: "" });
      setError(null);
      void Promise.all([
        qc.invalidateQueries({ queryKey: ['project-summary-page'] }),
        qc.invalidateQueries({ queryKey: ['project-summaries'] }),
        qc.invalidateQueries({ queryKey: ['projects'] }),
      ]);
    },
    onError: (e: Error) => setError(e.message),
  });

  const list = projects.data?.items ?? [];
  const aggregateCounts = projects.data?.status_counts ?? { passed: 0, failed: 0, running: 0, incomplete: 0 };

  function updateParams(changes: Record<string, string | null>) {
    setParams(current => {
      const next = new URLSearchParams(current);
      for (const [key, value] of Object.entries(changes)) value ? next.set(key, value) : next.delete(key);
      return next;
    });
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <StatTile label="프로젝트" value={projects.data?.total ?? 0} suffix="개" />
        <StatTile
          label="최신 공정 노드"
          value={projects.data?.latest_process_node ?? "–"}
        />
        <StatTile
          label="파운드리"
          value={projects.data?.foundry_count ?? 0}
          suffix="곳"
        />
      </div>

      {(projects.data?.total ?? 0) > 0 && (
        <Card title="전체 런 현황" subtitle="모든 프로젝트의 사인오프 런 상태를 한눈에 봅니다">
          <RunStatusBar counts={aggregateCounts} />
        </Card>
      )}

      <Card title="프로젝트" subtitle="칩 프로젝트별 사인오프 현황을 관리합니다">
        <form className="mb-4 flex flex-wrap items-end gap-3" onSubmit={(event) => { event.preventDefault(); updateParams({ q: search.trim() || null, page: null }); }}>
          <Field label="프로젝트 검색">
            <input className="input" value={search} onChange={event => setSearch(event.target.value)} placeholder="이름·공정 노드·파운드리" maxLength={120} />
          </Field>
          <Field label="정렬">
            <select className="input" value={sort} onChange={event => updateParams({ sort: event.target.value === 'newest' ? null : event.target.value, page: null })}>
              <option value="newest">최근 등록순</option><option value="oldest">오래된 등록순</option><option value="name">이름순</option>
            </select>
          </Field>
          <Field label="수명주기">
            <select className="input" value={lifecycle} onChange={event => updateParams({ lifecycle: event.target.value === 'active' ? null : event.target.value, page: null })}>
              <option value="active">활성 프로젝트</option><option value="archived">보관 프로젝트</option><option value="all">전체</option>
            </select>
          </Field>
          <button className="btn btn-primary">검색</button>
          {(appliedSearch || sort !== 'newest' || lifecycle !== 'active') && <button type="button" className="btn btn-ghost" onClick={() => { setSearch(''); setParams({}); }}>초기화</button>}
        </form>
        {projects.isLoading ? (
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            불러오는 중…
          </p>
        ) : projects.isError ? (
          <p role="alert" className="text-sm" style={{ color: "var(--status-critical)" }}>프로젝트를 불러오지 못했습니다: {projects.error.message} <button className="btn btn-ghost" onClick={() => void projects.refetch()}>다시 시도</button></p>
        ) : list.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            {appliedSearch ? '검색 조건에 맞는 프로젝트가 없습니다.' : '아직 프로젝트가 없습니다. 아래에서 첫 프로젝트를 등록하세요.'}
          </p>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2">
            {list.map((p) => (
              <li key={p.id}>
                <Link
                  to={`/projects/${p.id}`}
                  className="card card-hover block px-4 py-3.5"
                  style={{ background: "var(--surface-2)" }}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-semibold">{p.name}{p.archived_at && <span className="ml-2 rounded-full border px-2 py-0.5 text-xs">보관됨</span>}</span>
                    <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                      #{p.id} →
                    </span>
                  </div>
                  <div className="mt-2 flex gap-1.5">
                    {[p.process_node, p.foundry].map((tag) => (
                      <span
                        key={tag}
                        className="rounded-full px-2 py-0.5 text-xs"
                        style={{
                          border: "1px solid var(--grid-hairline)",
                          color: "var(--text-secondary)",
                        }}
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                  <div className="mt-3">
                    <ProjectRunGlance counts={p.status_counts} total={p.total_runs} />
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
        {projects.data && projects.data.total > pageSize && <nav className="mt-4 flex items-center justify-between" aria-label="프로젝트 페이지">
          <button className="btn btn-ghost" disabled={page === 1} onClick={() => updateParams({ page: page <= 2 ? null : String(page - 1) })}>이전</button>
          <span className="text-sm" style={{ color: 'var(--text-muted)' }}>{page} / {Math.ceil(projects.data.total / pageSize)} 페이지 · 총 {projects.data.total}개</span>
          <button className="btn btn-ghost" disabled={page * pageSize >= projects.data.total} onClick={() => updateParams({ page: String(page + 1) })}>다음</button>
        </nav>}
      </Card>

      <Card title="새 프로젝트">
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate(form);
          }}
        >
          <Field label="이름">
            <input
              className="input"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="orion-soc"
              required
            />
          </Field>
          <Field label="공정 노드">
            <input
              className="input w-28"
              value={form.process_node}
              onChange={(e) => setForm({ ...form, process_node: e.target.value })}
              placeholder="3nm"
              required
            />
          </Field>
          <Field label="파운드리">
            <input
              className="input w-32"
              value={form.foundry}
              onChange={(e) => setForm({ ...form, foundry: e.target.value })}
              placeholder="TSMC"
              required
            />
          </Field>
          <button className="btn btn-primary" disabled={create.isPending}>
            등록
          </button>
          {error && (
            <span className="text-xs" style={{ color: "var(--status-critical)" }}>
              {error}
            </span>
          )}
        </form>
      </Card>
    </div>
  );
}

/** Compact per-card glance: thin status bar, no legend, so the project grid stays scannable. */
function ProjectRunGlance({ counts, total }: { counts?: Record<RunStatus, number>; total: number }) {
  if (total === 0 || !counts) {
    return (
      <p className="text-xs" style={{ color: "var(--text-muted)" }}>
        아직 런이 없습니다.
      </p>
    );
  }
  const order: (keyof typeof counts)[] = ["passed", "failed", "running", "incomplete"];
  const color = { passed: "var(--status-good)", failed: "var(--status-critical)", running: "var(--status-warning)", incomplete: "var(--text-muted)" };

  return (
    <div>
      <div className="flex h-1.5 w-full overflow-hidden rounded-full" style={{ background: "var(--seq-100)" }}>
        {order.map(
          (k) =>
            counts[k] > 0 && (
              <div key={k} style={{ width: `${(counts[k] / total) * 100}%`, background: color[k] }} />
            ),
        )}
      </div>
      <p className="mt-1 text-xs" style={{ color: "var(--text-muted)" }}>
        런 {total}건 · 통과 {counts.passed} · 실패 {counts.failed}
        {counts.incomplete > 0 && ` · 검증 미완료 ${counts.incomplete}`}
        {counts.running > 0 && ` · 진행 중 ${counts.running}`}
      </p>
    </div>
  );
}
