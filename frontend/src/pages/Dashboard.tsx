import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import type { RunStatus } from "../api";
import { api } from "../api";
import { RunStatusBar } from "../components/charts";
import { Card, Field, StatTile } from "../components/ui";

export default function Dashboard() {
  const qc = useQueryClient();
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.listProjects });
  const [form, setForm] = useState({ name: "", process_node: "", foundry: "" });
  const [error, setError] = useState<string | null>(null);

  const list0 = projects.data ?? [];
  // Fetch one row plus server-side totals; report bodies and full history stay out of the dashboard.
  const runQueries = useQueries({
    queries: list0.map((p) => ({
      queryKey: ["run-summary", p.id],
      queryFn: () => api.runPage(p.id, undefined, 1),
    })),
  });

  const create = useMutation({
    mutationFn: api.createProject,
    onSuccess: () => {
      setForm({ name: "", process_node: "", foundry: "" });
      setError(null);
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
    onError: (e: Error) => setError(e.message),
  });

  const list = list0;
  const runsByProject = new Map(list.map((p, i) => [p.id, runQueries[i]?.data]));
  const aggregateCounts = { passed: 0, failed: 0, running: 0, incomplete: 0 };
  for (const page of runsByProject.values()) if (page)
    for (const status of Object.keys(aggregateCounts) as RunStatus[]) aggregateCounts[status] += page.status_counts[status];

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <StatTile label="프로젝트" value={list.length} suffix="개" />
        <StatTile
          label="최신 공정 노드"
          value={list[0] ? list[list.length - 1].process_node : "–"}
        />
        <StatTile
          label="파운드리"
          value={new Set(list.map((p) => p.foundry)).size}
          suffix="곳"
        />
      </div>

      {list.length > 0 && (
        <Card title="전체 런 현황" subtitle="모든 프로젝트의 사인오프 런 상태를 한눈에 봅니다">
          <RunStatusBar counts={aggregateCounts} />
        </Card>
      )}

      <Card title="프로젝트" subtitle="칩 프로젝트별 사인오프 현황을 관리합니다">
        {projects.isLoading ? (
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            불러오는 중…
          </p>
        ) : list.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            아직 프로젝트가 없습니다. 아래에서 첫 프로젝트를 등록하세요.
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
                    <span className="text-sm font-semibold">{p.name}</span>
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
                    <ProjectRunGlance counts={runsByProject.get(p.id)?.status_counts} total={runsByProject.get(p.id)?.total ?? 0} />
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
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
