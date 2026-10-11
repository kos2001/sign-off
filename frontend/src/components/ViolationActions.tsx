import { useParams } from "react-router";
import { useAuth } from "./AuthProvider";
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, type Violation, type ViolationStatus } from "../api";
import { Field, StatusBadge } from "./ui";
import { useReviewDraft } from "./ReviewDrafts";
import { formatDateTime, tr, useLanguage } from "./LanguageProvider";

const labels: Record<ViolationStatus, string> = {
  get open() { return tr("미해결", "Open"); },
  get fixed() { return tr("수정 완료", "Fixed"); },
  get waived() { return tr("웨이버 승인", "Waiver approved"); },
};

export function ViolationActions({ violation: v, onChange, projectId: explicitProjectId }: { violation: Violation; onChange: () => void; projectId?: number }) {
  const { t } = useLanguage();
  const qc = useQueryClient();
  const auth = useAuth();
  const routeProjectId = Number(useParams().id);
  const projectId = explicitProjectId ?? routeProjectId;
  const canEdit = auth.can(projectId, "editor");
  const canApprove = auth.can(projectId, "approver");
  const account = auth.state.user?.username;
  const [{ target, reviewVersion, reviewStatus, actor, reason }, updateDraft] = useReviewDraft(v);
  const [showHistory, setShowHistory] = useState(false);
  const [waiverExpiresAt, setWaiverExpiresAt] = useState('');
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
      ...(target === 'waived' && waiverExpiresAt ? { waiver_expires_at: new Date(waiverExpiresAt).toISOString() } : {}),
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
    if (status === 'waived') {
      const expiry = new Date(Date.now() + 90 * 24 * 60 * 60 * 1000);
      const local = new Date(expiry.getTime() - expiry.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
      setWaiverExpiresAt(local);
    }
    updateDraft({ reviewVersion: v.version, reviewStatus: v.status, target: status });
  };
  const stale = target !== null && reviewVersion !== v.version;
  return (
    <div className="space-y-3">
      {v.description && <p className="text-xs whitespace-pre-wrap">{v.description}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={v.status === "open" ? "warning" : "good"} label={labels[v.status]} />
        {v.status === "open" ? <>
          <button className="btn btn-ghost" disabled={!canEdit || change.isPending || stale} onClick={() => start("fixed")}>{t("수정 완료 처리", "Mark fixed")}</button>
          <button className="btn btn-ghost" disabled={!canApprove || change.isPending || stale} onClick={() => start("waived")}>{t("웨이버 검토", "Review waiver")}</button>
        </> : <button className="btn btn-ghost" disabled={!(v.status === "waived" ? canApprove : canEdit) || change.isPending || stale} onClick={() => start("open")}>{t("재오픈", "Reopen")}</button>}
        <button className="btn btn-ghost" aria-expanded={showHistory} onClick={() => setShowHistory(!showHistory)}>{t("변경 이력", "Change history")}</button>
      </div>
      {v.waiver && <div className="text-xs space-y-1"><p className="whitespace-pre-wrap">{v.waiver.approved_by} · {v.waiver.reason}</p><p className={v.waiver.active ? 'text-[var(--text-muted)]' : 'text-[var(--status-critical)]'}>{v.waiver.active ? t('웨이버 유효', 'Waiver active') : v.waiver.inactive_reason === 'expired' ? t('웨이버 만료 · 게이트에 다시 반영', 'Waiver expired · counted in the gate again') : t('설계 리비전 범위 불일치 · 게이트에 다시 반영', 'Design revision scope mismatch · counted in the gate again')} · {t('리비전', 'Revision')} {v.waiver.design_revision || t('미기록', 'not recorded')} · {t('만료', 'Expires')} {v.waiver.expires_at ? formatDateTime(v.waiver.expires_at) : t('기존 무기한 웨이버', 'legacy waiver with no expiry')}</p></div>}
      {target && <form className="rounded-lg bg-[var(--surface-1)] p-3 space-y-3" onSubmit={e => { e.preventDefault(); if (!stale && !change.isPending) change.mutate(); }}>
        <p className="font-medium">{labels[reviewStatus]} → {labels[target]}</p>
        {account ? <p className="text-sm">{t("처리 계정:", "Acting account:")} {account}</p> : <Field label={t("처리자 이름 (직접 입력)", "Actor name (entered manually)")}><input className="input" required maxLength={80} value={actor} disabled={change.isPending} onChange={e => updateDraft({ actor: e.target.value })} /></Field>}
        <Field label={target === "fixed" ? t("수정 근거 · 검증 결과", "Fix evidence · verification result") : t("처리 사유", "Reason")}><textarea autoFocus className="input w-full" required maxLength={4000} rows={3} value={reason} disabled={change.isPending} onChange={e => updateDraft({ reason: e.target.value })} /></Field>
        {target === 'waived' && <Field label={t("웨이버 만료 시각 · 최대 365일", "Waiver expiry · up to 365 days")}><input className="input w-full" type="datetime-local" required value={waiverExpiresAt} disabled={change.isPending} onChange={event => setWaiverExpiresAt(event.target.value)} /></Field>}
        {target === 'waived' && <p className="text-xs">{t("현재 런의 설계 리비전에 자동으로 한정됩니다. 만료되거나 범위가 달라지면 차단 위반으로 다시 계산됩니다.", "Automatically limited to the current run's design revision. If it expires or the scope changes, the violation counts as blocking again.")}</p>}
        {target === "open" && <p className="text-xs">{t("웨이버가 있으면 해제되며, 차단 위반은 게이트에 다시 반영됩니다.", "Any waiver is released, and blocking violations count toward the gate again.")}</p>}
        {change.isError && !stale && <p role="alert" className="text-xs text-[var(--status-critical)]">{change.error.message}</p>}
        {stale && <div role="alert" className="space-y-2 text-xs">
          <p>{t("다른 검토자가 이 항목을 변경했습니다. 변경 이력을 확인한 뒤 다시 처리하세요. 작성한 사유는 유지됩니다.", "Another reviewer changed this item. Check the change history, then try again. Your reason is kept.")}</p>
          <button type="button" className="btn btn-ghost" onClick={() => { setShowHistory(true); updateDraft({ target: null }); change.reset(); qc.invalidateQueries({ queryKey: ["violation-history", v.id] }); }}>{t("변경 내용 확인", "Review changes")}</button>
        </div>}
        <div className="flex gap-2">
          <button className="btn btn-primary" disabled={change.isPending || stale || !(account ?? actor.trim()) || !reason.trim() || (target === 'waived' && !waiverExpiresAt)}>{change.isPending ? t("저장 중…", "Saving…") : t("변경 저장", "Save change")}</button>
          <button type="button" className="btn btn-ghost" disabled={change.isPending} onClick={() => { updateDraft({ target: null, reason: "" }); change.reset(); }}>{t("취소", "Cancel")}</button>
        </div>
      </form>}
      {showHistory && <div className="hairline-t pt-3 text-xs" aria-label={t("변경 이력", "Change history")}>
        <div className="mb-3 space-y-2">
          <button className="btn btn-ghost" disabled={download.isPending} onClick={() => download.mutate(v.id)}>{download.isPending ? t('내보내는 중…', 'Exporting…') : t('변경 이력 JSON 내보내기', 'Export change history as JSON')}</button>
          <p>{t("내보내기에는 현재 상태와 전체 변경 이력을 포함합니다. 최대 10,000건·8 MiB입니다.", "The export includes the current status and the full change history. Up to 10,000 entries / 8 MiB.")}</p>
          {download.isError && <p role="alert">{t("이력을 내보내지 못했습니다:", "Could not export history:")} {download.error.message}</p>}
          {download.isSuccess && <p role="status">{t(`위반 #${download.data.bundle.violation.id}의 변경 이력 ${download.data.bundle.total}건을 내보냈습니다.`, `Exported ${download.data.bundle.total} history entries for violation #${download.data.bundle.violation.id}.`)}</p>}
        </div>
        <form className="mb-3 space-y-2" onSubmit={e => { e.preventDefault(); filterHistory(historySearch.trim(), historyStatus); }}>
          <Field label={t("이력 처리자 · 사유 검색", "Search history by actor · reason")}><input className="input w-full" maxLength={200} value={historySearch} onChange={e => setHistorySearch(e.target.value)} /></Field>
          <Field label={t("변경 후 상태", "Status after change")}><select className="input w-full" value={historyStatus} onChange={e => filterHistory(historyQuery, e.target.value)}>
            <option value="">{t("모든 변경 상태", "All statuses")}</option>{Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select></Field>
          <div className="flex flex-wrap gap-2"><button className="btn btn-ghost">{t("이력 검색", "Search history")}</button><button type="button" className="btn btn-ghost" onClick={() => { setHistorySearch(''); filterHistory('', ''); }}>{t("이력 검색 초기화", "Reset history search")}</button></div>
        </form>
        <p className="mb-2">{t("최근 변경부터 표시합니다. 조회 중 생긴 변경은 이력 새로고침으로 확인하세요.", "Newest changes first. Use Refresh history to see changes made while you browse.")}</p>
        <button className="btn btn-ghost mb-3" disabled={history.isFetching} onClick={() => void history.refetch()}>{t("이력 새로고침", "Refresh history")}</button>
        {history.isPending ? <p role="status">{t("이력 불러오는 중…", "Loading history…")}</p> : !history.data && history.isError ? <p role="alert">{history.error.message} <button className="btn btn-ghost" onClick={() => history.refetch()}>{t("다시 시도", "Try again")}</button></p> : historyItems.length === 0 ? <p>{historyQuery || historyStatus ? t('조건에 맞는 변경 이력이 없습니다.', 'No history matches these filters.') : t('기록된 상태 변경이 없습니다. 기존 데이터에는 과거 이력이 없을 수 있습니다.', 'No status changes recorded. Older data may not include past history.')}</p> : <ol className="space-y-3">{historyItems.map(event => <li key={event.id}>
          <p>{labels[event.from_status]} → {labels[event.to_status]} · {event.actor} ({event.actor_user_id ? t("로그인 계정", "signed-in account") : t("직접 입력", "entered manually")}) · {formatDateTime(event.created_at)}</p>
          <p className="mt-1 whitespace-pre-wrap break-words">{event.reason}</p>
        </li>)}</ol>}
        {history.data && <p role="status" className="mt-3">{t(`조회한 이력 ${historyItems.length} / ${history.data.pages[0].total}건`, `Showing ${historyItems.length} of ${history.data.pages[0].total} history entries`)}</p>}
        {history.data && history.isError && <p role="alert">{t("이력을 불러오지 못했습니다:", "Could not load history:")} {history.error.message}</p>}
        {history.hasNextPage && <button className="btn btn-ghost mt-2" disabled={history.isFetching} onClick={() => void history.fetchNextPage()}>{history.isFetchingNextPage ? t('이전 이력 불러오는 중…', 'Loading earlier history…') : t('이전 변경 더 보기', 'Show earlier changes')}</button>}
      </div>}
    </div>
  );
}
