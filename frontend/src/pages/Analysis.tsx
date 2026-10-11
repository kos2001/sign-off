import { formatDateTime, useLanguage } from "../components/LanguageProvider";
import { useAuth } from "../components/AuthProvider";
import { PULSE_TESTBENCH } from "./pulseTestbench";
import { SimulationDetails } from "../components/SimulationDetails";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, Navigate, useLocation, useParams } from "react-router";

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
  const { t } = useLanguage();
  const analysisTools = [
  { slug: 'rtl', legacy: 'rtl-signoff', title: t("RTL 사인오프 래더", "RTL sign-off ladder"), description: t("RTL 린트·구조 규칙·시뮬레이션·합성을 실행하고 결과와 근거를 확인합니다.", "Run RTL lint, structural checks, simulation and synthesis, then review results and evidence."), kind: t("도구 실행", "Tool execution"), component: RtlSignoffSection },
  { slug: 'sta', legacy: 'sta-signoff', title: t("OpenSTA 타이밍 실행", "OpenSTA timing execution"), description: t("넷리스트·Liberty·SDC와 선택적 SPEF로 정적 타이밍을 실행하고 경로를 저장합니다.", "Run static timing with a netlist, Liberty, SDC and optional SPEF, and retain timing paths."), kind: t("도구 실행", "Tool execution"), component: StaSignoffSection },
  { slug: 'ir-drop', legacy: 'ir-drop', title: t("IR-drop 스크리닝", "IR-drop screening"), description: t("전원망 밀도·활동도·강도를 바탕으로 전압 강하 위험 영역을 탐색합니다.", "Explore voltage-drop risk using power-grid density, activity and strength."), kind: t("추정 · 스크리닝", "Estimate \u00b7 screening"), component: IrDropSection },
  { slug: 'timing', legacy: 'timing', title: t("MMMC 타이밍", "MMMC timing"), description: t("코너별 요약 수치를 비교하고 머지 WNS/TNS 및 PBA 추정을 확인합니다.", "Compare corner summaries, merged WNS/TNS and PBA estimates."), kind: t("요약 · 추정", "Summary \u00b7 estimate"), component: TimingSection },
  { slug: 'glitch-power', legacy: 'glitch-power', title: t("글리치 파워", "Glitch power"), description: t("활동도 기반 글리치 전력 비중과 네트별 위험을 분석합니다.", "Analyze activity-based glitch power and risks by net."), kind: t("추정 분석", "Estimated analysis"), component: GlitchSection },
];

  const { hash, search } = useLocation();
  const { tool } = useParams();
  const selected = analysisTools.find(item => item.slug === tool);
  const legacy = !tool && analysisTools.find(item => `#${item.legacy}` === hash);
  useEffect(() => { window.scrollTo(0, 0); }, [tool]);
  if (legacy) return <Navigate replace to={`/analysis/${legacy.slug}${search}`} />;
  if (tool && !selected) return <div className="space-y-4"><h1 className="text-2xl font-semibold">{t('분석 도구를 찾을 수 없습니다', 'Analysis tool not found')}</h1><Link className="btn btn-ghost" to="/analysis">{t('분석 도구 선택', 'Choose an analysis tool')}</Link></div>;
  const Tool = selected?.component;
  return <div className="space-y-6">
    <header className="space-y-3">
      {selected && <Link className="text-sm text-[var(--series-1)]" to="/analysis">{t('← 분석 도구 선택', '← Choose an analysis tool')}</Link>}
      <h1 className="text-2xl font-semibold">{selected?.title ?? t("분석 도구", "Analysis tools")}</h1>
      <p className="text-sm text-[var(--text-secondary)]">{selected?.description ?? t("목적에 맞는 도구를 선택하세요. 실제 검증 실행과 빠른 추정 분석을 구분해 사용합니다.", "Choose a tool for your task. Distinguish verification execution from fast estimates.")}</p>
      <Link className="text-sm text-[var(--series-1)]" to="/guide">{t('서비스 목적과 검증 범위 →', 'Service purpose and verification scope →')}</Link>
    </header>
    {Tool ? <Tool key={tool} /> : <div className="grid gap-4 md:grid-cols-2">{analysisTools.map(item => <Link key={item.slug} to={`/analysis/${item.slug}`} className="card card-hover p-6"><p className="text-xs text-[var(--series-1)]">{item.kind}</p><h2 className="mt-3 font-semibold">{item.title} →</h2><p className="mt-3 text-sm leading-relaxed text-[var(--text-secondary)]">{item.description}</p></Link>)}</div>}
  </div>;
}

function StaSignoffSection() {
  const { t } = useLanguage();
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
    { label: t("게이트 레벨 Verilog 넷리스트", "Gate-level Verilog netlist"), value: netlist, set: setNetlist, accept: ".v,.sv", max: 1_000_000 },
    { label: t("Liberty 타이밍 라이브러리", "Liberty timing library"), value: liberty, set: setLiberty, accept: ".lib", max: 5_000_000 },
    { label: t("SDC 제약", "SDC constraints"), value: sdc, set: setSdc, accept: ".sdc", max: 500_000 },
    { label: t("SPEF 배선 기생성분 (선택)", "SPEF wire parasitics (optional)"), value: spef, set: setSpef, accept: ".spef", max: 8_000_000 },
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
  return <Card id="sta-signoff" title={t("OpenSTA 정적 타이밍 실행", "OpenSTA static timing run")} subtitle={t("넷리스트 · Liberty · SDC → 격리 OpenSTA → 저장된 경로·위반·실행 근거", "Netlist · Liberty · SDC → isolated OpenSTA → stored paths, violations and run evidence")}>
    <div className="mb-4 rounded-lg border border-[var(--border)] px-3 py-2 text-xs text-[var(--text-secondary)]">
      {t("이 단계는 서버의 OpenSTA 도구만 실행하며 AI 에이전트는 개입하지 않습니다. 실행 후 런 작업공간에서 A2 타이밍 분석가 검토를 사용자가 별도로 요청할 수 있습니다.", "This step runs only the server's OpenSTA tool; no AI agent is involved. After the run, you can separately request an A2 timing analyst review from the run workspace.")}
    </div>
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <Field label={t("프로젝트", "Project")}><select className="input" value={projectId} onChange={e => setProjectId(e.target.value ? Number(e.target.value) : "")}><option value="">{t("선택", "Select")}</option>{(projects.data ?? []).filter(p => auth.can(p.id, "editor")).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
      <Field label={t("설계 단계", "Design stage")}><select className="input" value={stage} onChange={e => setStage(e.target.value)}>{["rtl", "synthesis", "placement", "routing", "final"].map(v => <option key={v}>{v}</option>)}</select></Field>
      <Field label={t("최상위 모듈", "Top module")}><input className="input" value={topModule} maxLength={120} onChange={e => setTopModule(e.target.value)} placeholder="chip_top" /></Field>
      <Field label={t("설계 리비전", "Design revision")}><input className="input" value={revision} maxLength={160} onChange={e => setRevision(e.target.value)} placeholder="Git SHA" /></Field>
      <Field label={t("시나리오", "Scenario")}><input className="input" value={scenario} maxLength={160} onChange={e => setScenario(e.target.value)} placeholder="ss_0p72v_125c" /></Field>
    </div>
    <div className="mt-4 grid gap-4 lg:grid-cols-2">{fields.map(field => <Field key={field.label} label={field.label}>
      <input className="mb-2 block w-full text-xs" type="file" accept={field.accept} onChange={e => loadFile(e.target.files?.[0], field.set, field.max)} />
      <textarea className="code-editor w-full" rows={10} value={field.value} maxLength={field.max} spellCheck={false} onChange={e => field.set(e.target.value)} aria-label={field.label} />
      <span className="text-xs text-[var(--text-muted)]">{new Blob([field.value]).size.toLocaleString()} / {field.max.toLocaleString()} bytes</span>
    </Field>)}</div>
    <p className="mt-3 text-xs text-[var(--text-secondary)]">{t("SPEF를 제공하면 OpenSTA가 배선 저항·정전용량을 읽어 타이밍에 반영합니다. 비워 두면 기생성분 없는 분석으로 근거에 기록합니다. SDC는 Tcl 기반 제약 파일이며 서버는 일반 파일·프로세스·네트워크 명령을 비활성화한 제한 컨테이너에서 실행합니다.", "When SPEF is provided, OpenSTA reads wire resistance and capacitance into timing. If left empty, the evidence records an analysis without parasitics. SDC is a Tcl-based constraint file; the server runs it in a restricted container with general file, process and network commands disabled.")}</p>
    <button className="btn btn-primary mt-3" disabled={!valid || running} onClick={execute}>{running ? t("OpenSTA 실행 중…", "Running OpenSTA…") : t("OpenSTA 실행 및 기록", "Run OpenSTA and record")}</button>
    {(running || result || error) && <div className="mt-3 grid gap-2 sm:grid-cols-2" aria-live="polite">{(['opensta', 'persist'] as const).map(name => <div key={name} className="rounded-lg border border-[var(--border)] p-3 text-sm"><div className="flex justify-between"><strong>{name === 'opensta' ? t('OpenSTA 분석', 'OpenSTA analysis') : t('근거 저장', 'Save evidence')}</strong><span>{progress[name].status === 'pending' ? t('대기', 'Pending') : progress[name].status === 'running' ? t('실행 중', 'Running') : progress[name].status === 'error' ? t('중단', 'Stopped') : t('완료', 'Done')}</span></div>{progress[name].detail && <p className="mt-1 text-xs text-[var(--text-secondary)]">{progress[name].detail}</p>}</div>)}</div>}
    {error && <p role="alert" className="mt-3 text-sm">{error}</p>}
    {result && <div className="mt-4 rounded-lg border border-[var(--border)] p-3 text-sm space-y-2"><p><strong>{t("런", "Run")} #{result.run_id}</strong> · {t(`보고 경로 ${result.metrics.reported_paths}개`, `${result.metrics.reported_paths} reported paths`)} · {t(`위반 ${result.metrics.violating_paths}개`, `${result.metrics.violating_paths} violations`)} · {t("최악 슬랙", "Worst slack")} {result.metrics.worst_reported_slack_ps ?? t("없음", "none")} ps</p><p className="text-xs text-[var(--text-secondary)]">OpenSTA {result.execution.opensta_commit.slice(0, 12)} · {t("AI 개입 없음 · 경로 표본만 생성되어 전체 STA 게이트는 미완료로 유지됩니다.", "No AI involvement · only a path sample was generated, so the full STA gate stays incomplete.")}</p><Link className="btn btn-ghost inline-block" to={`/runs/${result.run_id}`}>{t("런 작업공간 열기", "Open run workspace")}</Link></div>}
    <details className="mt-5 rounded-lg border border-[var(--border)] p-4">
      <summary className="cursor-pointer font-semibold">{t("MCMM 시나리오 배치 실행", "MCMM scenario batch run")}</summary>
      <p className="mt-2 text-xs text-[var(--text-secondary)]">{t("위의 프로젝트·단계·최상위 모듈·리비전·넷리스트를 공통으로 사용합니다. 서버 작업 큐에 접수되므로 브라우저를 닫아도 실행하며, 여러 프로젝트는 실행 기회를 공정하게 나눕니다. 한 시나리오의 실패가 뒤 실행을 막지 않습니다. 최대 8개, 전체 입력 32 MiB입니다.", "Uses the project, stage, top module, revision and netlist above for every scenario. Jobs go to the server work queue, so they keep running after you close the browser, and projects share run slots fairly. A failure in one scenario does not block later ones. Up to 8 scenarios, 32 MiB of total input.")}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <button className="btn btn-ghost" disabled={!expectedScenarios.data?.length || batchRunning} onClick={() => setBatchRows(expectedScenarios.data!.slice(0, 8).map(item => ({ scenario: item.name, liberty: '', sdc: '', spef: '', requireSpef: item.require_spef })))}>{t("기대 시나리오 불러오기", "Load expected scenarios")}</button>
        <button className="btn btn-ghost" disabled={batchRows.length >= 8 || batchRunning} onClick={() => setBatchRows(rows => [...rows, { scenario: '', liberty: '', sdc: '', spef: '', requireSpef: false }])}>{t('시나리오 추가', 'Add scenario')}</button>
      </div>
      {expectedScenarios.isError && <p role="alert" className="mt-2 text-sm">{t("기대 시나리오를 불러오지 못했습니다:", "Could not load expected scenarios:")} {expectedScenarios.error.message}</p>}
      <div className="mt-3 space-y-3">{batchRows.map((row, index) => <section key={index} className="rounded-lg border border-[var(--border)] p-3" aria-label={t(`배치 시나리오 ${index + 1}`, `Batch scenario ${index + 1}`)}>
        <div className="flex flex-wrap items-center gap-2"><input aria-label={t(`배치 시나리오 ${index + 1} 이름`, `Batch scenario ${index + 1} name`)} className="input min-w-56 flex-1" maxLength={160} disabled={batchRunning} value={row.scenario} onChange={event => updateBatch(index, { scenario: event.target.value })} placeholder="slow-setup-functional" />{row.requireSpef && <StatusBadge status="warning" label={t("SPEF 필수", "SPEF required")} />}<button className="btn btn-ghost" disabled={batchRunning} onClick={() => setBatchRows(rows => rows.filter((_, i) => i !== index))}>{t('삭제', 'Remove')}</button></div>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">{([
          ['liberty', 'Liberty', '.lib', 5_000_000], ['sdc', 'SDC', '.sdc', 500_000], ['spef', t('SPEF (선택)', 'SPEF (optional)'), '.spef', 8_000_000],
        ] as const).map(([key, label, accept, max]) => <label className="text-xs" key={key}>{label}<input className="mt-1 block w-full" type="file" accept={accept} disabled={batchRunning} onChange={event => loadBatchFile(event.target.files?.[0], index, key, max)} /><span className="text-[var(--text-muted)]">{new Blob([row[key]]).size.toLocaleString()} bytes</span></label>)}</div>
      </section>)}</div>
      {batchRows.length === 0 && <p className="mt-3 text-sm text-[var(--text-muted)]">{t("기대 세트를 불러오거나 시나리오를 추가하세요.", "Load the expected set or add scenarios.")}</p>}
      {new Set(batchNames).size !== batchNames.length && batchRows.length > 1 && <p role="alert" className="mt-2 text-sm">{t("시나리오 이름은 대소문자를 무시하고 고유해야 합니다.", "Scenario names must be unique, ignoring case.")}</p>}
      <button className="btn btn-primary mt-3" disabled={!batchValid || batchRunning} onClick={executeBatch}>{batchRunning ? t('배치 제출 중…', 'Submitting batch…') : t(`${batchRows.length}개 시나리오 작업 제출`, `Submit ${batchRows.length} scenario job${batchRows.length === 1 ? '' : 's'}`)}</button>
      {batchId && <p role="status" className="mt-2 text-xs">{t(`배치 #${batchId}가 서버 작업 큐에 접수됐습니다. 이 페이지를 닫아도 실행을 계속합니다.`, `Batch #${batchId} was accepted into the server work queue. It keeps running even if you close this page.`)}</p>}
      {batchError && <p role="alert" className="mt-3 text-sm">{batchError}</p>}
      <section className="mt-5 border-t border-[var(--border)] pt-4" aria-label={t("최근 STA 배치 이력", "Recent STA batch history")}>
        <h3 className="text-sm font-semibold">{t("최근 배치 이력", "Recent batch history")}</h3>
        <p className="mt-1 text-xs text-[var(--text-muted)]">{t("접수한 시나리오와 성공·실패·취소 상태를 서버 DB에서 조회합니다. 입력 파일 본문은 각 성공 런의 실행 근거에 저장됩니다.", "Submitted scenarios and their succeeded, failed or cancelled status are read from the server database. Input file contents are stored in the run evidence of each successful run.")}</p>
        {batchHistory.isPending && projectId !== '' ? <p role="status" className="mt-3 text-sm">{t("배치 이력 불러오는 중…", "Loading batch history…")}</p> : batchHistory.isError ? <p role="alert" className="mt-3 text-sm">{batchHistory.error.message}</p> : <ul className="mt-3 space-y-3">{(batchHistory.data?.items ?? []).slice(0, 5).map(batch => <li className="rounded-lg border border-[var(--border)] p-3" key={batch.id}>
          <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm font-semibold">{t("배치", "Batch")} #{batch.id} · {batch.design_revision}</p><div className="flex items-center gap-2"><StatusBadge status={batch.status === 'completed' ? 'good' : batch.status === 'queued' ? 'neutral' : batch.status === 'running' ? 'warning' : batch.status === 'partial' ? 'serious' : 'critical'} label={{ queued: t('대기', 'Queued'), running: batch.cancel_requested ? t('취소 처리 중', 'Cancelling') : t('실행 중', 'Running'), completed: t('완료', 'Completed'), partial: t('부분 성공', 'Partially succeeded'), failed: t('실패', 'Failed'), cancelled: t('취소', 'Cancelled') }[batch.status]} />{(batch.status === 'queued' || batch.status === 'running') && auth.can(Number(projectId), 'editor') && <button className="btn btn-ghost" disabled={cancellingBatch === batch.id || batch.cancel_requested} onClick={async () => { setCancellingBatch(batch.id); setBatchError(null); try { await api.cancelStaBatch(Number(projectId), batch.id); await qc.invalidateQueries({ queryKey: ['sta-batches', projectId] }); } catch (reason) { setBatchError((reason as Error).message); } finally { setCancellingBatch(null); } }}>{cancellingBatch === batch.id ? t('취소 요청 중…', 'Requesting cancellation…') : t('작업 취소', 'Cancel job')}</button>}{!['queued', 'running'].includes(batch.status) && auth.can(Number(projectId), 'editor') && <button className="btn btn-ghost" disabled={retryingBatch === batch.id} onClick={async () => { setRetryingBatch(batch.id); setBatchError(null); try { const retried = await api.retryStaBatch(Number(projectId), batch.id, crypto.randomUUID()); setBatchId(retried.id); await qc.invalidateQueries({ queryKey: ['sta-batches', projectId] }); } catch (reason) { setBatchError((reason as Error).message); } finally { setRetryingBatch(null); } }}>{retryingBatch === batch.id ? t('재실행 접수 중…', 'Submitting rerun…') : t('동일 입력 재실행', 'Rerun with same inputs')}</button>}</div></div>
          <p className="mt-1 text-xs text-[var(--text-muted)]">{batch.stage} · {batch.top_module} · {t('시도', 'Attempt')} {batch.attempt}{batch.retry_of_batch_id ? t(` (배치 #${batch.retry_of_batch_id}에서 재실행)`, ` (rerun of batch #${batch.retry_of_batch_id})`) : ''} · {batch.submitted_by} · {formatDateTime(batch.created_at)}</p>
          <div className="mt-2 flex flex-wrap gap-2">{batch.items.map(item => <span className="rounded border border-[var(--border)] px-2 py-1 text-xs" key={item.position}>{item.scenario} · {item.run_id ? <Link className="underline" to={`/runs/${item.run_id}`}>run #{item.run_id}</Link> : item.status === 'running' ? t('실행 중', 'Running') : item.status === 'pending' ? t('대기', 'Pending') : item.status === 'cancelled' ? t('취소', 'Cancelled') : t('실패', 'Failed')}</span>)}</div>
          <details className="mt-2 text-xs"><summary className="cursor-pointer text-[var(--text-secondary)]">{t(`실행 타임라인 ${batch.events.length}건`, `Run timeline (${batch.events.length} events)`)}</summary>{batch.events.length ? <ol className="mt-2 space-y-1 border-l border-[var(--border)] pl-3">{batch.events.map(event => <li key={event.id}><time className="text-[var(--text-muted)]">{formatDateTime(event.created_at)}</time> · <strong>{{ submitted: t('접수', 'Submitted'), retry_submitted: t('재실행 접수', 'Rerun submitted'), started: t('워커 시작', 'Worker started'), scenario_started: t('시나리오 시작', 'Scenario started'), scenario_completed: t('시나리오 완료', 'Scenario completed'), scenario_failed: t('시나리오 실패', 'Scenario failed'), scenario_cancelled: t('시나리오 취소', 'Scenario cancelled'), cancel_requested: t('취소 요청', 'Cancellation requested'), finalized: t('배치 종결', 'Batch finalized') }[event.kind]}</strong>{event.scenario ? ` · ${event.scenario}` : ''} · {event.actor}{event.detail ? ` · ${event.detail}` : ''}</li>)}</ol> : <p className="mt-2 text-[var(--text-muted)]">{t("타임라인 기능 도입 전 배치입니다.", "This batch predates the timeline feature.")}</p>}</details>
        </li>)}</ul>}
        {batchHistory.data?.items.length === 0 && <p className="mt-3 text-sm text-[var(--text-muted)]">{t("저장된 배치 실행이 없습니다.", "No saved batch runs.")}</p>}
      </section>
    </details>
  </Card>;
}

const LADDER = ["lint", "design", "synthesize", "simulate"] as const;
type LiveStatus = "pending" | "running" | "pass" | "fail" | "skip" | "interrupted";

function AgentEntry({ role }: { role: AgentRoleId }) {
  const { t } = useLanguage();
  const info = AGENT_ROLES[role];
  const condition = info.condition;
  return <p className="mb-4 rounded-lg border border-[var(--border)] px-3 py-2 text-xs text-[var(--text-secondary)]">
    <strong className="text-[var(--series-1)]">{t(`${info.code} 자동 검토`, `${info.code} automatic review`)}</strong> · {t(`${condition} 개입합니다.`, `Engages ${condition.charAt(0).toLowerCase()}${condition.slice(1)}.`)}
    {' '}<Link className="underline" to={`/agents#${role}`}>{t('자세히 보기', 'Learn more')}</Link>
  </p>;
}

function RtlSignoffSection() {
  const { t, locale } = useLanguage();
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
    setLog((prev) => [...prev, `${new Date().toLocaleTimeString(locale, { hour12: false })}  ${line}`]);

  async function runLadder() {
    setRunning(true);
    setResult(null);
    setError(null);
    setLog([]);
    setLive(Object.fromEntries(LADDER.map((s) => [s, { status: "pending" as LiveStatus }])));
    appendLog(t("▸ 사인오프 래더 실행 요청", "▸ Sign-off ladder run requested"));
    try {
      await api.rtlSignoffStream(
        { code, ...(topModule.trim() ? { top_module: topModule.trim() } : {}), ...(testbench.trim() ? { testbench, testbench_top: testbenchTop.trim() } : {}), ...(designRevision.trim() ? { design_revision: designRevision.trim() } : {}), ...(projectId !== "" ? { project_id: projectId } : {}) },
        (ev) => {
          if (ev.event === "stage_start") {
            setLive((p) => ({ ...p, [ev.stage]: { status: "running" } }));
            appendLog(t(`▸ ${ev.stage} 실행 중…`, `▸ Running ${ev.stage}…`));
          } else if (ev.event === "stage_done") {
            setLive((p) => ({ ...p, [ev.stage]: { status: ev.status, detail: ev.detail } }));
            const icon = ev.status === "pass" ? "✓" : ev.status === "fail" ? "✕" : "–";
            appendLog(`${icon} ${ev.stage} ${ev.status} — ${ev.detail}`);
          } else {
            setResult(ev.result);
            appendLog(t(`■ 판정: ${ev.result.verdict} (QoR ${ev.result.score}점)`, `■ Verdict: ${ev.result.verdict} (QoR ${ev.result.score} pts)`));
            if (ev.result.run_id) appendLog(t(`■ 런 #${ev.result.run_id}로 기록됨`, `■ Recorded as run #${ev.result.run_id}`));
          }
        },
      );
    } catch (e) {
      setError((e as Error).message);
      setLive(previous => Object.fromEntries(Object.entries(previous).map(([name, stage]) => [
        name, stage.status === "running" ? { status: "interrupted", detail: t("최종 결과 확인 불가", "Final result unavailable") } : stage,
      ])));
      appendLog(t(`✕ 오류: ${(e as Error).message}`, `✕ Error: ${(e as Error).message}`));
    } finally {
      setRunning(false);
    }
  }

  const verdictStatus = { SIGNED_OFF: "good", CONDITIONAL: "warning", REJECTED: "critical" } as const;
  const verdictLabel = {
    SIGNED_OFF: "SIGNED_OFF",
    CONDITIONAL: t("CONDITIONAL — 게이팅 단계 일부 생략", "CONDITIONAL — some gating stages skipped"),
    REJECTED: "REJECTED",
  };
  const liveStatusBadge: Record<LiveStatus, { status: "good" | "critical" | "warning" | "neutral"; label: string }> = {
    pending: { status: "neutral", label: t("대기", "Pending") },
    running: { status: "warning", label: t("실행 중", "Running") },
    interrupted: { status: "warning", label: t("중단", "Interrupted") },
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
      title={t("RTL 사인오프 래더", "RTL sign-off ladder")}
      subtitle={t("verilator lint → 설계 룰(CDC/리셋/FSM) → yosys 합성 → 테스트벤치 시뮬레이션 → 판정", "verilator lint → design rules (CDC/reset/FSM) → yosys synthesis → testbench simulation → verdict")}
      actions={
        <div className="flex w-full min-w-0 flex-wrap items-end gap-2 sm:w-auto">
          <Field label={t("프로젝트에 기록 (선택)", "Record to project (optional)")}>
            <select
              aria-label={t("프로젝트에 기록 (선택)", "Record to project (optional)")}
              className="input max-w-[16rem]"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value === "" ? "" : Number(e.target.value))}
            >
              <option value="">{t("기록 안 함", "Do not record")}</option>
              {(projects.data ?? []).filter(p => auth.can(p.id, "editor")).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </Field>
          <button className="btn btn-primary whitespace-nowrap" onClick={runLadder} disabled={running || (!!topModule.trim() && !/^[A-Za-z_][A-Za-z0-9_$]*$/.test(topModule.trim())) || (!!testbench.trim() && !/^[A-Za-z_][A-Za-z0-9_$]*$/.test(testbenchTop.trim()))}>
            {running ? t("래더 실행 중…", "Running ladder…") : t("사인오프 래더 실행", "Run sign-off ladder")}
          </button>
        </div>
      }
    >
      <AgentEntry role="a1_rtl" />
      <div className="mb-3 space-y-2"><Field label={t("린트·합성 최상위 모듈 (선택)", "Lint/synthesis top module (optional)")}><input className="input w-full" value={topModule} maxLength={120} disabled={running} onChange={e => setTopModule(e.target.value)} placeholder={t("예: chip_top", "e.g. chip_top")} /></Field>
        <p className="text-xs text-[var(--text-secondary)]">{t("비워 두면 첫 모듈 선언을 선택합니다. 정적 설계 규칙은 전체 입력을 검사하며, 시뮬레이션은 아래 테스트벤치 최상위를 사용합니다.", "If left empty, the first module declaration is used. Static design rules check the entire input, and simulation uses the testbench top module below.")}</p>
        <p className="text-xs text-[var(--text-secondary)]">{t("합성은 하위 모듈의 RTL 정의가 모두 필요합니다. 블랙박스는 지원하지 않습니다. 모듈 간 연결을 포함해 구동되지 않는 신호·다중 드라이버·조합 논리 루프가 발견되면 실패합니다.", "Synthesis needs RTL definitions for every submodule; black boxes are not supported. It fails on undriven signals, multiple drivers or combinational loops, including across module connections.")}</p>
        {!!topModule.trim() && !/^[A-Za-z_][A-Za-z0-9_$]*$/.test(topModule.trim()) && <p role="alert" className="text-xs">{t("모듈 이름은 영문자 또는 밑줄로 시작하고 영문자·숫자·밑줄·$만 사용할 수 있습니다.", "Module names must start with a letter or underscore and may contain only letters, digits, underscores and $.")}</p>}
      </div>
      <div className="mb-3"><Field label={t("설계 리비전 (선택)", "Design revision (optional)")}><input className="input w-full" value={designRevision} maxLength={160} disabled={running} onChange={e => setDesignRevision(e.target.value)} placeholder={t("예: Git 커밋 SHA 또는 검토용 리비전", "e.g. Git commit SHA or review revision")} /></Field></div>
      <div className="mb-2 flex flex-wrap gap-2">
        <button className="btn btn-ghost" disabled={running} onClick={() => setCode(BUGGY_RTL)}>
          {t("버그 있는 예제 (CDC 미동기화)", "Buggy example (unsynchronized CDC)")}
        </button>
        <button className="btn btn-ghost" disabled={running} onClick={() => setCode(CLEAN_RTL)}>
          {t("클린 예제 (2-FF 동기화)", "Clean example (2-FF synchronizer)")}
        </button>
      </div>
      <textarea
        className="code-editor w-full"
        style={{ minHeight: 220 }}
        spellCheck={false}
        value={code}
        onChange={(e) => setCode(e.target.value)}
        aria-label={t("SystemVerilog 소스", "SystemVerilog source")}
        disabled={running}
        maxLength={500000}
      />

      <details className="mt-3">
        <summary className="cursor-pointer font-semibold text-sm">{t("테스트벤치 (선택)", "Testbench (optional)")}</summary>
        <p className="my-2 text-xs text-[var(--text-secondary)]">{t('자체 검사 테스트벤치를 입력하세요. 실패 시 $fatal(1, …)을 호출하고, 모든 검사 후 $display("SIGNOFF_TEST_PASS"); $finish;로 종료합니다. 미제공 또는 서버 실행 비활성 시 필수 시뮬레이션 단계는 미완료로 남습니다.', 'Enter a self-checking testbench. Call $fatal(1, …) on failure, and end with $display("SIGNOFF_TEST_PASS"); $finish; after all checks. If none is provided or server execution is disabled, the required simulation stage stays incomplete.')}</p>
        <button className="btn btn-ghost mb-2" disabled={running} onClick={() => { setCode(CLEAN_RTL); setTestbench(PULSE_TESTBENCH); setTestbenchTop("tb"); }}>{t("펄스 동기화 검증 예제 불러오기", "Load pulse synchronizer test example")}</button>
        <Field label={t("테스트벤치 최상위 모듈", "Testbench top module")}><input className="input" value={testbenchTop} maxLength={120} disabled={running} onChange={e => setTestbenchTop(e.target.value)} /></Field>
        <textarea aria-label={t("테스트벤치 SystemVerilog", "Testbench SystemVerilog")} className="code-editor w-full mt-2" rows={10} spellCheck={false} maxLength={500000} disabled={running} value={testbench} onChange={e => setTestbench(e.target.value)} />
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
                    {s.detail ?? (s.status === "running" ? t("툴 실행 중…", "Running tool…") : " ")}
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
            aria-label={t("사인오프 실행 로그", "Sign-off run log")}
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
              {t(`QoR ${result.score}점 · 등급 ${result.grade}`, `QoR ${result.score} pts · grade ${result.grade}`)}
              {result.module && t(` · 모듈 ${result.module}`, ` · module ${result.module}`)}
              {result.run_id && t(` · 런 #${result.run_id}로 기록됨`, ` · recorded as run #${result.run_id}`)}
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs" style={{ color: "var(--text-muted)" }}>
                  <th className="py-1.5 font-medium">{t("DRC 룰", "DRC rule")}</th>
                  <th className="py-1.5 font-medium">{t("이름", "Name")}</th>
                  <th className="py-1.5 font-medium">{t("상태", "Status")}</th>
                  <th className="py-1.5 font-medium">{t("상세", "Details")}</th>
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
                {t("개선 제안", "Suggested improvements")}
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
      <AgentReviewPanel role="a1_rtl" scope={result ? `${result.run_id ? t(`런 #${result.run_id} · `, `Run #${result.run_id} · `) : ''}${t(`규칙 위반 ${result.rules.filter(rule => rule.status === 'violation').length}건`, `${result.rules.filter(rule => rule.status === 'violation').length} rule violations`)}` : undefined} review={a1.data} loading={a1.isFetching} failed={a1.isError} onRetry={() => void a1.refetch()} />
    </Card>
  );
}

function IrDropSection() {
  const { t } = useLanguage();
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
      title={t("IR-drop 사전 스크리닝 — Ibex @ SKY130", "IR-drop pre-screening — Ibex @ SKY130")}
      subtitle={t("물리 기반 서로게이트 (arXiv:2601.22707) · VDD 1.8V, 임계 5% (90mV) — 골든 EM/IR 사인오프 전 핫스팟 탐지", "Physics-based surrogate (arXiv:2601.22707) · VDD 1.8V, 5% threshold (90mV) — hotspot detection before golden EM/IR sign-off")}
      actions={
        <button className="btn btn-primary" onClick={() => run.mutate()} disabled={run.isPending}>
          {t("Ibex 플로어플랜 분석", "Analyze Ibex floorplan")}
        </button>
      }
    >
      <AgentEntry role="a3_power_ir" />
      {run.data ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatTile
              label={t("최악 IR-drop", "Worst IR-drop")}
              value={run.data.worst_drop_mv.toFixed(1)}
              suffix="mV"
              tone={run.data.passed ? "good" : "critical"}
            />
            <StatTile label={t("평균 IR-drop", "Mean IR-drop")} value={run.data.mean_drop_mv.toFixed(1)} suffix="mV" />
            <StatTile label={t("핫스팟", "Hotspots")} value={run.data.hotspot_count} suffix={t("타일", "tiles")} />
            <StatTile label={t("임계값", "Threshold")} value={run.data.threshold_mv.toFixed(0)} suffix="mV" />
          </div>
          <StatusBadge
            status={run.data.passed ? "good" : "critical"}
            label={run.data.passed ? t("스크리닝 통과", "Screening passed") : t("핫스팟 검출 — 골든 사인오프 필요", "Hotspots detected — golden sign-off required")}
          />
          <IrDropHeatmap map={run.data.drop_map_mv} thresholdMv={run.data.threshold_mv} />

        </div>
      ) : (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          {t("Ibex RISC-V 코어(lowRISC)의 10×10 타일 플로어플랜 — multdiv_fast 고활동 클러스터와 M4 파워 스트랩에서 먼 레지스터 파일 코너(취약 PDN)를 포함합니다.", "A 10×10-tile floorplan of the Ibex RISC-V core (lowRISC) — includes the high-activity multdiv_fast cluster and a register-file corner far from the M4 power straps (weak PDN).")}
        </p>
      )}
      <AgentReviewPanel role="a3_power_ir" scope={run.data ? t(`최악 IR-drop ${run.data.worst_drop_mv.toFixed(1)} mV / 임계 ${run.data.threshold_mv.toFixed(1)} mV`, `Worst IR-drop ${run.data.worst_drop_mv.toFixed(1)} mV / threshold ${run.data.threshold_mv.toFixed(1)} mV`) : undefined} review={a3.data} loading={a3.isFetching} failed={a3.isError} onRetry={() => void a3.refetch()} />
    </Card>
  );
}

function TimingSection() {
  const { t } = useLanguage();
  const [cornersText, setCornersText] = useState(JSON.stringify(IBEX_CORNERS, null, 2));
  const [credit, setCredit] = useState(15);
  const run = useMutation({
    mutationFn: () => {
      const corners = JSON.parse(cornersText);
      if (!Array.isArray(corners)) throw new Error(t('코너 JSON은 배열이어야 합니다.', 'Corner JSON must be an array.'));
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
      title={t("MMMC 타이밍 요약", "MMMC timing summary")}
      subtitle={t("코너별 WNS/TNS 집계 · 종점 대응 확인 · PBA 크레딧 추정", "Per-corner WNS/TNS rollup · endpoint alignment check · PBA credit estimate")}
      actions={
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs" style={{ color: "var(--text-secondary)" }}>
            {t("PBA 크레딧 (ps)", "PBA credit (ps)")}
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
            {t("코너 분석", "Analyze corners")}
          </button>
        </div>
      }
    >
      <AgentEntry role="a2_timing" />
      <details className="mb-4"><summary className="cursor-pointer text-sm font-semibold">{t("분석 데이터 편집", "Edit analysis data")}</summary>
        <p className="my-2 text-xs text-[var(--text-secondary)]">{t("각 코너에 name, endpoint_slacks_ps와 선택 사항인 endpoint_ids를 입력하세요. ID를 사용하면 모든 코너에 같은 종점 집합을 제공해야 합니다.", "For each corner, enter name, endpoint_slacks_ps and optional endpoint_ids. If you use IDs, every corner must provide the same endpoint set.")}</p>
        <textarea aria-label={t("코너 JSON", "Corner JSON")} className="input w-full font-mono text-xs" rows={10} maxLength={2000000} spellCheck={false} disabled={run.isPending} value={cornersText} onChange={e => { setCornersText(e.target.value); run.reset(); }} />
        <button className="btn btn-ghost mt-2" disabled={run.isPending} onClick={() => { setCornersText(JSON.stringify(IBEX_CORNERS, null, 2)); run.reset(); }}>{t("Ibex 예제 불러오기", "Load Ibex example")}</button>
      </details>
      {run.isError && <p role="alert" className="mb-3 text-sm text-[var(--status-critical)]">{run.error.message}</p>}
      {run.data ? (
        <div className="space-y-4">
          <p role="status" className="text-sm">{run.data.endpoint_alignment === 'by_id' ? t('종점 ID 기준으로 코너를 대응했습니다.', 'Corners were aligned by endpoint ID.') : t('종점 ID가 없어 입력 순서대로 대응했습니다. 같은 위치가 같은 종점인지 확인하세요.', 'No endpoint IDs were given, so corners were aligned by input order. Confirm that each position is the same endpoint.')}</p>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile
              label={t("머지 WNS", "Merged WNS")}
              value={run.data.merged.wns_ps}
              suffix="ps"
              tone={run.data.merged.wns_ps < 0 ? "critical" : "good"}
            />
            <StatTile label={t("머지 TNS", "Merged TNS")} value={run.data.merged.tns_ps} suffix="ps" />
            <StatTile
              label={t("위반 엔드포인트", "Violating endpoints")}
              value={`${run.data.merged.violating_endpoints}/${run.data.merged.total_endpoints}`}
            />
            {run.data.estimated_pba && (
              <StatTile
                label={t("PBA 크레딧 후 회복", "Recovered after PBA credit")}
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
                  <th className="py-1.5 font-medium">{t("코너", "Corner")}</th>
                  <th className="py-1.5 text-right font-medium">WNS (ps)</th>
                  <th className="py-1.5 text-right font-medium">TNS (ps)</th>
                  <th className="py-1.5 text-right font-medium">{t("위반 EP", "Violating EP")}</th>
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
              {t("머지 엔드포인트 슬랙 (입력 순서, 최대 50개)", "Merged endpoint slack (input order, up to 50)")}
            </h3>
            <SlackBars
              slacks={run.data.merged_slacks_ps.slice(0, 50)}
              endpointIds={run.data.endpoint_ids?.slice(0, 50)}
            />
          </div>

          <section aria-label={t("최악 종점과 코너", "Worst endpoints and corners")} className="space-y-2">
            <h3 className="font-semibold text-sm">{t("최악 종점과 제한 코너 (최대 20개)", "Worst endpoints and limiting corners (up to 20)")}</h3>
            <ul className="space-y-2">{run.data.worst_endpoints.map(endpoint => <li key={endpoint.index} className="rounded-lg border border-[var(--border)] p-3 text-xs break-all">
              <strong>EP{endpoint.index} · {endpoint.endpoint_id ?? t('ID 미제공', 'No ID provided')}</strong><p>{endpoint.slack_ps} ps · {endpoint.limiting_corners.join(', ')}</p>
            </li>)}</ul>
            <p className="text-xs text-[var(--text-muted)]">{t("제공된 종점·코너의 요약입니다. 입력 ID의 일치는 실제 설계나 전체 코너 검증의 완료를 증명하지 않습니다.", "A summary of the endpoints and corners provided. Matching input IDs does not prove the real design or full-corner verification is complete.")}</p>
          </section>

        </div>
      ) : (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          {t("기본 입력은 Ibex / SKY130의 종점 12개를 사용하는 설명용 예제입니다. 분석 데이터 편집에서 실제 코너 데이터를 입력한 뒤 분석하세요.", "The default input is an illustrative example using 12 Ibex / SKY130 endpoints. Enter real corner data under Edit analysis data, then analyze.")}
        </p>
      )}
      <AgentReviewPanel role="a2_timing" scope={run.data ? t(`머지 WNS ${run.data.merged.wns_ps} ps`, `Merged WNS ${run.data.merged.wns_ps} ps`) : undefined} review={a2.data} loading={a2.isFetching} failed={a2.isError} onRetry={() => void a2.refetch()} />
    </Card>
  );
}

function GlitchSection() {
  const { t } = useLanguage();
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
      title={t("벡터리스 글리치 파워 추정 — Ibex ALU/MULTDIV", "Vectorless glitch power estimate — Ibex ALU/MULTDIV")}
      subtitle={t("토글률 초과분 기반 (Synopsys US 12,001,768 방식 단순화) · VDD 1.8V, clk 10ns — 깊은 연산 로직이 글리치에 취약", "Based on excess toggle rate (simplified Synopsys US 12,001,768 method) · VDD 1.8V, clk 10ns — deep arithmetic logic is glitch-prone")}
      actions={
        <button className="btn btn-primary" onClick={() => run.mutate()} disabled={run.isPending}>
          {t("Ibex 네트 분석", "Analyze Ibex nets")}
        </button>
      }
    >
      <AgentEntry role="a3_power_ir" />
      {run.data ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <StatTile
              label={t("총 동적 전력", "Total dynamic power")}
              value={(run.data.total_dynamic_power_mw * 1000).toFixed(2)}
              suffix="µW"
            />
            <StatTile
              label={t("글리치 전력", "Glitch power")}
              value={(run.data.glitch_power_mw * 1000).toFixed(2)}
              suffix="µW"
            />
            <StatTile
              label={t("글리치 비중", "Glitch share")}
              value={`${(run.data.glitch_share * 100).toFixed(1)}%`}
              tone={run.data.glitch_share >= 0.5 ? "critical" : undefined}
            />
          </div>
          <div>
            <div className="mb-1.5 flex justify-between text-xs" style={{ color: "var(--text-muted)" }}>
              <span>{t("글리치 비중", "Glitch share")}</span>
              <span>{t("경고 30% · 위험 50%", "Warning 30% · critical 50%")}</span>
            </div>
            <Meter ratio={run.data.glitch_share} />
          </div>
          <PowerStackBars nets={run.data.nets} />

        </div>
      ) : (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          {t("ibex_alu / ibex_multdiv_fast의 글리치 취약 네트 5개(가산기 출력, MAC 결과, 중간값 레지스터 입력 등)로 추정을 실행합니다.", "Runs the estimate on 5 glitch-prone nets in ibex_alu / ibex_multdiv_fast (adder output, MAC result, intermediate register inputs and more).")}
        </p>
      )}
      <AgentReviewPanel role="a3_power_ir" scope={run.data ? t(`글리치 비중 ${(run.data.glitch_share * 100).toFixed(1)}%`, `Glitch share ${(run.data.glitch_share * 100).toFixed(1)}%`) : undefined} review={a3.data} loading={a3.isFetching} failed={a3.isError} onRetry={() => void a3.refetch()} />
    </Card>
  );
}
