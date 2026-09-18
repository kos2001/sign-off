import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router";

import type { Domain, RunStatus, Severity, SignoffReleaseReview, SignoffRun, Stage } from "../api";
import { api, DOMAIN_LABELS, STAGE_LABELS, STAGES } from "../api";
import { useAuth } from "../components/AuthProvider";
import { RunEvidencePanel } from "../components/RunEvidencePanel";
import { ViolationActions } from "../components/ViolationActions";
import { AgentReviewPanel } from "../components/AgentReviewPanel";
import { ReadyProgress, RunStatusBar } from "../components/charts";
import { Card, Field, StatusBadge } from "../components/ui";
import { defaultSignoffTool, SIGNOFF_TOOLS, signoffTool } from "../signoffTools";

function SignoffPlanEditor({ projectId, stage, readOnly = false }: { projectId: number; stage: Stage; readOnly?: boolean }) {
  const auth = useAuth();
  const qc = useQueryClient();
  const plan = useQuery({ queryKey: ['signoff-plan', projectId], queryFn: () => api.signoffPlan(projectId) });
  const current = plan.data?.stages.find(item => item.stage === stage);
  const [domains, setDomains] = useState<Domain[]>([]);
  const [reason, setReason] = useState('');
  useEffect(() => { if (current) { setDomains(current.required_domains); setReason(''); } }, [current?.stage, current?.version]);
  const update = useMutation({ mutationFn: () => api.updateSignoffPlan(projectId, stage, { expected_version: current?.version ?? 0, required_domains: domains, reason }), onSuccess: async () => { setReason(''); await Promise.all([qc.invalidateQueries({ queryKey: ['signoff-plan', projectId] }), qc.invalidateQueries({ queryKey: ['gate', projectId, stage] })]); } });
  if (plan.isPending) return <p className="text-sm">사인오프 계획 불러오는 중…</p>;
  if (plan.isError || !current) return <p role="alert" className="text-sm">사인오프 계획을 불러오지 못했습니다.</p>;
  return <section className="rounded-lg border border-[var(--border)] p-3 space-y-3" aria-label="프로젝트 사인오프 계획">
    <div><h3 className="font-semibold text-sm">프로젝트 사인오프 계획 · {STAGE_LABELS[stage]}</h3><p className="text-xs text-[var(--text-muted)]">{current.source === 'default' ? '서비스 기본 계획' : `사용자 정의 계획 v${current.version}`} · 필수 도메인 {current.required_domains.map(domain => DOMAIN_LABELS[domain]).join(', ')}</p>{current.reason && <p className="mt-1 text-xs">변경 사유: {current.reason} · {current.updated_by}</p>}</div>
    {auth.can(projectId, 'approver') && !readOnly && <details><summary className="cursor-pointer text-sm font-medium">필수 도메인 편집</summary><div className="mt-3 space-y-3">
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{(Object.keys(DOMAIN_LABELS) as Domain[]).map(domain => <label key={domain} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={domains.includes(domain)} onChange={event => setDomains(values => event.target.checked ? [...values, domain] : values.filter(value => value !== domain))}/>{DOMAIN_LABELS[domain]}</label>)}</div>
      <textarea className="input w-full" rows={2} maxLength={4000} value={reason} onChange={event => setReason(event.target.value)} placeholder="계획 변경 사유" aria-label="사인오프 계획 변경 사유"/>
      <button className="btn btn-primary" disabled={!domains.length || !reason.trim() || update.isPending} onClick={() => update.mutate()}>{update.isPending ? '계획 저장 중…' : '새 계획 버전 저장'}</button>
      <p className="text-xs text-[var(--text-muted)]">변경은 새 버전으로 보존되며 과거 근거와 결정을 수정하지 않습니다. AI는 필수 도메인을 변경하지 않습니다.</p>
      {update.isError && <p role="alert" className="text-sm">{update.error.message}</p>}{update.isSuccess && <p role="status" className="text-sm">사인오프 계획을 저장했습니다.</p>}
    </div></details>}
  </section>;
}

function TargetRevisionEditor({ projectId, stage, readOnly = false }: { projectId: number; stage: Stage; readOnly?: boolean }) {
  const auth = useAuth();
  const qc = useQueryClient();
  const targets = useQuery({ queryKey: ['target-revisions', projectId], queryFn: () => api.targetRevisions(projectId) });
  const revisions = useQuery({ queryKey: ['run-revisions', projectId], queryFn: () => api.runRevisions(projectId) });
  const history = useQuery({ queryKey: ['target-revision-history', projectId, stage], queryFn: () => api.targetRevisionHistory(projectId, stage) });
  const current = targets.data?.stages.find(item => item.stage === stage);
  const [revision, setRevision] = useState('');
  const [reason, setReason] = useState('');
  useEffect(() => { if (current) { setRevision(current.design_revision ?? ''); setReason(''); } }, [current?.stage, current?.version]);
  const update = useMutation({
    mutationFn: () => api.updateTargetRevision(projectId, stage, {
      expected_version: current!.version, design_revision: revision.trim() || null, reason: reason.trim(),
    }),
    onSuccess: async () => {
      setReason('');
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['target-revisions', projectId] }),
        qc.invalidateQueries({ queryKey: ['target-revision-history', projectId, stage] }),
        qc.invalidateQueries({ queryKey: ['gate', projectId, stage] }),
        qc.invalidateQueries({ queryKey: ['signoff-releases', projectId] }),
      ]);
    },
  });
  if (targets.isPending) return <p className="text-sm">목표 리비전 불러오는 중…</p>;
  if (targets.isError || !current) return <p role="alert" className="text-sm">목표 리비전을 불러오지 못했습니다.</p>;
  const changed = (revision.trim() || null) !== current.design_revision;
  return <section className="rounded-lg border border-[var(--border)] p-3 space-y-3" aria-label="스테이지 목표 리비전">
    <div><h3 className="font-semibold text-sm">릴리스 후보 리비전 · {STAGE_LABELS[stage]}</h3><p className="text-xs text-[var(--text-muted)]">{current.design_revision ? `${current.design_revision} · 고정 v${current.version}` : '고정 안 함 · 전체 최신 런 사용'}{current.reason && ` · ${current.updated_by}: ${current.reason}`}</p></div>
    {auth.can(projectId, 'approver') && !readOnly && <div className="space-y-3">
      <Field label="정확한 설계 리비전"><input className="input w-full" list="target-revision-options" maxLength={160} value={revision} onChange={event => setRevision(event.target.value)} placeholder="비우면 고정 해제" /><datalist id="target-revision-options">{(revisions.data?.items ?? []).map(item => <option key={item.design_revision} value={item.design_revision}>{item.run_count}개 런</option>)}</datalist></Field>
      <Field label="변경 사유"><textarea className="input w-full" rows={2} maxLength={4000} value={reason} onChange={event => setReason(event.target.value)} /></Field>
      <button className="btn btn-primary" disabled={!changed || !reason.trim() || update.isPending} onClick={() => update.mutate()}>{update.isPending ? '저장 중…' : revision.trim() ? '목표 리비전 고정' : '목표 리비전 고정 해제'}</button>
      {update.isError && <p role="alert" className="text-sm">{update.error.message}</p>}
      <p className="text-xs text-[var(--text-muted)]">고정하면 게이트·내보내기·승인 패키지는 이 리비전의 최신 런만 사용합니다. 변경은 버전형 이력으로 보존되며 AI가 선택하지 않습니다.</p>
    </div>}
    {history.data?.items.length ? <details><summary className="cursor-pointer text-sm font-medium">최근 목표 변경 이력</summary><ul className="mt-2 space-y-2">{history.data.items.map(item => <li className="rounded border p-2 text-xs" key={item.id}>v{item.version} · {item.design_revision || '고정 해제'} · {item.updated_by} · {item.reason}</li>)}</ul></details> : null}
  </section>;
}

function gateReasonLabel(reason?: string | null) {
  const labels: Record<string, string> = {
    'no run for this stage': '이 단계 검증 미실행',
    'Imported DFT result does not establish full scan and ATPG coverage': 'DFT 전체 검증 범위 미확인',
    'Imported CDC/RDC findings do not establish full crossing coverage': 'CDC/RDC 전체 검증 범위 미확인',
    'RTL requires captured ladder evidence; rerun the analysis': 'RTL 실행 근거 필요 · 재분석 필요',
    'Imported path report does not establish full STA coverage': 'STA 전체 검증 범위 미확인',
    'Imported marker report does not establish full DRC coverage': 'DRC 전체 검증 범위 미확인',
    'Imported LVS result does not establish full LVS coverage': 'LVS 전체 검증 범위 미확인',
    'Imported LEC result does not establish full equivalence coverage': 'LEC 전체 검증 범위 미확인',
    'Captured verification coverage required; manual status is not evidence': '검증 범위 근거 필요 · 수동 상태만으로 통과 불가',
    "latest run status is 'running'": '최신 런 실행 중',
    "latest run status is 'failed'": '최신 런 실패',
    'RTL evidence is failed; required stages must all pass': 'RTL 필수 단계 실패',
    'RTL evidence is running; required stages must all pass': 'RTL 필수 단계 미완료',
  };
  if (!reason) return '미실행';
  const blocking = reason.match(/^(\d+) open blocking violation\(s\)$/);
  const inactiveWaiver = reason.match(/^(\d+) expired or out-of-scope waiver\(s\)$/);
  return inactiveWaiver ? `만료·범위 불일치 웨이버 ${inactiveWaiver[1]}건` : blocking ? `미해결 차단 위반 ${blocking[1]}건` : labels[reason] ?? reason;
}

function mergeRuns(latest: SignoffRun[], older: SignoffRun[]) {
  const seen = new Set<number>();
  return [...latest, ...older].filter(run => {
    if (seen.has(run.id)) return false;
    seen.add(run.id);
    return true;
  });
}

export default function ProjectDetail() {
  const { id } = useParams();
  const projectId = Number(id);
  const auth = useAuth();
  const qc = useQueryClient();
  const [stage, setStage] = useState<Stage>("placement");
  const [olderRuns, setOlderRuns] = useState<SignoffRun[]>([]);
  const [olderCursor, setOlderCursor] = useState<number | null | undefined>(undefined);
  const [runFilters, setRunFilters] = useState<{ domain?: Domain; stage?: Stage; status?: RunStatus; revisionScope?: 'all' | 'labeled' | 'unlabeled' }>({});
  const [toolQuery, setToolQuery] = useState('');
  const [appliedToolQuery, setAppliedToolQuery] = useState('');
  const [revisionQuery, setRevisionQuery] = useState('');
  const [releaseReview, setReleaseReview] = useState<SignoffReleaseReview | null>(null);
  const [appliedRevisionQuery, setAppliedRevisionQuery] = useState('');
  const runFilterKey = JSON.stringify({ ...runFilters, q: appliedToolQuery, revision: appliedRevisionQuery });
  const runFilterKeyRef = useRef(runFilterKey);
  runFilterKeyRef.current = runFilterKey;
  useEffect(() => { setOlderRuns([]); setOlderCursor(undefined); }, [runFilterKey]);
  const [releaseReason, setReleaseReason] = useState("");
  const [releasePassword, setReleasePassword] = useState('');
  const [lifecycleReason, setLifecycleReason] = useState('');
  const project = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.getProject(projectId),
  });
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
  const evidencePackage = useMutation({
    mutationFn: (input: { projectId: number; stage: Stage }) => api.exportSignoffPackage(input.projectId, input.stage),
    onSuccess: (blob, input) => {
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `project-${input.projectId}-${input.stage}-evidence.zip`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
  });
  const releases = useInfiniteQuery({
    queryKey: ['signoff-releases', projectId],
    queryFn: ({ pageParam }) => api.signoffReleases(projectId, pageParam),
    initialPageParam: null as number | null,
    getNextPageParam: page => page.next_before_id ?? undefined,
    refetchInterval: project.data?.archived_at ? false : 5000,
  });
  const releaseAudit = useQuery({
    queryKey: ['signoff-release-audit', projectId],
    queryFn: () => api.signoffReleaseAudit(projectId),
    refetchInterval: project.data?.archived_at ? false : 5000,
  });
  const releaseLedger = useMutation({
    mutationFn: () => api.exportSignoffReleaseLedger(projectId),
    onSuccess: blob => {
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `project-${projectId}-decision-ledger.json`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
  });
  const prepareReleaseReview = useMutation({
    mutationFn: () => api.signoffReleaseReview(projectId, stage),
    onSuccess: review => setReleaseReview(review),
  });
  const releaseDecision = useMutation({
    mutationFn: (decision: 'approved' | 'rejected') => api.createSignoffRelease(projectId, {
      stage, decision, reason: releaseReason,
      ...(decision === 'approved' && releaseReview ? { expected_evidence_sha256: releaseReview.evidence_snapshot_sha256 } : {}),
      ...(auth.state.mode === 'required' ? { confirmation_password: releasePassword } : {}),
    }),
    onSuccess: async () => {
      setReleaseReason('');
      setReleaseReview(null);
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['signoff-releases', projectId] }),
        qc.invalidateQueries({ queryKey: ['signoff-release-audit', projectId] }),
      ]);
    },
    onSettled: () => setReleasePassword(''),
  });
  useEffect(() => { setReleaseReview(null); }, [stage]);
  const archivedPackage = useMutation({
    mutationFn: (releaseId: number) => api.downloadSignoffRelease(projectId, releaseId),
    onSuccess: (blob, releaseId) => {
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `project-${projectId}-decision-${releaseId}.zip`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
  });

  const lifecycleHistory = useQuery({
    queryKey: ['project-lifecycle-history', projectId], queryFn: () => api.projectLifecycleHistory(projectId),
    enabled: auth.can(projectId, 'owner'),
  });
  const lifecycle = useMutation({
    mutationFn: (archived: boolean) => api.updateProjectLifecycle(projectId, {
      expected_version: project.data!.lifecycle_version, archived, reason: lifecycleReason.trim(),
    }),
    onSuccess: async () => {
      setLifecycleReason('');
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['project', projectId] }),
        qc.invalidateQueries({ queryKey: ['project-lifecycle-history', projectId] }),
        qc.invalidateQueries({ queryKey: ['project-summary-page'] }),
        qc.invalidateQueries({ queryKey: ['projects'] }),
      ]);
    },
  });
  // 5s polling keeps runs and gate status live while ladders execute elsewhere
  const runs = useQuery({
    queryKey: ["runs-page", projectId, runFilters, appliedToolQuery],
    queryFn: () => api.runPage(projectId, { ...runFilters, q: appliedToolQuery || undefined, revision: appliedRevisionQuery || undefined }),
    refetchInterval: project.data?.archived_at ? false : 5000,
  });
  const runRevisions = useQuery({
    queryKey: ['run-revisions', projectId], queryFn: () => api.runRevisions(projectId),
  });
  const loadOlderRuns = useMutation({
    mutationFn: ({ beforeId }: { beforeId: number; filterKey: string }) => api.runPage(projectId, {
      ...runFilters, q: appliedToolQuery || undefined, beforeId,
      revision: appliedRevisionQuery || undefined,
    }),
    onSuccess: (page, variables) => {
      if (variables.filterKey !== runFilterKeyRef.current) return;
      setOlderRuns(current => {
        const items = new Map(current.map(item => [item.id, item]));
        for (const item of page.items) items.set(item.id, item);
        return [...items.values()].sort((a, b) => b.id - a.id);
      });
      setOlderCursor(page.next_before_id);
    },
  });
  const gate = useQuery({
    queryKey: ["gate", projectId, stage],
    queryFn: () => api.gateStatus(projectId, stage),
    refetchInterval: project.data?.archived_at ? false : 5000,
  });

  const invalidate = () => {
    setOlderRuns([]);
    setOlderCursor(undefined);
    qc.invalidateQueries({ queryKey: ["runs-page", projectId] });
    qc.invalidateQueries({ queryKey: ["gate", projectId] });
  };

  // A5 사인오프 종합 판정관 -> V 검증 에이전트: chained, only when the gate
  // for this stage isn't ready (see backend/app/hermes.py trigger_ko).
  const gateReview = useQuery({
    queryKey: ["agent-review-gate", projectId, stage, gate.data],
    queryFn: () => api.reviewGate({ gate_status: gate.data }),
    enabled: !!gate.data && !project.data?.archived_at,
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
  const releaseItems = releases.data?.pages.flatMap(page => page.items) ?? [];

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-xl font-bold">{p.name}</h1>
        <span className="text-sm" style={{ color: "var(--text-muted)" }}>
          {p.process_node} · {p.foundry}
        </span>
        <Link className="btn btn-primary" to={`/projects/${projectId}/violations`}>전체 위반 검토</Link>
        <Link className="btn btn-ghost" to={`/projects/${projectId}/compare`}>런 비교</Link>
        <Link className="btn btn-ghost" to={`/projects/${projectId}/sta-matrix`}>STA 시나리오 매트릭스</Link>
        <Link className="btn btn-ghost" to={`/projects/${projectId}/revision-coverage`}>리비전 검증 매트릭스</Link>
        {auth.can(projectId, "editor") && !p.archived_at && <Link className="btn btn-ghost" to={`/projects/${projectId}/import`}>보고서 가져오기</Link>}
        {auth.state.mode === "required" && auth.can(projectId, "owner") && <Link className="btn btn-ghost" to={`/projects/${projectId}/members`}>접근 권한</Link>}
        {auth.can(projectId, "owner") && <Link className="btn btn-ghost" to={`/projects/${projectId}/collectors`}>수집기 자격증명</Link>}
      </header>

      {p.archived_at && <p role="status" className="rounded-lg border border-[var(--status-warning)] p-3">이 프로젝트는 보관 상태이며 모든 쓰기 작업과 수집기 제출이 차단됩니다. 기존 근거·결정·감사 이력은 계속 조회할 수 있습니다.</p>}

      {auth.can(projectId, 'owner') && <Card title="프로젝트 수명주기" subtitle="완료된 설계를 삭제하지 않고 운영 목록에서 보관합니다">
        <div className="space-y-3">
          <p className="text-sm">현재 상태: <strong>{p.archived_at ? '보관됨' : '활성'}</strong> · 버전 {p.lifecycle_version}{p.archived_at && ` · ${p.archived_by ?? '알 수 없음'} · ${new Date(p.archived_at).toLocaleString()}`}</p>
          <Field label={p.archived_at ? '복원 사유' : '보관 사유'}><textarea className="input w-full" rows={2} maxLength={2000} value={lifecycleReason} onChange={event => setLifecycleReason(event.target.value)} /></Field>
          <button className={p.archived_at ? 'btn btn-primary' : 'btn btn-ghost'} disabled={!lifecycleReason.trim() || lifecycle.isPending} onClick={() => lifecycle.mutate(!p.archived_at)}>{lifecycle.isPending ? '처리 중…' : p.archived_at ? '활성 프로젝트로 복원' : '프로젝트 보관'}</button>
          {!p.archived_at && <p className="text-xs text-[var(--text-muted)]">실행 중인 런이나 STA 배치가 있으면 보관할 수 없습니다. 보관 후 모든 쓰기와 자동 수집이 중단됩니다.</p>}
          {lifecycle.isError && <p role="alert" className="text-sm">{lifecycle.error.message}</p>}
          <details><summary className="cursor-pointer text-sm font-medium">보관·복원 이력</summary>{lifecycleHistory.isPending ? <p>이력 불러오는 중…</p> : lifecycleHistory.isError ? <p role="alert">{lifecycleHistory.error.message}</p> : lifecycleHistory.data.items.length === 0 ? <p className="text-sm">아직 변경 이력이 없습니다.</p> : <ul className="mt-2 space-y-2">{lifecycleHistory.data.items.map(item => <li key={item.id} className="rounded border p-2 text-sm">v{item.version} · {item.after_state === 'archived' ? '보관' : '복원'} · {item.actor} · {new Date(item.created_at).toLocaleString()}<p>{item.reason}</p></li>)}</ul>}</details>
          <p className="text-xs text-[var(--text-muted)]">보관·복원 판단에는 AI가 개입하지 않습니다.</p>
        </div>
      </Card>}

      <Card
        title="Shift-left 스테이지 게이트"
        subtitle="도메인별 최신 런의 검증 범위와 설계 리비전을 확인합니다. 수동 통과 상태만으로는 게이트를 통과할 수 없습니다."
      >
        <SignoffPlanEditor key={stage} projectId={projectId} stage={stage} readOnly={!!p.archived_at} />
        <div className="mt-3"><TargetRevisionEditor key={`target-${stage}`} projectId={projectId} stage={stage} readOnly={!!p.archived_at} /></div>
        <div className="mb-4 mt-4 space-y-2 text-sm">
          <div className="flex flex-wrap gap-2">
            <button className="btn btn-primary" disabled={evidencePackage.isPending} onClick={() => evidencePackage.mutate({ projectId, stage })}>{evidencePackage.isPending ? `${STAGE_LABELS[evidencePackage.variables.stage]} 패키지 준비 중…` : '검증된 근거 패키지 다운로드'}</button>
            <button className="btn btn-ghost" disabled={gateExport.isPending} onClick={() => gateExport.mutate({ projectId, stage })}>{gateExport.isPending ? `${STAGE_LABELS[gateExport.variables.stage]} 근거 파일 준비 중…` : '게이트 JSON 다운로드'}</button>
          </div>
          <p className="text-[var(--text-muted)]">근거 패키지는 현재 게이트가 선택한 최신 런의 원본 보고서를 SHA-256으로 검증해 매니페스트와 함께 ZIP으로 보존합니다. 원본이나 저장 해시가 없거나 변조되었으면 생성을 거부합니다.</p>
          <p className="text-[var(--text-muted)]">게이트 JSON은 다운로드 시점의 판정·최신 런·현재 위반과 웨이버를 포함하며 원본 파일은 제외합니다. JSON 최대 8 MiB, 패키지 최대 32 MiB, 위반 10,000건.</p>
          {evidencePackage.variables?.projectId === projectId && evidencePackage.variables.stage === stage && evidencePackage.isError && <p role="alert">{evidencePackage.error.message}</p>}
          {evidencePackage.variables?.projectId === projectId && evidencePackage.variables.stage === stage && evidencePackage.isSuccess && <p role="status">검증된 근거 패키지 다운로드를 시작했습니다.</p>}
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
            <section className="rounded-lg border border-[var(--border)] p-3 space-y-3" aria-label="사인오프 결정 기록">
              <div>
                <h3 className="font-semibold text-sm">사람의 사인오프 결정</h3>
                <p className="mt-1 text-xs text-[var(--text-muted)]">승인자만 결정할 수 있습니다. 서버가 현재 근거 패키지를 다시 검증해 결정과 함께 불변 보관하며 AI는 승인·거절에 개입하지 않습니다.</p>
                {releaseAudit.data && <p className="mt-1 break-all text-xs text-[var(--status-good)]">결정 체인 검증 완료 · {releaseAudit.data.decision_count}건 · 헤드 {releaseAudit.data.chain_head_sha256 || '기록 없음'}</p>}
                {releaseAudit.isError && <p role="alert" className="mt-1 text-xs text-[var(--status-critical)]">결정 감사 체인 검증 실패: {releaseAudit.error.message}</p>}
                <button className="btn btn-ghost mt-2" disabled={releaseLedger.isPending || releaseAudit.isError} onClick={() => releaseLedger.mutate()}>{releaseLedger.isPending ? '감사 원장 생성 중…' : '검증 가능한 감사 원장 내보내기'}</button>
                {releaseLedger.isError && <p role="alert" className="mt-1 text-xs text-[var(--status-critical)]">{releaseLedger.error.message}</p>}
              </div>
              {auth.can(projectId, 'approver') && !p.archived_at && <div className="space-y-2">
                <textarea className="input w-full" rows={2} maxLength={4000} value={releaseReason} onChange={event => setReleaseReason(event.target.value)} placeholder="결정 사유" aria-label="사인오프 결정 사유" />
                {auth.state.mode === 'required' && <label className="block text-sm">전자서명 비밀번호 확인<input className="input mt-1 w-full" type="password" autoComplete="current-password" maxLength={256} value={releasePassword} onChange={event => setReleasePassword(event.target.value)} placeholder="현재 계정 비밀번호" /></label>}
                <div className="flex flex-wrap items-center gap-2">
                  <button className="btn btn-ghost" disabled={prepareReleaseReview.isPending} onClick={() => prepareReleaseReview.mutate()}>{prepareReleaseReview.isPending ? '근거 확인 중…' : '현재 승인 근거 검토'}</button>
                  {releaseReview && <span className="break-all text-xs text-[var(--text-muted)]">검토 SHA-256 {releaseReview.evidence_snapshot_sha256}</span>}
                </div>
                <div className="flex flex-wrap gap-2">
                  <button className="btn btn-primary" disabled={!gate.data.ready || !gate.data.target_revision.design_revision || !releaseReview || !releaseReview.gate.ready || !releaseReason.trim() || (auth.state.mode === 'required' && !releasePassword) || releaseDecision.isPending} onClick={() => releaseDecision.mutate('approved')}>게이트 승인·동결</button>
                  <button className="btn btn-ghost" disabled={!releaseReason.trim() || (auth.state.mode === 'required' && !releasePassword) || releaseDecision.isPending} onClick={() => releaseDecision.mutate('rejected')}>차단 결정·동결</button>
                </div>
                {!gate.data.ready && <p className="text-xs text-[var(--text-muted)]">현재 게이트가 차단되어 승인은 사용할 수 없습니다. 근거를 보완하거나 차단 결정을 기록하세요.</p>}
                {gate.data.ready && !gate.data.target_revision.design_revision && <p className="text-xs text-[var(--text-muted)]">승인 전에 위에서 이 스테이지의 릴리스 후보 리비전을 고정하세요.</p>}
                {gate.data.ready && gate.data.target_revision.design_revision && !releaseReview && <p className="text-xs text-[var(--text-muted)]">승인할 근거를 명시적으로 검토해 스냅샷 해시를 고정하세요.</p>}
                {prepareReleaseReview.isError && <p role="alert" className="text-sm text-[var(--status-critical)]">{prepareReleaseReview.error.message}</p>}
                {releaseDecision.isError && <p role="alert" className="text-sm text-[var(--status-critical)]">{releaseDecision.error.message}</p>}
                {releaseDecision.isSuccess && <p role="status" className="text-sm">결정과 근거 패키지를 보관했습니다.</p>}
              </div>}
              {releaseItems.length ? <ul className="space-y-2">
                {releaseItems.map(item => <li key={item.id} className="rounded-md border border-[var(--grid-hairline)] p-2 text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge status={item.decision === 'approved' ? 'good' : 'critical'} label={item.decision === 'approved' ? '승인' : '차단'} />
                    <StatusBadge status={item.lifecycle_status === 'current' ? 'good' : 'warning'} label={{ current: '현재 근거와 일치', evidence_changed: '근거 변경 · 재결정 필요', superseded_by_decision: '후속 결정으로 대체됨', legacy_unbound: '기존 기록 · 현재성 미확인' }[item.lifecycle_status]} />
                    <strong>{STAGE_LABELS[item.stage]}</strong>
                    <span>{item.decided_by} · {new Date(item.created_at).toLocaleString()}</span>
                    <button className="btn btn-ghost" disabled={archivedPackage.isPending} onClick={() => archivedPackage.mutate(item.id)}>보관 패키지</button>
                  </div>
                  <p className="mt-1 break-words">{item.reason}</p>
                  <p className="mt-1 break-all text-[var(--text-muted)]">리비전 {item.design_revision || '미확정'} · 패키지 SHA-256 {item.package_sha256}{item.chain_version ? ` · 결정 체인 v${item.chain_version}` : ' · 기존 비연결 기록'}{item.credential_confirmed_at ? ` · 비밀번호 재확인 ${new Date(/[Zz]|[+-]\d\d:\d\d$/.test(item.credential_confirmed_at) ? item.credential_confirmed_at : `${item.credential_confirmed_at}Z`).toLocaleString()}` : ' · 자격 증명 재확인 기록 없음'}</p>
                  {item.lifecycle_status === 'evidence_changed' && <p className="mt-1 text-[var(--status-warning)]">현재 런·웨이버·사인오프 계획이 이 결정의 동결 근거와 다릅니다. 현재 게이트를 다시 검토해 새 결정을 기록하세요.</p>}
                </li>)}
              </ul> : <p className="text-xs text-[var(--text-muted)]">기록된 사인오프 결정이 없습니다.</p>}
              {releases.hasNextPage && <button className="btn btn-ghost" disabled={releases.isFetchingNextPage} onClick={() => void releases.fetchNextPage()}>{releases.isFetchingNextPage ? '이전 결정 불러오는 중…' : '이전 결정 더 보기'}</button>}
              {archivedPackage.isError && <p role="alert" className="text-sm text-[var(--status-critical)]">{archivedPackage.error.message}</p>}
            </section>
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
            {!p.archived_at ? <div className="pt-3">
              <h3 className="font-semibold text-sm">에이전트 검토 흐름 · A5 종합 → V 검증</h3>
              <p className="mt-1 text-xs text-[var(--text-muted)]">선택한 스테이지의 현재 게이트 근거를 검토합니다. 두 역할의 결과는 함께 표시되며, 승인·웨이버는 사람이 별도로 결정합니다.</p>
              <AgentReviewPanel role="a5_synth" scope={STAGE_LABELS[stage]} review={gateReview.data?.a5} loading={gateReview.isFetching} failed={gateReview.isError} onRetry={() => void gateReview.refetch()} retryLabel="종합·검증 다시 시도" />
              <AgentReviewPanel role="v_verify" scope={STAGE_LABELS[stage]} review={gateReview.data?.v} loading={gateReview.isFetching} waitingLabel={gateReview.isError ? '진행 확인 불가' : gateReview.data?.a5.available === false ? '선행 검토 미완료' : gateReview.data?.a5.triggered === false ? '조건 미해당 · 실행 안 됨' : '실행 전'} waiting={gateReview.isError ? '요청 결과를 받지 못해 V의 실행 여부를 확인할 수 없습니다.' : gateReview.data?.a5.available === false ? '선행 검토 미완료 · A5 의견이 없어 V는 실행되지 않았습니다.' : gateReview.data?.a5.triggered === false ? '게이트가 통과 가능하여 A5와 V를 실행하지 않았습니다.' : 'A5 종합 검토가 완료되면 원본 근거와 대조합니다.'} onRetry={() => void gateReview.refetch()} retryLabel="종합·검증 다시 시도" />
            </div> : <p className="pt-3 text-xs text-[var(--text-muted)]">보관 프로젝트에서는 자동 검토를 새로 실행하지 않습니다. 기존 런의 저장된 검토 이력은 런 워크스페이스에서 확인할 수 있습니다.</p>}
          </div>
        )}
      </Card>

      <Card title="런 이력 필터" subtitle="도메인·단계·상태와 툴 이름으로 서버에서 런 이력을 좁힙니다.">
        <form className="flex flex-wrap items-end gap-3" onSubmit={event => { event.preventDefault(); setAppliedToolQuery(toolQuery.trim()); setAppliedRevisionQuery(revisionQuery.trim()); }}>
          <Field label="도메인"><select className="input" value={runFilters.domain ?? ''} onChange={event => setRunFilters(current => ({ ...current, domain: event.target.value ? event.target.value as Domain : undefined }))}><option value="">전체</option>{Object.entries(DOMAIN_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
          <Field label="스테이지"><select className="input" value={runFilters.stage ?? ''} onChange={event => setRunFilters(current => ({ ...current, stage: event.target.value ? event.target.value as Stage : undefined }))}><option value="">전체</option>{STAGES.map(value => <option key={value} value={value}>{STAGE_LABELS[value]}</option>)}</select></Field>
          <Field label="상태"><select className="input" value={runFilters.status ?? ''} onChange={event => setRunFilters(current => ({ ...current, status: event.target.value ? event.target.value as RunStatus : undefined }))}><option value="">전체</option><option value="passed">통과</option><option value="failed">실패</option><option value="running">실행 중</option><option value="incomplete">검증 미완료</option></select></Field>
          <Field label="툴 이름"><input className="input" maxLength={80} value={toolQuery} onChange={event => setToolQuery(event.target.value)} placeholder="예: PrimeTime" /></Field>
          <Field label="리비전 범위"><select className="input" value={runFilters.revisionScope ?? 'all'} onChange={event => { const revisionScope = event.target.value as 'all' | 'labeled' | 'unlabeled'; setRunFilters(current => ({ ...current, revisionScope })); if (revisionScope === 'unlabeled') { setRevisionQuery(''); setAppliedRevisionQuery(''); } }}><option value="all">전체</option><option value="labeled">리비전 기록 있음</option><option value="unlabeled">리비전 미기록</option></select></Field>
          <Field label="정확한 설계 리비전"><input className="input" list="run-revision-options" maxLength={160} disabled={runFilters.revisionScope === 'unlabeled'} value={revisionQuery} onChange={event => setRevisionQuery(event.target.value)} placeholder="예: git SHA / netlist tag" /><datalist id="run-revision-options">{(runRevisions.data?.items ?? []).map(item => <option key={item.design_revision} value={item.design_revision}>{item.run_count}개 런</option>)}</datalist></Field>
          <button className="btn btn-primary">검색</button>
          <button type="button" className="btn btn-ghost" onClick={() => { setRunFilters({}); setToolQuery(''); setAppliedToolQuery(''); setRevisionQuery(''); setAppliedRevisionQuery(''); }}>초기화</button>
        </form>
        {runRevisions.data && <p className="mt-2 text-xs text-[var(--text-muted)]">기록된 리비전 {runRevisions.data.total}개 · 리비전 미기록 런 {runRevisions.data.unlabeled_runs}개{runRevisions.data.total > runRevisions.data.items.length ? ' · 최근 100개를 자동완성에 표시' : ''}</p>}
      </Card>
      <RunsCard projectId={projectId}
        runs={mergeRuns(runs.data?.items ?? [], olderRuns)}
        total={runs.data?.total ?? 0} statusCounts={runs.data?.status_counts}
        loading={runs.isPending} error={runs.error?.message}
        hasMore={(olderCursor === undefined ? runs.data?.next_before_id : olderCursor) != null}
        loadingMore={loadOlderRuns.isPending} loadError={loadOlderRuns.error?.message}
        onLoadMore={() => { const cursor = olderCursor === undefined ? runs.data?.next_before_id : olderCursor; if (cursor) loadOlderRuns.mutate({ beforeId: cursor, filterKey: runFilterKey }); }}
        onChange={invalidate} readOnly={!!p.archived_at} />
    </div>
  );
}

function RunsCard({
  projectId,
  runs,
  total,
  statusCounts,
  loading,
  error,
  hasMore,
  loadingMore,
  loadError,
  onLoadMore,
  onChange,
  readOnly,
}: {
  projectId: number;
  runs: SignoffRun[];
  total: number;
  statusCounts?: Record<'passed' | 'failed' | 'running' | 'incomplete', number>;
  loading: boolean;
  error?: string;
  hasMore: boolean;
  loadingMore: boolean;
  loadError?: string;
  onLoadMore: () => void;
  onChange: () => void;
  readOnly: boolean;
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

  const counts = statusCounts ?? { passed: 0, failed: 0, running: 0, incomplete: 0 };

  return (
    <Card title="사인오프 런" subtitle="도메인별 런 생성 · 상태 갱신 · 위반/웨이버 관리">
      <div className="mb-4">
        <RunStatusBar counts={counts} />
        <p className="mt-2 text-xs text-[var(--text-muted)]">전체 {total}개 중 최신 {runs.length}개 표시</p>
      </div>
      {loading && <p role="status" className="mb-3 text-sm">런 이력 불러오는 중…</p>}
      {error && <p role="alert" className="mb-3 text-sm">{error}</p>}
      {!readOnly && <form
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
      </form>}

      <section id="run-tool-help" aria-label="선택한 툴 안내" className="mb-4 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-3 text-sm space-y-1">
        <p className="font-semibold">{selectedTool.label}</p>
        <p>{selectedTool.description}</p>
        <p className="text-xs text-[var(--text-secondary)]">{selectedTool.workflow} 여기서 런을 생성하면 툴을 실행하지 않고 수동 런의 출처만 기록하며, 검증 근거가 없어 게이트를 통과시키지 않습니다.</p>
        {form.domain === 'dft' && <Link className="text-xs underline" to={`/projects/${projectId}/import/commercial-dft`}>TestMAX / Tessent / Modus DFT 결과 가져오기로 이동</Link>}
        {form.domain === 'low_power' && <Link className="text-xs underline" to={`/projects/${projectId}/import/commercial-low-power`}>VC LP / Conformal Low Power 결과 가져오기로 이동</Link>}
        {form.domain === 'cdc' && <Link className="text-xs underline" to={`/projects/${projectId}/import/commercial-cdc`}>VC SpyGlass / Jasper CDC·RDC 결과 가져오기로 이동</Link>}
        {form.domain === 'rtl' && <Link className="text-xs underline" to="/analysis#rtl">RTL 분석 실행으로 이동</Link>}
        {(form.domain === 'sta' || form.domain === 'pv') && <Link className="text-xs underline" to={`/projects/${projectId}/import${form.domain === 'pv' ? '/klayout' : ''}`}>{form.domain === 'sta' ? 'OpenSTA' : 'KLayout DRC'} 보고서 가져오기로 이동</Link>}
        {form.domain === 'lec' && <Link className="text-xs underline" to={`/projects/${projectId}/import/commercial-lec`}>Formality / Conformal LEC 결과 가져오기로 이동</Link>}
        {form.domain === 'lvs' && <Link className="text-xs underline" to={`/projects/${projectId}/import/commercial-lvs`}>Calibre / Pegasus LVS 결과 가져오기로 이동</Link>}
      </section>

      {create.isError && <p role="alert">{create.error.message}</p>}
      {runs.length === 0 ? (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          아직 런이 없습니다.
        </p>
      ) : (
        <ul className="space-y-3">
          {runs.map((run) => (
            <RunRow key={run.id} run={run} onChange={onChange} readOnly={readOnly} />
          ))}
        </ul>
      )}
      {hasMore && <button className="btn btn-ghost mt-4" disabled={loadingMore} onClick={onLoadMore}>{loadingMore ? '이전 런 불러오는 중…' : '이전 런 더 보기'}</button>}
      {loadError && <p role="alert" className="mt-2">{loadError}</p>}
    </Card>
  );
}

function RunRow({ run, onChange, readOnly }: { run: SignoffRun; onChange: () => void; readOnly: boolean }) {
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
            {STAGE_LABELS[run.stage]} · {run.tool} · run #{run.id} · 리비전 {run.design_revision || '미기록'}
          </span>
          <StatusBadge
            status={
              run.status === "passed" ? "good" : run.status === "failed" ? "critical" : "warning"
            }
            label={run.status === "incomplete" ? "검증 미완료" : run.status}
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <Link className="btn btn-ghost" to={`/runs/${run.id}`}>런 워크스페이스</Link>
          {(run.evidence_source === 'opensta_report' || run.evidence_source === 'opensta_execution' || run.evidence_source === 'commercial_sta_report') && <Link className="btn btn-ghost" to={`/runs/${run.id}/paths`}>타이밍 경로</Link>}
          {(run.evidence_source === 'klayout_report' || run.evidence_source === 'commercial_drc_report') && <Link className="btn btn-ghost" to={`/runs/${run.id}/markers`}>DRC 마커 탐색</Link>}
          {run.evidence_source === 'commercial_emir_report' && <Link className="btn btn-ghost" to={`/runs/${run.id}/power-integrity`}>EM/IR 핫스폿</Link>}
          {run.evidence_source === 'commercial_power_report' && <Link className="btn btn-ghost" to={`/runs/${run.id}/power-breakdown`}>전력 계층</Link>}
          {run.evidence_source === 'commercial_thermal_report' && <Link className="btn btn-ghost" to={`/runs/${run.id}/thermal-hotspots`}>열 핫스폿</Link>}
          {run.evidence_source === 'commercial_rtl_report' && <Link className="btn btn-ghost" to={`/runs/${run.id}/rtl-regression`}>RTL 회귀</Link>}
          {run.evidence_source === 'commercial_dft_report' && <Link className="btn btn-ghost" to={`/runs/${run.id}/dft-findings`}>DFT finding</Link>}
          {run.evidence_source === 'commercial_low_power_report' && <Link className="btn btn-ghost" to={`/runs/${run.id}/low-power-findings`}>저전력 finding</Link>}
          {run.evidence_source === 'commercial_cdc_report' && <Link className="btn btn-ghost" to={`/runs/${run.id}/cdc-findings`}>CDC·RDC finding</Link>}
          {run.evidence_source === 'commercial_lec_report' && <Link className="btn btn-ghost" to={`/runs/${run.id}/lec-failures`}>LEC 실패</Link>}
          {run.evidence_source === 'commercial_lvs_report' && <Link className="btn btn-ghost" to={`/runs/${run.id}/lvs-mismatches`}>LVS 불일치</Link>}
          <button className="btn btn-ghost" disabled={readOnly || !auth.can(run.project_id, "editor") || update.isPending || run.result_locked} title={readOnly ? '보관 프로젝트는 읽기 전용입니다' : run.result_locked ? "서버 분석 결과는 다시 실행하여 갱신하세요" : "수동 상태 변경"} onClick={() => update.mutate("passed")}>
            Pass
          </button>
          <button className="btn btn-ghost" disabled={readOnly || !auth.can(run.project_id, "editor") || update.isPending || run.result_locked} title={readOnly ? '보관 프로젝트는 읽기 전용입니다' : run.result_locked ? "서버 분석 결과는 다시 실행하여 갱신하세요" : "수동 상태 변경"} onClick={() => update.mutate("failed")}>
            Fail
          </button>
          <button className="btn btn-ghost" onClick={() => setOpen((v) => !v)}>
            위반 {open ? "접기" : "보기"}
          </button>
        </div>
      </div>
      {update.isError && <p role="alert">{update.error.message}</p>}
      <RunEvidencePanel run={run} />
      {open && <ViolationList locked={run.result_locked || readOnly} runId={run.id} onChange={onChange} />}
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
