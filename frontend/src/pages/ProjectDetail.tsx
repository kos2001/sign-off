import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";

import type { Domain, Severity, SignoffRun, Stage } from "../api";
import { api, DOMAIN_LABELS, STAGE_LABELS, STAGES } from "../api";
import { useAuth } from "../components/AuthProvider";
import { RunEvidencePanel } from "../components/RunEvidencePanel";
import { ViolationActions } from "../components/ViolationActions";
import { AgentReviewPanel } from "../components/AgentReviewPanel";
import { ReadyProgress, RunStatusBar } from "../components/charts";
import { Card, Field, StatusBadge } from "../components/ui";
import { defaultSignoffTool, SIGNOFF_TOOLS, signoffTool } from "../signoffTools";

function gateReasonLabel(reason?: string | null) {
  const labels: Record<string, string> = {
    'no run for this stage': '이 단계 검증 미실행',
    'RTL requires captured ladder evidence; rerun the analysis': 'RTL 실행 근거 필요 · 재분석 필요',
    'Imported path report does not establish full STA coverage': 'STA 전체 검증 범위 미확인',
    'Imported marker report does not establish full DRC coverage': 'DRC 전체 검증 범위 미확인',
    'Captured verification coverage required; manual status is not evidence': '검증 범위 근거 필요 · 수동 상태만으로 통과 불가',
    "latest run status is 'running'": '최신 런 실행 중',
    "latest run status is 'failed'": '최신 런 실패',
    'RTL evidence is failed; required stages must all pass': 'RTL 필수 단계 실패',
    'RTL evidence is running; required stages must all pass': 'RTL 필수 단계 미완료',
  };
  if (!reason) return '미실행';
  const blocking = reason.match(/^(\d+) open blocking violation\(s\)$/);
  return blocking ? `미해결 차단 위반 ${blocking[1]}건` : labels[reason] ?? reason;
}

export default function ProjectDetail() {
  const { id } = useParams();
  const projectId = Number(id);
  const auth = useAuth();
  const qc = useQueryClient();
  const [stage, setStage] = useState<Stage>("placement");
  const gateExport = useMutation({
    mutationFn: (input: { projectId: number; stage: Stage }) => api.exportGate(input.projectId, input.stage),
    onSuccess: (blob, input) => {
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `project-${input.projectId}-${input.stage}-gate.json`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
  });

  const project = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.getProject(projectId),
  });
  // 5s polling keeps runs and gate status live while ladders execute elsewhere
  const runs = useQuery({
    queryKey: ["runs", projectId],
    queryFn: () => api.listRuns(projectId),
    refetchInterval: 5000,
  });
  const gate = useQuery({
    queryKey: ["gate", projectId, stage],
    queryFn: () => api.gateStatus(projectId, stage),
    refetchInterval: 5000,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["runs", projectId] });
    qc.invalidateQueries({ queryKey: ["gate", projectId] });
  };

  // A5 사인오프 종합 판정관 -> V 검증 에이전트: chained, only when the gate
  // for this stage isn't ready (see backend/app/hermes.py trigger_ko).
  const gateReview = useQuery({
    queryKey: ["agent-review-gate", projectId, stage, gate.data],
    queryFn: () => api.reviewGate({ gate_status: gate.data }),
    enabled: !!gate.data,
    staleTime: Infinity, refetchOnWindowFocus: false, retry: false,
  });

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
      <header className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-xl font-bold">{p.name}</h1>
        <span className="text-sm" style={{ color: "var(--text-muted)" }}>
          {p.process_node} · {p.foundry}
        </span>
        <Link className="btn btn-primary" to={`/projects/${projectId}/violations`}>전체 위반 검토</Link>
        <Link className="btn btn-ghost" to={`/projects/${projectId}/compare`}>런 비교</Link>
        {auth.can(projectId, "editor") && <Link className="btn btn-ghost" to={`/projects/${projectId}/import`}>보고서 가져오기</Link>}
        {auth.state.mode === "required" && auth.can(projectId, "owner") && <Link className="btn btn-ghost" to={`/projects/${projectId}/members`}>접근 권한</Link>}
      </header>

      <Card
        title="Shift-left 스테이지 게이트"
        subtitle="도메인별 최신 런의 검증 범위와 설계 리비전을 확인합니다. 수동 통과 상태만으로는 게이트를 통과할 수 없습니다."
      >
        <div className="mb-4 space-y-2 text-sm">
          <button className="btn btn-ghost" disabled={gateExport.isPending} onClick={() => gateExport.mutate({ projectId, stage })}>{gateExport.isPending ? `${STAGE_LABELS[gateExport.variables.stage]} 근거 파일 준비 중…` : '게이트·근거 JSON 다운로드'}</button>
          <p className="text-[var(--text-muted)]">다운로드 시점의 선택 스테이지 게이트·최신 런 결과·현재 위반과 웨이버를 포함합니다. 원본 파일·변경 이력·AI 의견은 별도입니다. 최대 8 MiB / 위반 10,000건.</p>
          {gateExport.variables?.projectId === projectId && gateExport.variables.stage === stage && gateExport.isError && <p role="alert">{gateExport.error.message}</p>}
          {gateExport.variables?.projectId === projectId && gateExport.variables.stage === stage && gateExport.isSuccess && <p role="status">게이트 근거 다운로드를 시작했습니다.</p>}
        </div>
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
            <div className="flex flex-wrap items-center gap-3">
              <StatusBadge
                status={gate.data.ready ? "good" : "critical"}
                label={gate.data.ready ? "게이트 통과 가능" : "게이트 차단됨"}
              />
              <ReadyProgress
                ready={gate.data.domains.filter((d) => d.ready).length}
                total={gate.data.domains.length}
              />
            </div>
            {gate.data.revision_check && <div className="rounded-lg border border-[var(--border)] p-3 space-y-1 text-sm" aria-label="게이트 설계 리비전 확인">
              <p className="font-semibold">{gate.data.revision_check.status === 'consistent' ? '선언된 설계 리비전 일치' : gate.data.revision_check.status === 'mismatch' ? '설계 리비전 불일치 · 게이트 차단' : '설계 리비전 미확인 · 게이트 차단'}</p>
              {gate.data.revision_check.revisions.length > 0 && <p className="break-words">선택된 리비전: {gate.data.revision_check.revisions.join(' / ')}</p>}
              {gate.data.revision_check.missing_domains.length > 0 && <p>리비전 누락: {gate.data.revision_check.missing_domains.map(domain => DOMAIN_LABELS[domain]).join(', ')}</p>}
              <p className="text-[var(--text-muted)]">도메인별 최신 런을 비교합니다. 리비전 이름의 일치만으로 실제 설계 입력과 전체 검증 범위가 같다는 것을 보장하지 않습니다.</p>
            </div>}
            <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {gate.data.domains.map((d) => (
                <li
                  key={d.domain}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg px-3 py-2"
                  style={{ border: "1px solid var(--grid-hairline)" }}
                >
                  <span className="text-sm font-medium">{DOMAIN_LABELS[d.domain]}</span>
                  <StatusBadge
                    status={d.ready ? "good" : d.run_id ? "critical" : "neutral"}
                    label={d.ready ? "준비 완료" : gateReasonLabel(d.reason)}
                  />
                  {d.run_id && <span className="w-full break-words text-xs text-[var(--text-muted)]">런 #{d.run_id} · 리비전: {d.design_revision || '미기록'}</span>}
                </li>
              ))}
            </ul>
            <div className="pt-3">
              <h3 className="font-semibold text-sm">에이전트 검토 흐름 · A5 종합 → V 검증</h3>
              <p className="mt-1 text-xs text-[var(--text-muted)]">선택한 스테이지의 현재 게이트 근거를 검토합니다. 두 역할의 결과는 함께 표시되며, 승인·웨이버는 사람이 별도로 결정합니다.</p>
              <AgentReviewPanel role="a5_synth" scope={STAGE_LABELS[stage]} review={gateReview.data?.a5} loading={gateReview.isFetching} failed={gateReview.isError} onRetry={() => void gateReview.refetch()} retryLabel="종합·검증 다시 시도" />
              <AgentReviewPanel role="v_verify" scope={STAGE_LABELS[stage]} review={gateReview.data?.v} loading={gateReview.isFetching} waitingLabel={gateReview.isError ? '진행 확인 불가' : gateReview.data?.a5.available === false ? '선행 검토 미완료' : gateReview.data?.a5.triggered === false ? '조건 미해당 · 실행 안 됨' : '실행 전'} waiting={gateReview.isError ? '요청 결과를 받지 못해 V의 실행 여부를 확인할 수 없습니다.' : gateReview.data?.a5.available === false ? '선행 검토 미완료 · A5 의견이 없어 V는 실행되지 않았습니다.' : gateReview.data?.a5.triggered === false ? '게이트가 통과 가능하여 A5와 V를 실행하지 않았습니다.' : 'A5 종합 검토가 완료되면 원본 근거와 대조합니다.'} onRetry={() => void gateReview.refetch()} retryLabel="종합·검증 다시 시도" />
            </div>
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
  const auth = useAuth();
  const [form, setForm] = useState({
    domain: "sta" as Domain,
    stage: "placement" as Stage,
    tool: defaultSignoffTool("sta"),
  });
  const create = useMutation({
    mutationFn: () => api.createRun(projectId, form),
    onSuccess: () => {
      onChange();
    },
  });
  const selectedTool = signoffTool(form.domain, form.tool);

  const statusCounts = { passed: 0, failed: 0, running: 0, incomplete: 0 };
  for (const r of runs) statusCounts[r.status] += 1;

  return (
    <Card title="사인오프 런" subtitle="도메인별 런 생성 · 상태 갱신 · 위반/웨이버 관리">
      <div className="mb-4">
        <RunStatusBar counts={statusCounts} />
      </div>
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
            onChange={(e) => {
              const domain = e.target.value as Domain;
              setForm({ ...form, domain, tool: defaultSignoffTool(domain) });
            }}
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
        <Field label="결과 생성 툴">
          <select
            aria-describedby="run-tool-help"
            className="input min-w-56"
            value={form.tool}
            onChange={(e) => setForm({ ...form, tool: e.target.value })}
            required
          >
            {SIGNOFF_TOOLS[form.domain].map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </Field>
        <button className="btn btn-primary" disabled={create.isPending || !auth.can(projectId, "editor")}>
          런 생성
        </button>
      </form>

      <section id="run-tool-help" aria-label="선택한 툴 안내" className="mb-4 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-3 text-sm space-y-1">
        <p className="font-semibold">{selectedTool.label}</p>
        <p>{selectedTool.description}</p>
        <p className="text-xs text-[var(--text-secondary)]">{selectedTool.workflow} 여기서 런을 생성하면 툴을 실행하지 않고 수동 런의 출처만 기록하며, 검증 근거가 없어 게이트를 통과시키지 않습니다.</p>
        {form.domain === 'rtl' && <Link className="text-xs underline" to="/analysis#rtl">RTL 분석 실행으로 이동</Link>}
        {(form.domain === 'sta' || form.domain === 'pv') && <Link className="text-xs underline" to={`/projects/${projectId}/import${form.domain === 'pv' ? '/klayout' : ''}`}>{form.domain === 'sta' ? 'OpenSTA' : 'KLayout DRC'} 보고서 가져오기로 이동</Link>}
      </section>

      {create.isError && <p role="alert">{create.error.message}</p>}
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
  const auth = useAuth();
  const [open, setOpen] = useState(false);
  const update = useMutation({
    mutationFn: (status: "passed" | "failed") => api.updateRun(run.id, status),
    onSuccess: onChange,
  });

  return (
    <li aria-label={`런 #${run.id}`} className="rounded-lg px-4 py-3" style={{ border: "1px solid var(--grid-hairline)" }}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-3">
          <span className="text-sm font-semibold">{DOMAIN_LABELS[run.domain]}</span>
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>
            {STAGE_LABELS[run.stage]} · {run.tool} · run #{run.id}
          </span>
          <StatusBadge
            status={
              run.status === "passed" ? "good" : run.status === "failed" ? "critical" : "warning"
            }
            label={run.status === "incomplete" ? "검증 미완료" : run.status}
          />
        </div>
        <div className="flex flex-wrap gap-2">
          {run.evidence_source === 'opensta_report' && <Link className="btn btn-ghost" to={`/runs/${run.id}/paths`}>타이밍 경로</Link>}
          {run.evidence_source === 'klayout_report' && <Link className="btn btn-ghost" to={`/runs/${run.id}/markers`}>DRC 마커 탐색</Link>}
          <button className="btn btn-ghost" disabled={!auth.can(run.project_id, "editor") || update.isPending || run.result_locked} title={run.result_locked ? "서버 분석 결과는 다시 실행하여 갱신하세요" : "수동 상태 변경"} onClick={() => update.mutate("passed")}>
            Pass
          </button>
          <button className="btn btn-ghost" disabled={!auth.can(run.project_id, "editor") || update.isPending || run.result_locked} title={run.result_locked ? "서버 분석 결과는 다시 실행하여 갱신하세요" : "수동 상태 변경"} onClick={() => update.mutate("failed")}>
            Fail
          </button>
          <button className="btn btn-ghost" onClick={() => setOpen((v) => !v)}>
            위반 {open ? "접기" : "보기"}
          </button>
        </div>
      </div>
      {update.isError && <p role="alert">{update.error.message}</p>}
      <RunEvidencePanel run={run} />
      {open && <ViolationList locked={run.result_locked} runId={run.id} onChange={onChange} />}
    </li>
  );
}

function ViolationList({ runId, onChange, locked }: { runId: number; onChange: () => void; locked: boolean }) {
  const qc = useQueryClient();
  const violations = useQuery({
    queryKey: ["violations", runId],
    queryFn: () => api.listViolations(runId),
  });
  const auth = useAuth();
  const projectId = Number(useParams().id);
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
  const severityStatus = (s: Severity) =>
    s === "critical" ? "critical" : s === "error" ? "serious" : s === "warning" ? "warning" : "neutral";

  return (
    <div className="hairline-t mt-3 pt-3">
      <form
        className={`mb-3 flex flex-wrap items-end gap-2 ${locked ? "hidden" : ""}`}
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
        <button className="btn btn-ghost" disabled={!auth.can(projectId, "editor") || add.isPending}>
          위반 추가
        </button>
      </form>

      {add.isError && <p role="alert">{add.error.message}</p>}
      {violations.isPending ? <p role="status">위반 불러오는 중…</p> : violations.isError ? (
        <p role="alert">{violations.error.message} <button className="btn btn-ghost" onClick={() => violations.refetch()}>다시 시도</button></p>
      ) : violations.data.length === 0 ? (
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          위반 없음
        </p>
      ) : (
        <ul className="space-y-1.5">
          {violations.data!.map((v) => (
            <li key={v.id} className="rounded-lg border border-[var(--border)] p-3 space-y-3 text-sm">
              <span className="flex items-center gap-2">
                <StatusBadge status={severityStatus(v.severity)} label={v.severity} />
                <span>{v.check_name}</span>
                {v.location && (
                  <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                    {v.location}
                  </span>
                )}
              </span>
              <ViolationActions violation={v} onChange={refresh} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
