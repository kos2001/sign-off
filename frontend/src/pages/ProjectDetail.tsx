import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";

import type { Domain, Severity, SignoffRun, Stage } from "../api";
import { api, DOMAIN_LABELS, STAGE_LABELS, STAGES } from "../api";
import { Card, Field, StatusBadge } from "../components/ui";

export default function ProjectDetail() {
  const { id } = useParams();
  const projectId = Number(id);
  const qc = useQueryClient();
  const [stage, setStage] = useState<Stage>("placement");

  const project = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.getProject(projectId),
  });
  const runs = useQuery({
    queryKey: ["runs", projectId],
    queryFn: () => api.listRuns(projectId),
  });
  const gate = useQuery({
    queryKey: ["gate", projectId, stage],
    queryFn: () => api.gateStatus(projectId, stage),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["runs", projectId] });
    qc.invalidateQueries({ queryKey: ["gate", projectId] });
  };

  if (project.isLoading) return <p className="text-sm">불러오는 중…</p>;
  if (project.isError)
    return (
      <p className="text-sm" style={{ color: "var(--status-critical)" }}>
        프로젝트를 찾을 수 없습니다. <Link to="/" className="underline">대시보드로</Link>
      </p>
    );

  const p = project.data!;

  return (
    <div className="space-y-6">
      <header className="flex items-baseline gap-3">
        <h1 className="text-xl font-bold">{p.name}</h1>
        <span className="text-sm" style={{ color: "var(--text-muted)" }}>
          {p.process_node} · {p.foundry}
        </span>
      </header>

      <Card
        title="Shift-left 스테이지 게이트"
        subtitle="단계별 필수 사인오프 도메인이 모두 통과해야 게이트가 열립니다"
      >
        <div className="mb-5 flex flex-wrap items-center gap-1">
          {STAGES.map((s, i) => (
            <div key={s} className="flex items-center gap-1">
              {i > 0 && (
                <span
                  aria-hidden
                  className="h-px w-4 sm:w-6"
                  style={{ background: "var(--baseline)" }}
                />
              )}
              <button
                className="btn flex items-center gap-2"
                style={
                  s === stage
                    ? { background: "var(--series-1)", color: "#fff" }
                    : {
                        background: "transparent",
                        color: "var(--text-secondary)",
                        border: "1px solid var(--border)",
                      }
                }
                onClick={() => setStage(s)}
              >
                <span
                  aria-hidden
                  className="flex h-4.5 w-4.5 items-center justify-center rounded-full text-[10px] font-bold"
                  style={
                    s === stage
                      ? { background: "rgba(255,255,255,0.25)" }
                      : { border: "1px solid var(--baseline)", color: "var(--text-muted)" }
                  }
                >
                  {i + 1}
                </span>
                {STAGE_LABELS[s]}
              </button>
            </div>
          ))}
        </div>

        {gate.data && (
          <div className="space-y-3">
            <StatusBadge
              status={gate.data.ready ? "good" : "critical"}
              label={gate.data.ready ? "게이트 통과 가능" : "게이트 차단됨"}
            />
            <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {gate.data.domains.map((d) => (
                <li
                  key={d.domain}
                  className="flex items-center justify-between rounded-lg px-3 py-2"
                  style={{ border: "1px solid var(--grid-hairline)" }}
                >
                  <span className="text-sm font-medium">{DOMAIN_LABELS[d.domain]}</span>
                  <StatusBadge
                    status={d.ready ? "good" : d.run_id ? "critical" : "neutral"}
                    label={d.ready ? "Ready" : (d.reason ?? "미실행")}
                  />
                </li>
              ))}
            </ul>
          </div>
        )}
      </Card>

      <RunsCard projectId={projectId} runs={runs.data ?? []} onChange={invalidate} />
    </div>
  );
}

function RunsCard({
  projectId,
  runs,
  onChange,
}: {
  projectId: number;
  runs: SignoffRun[];
  onChange: () => void;
}) {
  const [form, setForm] = useState({
    domain: "sta" as Domain,
    stage: "placement" as Stage,
    tool: "",
  });
  const create = useMutation({
    mutationFn: () => api.createRun(projectId, form),
    onSuccess: () => {
      setForm({ ...form, tool: "" });
      onChange();
    },
  });

  return (
    <Card title="사인오프 런" subtitle="도메인별 런 생성 · 상태 갱신 · 위반/웨이버 관리">
      <form
        className="mb-4 flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <Field label="도메인">
          <select
            className="input"
            value={form.domain}
            onChange={(e) => setForm({ ...form, domain: e.target.value as Domain })}
          >
            {Object.entries(DOMAIN_LABELS).map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </Field>
        <Field label="스테이지">
          <select
            className="input"
            value={form.stage}
            onChange={(e) => setForm({ ...form, stage: e.target.value as Stage })}
          >
            {STAGES.map((s) => (
              <option key={s} value={s}>
                {STAGE_LABELS[s]}
              </option>
            ))}
          </select>
        </Field>
        <Field label="툴">
          <input
            className="input w-36"
            value={form.tool}
            onChange={(e) => setForm({ ...form, tool: e.target.value })}
            placeholder="PrimeTime"
            required
          />
        </Field>
        <button className="btn btn-primary" disabled={create.isPending}>
          런 생성
        </button>
      </form>

      {runs.length === 0 ? (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          아직 런이 없습니다.
        </p>
      ) : (
        <ul className="space-y-3">
          {runs.map((run) => (
            <RunRow key={run.id} run={run} onChange={onChange} />
          ))}
        </ul>
      )}
    </Card>
  );
}

function RunRow({ run, onChange }: { run: SignoffRun; onChange: () => void }) {
  const [open, setOpen] = useState(false);
  const update = useMutation({
    mutationFn: (status: "passed" | "failed") => api.updateRun(run.id, status),
    onSuccess: onChange,
  });

  return (
    <li className="rounded-lg px-4 py-3" style={{ border: "1px solid var(--grid-hairline)" }}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold">{DOMAIN_LABELS[run.domain]}</span>
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>
            {STAGE_LABELS[run.stage]} · {run.tool} · run #{run.id}
          </span>
          <StatusBadge
            status={
              run.status === "passed" ? "good" : run.status === "failed" ? "critical" : "warning"
            }
            label={run.status}
          />
        </div>
        <div className="flex gap-2">
          <button className="btn btn-ghost" onClick={() => update.mutate("passed")}>
            Pass
          </button>
          <button className="btn btn-ghost" onClick={() => update.mutate("failed")}>
            Fail
          </button>
          <button className="btn btn-ghost" onClick={() => setOpen((v) => !v)}>
            위반 {open ? "접기" : "보기"}
          </button>
        </div>
      </div>
      {open && <ViolationList runId={run.id} onChange={onChange} />}
    </li>
  );
}

function ViolationList({ runId, onChange }: { runId: number; onChange: () => void }) {
  const qc = useQueryClient();
  const violations = useQuery({
    queryKey: ["violations", runId],
    queryFn: () => api.listViolations(runId),
  });
  const [form, setForm] = useState({ check_name: "", severity: "error" as Severity });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["violations", runId] });
    onChange();
  };
  const add = useMutation({
    mutationFn: () => api.addViolation(runId, form),
    onSuccess: () => {
      setForm({ ...form, check_name: "" });
      refresh();
    },
  });
  const waive = useMutation({
    mutationFn: (violationId: number) =>
      api.waiveViolation(violationId, {
        reason: window.prompt("웨이버 사유를 입력하세요") || "no reason given",
        approved_by: "web-ui",
      }),
    onSuccess: refresh,
  });

  const severityStatus = (s: Severity) =>
    s === "critical" ? "critical" : s === "error" ? "serious" : s === "warning" ? "warning" : "neutral";

  return (
    <div className="hairline-t mt-3 pt-3">
      <form
        className="mb-3 flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          add.mutate();
        }}
      >
        <Field label="체크 이름">
          <input
            className="input w-40"
            value={form.check_name}
            onChange={(e) => setForm({ ...form, check_name: e.target.value })}
            placeholder="M2.S.1"
            required
          />
        </Field>
        <Field label="심각도">
          <select
            className="input"
            value={form.severity}
            onChange={(e) => setForm({ ...form, severity: e.target.value as Severity })}
          >
            {["info", "warning", "error", "critical"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </Field>
        <button className="btn btn-ghost" disabled={add.isPending}>
          위반 추가
        </button>
      </form>

      {(violations.data ?? []).length === 0 ? (
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          위반 없음
        </p>
      ) : (
        <ul className="space-y-1.5">
          {violations.data!.map((v) => (
            <li key={v.id} className="flex items-center justify-between text-sm">
              <span className="flex items-center gap-2">
                <StatusBadge status={severityStatus(v.severity)} label={v.severity} />
                <span>{v.check_name}</span>
                {v.location && (
                  <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                    {v.location}
                  </span>
                )}
              </span>
              {v.status === "waived" ? (
                <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                  웨이버 승인됨 ({v.waiver?.approved_by})
                </span>
              ) : (
                <button className="btn btn-ghost" onClick={() => waive.mutate(v.id)}>
                  웨이버
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
