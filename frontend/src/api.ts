export type Domain = "rtl" | "sta" | "emir" | "pv" | "glitch_power" | "thermal";
export type Stage = "rtl" | "synthesis" | "placement" | "routing" | "final";
export type RunStatus = "running" | "passed" | "failed" | "incomplete";
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
  evidence_source: "manual" | "rtl_ladder" | "legacy" | "opensta_report" | "klayout_report";
  result_locked: boolean;
}

export interface RunEvidence {
  run_id: number;
  source: string;
  source_text: string | null;
  source_sha256: string | null;
  design_revision: string | null;
  result: Partial<RtlSignoffResult> & Partial<ReportPreview> & Partial<KLayoutPreview> & { metadata?: { filename: string; tool_version: string; scenario: string }; submitted_by?: { user_id: number; username: string } | null };
  created_at: string;
}

export interface ReportImportInput {
  import_id: string; stage: Stage; filename: string; tool_version: string;
  design_revision: string; scenario: string; source_text: string;
}
export interface ReportPreview {
  parser: string; coverage: string; coverage_note: string; status: "failed" | "incomplete"; source_sha256: string;
  metrics: { reported_paths: number; violating_paths: number; unconstrained_paths: number; worst_reported_slack_ps: number | null };
  paths: { index: number; type: string; path_type: string; path_group: string; startpoint: string; endpoint: string; slack_ps: number | null; fingerprint: string }[];
}

export interface KLayoutPreview {
  parser: string; coverage: string; coverage_note: string; status: 'failed' | 'incomplete'; source_sha256: string;
  metrics: { reported_items: number; reported_multiplicity: number };
  items: { index: number; category: string; cell: string; values: string[]; multiplicity: number; tags: string; comment: string }[];
}

export interface MarkerPage {
  run: SignoffRun; source_sha256: string; design_revision: string | null;
  reported_total: number; total: number; matched_multiplicity: number; offset: number; limit: number;
  categories: { value: string; count: number }[]; cells: { value: string; count: number }[];
  items: { index: number; category: string; cell: string; multiplicity: number }[];
}
export interface MarkerDetail {
  item: KLayoutPreview['items'][number];
  violation_matches: { status: 'missing' | 'unique' | 'ambiguous'; source_marker_count: number;
    items: { id: number; status: ViolationStatus; version: number }[] };
  geometry: { shapes: { value_index: number; closed: boolean; contours: number[][][] }[];
    bounds_um: { xmin: string; xmax: string; ymin: string; ymax: string } | null;
    rendered_values: number; unrendered_values: number[] };
}

export type TimingPath = ReportPreview['paths'][number] & { status: 'violated' | 'met' | 'unconstrained' };
export interface TimingPathSummary {
  violated_paths: number; met_paths: number; unconstrained_paths: number; worst_slack_ps: number | null;
}
export interface TimingPathPage {
  run: SignoffRun; metadata: { filename?: string; tool_version?: string; scenario?: string };
  design_revision: string | null; source_sha256: string; reported_total: number; total: number;
  offset: number; limit: number; items: TimingPath[]; summary: TimingPathSummary;
}
export interface TimingPathExport {
  format: 'signoff/timing-path-export/v1'; exported_at: string; run: SignoffRun;
  report: { source: string; parser: string; source_sha256: string; design_revision: string | null;
    metadata: TimingPathPage['metadata']; coverage: string; coverage_note: string };
  filters: { q: string; path_type: string | null; status: string; slack_min_ps: number | null; slack_max_ps: number | null; sort: string };
  units: { slack_ps: 'ps' }; reported_total: number; total: number; items: TimingPath[]; summary: TimingPathSummary;
}
export interface TimingPathDetail {
  path: TimingPath; source_clock: string | null; target_clock: string | null;
  arrival_ps: number | null; required_ps: number | null;
  point_total: number; point_offset: number; point_limit: number;
  arrival_delta_summary: { total_pairs: number; reported_pairs: number; largest_increases: { from_index: number; to_index: number; from_pin: string | null; to_pin: string | null; delta_ps: number }[] };
  points: { index: number; pin: string | null; instance: string | null; cell: string | null; net: string | null; arrival_ps: number | null; slew_ps: number | null; arrival_delta_ps: number | null }[];
}

export interface Waiver {
  id: number;
  violation_id: number;
  reason: string;
  approved_by: string;
  approved_user_id: number | null;
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
  version: number;
  waiver: Waiver | null;
}

export interface ViolationEvent {
  id: number;
  from_status: ViolationStatus;
  to_status: ViolationStatus;
  actor: string;
  actor_user_id: number | null;
  reason: string;
  created_at: string;
}

export interface ViolationHistoryExport {
  format: 'signoff/violation-history-export/v1'; exported_at: string;
  violation: ProjectViolation; events: ViolationEvent[]; total: number; coverage_note: string;
}

export interface ViolationHistoryPage {
  items: ViolationEvent[]; total: number; snapshot_max_id: number; next_before_id: number | null;
}

export interface ProjectViolation extends Violation {
  run: SignoffRun;
}

export interface ViolationPage {
  items: ProjectViolation[];
  total: number;
  open_blocking: number;
  offset: number;
  limit: number;
}

export interface ViolationExport {
  format: 'signoff/violation-export/v1'; exported_at: string; project_id: number;
  filters: { q: string; status: string | null; severity: string | null; domain: string | null;
    stage: string | null; latest_only: boolean; sort: string }; total: number; open_blocking: number;
  coverage_note: string; items: ProjectViolation[];
}

export interface ViolationFilters {
  q: string;
  status: string;
  severity: string;
  domain: string;
  stage: string;
  latest_only: boolean;
  sort: string;
  offset: number;
  limit: number;
}

export type ComparisonKind = "new" | "changed" | "removed" | "unchanged";

export interface RunProvenance {
  source: string;
  design_revision: string | null;
  source_sha256: string | null;
  scenario: string | null;
  tool_version: string | null;
  coverage: string | null;
}

export interface RunComparison {
  baseline_run: SignoffRun;
  candidate_run: SignoffRun;
  baseline_provenance: RunProvenance;
  candidate_provenance: RunProvenance;
  partial: boolean;
  different_tools: boolean;
  summary: Record<ComparisonKind, number>;
  metrics: {
    name: string;
    baseline: unknown;
    candidate: unknown;
    baseline_present: boolean;
    candidate_present: boolean;
    changed: boolean;
    delta: number | null;
  }[];
  items: {
    kind: ComparisonKind;
    baseline: Violation | null;
    candidate: Violation | null;
    changed_fields: string[];
    ambiguous_match: boolean;
  }[];
  total: number;
  offset: number;
  limit: number;
}

export interface GateDomain {
  domain: Domain;
  ready: boolean;
  reason: string | null;
  run_id?: number;
  open_blocking_violations?: number;
  evidence_source?: string;
  design_revision?: string | null;
}

export interface GateStatus {
  stage: Stage;
  ready: boolean;
  domains: GateDomain[];
  revision_check?: { status: 'missing' | 'mismatch' | 'consistent'; revisions: string[]; missing_domains: Domain[]; common_revision: string | null };
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

export interface SimulationEvidence {
  status: "pass" | "fail" | "skip";
  detail: string;
  engine: string;
  top: string | null;
  testbench_source: string | null;
  testbench_sha256: string | null;
  tool_version?: string;
  compile?: { exit_code: number | null; log: string; error: string | null };
  runtime?: { exit_code: number | null; log: string; error: string | null };
}

export interface RtlSignoffResult {
  execution?: { backend: 'container'; image_id: string };
  simulation?: SimulationEvidence;
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
  endpoint_alignment: 'by_id' | 'positional';
  endpoint_ids: string[] | null;
  merged_slacks_ps: number[];
  worst_endpoints: { index: number; endpoint_id: string | null; slack_ps: number; limiting_corners: string[] }[];
  corners: (CornerStats & { name: string })[];
  merged: CornerStats;
  signoff_clean: boolean;
  estimated_pba?: CornerStats & {
    pessimism_credit_ps: number;
    recovered_endpoints: number;
  };
}

export interface AgentReview {
  review_id?: string;
  completed_at?: string;
  duration_ms?: number;
  error_id?: string;
  role: string;
  role_name: string;
  triggered: boolean;
  trigger: string;
  available: boolean | null;
  review: string | null;
  error: string | null;
}

export interface SavedRunReviewSummary {
  id: number; run_id: number; request_key: string; requester: string; requester_user_id: number | null;
  role: string; status: 'running' | 'completed' | 'failed'; created_at: string; completion_overdue: boolean;
}
export interface SavedRunReview extends SavedRunReviewSummary {
  input_snapshot: Record<string, unknown>; review_policy: string; model_alias: string;
  outcome: { available?: boolean; review?: string | null; completed_at?: string; duration_ms?: number; error?: string;
    closure?: { actor: string; actor_user_id: number | null; reason: string; closed_at: string } };
}

export interface GateAgentReview {
  a5: AgentReview;
  v: AgentReview | null;
}

export type ProjectRole = "viewer" | "editor" | "approver" | "owner";
export interface AuthState {
  mode: "local" | "required";
  user: { id: number; username: string; is_admin: boolean } | null;
  csrf_token: string | null;
  memberships: Record<string, ProjectRole>;
}
export interface ProjectAccessEvent {
  id: number; project_id: number; subject_user_id: number; subject_username: string;
  actor_user_id: number | null; actor: string; source: "api" | "operator";
  before_role: ProjectRole | null; after_role: ProjectRole | null; created_at: string;
}
export interface ProjectMember { user_id: number; username: string; role: ProjectRole; disabled: boolean }
let csrfToken: string | null = null;
export function setCsrfToken(token: string | null) { csrfToken = token; }
function requestHeaders() { return { "Content-Type": "application/json", "X-Signoff-Client": "1", ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}) }; }
function sessionExpired() { window.dispatchEvent(new Event("signoff-session-expired")); }

function serverFailure(response: Response) {
  const id = response.headers.get('X-Request-ID');
  return '서버가 요청을 처리하지 못했습니다.' + (id && /^[a-f0-9]{32}$/.test(id) ? ` 문의 번호: ${id}` : ' 잠시 후 다시 확인하세요.');
}

function validationMessage(body: unknown): string | null {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (!Array.isArray(detail)) return null;
  const messages = detail.slice(0, 3).flatMap(item => {
    if (!item || !Array.isArray(item.loc) || typeof item.msg !== 'string') return [];
    const field = item.loc.filter((part: unknown) => part !== 'body' && (typeof part === 'string' || typeof part === 'number')).join('.');
    return [`${field ? field + ': ' : ''}${item.msg}`];
  });
  return messages.length ? messages.join(' · ') + (detail.length > 3 ? ' · 추가 입력 오류가 있습니다.' : '') : null;
}

async function request<T>(path: string, init?: RequestInit, responseType: 'json' | 'text' | 'blob' = 'json'): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: requestHeaders(),
    ...init,
  });
  if (res.status === 401 && path !== "/auth/login") sessionExpired();
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    if (res.status >= 500) throw new Error(serverFailure(res));
    const detail =
      body && typeof body.detail === "string"
        ? body.detail
        : validationMessage(body) ?? `${res.status} ${res.statusText}`;
    throw new Error(detail);
  }
  if (path === "/projects" && init?.method === "POST") window.dispatchEvent(new Event("signoff-auth-refresh"));
  return (responseType === 'blob' ? res.blob() : responseType === 'text' ? res.text() : res.json()) as Promise<T>;
}

export const api = {
  runReviews: (runId: number, before: number | null) => request<{ items: SavedRunReviewSummary[]; next_before_id: number | null }>(`/runs/${runId}/agent-reviews${before ? `?before_id=${before}` : ''}`),
  exportRunReview: (runId: number, reviewId: number) => request<Blob>(`/runs/${runId}/agent-reviews/${reviewId}/export`, undefined, 'blob'),
  runReview: (runId: number, reviewId: number) => request<SavedRunReview>(`/runs/${runId}/agent-reviews/${reviewId}`),
  createRunReview: (runId: number, requestKey: string) => request<SavedRunReview>(`/runs/${runId}/agent-reviews`, { method: 'POST', body: JSON.stringify({ request_key: requestKey }) }),
  closeRunReview: (runId: number, reviewId: number, reason: string) => request<SavedRunReview>(`/runs/${runId}/agent-reviews/${reviewId}/close`, { method: 'POST', body: JSON.stringify({ reason }) }),
  timingPaths: (runId: number, filters: Record<string, string>) => request<TimingPathPage>(`/runs/${runId}/timing-paths?${new URLSearchParams(filters)}`),
  exportTimingPaths: (runId: number, filters: Record<string, string>) => request<TimingPathExport>(`/runs/${runId}/timing-paths/export?${new URLSearchParams(filters)}`),
  exportTimingPathsCsv: (runId: number, filters: Record<string, string>) => request<string>(`/runs/${runId}/timing-paths/export?${new URLSearchParams({ ...filters, format: 'csv' })}`, undefined, 'text'),
  timingPath: (runId: number, index: number, pointOffset: number) => request<TimingPathDetail>(`/runs/${runId}/timing-paths/${index}?point_offset=${pointOffset}`),
  previewOpenSta: (projectId: number, body: ReportImportInput) => request<ReportPreview>(`/projects/${projectId}/imports/opensta/preview`, { method: "POST", body: JSON.stringify(body) }),
  importOpenSta: (projectId: number, body: ReportImportInput) => request<SignoffRun>(`/projects/${projectId}/imports/opensta`, { method: "POST", body: JSON.stringify(body) }),
  previewKLayout: (projectId: number, body: ReportImportInput) => request<KLayoutPreview>(`/projects/${projectId}/imports/klayout/preview`, { method: 'POST', body: JSON.stringify(body) }),
  importKLayout: (projectId: number, body: ReportImportInput) => request<SignoffRun>(`/projects/${projectId}/imports/klayout`, { method: 'POST', body: JSON.stringify(body) }),
  markers: (runId: number, filters: Record<string, string>) => request<MarkerPage>(`/runs/${runId}/markers?${new URLSearchParams(filters)}`),
  marker: (runId: number, index: number) => request<MarkerDetail>(`/runs/${runId}/markers/${index}`),
  authSession: () => request<AuthState>("/auth/session"),
  login: (username: string, password: string) => request<AuthState>("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  changePassword: (current_password: string, new_password: string) => request<AuthState>("/auth/password", { method: "POST", body: JSON.stringify({ current_password, new_password }) }),
  logout: () => request("/auth/logout", { method: "POST" }),
  authSessions: (offset = 0) => request<{ total: number; offset: number; limit: number; items: { id: number; current: boolean; expires_at: number }[] }>(`/auth/sessions?offset=${offset}&limit=25`),
  revokeOtherSessions: () => request<{ revoked: number }>('/auth/sessions/revoke-others', { method: 'POST' }),
  securityEvents: (beforeId: number | null = null) => request<{ items: { id: number; action: string; actor: string; actor_user_id: number | null; source: string; revoked_sessions: number | null; created_at: string }[]; next_before_id: number | null }>(`/auth/security-events?limit=25${beforeId === null ? '' : `&before_id=${beforeId}`}`),
  adminSecurityEvents: (filters: Record<string, string>) => request<{ items: { id: number; subject_user_id: number | null; subject_username: string | null; action: string; actor: string; actor_user_id: number | null; source: string; revoked_sessions: number | null; created_at: string }[]; next_before_id: number | null }>(`/auth/admin/security-events?${new URLSearchParams(filters)}`),
  memberHistory: (id: number, before?: number) => request<{ items: ProjectAccessEvent[]; next_before_id: number | null }>(`/projects/${id}/members/history${before ? `?before_id=${before}` : ""}`),
  members: (id: number) => request<ProjectMember[]>(`/projects/${id}/members`),
  setMember: (id: number, username: string, role: ProjectRole) => request(`/projects/${id}/members`, { method: "PUT", body: JSON.stringify({ username, role }) }),
  removeMember: (id: number, userId: number) => request(`/projects/${id}/members/${userId}`, { method: "DELETE" }),
  listProjects: () => request<Project[]>("/projects"),
  createProject: (p: Omit<Project, "id" | "created_at">) =>
    request<Project>("/projects", { method: "POST", body: JSON.stringify(p) }),
  getProject: (id: number) => request<Project>(`/projects/${id}`),
  listRuns: (projectId: number) =>
    request<SignoffRun[]>(`/projects/${projectId}/runs`),
  runSource: (runId: number) => request<Blob>(`/runs/${runId}/evidence/source`, undefined, 'blob'),
  runEvidence: (runId: number) => request<RunEvidence>(`/runs/${runId}/evidence`),
  compareRuns: (projectId: number, baseline: number, candidate: number, kind: string, offset: number) =>
    request<RunComparison>(`/projects/${projectId}/run-comparison?${new URLSearchParams({
      baseline_run_id: String(baseline), candidate_run_id: String(candidate), kind, offset: String(offset),
    })}`),
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
  getViolation: (violationId: number) => request<Violation>(`/violations/${violationId}`),
  projectViolations: (projectId: number, filters: ViolationFilters) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) {
      if (value !== "") params.set(key, String(value));
    }
    return request<ViolationPage>(`/projects/${projectId}/violations?${params}`);
  },
  exportViolations: async (projectId: number, filters: ViolationFilters) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) {
      if (value !== '' && key !== 'offset' && key !== 'limit') params.set(key, String(value));
    }
    const content = await request<string>(`/projects/${projectId}/violations/export?${params}`, undefined, 'text');
    return { bundle: JSON.parse(content) as ViolationExport, content };
  },
  addViolation: (
    runId: number,
    v: { check_name: string; severity: Severity; location?: string },
  ) =>
    request<Violation[]>(`/runs/${runId}/violations`, {
      method: "POST",
      body: JSON.stringify([v]),
    }),
  waiveViolation: (violationId: number, w: { reason: string; approved_by: string; expected_version: number }) =>
    request<Violation>(`/violations/${violationId}/waiver`, {
      method: "POST",
      body: JSON.stringify(w),
    }),
  transitionViolation: (id: number, payload: {
    expected_status: ViolationStatus; expected_version: number; status: ViolationStatus; actor: string; reason: string;
  }) => request<Violation>(`/violations/${id}`, {
    method: "PATCH", body: JSON.stringify(payload),
  }),
  violationHistory: (id: number) => request<ViolationEvent[]>(`/violations/${id}/history`),
  violationHistoryPage: (id: number, cursor: { before_id: number; snapshot_max_id: number } | null, filters: { q: string; to_status: string }) =>
    request<ViolationHistoryPage>(`/violations/${id}/history/page?${new URLSearchParams({ ...(cursor ? { before_id: String(cursor.before_id), snapshot_max_id: String(cursor.snapshot_max_id) } : {}), q: filters.q, ...(filters.to_status ? { to_status: filters.to_status } : {}) })}`),
  exportViolationHistory: async (id: number) => {
    const content = await request<string>(`/violations/${id}/history/export`, undefined, 'text');
    return { bundle: JSON.parse(content) as ViolationHistoryExport, content };
  },
  gateStatus: (projectId: number, stage: Stage) =>
    request<GateStatus>(`/projects/${projectId}/signoff-status?stage=${stage}`),
  exportGate: (projectId: number, stage: Stage) =>
    request<Blob>(`/projects/${projectId}/signoff-status/export?stage=${stage}`, undefined, 'blob'),
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
  rtlSignoff: (payload: { code: string; project_id?: number; design_revision?: string; testbench?: string; testbench_top?: string }) =>
    request<RtlSignoffResult>("/analysis/rtl-signoff", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  rtlSignoffStream: async (
    payload: { code: string; project_id?: number; design_revision?: string; testbench?: string; testbench_top?: string },
    onEvent: (event: RtlStreamEvent) => void,
  ) => {
    const res = await fetch("/api/analysis/rtl-signoff/stream", {
      method: "POST",
      headers: requestHeaders(),
      body: JSON.stringify(payload),
    });
    if (res.status === 401) sessionExpired();
    if (!res.ok || !res.body) {
      const body = await res.json().catch(() => null);
      if (res.status >= 500) throw new Error(serverFailure(res));
      if (res.status === 429) {
        throw new Error('서버의 RTL 분석이 모두 사용 중입니다. 아직 분석을 시작하지 않았습니다. 5초 뒤 다시 실행하세요.');
      }
      throw new Error(
        body && typeof body.detail === "string" ? body.detail : validationMessage(body) ?? `${res.status} ${res.statusText}`,
      );
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let receivedResult = false;
    const deliver = (line: string) => {
      if (!line.trim()) return;
      const event = JSON.parse(line) as RtlStreamEvent | { event: "error"; detail: string };
      if (event.event === "error") {
        throw new Error('RTL 실행 워커가 작업을 완료하지 못했습니다. 서버 상태를 확인하고 다시 실행하세요.');
      }
      if (event.event === "result") {
        if (!event.result || !["SIGNED_OFF", "CONDITIONAL", "REJECTED"].includes(event.result.verdict)
          || !Array.isArray(event.result.stages) || !Array.isArray(event.result.rules)) {
          throw new Error("RTL 분석 결과 형식이 올바르지 않습니다. 다시 실행하세요.");
        }
        receivedResult = true;
      }
      onEvent(event);
    };
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) deliver(line);
      }
      buffer += decoder.decode();
      deliver(buffer);
      if (!receivedResult) throw new Error("RTL 분석 응답이 완료되기 전에 연결이 종료되었습니다. 다시 실행하세요.");
    } catch (error) {
      await reader.cancel().catch(() => {});
      throw error;
    } finally {
      reader.releaseLock();
    }
  },
  timingSummary: (payload: {
    corners: { name: string; endpoint_slacks_ps: number[]; endpoint_ids?: string[] }[];
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
