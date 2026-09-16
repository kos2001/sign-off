import { useParams } from "react-router";
import { useAuth } from "./AuthProvider";
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, type Violation, type ViolationStatus } from "../api";
import { Field, StatusBadge } from "./ui";
import { useReviewDraft } from "./ReviewDrafts";

const labels: Record<ViolationStatus, string> = { open: "미해결", fixed: "수정 완료", waived: "웨이버 승인" };

export function ViolationActions({ violation: v, onChange, projectId: explicitProjectId }: { violation: Violation; onChange: () => void; projectId?: number }) {
  const qc = useQueryClient();
  const auth = useAuth();
  const routeProjectId = Number(useParams().id);
  const projectId = explicitProjectId ?? routeProjectId;
  const canEdit = auth.can(projectId, "editor");
  const canApprove = auth.can(projectId, "approver");
  const account = auth.state.user?.username;
  const [{ target, reviewVersion, reviewStatus, actor, reason }, updateDraft] = useReviewDraft(v);
  const [showHistory, setShowHistory] = useState(false);
  const [historySearch, setHistorySearch] = useState('');
  const [historyQuery, setHistoryQuery] = useState('');
  const [historyStatus, setHistoryStatus] = useState('');
  useEffect(() => { setHistorySearch(''); setHistoryQuery(''); setHistoryStatus(''); }, [v.id]);
  const historyFilters = { q: historyQuery, to_status: historyStatus };
  const history = useInfiniteQuery({
    queryKey: ["violation-history", v.id, 'pages', historyFilters],
    initialPageParam: null as { before_id: number; snapshot_max_id: number } | null,
    queryFn: ({ pageParam }) => api.violationHistoryPage(v.id, pageParam, historyFilters),
    getNextPageParam: page => page.next_before_id === null ? undefined : { before_id: page.next_before_id, snapshot_max_id: page.snapshot_max_id },
    enabled: showHistory,
  });
  const historyItems = history.data?.pages.flatMap(page => page.items) ?? [];
  function filterHistory(q: string, to_status: string) {
    if (q === historyQuery && to_status === historyStatus) { void history.refetch(); return; }
    qc.removeQueries({ queryKey: ['violation-history', v.id, 'pages', { q, to_status }], exact: true });
    setHistoryQuery(q);
    setHistoryStatus(to_status);
  }
  const download = useMutation({
    mutationFn: (id: number) => api.exportViolationHistory(id),
    onSuccess: ({ bundle, content }) => {
      const url = URL.createObjectURL(new Blob([content], { type: 'application/json' }));
      const link = document.createElement('a');
      link.href = url;
      link.download = `violation-${bundle.violation.id}-history.json`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
  });
  const change = useMutation({
    mutationFn: () => api.transitionViolation(v.id, {
      expected_status: reviewStatus, expected_version: reviewVersion,
      status: target!, actor: account ?? actor.trim(), reason: reason.trim(),
    }),
    onSuccess: () => {
      updateDraft({ target: null, reason: "" });
      qc.invalidateQueries({ queryKey: ["violation-history", v.id] });
      onChange();
    },
    onError: () => onChange(),
  });
  const start = (status: ViolationStatus) => {
    change.reset();
    updateDraft({ reviewVersion: v.version, reviewStatus: v.status, target: status });
  };
  const stale = target !== null && reviewVersion !== v.version;
  return (
    <div className="space-y-3">
      {v.description && <p className="text-xs whitespace-pre-wrap">{v.description}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={v.status === "open" ? "warning" : "good"} label={labels[v.status]} />
        {v.status === "open" ? <>
          <button className="btn btn-ghost" disabled={!canEdit || change.isPending || stale} onClick={() => start("fixed")}>수정 완료 처리</button>
          <button className="btn btn-ghost" disabled={!canApprove || change.isPending || stale} onClick={() => start("waived")}>웨이버 검토</button>
        </> : <button className="btn btn-ghost" disabled={!(v.status === "waived" ? canApprove : canEdit) || change.isPending || stale} onClick={() => start("open")}>재오픈</button>}
        <button className="btn btn-ghost" aria-expanded={showHistory} onClick={() => setShowHistory(!showHistory)}>변경 이력</button>
      </div>
      {v.waiver && <p className="text-xs whitespace-pre-wrap">{v.waiver.approved_by} · {v.waiver.reason}</p>}
      {target && <form className="rounded-lg bg-[var(--surface-1)] p-3 space-y-3" onSubmit={e => { e.preventDefault(); if (!stale && !change.isPending) change.mutate(); }}>
        <p className="font-medium">{labels[reviewStatus]} → {labels[target]}</p>
        {account ? <p className="text-sm">처리 계정: {account}</p> : <Field label="처리자 이름 (직접 입력)"><input className="input" required maxLength={80} value={actor} disabled={change.isPending} onChange={e => updateDraft({ actor: e.target.value })} /></Field>}
        <Field label={target === "fixed" ? "수정 근거 · 검증 결과" : "처리 사유"}><textarea autoFocus className="input w-full" required maxLength={4000} rows={3} value={reason} disabled={change.isPending} onChange={e => updateDraft({ reason: e.target.value })} /></Field>
        {target === "open" && <p className="text-xs">웨이버가 있으면 해제되며, 차단 위반은 게이트에 다시 반영됩니다.</p>}
        {change.isError && !stale && <p role="alert" className="text-xs text-[var(--status-critical)]">{change.error.message}</p>}
        {stale && <div role="alert" className="space-y-2 text-xs">
          <p>다른 검토자가 이 항목을 변경했습니다. 변경 이력을 확인한 뒤 다시 처리하세요. 작성한 사유는 유지됩니다.</p>
          <button type="button" className="btn btn-ghost" onClick={() => { setShowHistory(true); updateDraft({ target: null }); change.reset(); qc.invalidateQueries({ queryKey: ["violation-history", v.id] }); }}>변경 내용 확인</button>
        </div>}
        <div className="flex gap-2">
          <button className="btn btn-primary" disabled={change.isPending || stale || !(account ?? actor.trim()) || !reason.trim()}>{change.isPending ? "저장 중…" : "변경 저장"}</button>
          <button type="button" className="btn btn-ghost" disabled={change.isPending} onClick={() => { updateDraft({ target: null, reason: "" }); change.reset(); }}>취소</button>
        </div>
      </form>}
      {showHistory && <div className="hairline-t pt-3 text-xs" aria-label="변경 이력">
        <div className="mb-3 space-y-2">
          <button className="btn btn-ghost" disabled={download.isPending} onClick={() => download.mutate(v.id)}>{download.isPending ? '내보내는 중…' : '변경 이력 JSON 내보내기'}</button>
          <p>내보내기에는 현재 상태와 전체 변경 이력을 포함합니다. 최대 10,000건·8 MiB입니다.</p>
          {download.isError && <p role="alert">이력을 내보내지 못했습니다: {download.error.message}</p>}
          {download.isSuccess && <p role="status">위반 #{download.data.bundle.violation.id}의 변경 이력 {download.data.bundle.total}건을 내보냈습니다.</p>}
        </div>
        <form className="mb-3 space-y-2" onSubmit={e => { e.preventDefault(); filterHistory(historySearch.trim(), historyStatus); }}>
          <Field label="이력 처리자 · 사유 검색"><input className="input w-full" maxLength={200} value={historySearch} onChange={e => setHistorySearch(e.target.value)} /></Field>
          <Field label="변경 후 상태"><select className="input w-full" value={historyStatus} onChange={e => filterHistory(historyQuery, e.target.value)}>
            <option value="">모든 변경 상태</option>{Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select></Field>
          <div className="flex flex-wrap gap-2"><button className="btn btn-ghost">이력 검색</button><button type="button" className="btn btn-ghost" onClick={() => { setHistorySearch(''); filterHistory('', ''); }}>이력 검색 초기화</button></div>
        </form>
        <p className="mb-2">최근 변경부터 표시합니다. 조회 중 생긴 변경은 이력 새로고침으로 확인하세요.</p>
        <button className="btn btn-ghost mb-3" disabled={history.isFetching} onClick={() => void history.refetch()}>이력 새로고침</button>
        {history.isPending ? <p role="status">이력 불러오는 중…</p> : !history.data && history.isError ? <p role="alert">{history.error.message} <button className="btn btn-ghost" onClick={() => history.refetch()}>다시 시도</button></p> : historyItems.length === 0 ? <p>{historyQuery || historyStatus ? '조건에 맞는 변경 이력이 없습니다.' : '기록된 상태 변경이 없습니다. 기존 데이터에는 과거 이력이 없을 수 있습니다.'}</p> : <ol className="space-y-3">{historyItems.map(event => <li key={event.id}>
          <p>{labels[event.from_status]} → {labels[event.to_status]} · {event.actor} ({event.actor_user_id ? "로그인 계정" : "직접 입력"}) · {new Date(event.created_at.endsWith("Z") || /[+-]\d\d:\d\d$/.test(event.created_at) ? event.created_at : `${event.created_at}Z`).toLocaleString()}</p>
          <p className="mt-1 whitespace-pre-wrap break-words">{event.reason}</p>
        </li>)}</ol>}
        {history.data && <p role="status" className="mt-3">조회한 이력 {historyItems.length} / {history.data.pages[0].total}건</p>}
        {history.data && history.isError && <p role="alert">이력을 불러오지 못했습니다: {history.error.message}</p>}
        {history.hasNextPage && <button className="btn btn-ghost mt-2" disabled={history.isFetching} onClick={() => void history.fetchNextPage()}>{history.isFetchingNextPage ? '이전 이력 불러오는 중…' : '이전 변경 더 보기'}</button>}
      </div>}
    </div>
  );
}
