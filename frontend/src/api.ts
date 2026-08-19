export type Domain = "rtl" | "sta" | "emir" | "pv" | "glitch_power" | "thermal";
export type Stage = "rtl" | "synthesis" | "placement" | "routing" | "final";
export type RunStatus = "running" | "passed" | "failed";
export type Severity = "info" | "warning" | "error" | "critical";
export type ViolationStatus = "open" | "fixed" | "waived";

export interface Project {
  id: number;
  name: string;
  process_node: string;
  foundry: string;
  created_at: string;
}

export interface SignoffRun {
  id: number;
  project_id: number;
  domain: Domain;
  stage: Stage;
  tool: string;
  status: RunStatus;
  metrics: Record<string, unknown>;
  created_at: string;
}

export interface Waiver {
  id: number;
  violation_id: number;
  reason: string;
  approved_by: string;
  created_at: string;
}

export interface Violation {
  id: number;
  run_id: number;
  check_name: string;
  severity: Severity;
  location: string | null;
  description: string | null;
  status: ViolationStatus;
  waiver: Waiver | null;
}

export interface GateDomain {
  domain: Domain;
  ready: boolean;
  reason: string | null;
  run_id?: number;
  open_blocking_violations?: number;
}

export interface GateStatus {
  stage: Stage;
  ready: boolean;
  domains: GateDomain[];
}

export interface IrDropResult {
  grid_shape: number[];
  vdd: number;
  threshold_mv: number;
  worst_drop_mv: number;
  mean_drop_mv: number;
  hotspot_count: number;
  hotspots: { row: number; col: number; drop_mv: number }[];
  passed: boolean;
  drop_map_mv: number[][];
}

export interface GlitchResult {
  net_count: number;
  functional_power_mw: number;
  glitch_power_mw: number;
  total_dynamic_power_mw: number;
  glitch_share: number;
  nets: {
    name: string;
    glitch_toggle_rate: number;
    functional_power_uw: number;
    glitch_power_uw: number;
  }[];
}

export interface RtlSignoffResult {
  verdict: "SIGNED_OFF" | "CONDITIONAL" | "REJECTED";
  score: number;
  grade: string;
  module: string | null;
  stages: { name: string; status: "pass" | "fail" | "skip"; gating: boolean; detail: string }[];
  rules: {
    code: string;
    name: string;
    severity: "error" | "warn" | "info";
    status: "pass" | "violation";
    detail: string;
  }[];
  suggestions: string[];
  run_id: number | null;
}

export type RtlStreamEvent =
  | { event: "stage_start"; stage: string }
  | { event: "stage_done"; stage: string; status: "pass" | "fail" | "skip"; detail: string }
  | { event: "result"; result: RtlSignoffResult };

export interface CornerStats {
  name?: string;
  wns_ps: number;
  tns_ps: number;
  violating_endpoints: number;
  total_endpoints: number;
}

export interface TimingResult {
  corners: (CornerStats & { name: string })[];
  merged: CornerStats;
  signoff_clean: boolean;
  estimated_pba?: CornerStats & {
    pessimism_credit_ps: number;
    recovered_endpoints: number;
  };
}

export interface AgentReview {
  role: string;
  role_name: string;
  triggered: boolean;
  trigger: string;
  available: boolean | null;
  review: string | null;
  error: string | null;
}

export interface GateAgentReview {
  a5: AgentReview;
  v: AgentReview | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail =
      body && typeof body.detail === "string"
        ? body.detail
        : `${res.status} ${res.statusText}`;
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listProjects: () => request<Project[]>("/projects"),
  createProject: (p: Omit<Project, "id" | "created_at">) =>
    request<Project>("/projects", { method: "POST", body: JSON.stringify(p) }),
  getProject: (id: number) => request<Project>(`/projects/${id}`),
  listRuns: (projectId: number) =>
    request<SignoffRun[]>(`/projects/${projectId}/runs`),
  createRun: (
    projectId: number,
    run: { domain: Domain; stage: Stage; tool: string },
  ) =>
    request<SignoffRun>(`/projects/${projectId}/runs`, {
      method: "POST",
      body: JSON.stringify(run),
    }),
  updateRun: (runId: number, status: RunStatus) =>
    request<SignoffRun>(`/runs/${runId}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),
  listViolations: (runId: number) =>
    request<Violation[]>(`/runs/${runId}/violations`),
  addViolation: (
    runId: number,
    v: { check_name: string; severity: Severity; location?: string },
  ) =>
    request<Violation[]>(`/runs/${runId}/violations`, {
      method: "POST",
      body: JSON.stringify([v]),
    }),
  waiveViolation: (violationId: number, w: { reason: string; approved_by: string }) =>
    request<Violation>(`/violations/${violationId}/waiver`, {
      method: "POST",
      body: JSON.stringify(w),
    }),
  gateStatus: (projectId: number, stage: Stage) =>
    request<GateStatus>(`/projects/${projectId}/signoff-status?stage=${stage}`),
  irDrop: (payload: {
    cell_density: number[][];
    switching_activity: number[][];
    pdn_strength: number[][];
    vdd?: number;
    scale?: number;
  }) =>
    request<IrDropResult>("/analysis/ir-drop", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  glitchPower: (payload: {
    nets: {
      name?: string;
      cap_ff: number;
      functional_toggle_rate: number;
      total_toggle_rate: number;
      transport_fraction?: number;
    }[];
    vdd?: number;
    clock_period_ns?: number;
  }) =>
    request<GlitchResult>("/analysis/glitch-power", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  rtlSignoff: (payload: { code: string; project_id?: number }) =>
    request<RtlSignoffResult>("/analysis/rtl-signoff", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  rtlSignoffStream: async (
    payload: { code: string; project_id?: number },
    onEvent: (event: RtlStreamEvent) => void,
  ) => {
    const res = await fetch("/api/analysis/rtl-signoff/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok || !res.body) {
      const body = await res.json().catch(() => null);
      throw new Error(
        body && typeof body.detail === "string" ? body.detail : `${res.status} ${res.statusText}`,
      );
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        if (line.trim()) onEvent(JSON.parse(line) as RtlStreamEvent);
      }
    }
    if (buffer.trim()) onEvent(JSON.parse(buffer) as RtlStreamEvent);
  },
  timingSummary: (payload: {
    corners: { name: string; endpoint_slacks_ps: number[] }[];
    pba_pessimism_credit_ps?: number;
  }) =>
    request<TimingResult>("/analysis/timing-summary", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  reviewRtl: (rtl_signoff_result: unknown) =>
    request<AgentReview>("/agents/review/rtl", {
      method: "POST",
      body: JSON.stringify({ rtl_signoff_result }),
    }),
  reviewTiming: (timing_result: unknown) =>
    request<AgentReview>("/agents/review/timing", {
      method: "POST",
      body: JSON.stringify({ timing_result }),
    }),
  reviewPowerIr: (payload: { ir_drop_result?: unknown; glitch_result?: unknown }) =>
    request<AgentReview>("/agents/review/power-ir", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  reviewGate: (payload: { gate_status: unknown; findings?: unknown }) =>
    request<GateAgentReview>("/agents/review/gate", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};

export const DOMAIN_LABELS: Record<Domain, string> = {
  rtl: "RTL 품질",
  sta: "STA",
  emir: "EM/IR",
  pv: "PV",
  glitch_power: "Glitch Power",
  thermal: "Thermal",
};

export const STAGES: Stage[] = ["rtl", "synthesis", "placement", "routing", "final"];

export const STAGE_LABELS: Record<Stage, string> = {
  rtl: "RTL",
  synthesis: "Synthesis",
  placement: "Placement",
  routing: "Routing",
  final: "Final",
};
