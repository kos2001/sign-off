import { useAuth } from "../components/AuthProvider";
import { PULSE_TESTBENCH } from "./pulseTestbench";
import { SimulationDetails } from "../components/SimulationDetails";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router";

import type { RtlSignoffResult, StaExecutionResult } from "../api";
import { api } from "../api";
import { AGENT_ROLES, type AgentRoleId } from "../agentRoles";
import { AgentReviewPanel } from "../components/AgentReviewPanel";
import { IrDropHeatmap, PowerStackBars, SlackBars } from "../components/charts";
import { Card, Field, Meter, StatTile, StatusBadge } from "../components/ui";

/* Real design example: lowRISC Ibex RISC-V core hardened on SkyWater SKY130
   (the OpenROAD/OpenLane reference flow). VDD 1.8V, clk 10ns (100MHz), SKY130
   liberty corner names, Ibex module/net names. Values are representative of a
   100MHz Ibex build; deterministic so refetches don't repaint the story. */

function ibexFloorplanGrids(size = 10) {
  const density: number[][] = [];
  const activity: number[][] = [];
  const strength: number[][] = [];
  for (let r = 0; r < size; r++) {
    const dRow: number[] = [];
    const aRow: number[] = [];
    const sRow: number[] = [];
    for (let c = 0; c < size; c++) {
      // multdiv_fast cluster near (2,7): dense and busy; register file corner
      // near (7,2) sits far from the M4 power straps (weak PDN)
      const multdiv = Math.exp(-((r - 2) ** 2 + (c - 7) ** 2) / 6);
      const regfile = Math.exp(-((r - 7) ** 2 + (c - 2) ** 2) / 8);
      dRow.push(Math.min(1, 0.25 + 0.65 * multdiv + 0.2 * regfile));
      aRow.push(Math.min(1, 0.2 + 0.7 * multdiv + 0.3 * regfile));
      sRow.push(Math.max(0.35, 1.1 - 0.6 * regfile));
    }
    density.push(dRow);
    activity.push(aRow);
    strength.push(sRow);
  }
  return { cell_density: density, switching_activity: activity, pdn_strength: strength };
}

// Glitch-prone nets in ibex_multdiv_fast / ibex_alu (deep arithmetic logic)
const IBEX_NETS = [
  { name: "alu_adder_result_ex_o[31]", cap_ff: 22, functional_toggle_rate: 0.22, total_toggle_rate: 0.61 },
  { name: "multdiv/mac_res[15]", cap_ff: 26, functional_toggle_rate: 0.31, total_toggle_rate: 0.78, transport_fraction: 0.8 },
  { name: "multdiv/imd_val_d[0][7]", cap_ff: 14, functional_toggle_rate: 0.18, total_toggle_rate: 0.33 },
  { name: "alu/cmp_result", cap_ff: 9, functional_toggle_rate: 0.12, total_toggle_rate: 0.41, transport_fraction: 0.6 },
  { name: "multdiv/alu_operand_a[19]", cap_ff: 21, functional_toggle_rate: 0.28, total_toggle_rate: 0.84 },
];

// SKY130 liberty corners; 12 worst setup endpoints of the ID->EX stage @ 100MHz
const IBEX_CORNERS = [
  { name: "ss_100C_1v60", endpoint_slacks_ps: [-320, -145, 60, -85, 210, 310, -30, 140, 480, -230, 95, 170] },
  { name: "tt_025C_1v80", endpoint_slacks_ps: [-80, 25, 250, 90, 400, 450, 40, 280, 600, -60, 210, 330] },
  { name: "ff_n40C_1v95", endpoint_slacks_ps: [120, 45, 380, 200, 550, 610, 85, 420, 770, 30, 300, 440] },
];

// Realistic buggy example (default): a fast-domain FSM's status bits read
// straight into the APB clock domain with no 2-FF synchronizer — the
// deterministic CDC/FSM checks below actually catch this, they aren't
// staged. verilator lint and yosys synthesis both pass cleanly, so the
// REJECTED verdict comes entirely from the design-rule stage (DRC-CDC-001 +
// DRC-FSM-002), not tool noise.
const BUGGY_RTL = `module cdc_status_bridge (
  input  logic clk_fast,
  input  logic clk_apb,
  input  logic rst_n,
  input  logic start_i,
  output logic apb_busy_o,
  output logic apb_error_o
);
  typedef enum logic [2:0] { IDLE, LOAD, PROCESS, DONE, ERROR } state_t;
  state_t state_q, state_d;

  reg legacy_error_latch;  // carried over from the old fixed-function block

  logic busy_q, error_q;

  // fast-domain FSM
  always_ff @(posedge clk_fast or negedge rst_n) begin
    if (!rst_n) state_q <= IDLE;
    else        state_q <= state_d;
  end

  always_comb begin
    state_d = state_q;
    case (state_q)
      default: state_d = IDLE;
      IDLE:    if (start_i) state_d = LOAD;
      LOAD:    state_d = PROCESS;
      PROCESS: begin
        if (start_i) state_d = ERROR;
        else         state_d = DONE;
      end
      DONE:    state_d = IDLE;
      ERROR:   ; // stuck once entered — requires an external reset, no recovery path
    endcase
  end

  always_ff @(posedge clk_fast or negedge rst_n) begin
    if (!rst_n) begin
      busy_q  <= 1'b0;
      error_q <= 1'b0;
    end else begin
      busy_q  <= (state_q == LOAD) || (state_q == PROCESS);
      error_q <= (state_q == ERROR);
    end
  end

  // BUG: the fast-domain status registers are read straight into the APB
  // clock domain below with no 2-FF synchronizer.
  always_ff @(posedge clk_apb or negedge rst_n) begin
    if (!rst_n) begin
      apb_busy_o         <= 1'b0;
      apb_error_o        <= 1'b0;
      legacy_error_latch <= 1'b0;
    end else begin
      apb_busy_o         <= busy_q;
      apb_error_o        <= error_q;
      legacy_error_latch <= error_q;
    end
  end
endmodule
`;

// Ibex-style pulse synchronizer (clean 2-FF CDC) — contrast example: same
// ladder, no violations, so the agent panel below explicitly shows "미개입".
const CLEAN_RTL = `module ibex_pulse_sync (
  input  logic clk_src_i,
  input  logic clk_dst_i,
  input  logic rst_ni,
  input  logic pulse_src_i,
  output logic pulse_dst_o
);
  logic toggle_q;
  logic toggle_q_meta, toggle_q_sync, toggle_q_prev;

  always_ff @(posedge clk_src_i or negedge rst_ni) begin
    if (!rst_ni) toggle_q <= 1'b0;
    else if (pulse_src_i) toggle_q <= ~toggle_q;
  end

  always_ff @(posedge clk_dst_i or negedge rst_ni) begin
    if (!rst_ni) begin
      toggle_q_meta <= 1'b0;
      toggle_q_sync <= 1'b0;
      toggle_q_prev <= 1'b0;
    end else begin
      toggle_q_meta <= toggle_q;
      toggle_q_sync <= toggle_q_meta;
      toggle_q_prev <= toggle_q_sync;
    end
  end

  assign pulse_dst_o = toggle_q_sync ^ toggle_q_prev;
endmodule
`;

export default function Analysis() {
  const { hash } = useLocation();

  // client-side routing never triggers the browser's native hash scroll,
  // and the target section doesn't exist in the DOM until React mounts it
  useEffect(() => {
    if (!hash) return;
    const el = document.getElementById(hash.slice(1));
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [hash]);

  return (
    <div className="space-y-6">
      <RtlSignoffSection />
      <StaSignoffSection />
      <IrDropSection />
      <TimingSection />
      <GlitchSection />
    </div>
  );
}

function StaSignoffSection() {
  const auth = useAuth();
  const qc = useQueryClient();
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.listProjects });
  const [projectId, setProjectId] = useState<number | "">("");
  const [stage, setStage] = useState("synthesis");
  const [topModule, setTopModule] = useState("");
  const [revision, setRevision] = useState("");
  const [scenario, setScenario] = useState("");
  const [netlist, setNetlist] = useState("");
  const [liberty, setLiberty] = useState("");
  const [sdc, setSdc] = useState("");
  const [spef, setSpef] = useState("");
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<Record<'opensta' | 'persist', { status: 'pending' | 'running' | 'pass' | 'error'; detail?: string }>>({ opensta: { status: 'pending' }, persist: { status: 'pending' } });
  const [result, setResult] = useState<StaExecutionResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  type BatchRow = { scenario: string; liberty: string; sdc: string; spef: string; requireSpef: boolean };
  const [batchRows, setBatchRows] = useState<BatchRow[]>([]);
  const [batchRunning, setBatchRunning] = useState(false);
  const [batchError, setBatchError] = useState<string | null>(null);
  const [batchId, setBatchId] = useState<number | null>(null);
  const [cancellingBatch, setCancellingBatch] = useState<number | null>(null);
  const [retryingBatch, setRetryingBatch] = useState<number | null>(null);
  const expectedScenarios = useQuery({
    queryKey: ['sta-scenarios', projectId, stage],
    queryFn: () => api.staScenarios(Number(projectId), stage as 'rtl' | 'synthesis' | 'placement' | 'routing' | 'final'),
    enabled: projectId !== '',
  });
  const batchHistory = useQuery({
    queryKey: ['sta-batches', projectId],
    queryFn: () => api.staBatches(Number(projectId)),
    enabled: projectId !== '',
    refetchInterval: query => query.state.data?.items.some(item => item.status === 'queued' || item.status === 'running') ? 2000 : false,
  });
  const fields = [
    { label: "게이트 레벨 Verilog 넷리스트", value: netlist, set: setNetlist, accept: ".v,.sv", max: 1_000_000 },
    { label: "Liberty 타이밍 라이브러리", value: liberty, set: setLiberty, accept: ".lib", max: 5_000_000 },
    { label: "SDC 제약", value: sdc, set: setSdc, accept: ".sdc", max: 500_000 },
    { label: "SPEF 배선 기생성분 (선택)", value: spef, set: setSpef, accept: ".spef", max: 8_000_000 },
  ];
  function loadFile(file: File | undefined, setter: (value: string) => void, max: number) {
    if (!file) return;
    if (file.size > max) return;
    void file.text().then(setter);
  }
  async function execute() {
    setRunning(true); setResult(null); setError(null);
    setProgress({ opensta: { status: 'pending' }, persist: { status: 'pending' } });
    try {
      await api.staSignoffStream({ project_id: Number(projectId), stage: stage as "rtl" | "synthesis" | "placement" | "routing" | "final", top_module: topModule.trim(), design_revision: revision.trim(), scenario: scenario.trim(), netlist, liberty, sdc, ...(spef.trim() ? { spef } : {}) }, event => {
        if (event.event === 'stage_start') setProgress(previous => ({ ...previous, [event.stage]: { status: 'running' } }));
        else if (event.event === 'stage_done') setProgress(previous => ({ ...previous, [event.stage]: { status: 'pass', detail: event.detail } }));
        else setResult(event.result);
      });
    } catch (reason) {
      const message = (reason as Error).message;
      setError(message);
      setProgress(previous => Object.fromEntries(Object.entries(previous).map(([name, value]) => [name, value.status === 'running' ? { status: 'error', detail: message } : value])) as typeof previous);
    }
    finally { setRunning(false); }
  }
  function updateBatch(index: number, patch: Partial<BatchRow>) {
    setBatchRows(rows => rows.map((row, i) => i === index ? { ...row, ...patch } : row));
  }
  function loadBatchFile(file: File | undefined, index: number, key: 'liberty' | 'sdc' | 'spef', max: number) {
    if (!file || file.size > max) return;
    void file.text().then(value => updateBatch(index, { [key]: value }));
  }
  async function executeBatch() {
    setBatchRunning(true); setBatchError(null); setBatchId(null);
    try {
      const receipt = await api.submitStaBatch({ project_id: Number(projectId), stage: stage as 'rtl' | 'synthesis' | 'placement' | 'routing' | 'final',
        top_module: topModule.trim(), design_revision: revision.trim(), netlist,
        scenarios: batchRows.map(row => ({ scenario: row.scenario.trim(), liberty: row.liberty,
          sdc: row.sdc, ...(row.spef.trim() ? { spef: row.spef } : {}) })) });
      setBatchId(receipt.id);
      await qc.invalidateQueries({ queryKey: ['sta-batches', projectId] });
    } catch (reason) {
      setBatchError((reason as Error).message);
    } finally { setBatchRunning(false); }
  }
  const valid = projectId !== "" && /^[A-Za-z_][A-Za-z0-9_$]*$/.test(topModule.trim()) && revision.trim() && scenario.trim() && netlist.trim() && liberty.trim() && sdc.trim();
  const batchNames = batchRows.map(row => row.scenario.trim().toLocaleLowerCase());
  const batchValid = projectId !== '' && /^[A-Za-z_][A-Za-z0-9_$]*$/.test(topModule.trim()) && revision.trim() && netlist.trim() && batchRows.length > 0 && batchRows.length <= 8 && batchRows.every(row => row.scenario.trim() && row.liberty.trim() && row.sdc.trim() && (!row.requireSpef || row.spef.trim())) && new Set(batchNames).size === batchNames.length;
  return <Card id="sta-signoff" title="OpenSTA 정적 타이밍 실행" subtitle="넷리스트 · Liberty · SDC → 격리 OpenSTA → 저장된 경로·위반·실행 근거">
    <div className="mb-4 rounded-lg border border-[var(--border)] px-3 py-2 text-xs text-[var(--text-secondary)]">
      이 단계는 서버의 OpenSTA 도구만 실행하며 AI 에이전트는 개입하지 않습니다. 실행 후 런 작업공간에서 A2 타이밍 분석가 검토를 사용자가 별도로 요청할 수 있습니다.
    </div>
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <Field label="프로젝트"><select className="input" value={projectId} onChange={e => setProjectId(e.target.value ? Number(e.target.value) : "")}><option value="">선택</option>{(projects.data ?? []).filter(p => auth.can(p.id, "editor")).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
      <Field label="설계 단계"><select className="input" value={stage} onChange={e => setStage(e.target.value)}>{["rtl", "synthesis", "placement", "routing", "final"].map(v => <option key={v}>{v}</option>)}</select></Field>
      <Field label="최상위 모듈"><input className="input" value={topModule} maxLength={120} onChange={e => setTopModule(e.target.value)} placeholder="chip_top" /></Field>
      <Field label="설계 리비전"><input className="input" value={revision} maxLength={160} onChange={e => setRevision(e.target.value)} placeholder="Git SHA" /></Field>
      <Field label="시나리오"><input className="input" value={scenario} maxLength={160} onChange={e => setScenario(e.target.value)} placeholder="ss_0p72v_125c" /></Field>
    </div>
    <div className="mt-4 grid gap-4 lg:grid-cols-2">{fields.map(field => <Field key={field.label} label={field.label}>
      <input className="mb-2 block w-full text-xs" type="file" accept={field.accept} onChange={e => loadFile(e.target.files?.[0], field.set, field.max)} />
      <textarea className="code-editor w-full" rows={10} value={field.value} maxLength={field.max} spellCheck={false} onChange={e => field.set(e.target.value)} aria-label={field.label} />
      <span className="text-xs text-[var(--text-muted)]">{new Blob([field.value]).size.toLocaleString()} / {field.max.toLocaleString()} bytes</span>
    </Field>)}</div>
    <p className="mt-3 text-xs text-[var(--text-secondary)]">SPEF를 제공하면 OpenSTA가 배선 저항·정전용량을 읽어 타이밍에 반영합니다. 비워 두면 기생성분 없는 분석으로 근거에 기록합니다. SDC는 Tcl 기반 제약 파일이며 서버는 일반 파일·프로세스·네트워크 명령을 비활성화한 제한 컨테이너에서 실행합니다.</p>
    <button className="btn btn-primary mt-3" disabled={!valid || running} onClick={execute}>{running ? "OpenSTA 실행 중…" : "OpenSTA 실행 및 기록"}</button>
    {(running || result || error) && <div className="mt-3 grid gap-2 sm:grid-cols-2" aria-live="polite">{(['opensta', 'persist'] as const).map(name => <div key={name} className="rounded-lg border border-[var(--border)] p-3 text-sm"><div className="flex justify-between"><strong>{name === 'opensta' ? 'OpenSTA 분석' : '근거 저장'}</strong><span>{progress[name].status === 'pending' ? '대기' : progress[name].status === 'running' ? '실행 중' : progress[name].status === 'error' ? '중단' : '완료'}</span></div>{progress[name].detail && <p className="mt-1 text-xs text-[var(--text-secondary)]">{progress[name].detail}</p>}</div>)}</div>}
    {error && <p role="alert" className="mt-3 text-sm">{error}</p>}
    {result && <div className="mt-4 rounded-lg border border-[var(--border)] p-3 text-sm space-y-2"><p><strong>런 #{result.run_id}</strong> · 보고 경로 {result.metrics.reported_paths}개 · 위반 {result.metrics.violating_paths}개 · 최악 슬랙 {result.metrics.worst_reported_slack_ps ?? "없음"} ps</p><p className="text-xs text-[var(--text-secondary)]">OpenSTA {result.execution.opensta_commit.slice(0, 12)} · AI 개입 없음 · 경로 표본만 생성되어 전체 STA 게이트는 미완료로 유지됩니다.</p><Link className="btn btn-ghost inline-block" to={`/runs/${result.run_id}`}>런 작업공간 열기</Link></div>}
    <details className="mt-5 rounded-lg border border-[var(--border)] p-4">
      <summary className="cursor-pointer font-semibold">MCMM 시나리오 배치 실행</summary>
      <p className="mt-2 text-xs text-[var(--text-secondary)]">위의 프로젝트·단계·최상위 모듈·리비전·넷리스트를 공통으로 사용합니다. 서버 작업 큐에 접수되므로 브라우저를 닫아도 실행하며, 한 시나리오의 실패가 뒤 실행을 막지 않습니다. 최대 8개, 전체 입력 32 MiB입니다.</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <button className="btn btn-ghost" disabled={!expectedScenarios.data?.length || batchRunning} onClick={() => setBatchRows(expectedScenarios.data!.slice(0, 8).map(item => ({ scenario: item.name, liberty: '', sdc: '', spef: '', requireSpef: item.require_spef })))}>기대 시나리오 불러오기</button>
        <button className="btn btn-ghost" disabled={batchRows.length >= 8 || batchRunning} onClick={() => setBatchRows(rows => [...rows, { scenario: '', liberty: '', sdc: '', spef: '', requireSpef: false }])}>시나리오 추가</button>
      </div>
      {expectedScenarios.isError && <p role="alert" className="mt-2 text-sm">기대 시나리오를 불러오지 못했습니다: {expectedScenarios.error.message}</p>}
      <div className="mt-3 space-y-3">{batchRows.map((row, index) => <section key={index} className="rounded-lg border border-[var(--border)] p-3" aria-label={`배치 시나리오 ${index + 1}`}>
        <div className="flex flex-wrap items-center gap-2"><input aria-label={`배치 시나리오 ${index + 1} 이름`} className="input min-w-56 flex-1" maxLength={160} disabled={batchRunning} value={row.scenario} onChange={event => updateBatch(index, { scenario: event.target.value })} placeholder="slow-setup-functional" />{row.requireSpef && <StatusBadge status="warning" label="SPEF 필수" />}<button className="btn btn-ghost" disabled={batchRunning} onClick={() => setBatchRows(rows => rows.filter((_, i) => i !== index))}>삭제</button></div>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">{([
          ['liberty', 'Liberty', '.lib', 5_000_000], ['sdc', 'SDC', '.sdc', 500_000], ['spef', 'SPEF (선택)', '.spef', 8_000_000],
        ] as const).map(([key, label, accept, max]) => <label className="text-xs" key={key}>{label}<input className="mt-1 block w-full" type="file" accept={accept} disabled={batchRunning} onChange={event => loadBatchFile(event.target.files?.[0], index, key, max)} /><span className="text-[var(--text-muted)]">{new Blob([row[key]]).size.toLocaleString()} bytes</span></label>)}</div>
      </section>)}</div>
      {batchRows.length === 0 && <p className="mt-3 text-sm text-[var(--text-muted)]">기대 세트를 불러오거나 시나리오를 추가하세요.</p>}
      {new Set(batchNames).size !== batchNames.length && batchRows.length > 1 && <p role="alert" className="mt-2 text-sm">시나리오 이름은 대소문자를 무시하고 고유해야 합니다.</p>}
      <button className="btn btn-primary mt-3" disabled={!batchValid || batchRunning} onClick={executeBatch}>{batchRunning ? '배치 제출 중…' : `${batchRows.length}개 시나리오 작업 제출`}</button>
      {batchId && <p role="status" className="mt-2 text-xs">배치 #{batchId}가 서버 작업 큐에 접수됐습니다. 이 페이지를 닫아도 실행을 계속합니다.</p>}
      {batchError && <p role="alert" className="mt-3 text-sm">{batchError}</p>}
      <section className="mt-5 border-t border-[var(--border)] pt-4" aria-label="최근 STA 배치 이력">
        <h3 className="text-sm font-semibold">최근 배치 이력</h3>
        <p className="mt-1 text-xs text-[var(--text-muted)]">접수한 시나리오와 성공·실패·취소 상태를 서버 DB에서 조회합니다. 입력 파일 본문은 각 성공 런의 실행 근거에 저장됩니다.</p>
        {batchHistory.isPending && projectId !== '' ? <p role="status" className="mt-3 text-sm">배치 이력 불러오는 중…</p> : batchHistory.isError ? <p role="alert" className="mt-3 text-sm">{batchHistory.error.message}</p> : <ul className="mt-3 space-y-3">{(batchHistory.data?.items ?? []).slice(0, 5).map(batch => <li className="rounded-lg border border-[var(--border)] p-3" key={batch.id}>
          <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm font-semibold">배치 #{batch.id} · {batch.design_revision}</p><div className="flex items-center gap-2"><StatusBadge status={batch.status === 'completed' ? 'good' : batch.status === 'queued' ? 'neutral' : batch.status === 'running' ? 'warning' : batch.status === 'partial' ? 'serious' : 'critical'} label={{ queued: '대기', running: batch.cancel_requested ? '취소 처리 중' : '실행 중', completed: '완료', partial: '부분 성공', failed: '실패', cancelled: '취소' }[batch.status]} />{(batch.status === 'queued' || batch.status === 'running') && auth.can(Number(projectId), 'editor') && <button className="btn btn-ghost" disabled={cancellingBatch === batch.id || batch.cancel_requested} onClick={async () => { setCancellingBatch(batch.id); setBatchError(null); try { await api.cancelStaBatch(Number(projectId), batch.id); await qc.invalidateQueries({ queryKey: ['sta-batches', projectId] }); } catch (reason) { setBatchError((reason as Error).message); } finally { setCancellingBatch(null); } }}>{cancellingBatch === batch.id ? '취소 요청 중…' : '작업 취소'}</button>}{!['queued', 'running'].includes(batch.status) && auth.can(Number(projectId), 'editor') && <button className="btn btn-ghost" disabled={retryingBatch === batch.id} onClick={async () => { setRetryingBatch(batch.id); setBatchError(null); try { const retried = await api.retryStaBatch(Number(projectId), batch.id, crypto.randomUUID()); setBatchId(retried.id); await qc.invalidateQueries({ queryKey: ['sta-batches', projectId] }); } catch (reason) { setBatchError((reason as Error).message); } finally { setRetryingBatch(null); } }}>{retryingBatch === batch.id ? '재실행 접수 중…' : '동일 입력 재실행'}</button>}</div></div>
          <p className="mt-1 text-xs text-[var(--text-muted)]">{batch.stage} · {batch.top_module} · 시도 {batch.attempt}{batch.retry_of_batch_id ? ` (배치 #${batch.retry_of_batch_id}에서 재실행)` : ''} · {batch.submitted_by} · {new Date(batch.created_at.endsWith('Z') || /[+-]\d\d:\d\d$/.test(batch.created_at) ? batch.created_at : batch.created_at + 'Z').toLocaleString('ko-KR')}</p>
          <div className="mt-2 flex flex-wrap gap-2">{batch.items.map(item => <span className="rounded border border-[var(--border)] px-2 py-1 text-xs" key={item.position}>{item.scenario} · {item.run_id ? <Link className="underline" to={`/runs/${item.run_id}`}>run #{item.run_id}</Link> : item.status === 'running' ? '실행 중' : item.status === 'pending' ? '대기' : item.status === 'cancelled' ? '취소' : '실패'}</span>)}</div>
          <details className="mt-2 text-xs"><summary className="cursor-pointer text-[var(--text-secondary)]">실행 타임라인 {batch.events.length}건</summary>{batch.events.length ? <ol className="mt-2 space-y-1 border-l border-[var(--border)] pl-3">{batch.events.map(event => <li key={event.id}><time className="text-[var(--text-muted)]">{new Date(event.created_at.endsWith('Z') || /[+-]\d\d:\d\d$/.test(event.created_at) ? event.created_at : event.created_at + 'Z').toLocaleString('ko-KR')}</time> · <strong>{{ submitted: '접수', retry_submitted: '재실행 접수', started: '워커 시작', scenario_started: '시나리오 시작', scenario_completed: '시나리오 완료', scenario_failed: '시나리오 실패', scenario_cancelled: '시나리오 취소', cancel_requested: '취소 요청', finalized: '배치 종결' }[event.kind]}</strong>{event.scenario ? ` · ${event.scenario}` : ''} · {event.actor}{event.detail ? ` · ${event.detail}` : ''}</li>)}</ol> : <p className="mt-2 text-[var(--text-muted)]">타임라인 기능 도입 전 배치입니다.</p>}</details>
        </li>)}</ul>}
        {batchHistory.data?.items.length === 0 && <p className="mt-3 text-sm text-[var(--text-muted)]">저장된 배치 실행이 없습니다.</p>}
      </section>
    </details>
  </Card>;
}

const LADDER = ["lint", "design", "synthesize", "simulate"] as const;
type LiveStatus = "pending" | "running" | "pass" | "fail" | "skip" | "interrupted";

function AgentEntry({ role }: { role: AgentRoleId }) {
  const info = AGENT_ROLES[role];
  return <p className="mb-4 rounded-lg border border-[var(--border)] px-3 py-2 text-xs text-[var(--text-secondary)]">
    <strong className="text-[var(--series-1)]">{info.code} 자동 검토</strong> · {info.condition} 개입합니다.
    {' '}<Link className="underline" to={`/agents#${role}`}>자세히 보기</Link>
  </p>;
}

function RtlSignoffSection() {
  const auth = useAuth();
  const [code, setCode] = useState(BUGGY_RTL);
  const [topModule, setTopModule] = useState("");
  const [testbench, setTestbench] = useState("");
  const [testbenchTop, setTestbenchTop] = useState("tb");
  const [designRevision, setDesignRevision] = useState("");
  const [projectId, setProjectId] = useState<number | "">("");
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.listProjects });

  const [running, setRunning] = useState(false);
  const [live, setLive] = useState<Record<string, { status: LiveStatus; detail?: string }>>({});
  const [log, setLog] = useState<string[]>([]);
  const [result, setResult] = useState<RtlSignoffResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const appendLog = (line: string) =>
    setLog((prev) => [...prev, `${new Date().toLocaleTimeString("ko-KR", { hour12: false })}  ${line}`]);

  async function runLadder() {
    setRunning(true);
    setResult(null);
    setError(null);
    setLog([]);
    setLive(Object.fromEntries(LADDER.map((s) => [s, { status: "pending" as LiveStatus }])));
    appendLog("▸ 사인오프 래더 실행 요청");
    try {
      await api.rtlSignoffStream(
        { code, ...(topModule.trim() ? { top_module: topModule.trim() } : {}), ...(testbench.trim() ? { testbench, testbench_top: testbenchTop.trim() } : {}), ...(designRevision.trim() ? { design_revision: designRevision.trim() } : {}), ...(projectId !== "" ? { project_id: projectId } : {}) },
        (ev) => {
          if (ev.event === "stage_start") {
            setLive((p) => ({ ...p, [ev.stage]: { status: "running" } }));
            appendLog(`▸ ${ev.stage} 실행 중…`);
          } else if (ev.event === "stage_done") {
            setLive((p) => ({ ...p, [ev.stage]: { status: ev.status, detail: ev.detail } }));
            const icon = ev.status === "pass" ? "✓" : ev.status === "fail" ? "✕" : "–";
            appendLog(`${icon} ${ev.stage} ${ev.status} — ${ev.detail}`);
          } else {
            setResult(ev.result);
            appendLog(`■ 판정: ${ev.result.verdict} (QoR ${ev.result.score}점)`);
            if (ev.result.run_id) appendLog(`■ 런 #${ev.result.run_id}로 기록됨`);
          }
        },
      );
    } catch (e) {
      setError((e as Error).message);
      setLive(previous => Object.fromEntries(Object.entries(previous).map(([name, stage]) => [
        name, stage.status === "running" ? { status: "interrupted", detail: "최종 결과 확인 불가" } : stage,
      ])));
      appendLog(`✕ 오류: ${(e as Error).message}`);
    } finally {
      setRunning(false);
    }
  }

  const verdictStatus = { SIGNED_OFF: "good", CONDITIONAL: "warning", REJECTED: "critical" } as const;
  const verdictLabel = {
    SIGNED_OFF: "SIGNED_OFF",
    CONDITIONAL: "CONDITIONAL — 게이팅 단계 일부 생략",
    REJECTED: "REJECTED",
  } as const;
  const liveStatusBadge: Record<LiveStatus, { status: "good" | "critical" | "warning" | "neutral"; label: string }> = {
    pending: { status: "neutral", label: "대기" },
    running: { status: "warning", label: "실행 중" },
    interrupted: { status: "warning", label: "중단" },
    pass: { status: "good", label: "pass" },
    fail: { status: "critical", label: "fail" },
    skip: { status: "neutral", label: "skip" },
  };

  // A1 RTL 리뷰어: runs automatically once a ladder result lands, so
  // "did an agent look at this" never depends on a second click.
  const a1 = useQuery({
    queryKey: ["agent-review-rtl", result],
    queryFn: () => api.reviewRtl(result),
    enabled: !!result,
    staleTime: Infinity, refetchOnWindowFocus: false, retry: false,
  });

  return (
    <Card
      id="rtl-signoff"
      title="RTL 사인오프 래더"
      subtitle="verilator lint → 설계 룰(CDC/리셋/FSM) → yosys 합성 → 테스트벤치 시뮬레이션 → 판정"
      actions={
        <div className="flex w-full min-w-0 flex-wrap items-end gap-2 sm:w-auto">
          <Field label="프로젝트에 기록 (선택)">
            <select
              aria-label="프로젝트에 기록 (선택)"
              className="input max-w-[16rem]"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value === "" ? "" : Number(e.target.value))}
            >
              <option value="">기록 안 함</option>
              {(projects.data ?? []).filter(p => auth.can(p.id, "editor")).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </Field>
          <button className="btn btn-primary whitespace-nowrap" onClick={runLadder} disabled={running || (!!topModule.trim() && !/^[A-Za-z_][A-Za-z0-9_$]*$/.test(topModule.trim())) || (!!testbench.trim() && !/^[A-Za-z_][A-Za-z0-9_$]*$/.test(testbenchTop.trim()))}>
            {running ? "래더 실행 중…" : "사인오프 래더 실행"}
          </button>
        </div>
      }
    >
      <AgentEntry role="a1_rtl" />
      <div className="mb-3 space-y-2"><Field label="린트·합성 최상위 모듈 (선택)"><input className="input w-full" value={topModule} maxLength={120} disabled={running} onChange={e => setTopModule(e.target.value)} placeholder="예: chip_top" /></Field>
        <p className="text-xs text-[var(--text-secondary)]">비워 두면 첫 모듈 선언을 선택합니다. 정적 설계 규칙은 전체 입력을 검사하며, 시뮬레이션은 아래 테스트벤치 최상위를 사용합니다.</p>
        <p className="text-xs text-[var(--text-secondary)]">합성은 하위 모듈의 RTL 정의가 모두 필요합니다. 블랙박스는 지원하지 않습니다. 모듈 간 연결을 포함해 구동되지 않는 신호·다중 드라이버·조합 논리 루프가 발견되면 실패합니다.</p>
        {!!topModule.trim() && !/^[A-Za-z_][A-Za-z0-9_$]*$/.test(topModule.trim()) && <p role="alert" className="text-xs">모듈 이름은 영문자 또는 밑줄로 시작하고 영문자·숫자·밑줄·$만 사용할 수 있습니다.</p>}
      </div>
      <div className="mb-3"><Field label="설계 리비전 (선택)"><input className="input w-full" value={designRevision} maxLength={160} disabled={running} onChange={e => setDesignRevision(e.target.value)} placeholder="예: Git 커밋 SHA 또는 검토용 리비전" /></Field></div>
      <div className="mb-2 flex flex-wrap gap-2">
        <button className="btn btn-ghost" disabled={running} onClick={() => setCode(BUGGY_RTL)}>
          버그 있는 예제 (CDC 미동기화)
        </button>
        <button className="btn btn-ghost" disabled={running} onClick={() => setCode(CLEAN_RTL)}>
          클린 예제 (2-FF 동기화)
        </button>
      </div>
      <textarea
        className="code-editor w-full"
        style={{ minHeight: 220 }}
        spellCheck={false}
        value={code}
        onChange={(e) => setCode(e.target.value)}
        aria-label="SystemVerilog 소스"
        disabled={running}
        maxLength={500000}
      />

      <details className="mt-3">
        <summary className="cursor-pointer font-semibold text-sm">테스트벤치 (선택)</summary>
        <p className="my-2 text-xs text-[var(--text-secondary)]">자체 검사 테스트벤치를 입력하세요. 실패 시 $fatal(1, …)을 호출하고, 모든 검사 후 $display("SIGNOFF_TEST_PASS"); $finish;로 종료합니다. 미제공 또는 서버 실행 비활성 시 필수 시뮬레이션 단계는 미완료로 남습니다.</p>
        <button className="btn btn-ghost mb-2" disabled={running} onClick={() => { setCode(CLEAN_RTL); setTestbench(PULSE_TESTBENCH); setTestbenchTop("tb"); }}>펄스 동기화 검증 예제 불러오기</button>
        <Field label="테스트벤치 최상위 모듈"><input className="input" value={testbenchTop} maxLength={120} disabled={running} onChange={e => setTestbenchTop(e.target.value)} /></Field>
        <textarea aria-label="테스트벤치 SystemVerilog" className="code-editor w-full mt-2" rows={10} spellCheck={false} maxLength={500000} disabled={running} value={testbench} onChange={e => setTestbench(e.target.value)} />
      </details>
      {result?.simulation && <SimulationDetails simulation={result.simulation} />}

      {error && (
        <p role="alert" className="mt-3 text-sm" style={{ color: "var(--status-critical)" }}>
          {error}
        </p>
      )}

      {Object.keys(live).length > 0 && (
        <div className="mt-4 space-y-4">
          {/* live ladder — updates as each tool actually runs */}
          <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {LADDER.map((name) => {
              const s = live[name] ?? { status: "pending" as LiveStatus };
              const badge = liveStatusBadge[s.status];
              return (
                <li
                  key={name}
                  className={`rounded-lg px-3 py-2 ${s.status === "running" ? "stage-running" : ""}`}
                  style={{ border: "1px solid var(--grid-hairline)" }}
                >
                  <div className="mb-1 flex items-center justify-between">
                    <span className="text-sm font-medium">{name}</span>
                    <StatusBadge status={badge.status} label={badge.label} />
                  </div>
                  <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                    {s.detail ?? (s.status === "running" ? "툴 실행 중…" : " ")}
                  </p>
                </li>
              );
            })}
          </ul>

          {/* live event log */}
          <div
            className="rounded-lg px-4 py-3 font-mono text-xs"
            style={{
              background: "#141413",
              border: "1px solid var(--grid-hairline)",
              color: "var(--text-secondary)",
              maxHeight: 140,
              overflowY: "auto",
            }}
            aria-live="polite"
            aria-label="사인오프 실행 로그"
          >
            {log.map((line, i) => (
              <div key={i}>{line}</div>
            ))}
          </div>
        </div>
      )}

      {result && (
        <div className="mt-4 space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <StatusBadge
              status={verdictStatus[result.verdict]}
              label={verdictLabel[result.verdict]}
            />
            <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
              QoR {result.score}점 · 등급 {result.grade}
              {result.module && ` · 모듈 ${result.module}`}
              {result.run_id && ` · 런 #${result.run_id}로 기록됨`}
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs" style={{ color: "var(--text-muted)" }}>
                  <th className="py-1.5 font-medium">DRC 룰</th>
                  <th className="py-1.5 font-medium">이름</th>
                  <th className="py-1.5 font-medium">상태</th>
                  <th className="py-1.5 font-medium">상세</th>
                </tr>
              </thead>
              <tbody>
                {result.rules.map((r) => (
                  <tr key={r.code + r.detail} className="hairline-t">
                    <td className="py-1.5 pr-3 font-mono text-xs">{r.code}</td>
                    <td className="py-1.5 pr-3">{r.name}</td>
                    <td className="py-1.5 pr-3">
                      <StatusBadge
                        status={
                          r.status === "pass"
                            ? "good"
                            : r.severity === "error"
                              ? "critical"
                              : r.severity === "warn"
                                ? "warning"
                                : "neutral"
                        }
                        label={r.status === "pass" ? "pass" : r.severity}
                      />
                    </td>
                    <td className="py-1.5 text-xs" style={{ color: "var(--text-secondary)" }}>
                      {r.detail}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {result.suggestions.length > 0 && (
            <div
              className="rounded-lg px-4 py-3 text-sm"
              style={{ border: "1px solid var(--grid-hairline)", color: "var(--text-secondary)" }}
            >
              <div className="mb-1 text-xs font-medium" style={{ color: "var(--text-muted)" }}>
                개선 제안
              </div>
              <ul className="list-disc space-y-1 pl-4">
                {result.suggestions.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </div>
          )}


        </div>
      )}
      <AgentReviewPanel role="a1_rtl" scope={result ? `${result.run_id ? `런 #${result.run_id} · ` : ''}규칙 위반 ${result.rules.filter(rule => rule.status === 'violation').length}건` : undefined} review={a1.data} loading={a1.isFetching} failed={a1.isError} onRetry={() => void a1.refetch()} />
    </Card>
  );
}

function IrDropSection() {
  const run = useMutation({
    mutationFn: () => api.irDrop({ ...ibexFloorplanGrids(), vdd: 1.8, scale: 0.06 }),
  });
  const a3 = useQuery({
    queryKey: ["agent-review-power-ir", "ir", run.data],
    queryFn: () => api.reviewPowerIr({ ir_drop_result: run.data }),
    enabled: !!run.data,
    staleTime: Infinity, refetchOnWindowFocus: false, retry: false,
  });

  return (
    <Card
      id="ir-drop"
      title="IR-drop 사전 스크리닝 — Ibex @ SKY130"
      subtitle="물리 기반 서로게이트 (arXiv:2601.22707) · VDD 1.8V, 임계 5% (90mV) — 골든 EM/IR 사인오프 전 핫스팟 탐지"
      actions={
        <button className="btn btn-primary" onClick={() => run.mutate()} disabled={run.isPending}>
          Ibex 플로어플랜 분석
        </button>
      }
    >
      <AgentEntry role="a3_power_ir" />
      {run.data ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatTile
              label="최악 IR-drop"
              value={run.data.worst_drop_mv.toFixed(1)}
              suffix="mV"
              tone={run.data.passed ? "good" : "critical"}
            />
            <StatTile label="평균 IR-drop" value={run.data.mean_drop_mv.toFixed(1)} suffix="mV" />
            <StatTile label="핫스팟" value={run.data.hotspot_count} suffix="타일" />
            <StatTile label="임계값" value={run.data.threshold_mv.toFixed(0)} suffix="mV" />
          </div>
          <StatusBadge
            status={run.data.passed ? "good" : "critical"}
            label={run.data.passed ? "스크리닝 통과" : "핫스팟 검출 — 골든 사인오프 필요"}
          />
          <IrDropHeatmap map={run.data.drop_map_mv} thresholdMv={run.data.threshold_mv} />

        </div>
      ) : (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          Ibex RISC-V 코어(lowRISC)의 10×10 타일 플로어플랜 — multdiv_fast 고활동 클러스터와 M4
          파워 스트랩에서 먼 레지스터 파일 코너(취약 PDN)를 포함합니다.
        </p>
      )}
      <AgentReviewPanel role="a3_power_ir" scope={run.data ? `최악 IR-drop ${run.data.worst_drop_mv.toFixed(1)} mV / 임계 ${run.data.threshold_mv.toFixed(1)} mV` : undefined} review={a3.data} loading={a3.isFetching} failed={a3.isError} onRetry={() => void a3.refetch()} />
    </Card>
  );
}

function TimingSection() {
  const [cornersText, setCornersText] = useState(JSON.stringify(IBEX_CORNERS, null, 2));
  const [credit, setCredit] = useState(15);
  const run = useMutation({
    mutationFn: () => {
      const corners = JSON.parse(cornersText);
      if (!Array.isArray(corners)) throw new Error('코너 JSON은 배열이어야 합니다.');
      return api.timingSummary({ corners, pba_pessimism_credit_ps: credit });
    },
  });
  const a2 = useQuery({
    queryKey: ["agent-review-timing", run.data],
    queryFn: () => api.reviewTiming(run.data),
    enabled: !!run.data,
    staleTime: Infinity, refetchOnWindowFocus: false, retry: false,
  });

  return (
    <Card
      id="timing"
      title="MMMC 타이밍 요약"
      subtitle="코너별 WNS/TNS 집계 · 종점 대응 확인 · PBA 크레딧 추정"
      actions={
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs" style={{ color: "var(--text-secondary)" }}>
            PBA 크레딧 (ps)
            <input
              type="number"
              className="input ml-2 w-20"
              value={credit}
              min={0}
              disabled={run.isPending}
              onChange={(e) => { setCredit(Number(e.target.value)); run.reset(); }}
            />
          </label>
          <button className="btn btn-primary shrink-0 whitespace-nowrap" onClick={() => run.mutate()} disabled={run.isPending}>
            코너 분석
          </button>
        </div>
      }
    >
      <AgentEntry role="a2_timing" />
      <details className="mb-4"><summary className="cursor-pointer text-sm font-semibold">분석 데이터 편집</summary>
        <p className="my-2 text-xs text-[var(--text-secondary)]">각 코너에 name, endpoint_slacks_ps와 선택 사항인 endpoint_ids를 입력하세요. ID를 사용하면 모든 코너에 같은 종점 집합을 제공해야 합니다.</p>
        <textarea aria-label="코너 JSON" className="input w-full font-mono text-xs" rows={10} maxLength={2000000} spellCheck={false} disabled={run.isPending} value={cornersText} onChange={e => { setCornersText(e.target.value); run.reset(); }} />
        <button className="btn btn-ghost mt-2" disabled={run.isPending} onClick={() => { setCornersText(JSON.stringify(IBEX_CORNERS, null, 2)); run.reset(); }}>Ibex 예제 불러오기</button>
      </details>
      {run.isError && <p role="alert" className="mb-3 text-sm text-[var(--status-critical)]">{run.error.message}</p>}
      {run.data ? (
        <div className="space-y-4">
          <p role="status" className="text-sm">{run.data.endpoint_alignment === 'by_id' ? '종점 ID 기준으로 코너를 대응했습니다.' : '종점 ID가 없어 입력 순서대로 대응했습니다. 같은 위치가 같은 종점인지 확인하세요.'}</p>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile
              label="머지 WNS"
              value={run.data.merged.wns_ps}
              suffix="ps"
              tone={run.data.merged.wns_ps < 0 ? "critical" : "good"}
            />
            <StatTile label="머지 TNS" value={run.data.merged.tns_ps} suffix="ps" />
            <StatTile
              label="위반 엔드포인트"
              value={`${run.data.merged.violating_endpoints}/${run.data.merged.total_endpoints}`}
            />
            {run.data.estimated_pba && (
              <StatTile
                label="PBA 크레딧 후 회복"
                value={run.data.estimated_pba.recovered_endpoints}
                suffix="EP"
                tone="good"
              />
            )}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm [&_th]:px-2 [&_td]:px-2 [&_th]:whitespace-nowrap [&_td]:whitespace-nowrap" style={{ fontVariantNumeric: "tabular-nums" }}>
              <thead>
                <tr className="text-left text-xs" style={{ color: "var(--text-muted)" }}>
                  <th className="py-1.5 font-medium">코너</th>
                  <th className="py-1.5 text-right font-medium">WNS (ps)</th>
                  <th className="py-1.5 text-right font-medium">TNS (ps)</th>
                  <th className="py-1.5 text-right font-medium">위반 EP</th>
                </tr>
              </thead>
              <tbody>
                {run.data.corners.map((c) => (
                  <tr key={c.name} className="hairline-t">
                    <td className="py-1.5">{c.name}</td>
                    <td
                      className="py-1.5 text-right"
                      style={{ color: c.wns_ps < 0 ? "var(--status-critical)" : "var(--delta-good-text)" }}
                    >
                      {c.wns_ps}
                    </td>
                    <td className="py-1.5 text-right">{c.tns_ps}</td>
                    <td className="py-1.5 text-right">
                      {c.violating_endpoints}/{c.total_endpoints}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div>
            <h3 className="mb-2 text-xs font-medium" style={{ color: "var(--text-muted)" }}>
              머지 엔드포인트 슬랙 (입력 순서, 최대 50개)
            </h3>
            <SlackBars
              slacks={run.data.merged_slacks_ps.slice(0, 50)}
              endpointIds={run.data.endpoint_ids?.slice(0, 50)}
            />
          </div>

          <section aria-label="최악 종점과 코너" className="space-y-2">
            <h3 className="font-semibold text-sm">최악 종점과 제한 코너 (최대 20개)</h3>
            <ul className="space-y-2">{run.data.worst_endpoints.map(endpoint => <li key={endpoint.index} className="rounded-lg border border-[var(--border)] p-3 text-xs break-all">
              <strong>EP{endpoint.index} · {endpoint.endpoint_id ?? 'ID 미제공'}</strong><p>{endpoint.slack_ps} ps · {endpoint.limiting_corners.join(', ')}</p>
            </li>)}</ul>
            <p className="text-xs text-[var(--text-muted)]">제공된 종점·코너의 요약입니다. 입력 ID의 일치는 실제 설계나 전체 코너 검증의 완료를 증명하지 않습니다.</p>
          </section>

        </div>
      ) : (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          기본 입력은 Ibex / SKY130의 종점 12개를 사용하는 설명용 예제입니다. 분석 데이터 편집에서 실제 코너 데이터를 입력한 뒤 분석하세요.
        </p>
      )}
      <AgentReviewPanel role="a2_timing" scope={run.data ? `머지 WNS ${run.data.merged.wns_ps} ps` : undefined} review={a2.data} loading={a2.isFetching} failed={a2.isError} onRetry={() => void a2.refetch()} />
    </Card>
  );
}

function GlitchSection() {
  const run = useMutation({
    mutationFn: () => api.glitchPower({ nets: IBEX_NETS, vdd: 1.8, clock_period_ns: 10 }),
  });
  const a3 = useQuery({
    queryKey: ["agent-review-power-ir", "glitch", run.data],
    queryFn: () => api.reviewPowerIr({ glitch_result: run.data }),
    enabled: !!run.data,
    staleTime: Infinity, refetchOnWindowFocus: false, retry: false,
  });

  return (
    <Card
      id="glitch-power"
      title="벡터리스 글리치 파워 추정 — Ibex ALU/MULTDIV"
      subtitle="토글률 초과분 기반 (Synopsys US 12,001,768 방식 단순화) · VDD 1.8V, clk 10ns — 깊은 연산 로직이 글리치에 취약"
      actions={
        <button className="btn btn-primary" onClick={() => run.mutate()} disabled={run.isPending}>
          Ibex 네트 분석
        </button>
      }
    >
      <AgentEntry role="a3_power_ir" />
      {run.data ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <StatTile
              label="총 동적 전력"
              value={(run.data.total_dynamic_power_mw * 1000).toFixed(2)}
              suffix="µW"
            />
            <StatTile
              label="글리치 전력"
              value={(run.data.glitch_power_mw * 1000).toFixed(2)}
              suffix="µW"
            />
            <StatTile
              label="글리치 비중"
              value={`${(run.data.glitch_share * 100).toFixed(1)}%`}
              tone={run.data.glitch_share >= 0.5 ? "critical" : undefined}
            />
          </div>
          <div>
            <div className="mb-1.5 flex justify-between text-xs" style={{ color: "var(--text-muted)" }}>
              <span>글리치 비중</span>
              <span>경고 30% · 위험 50%</span>
            </div>
            <Meter ratio={run.data.glitch_share} />
          </div>
          <PowerStackBars nets={run.data.nets} />

        </div>
      ) : (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          ibex_alu / ibex_multdiv_fast의 글리치 취약 네트 5개(가산기 출력, MAC 결과, 중간값
          레지스터 입력 등)로 추정을 실행합니다.
        </p>
      )}
      <AgentReviewPanel role="a3_power_ir" scope={run.data ? `글리치 비중 ${(run.data.glitch_share * 100).toFixed(1)}%` : undefined} review={a3.data} loading={a3.isFetching} failed={a3.isError} onRetry={() => void a3.refetch()} />
    </Card>
  );
}
