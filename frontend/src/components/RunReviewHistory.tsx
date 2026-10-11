import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { api, type SignoffRun, type SavedRunReviewSummary } from '../api';
import { useAuth } from './AuthProvider';
import { formatDateTime, tr, useLanguage } from './LanguageProvider';

const states: Record<string, string> = {
  get running() { return tr('요청 접수 · 완료 확인 전', 'Requested · awaiting completion'); },
  get completed() { return tr('검토 완료', 'Review completed'); },
  get failed() { return tr('검토 실패', 'Review failed'); },
};

function stateLabel(row: SavedRunReviewSummary) { return row.completion_overdue ? tr('완료 확인 필요', 'Completion check needed') : states[row.status] ?? row.status; }

export function RunReviewHistory({ run }: { run: SignoffRun }) {
  const { t } = useLanguage();
  const auth = useAuth();
  const qc = useQueryClient();
  const [submitting, setSubmitting] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const [requestKey, setRequestKey] = useState<string | null>(null);
  const [closeReason, setCloseReason] = useState('');
  const history = useInfiniteQuery({
    queryKey: ['run-reviews', run.id], initialPageParam: null as number | null,
    queryFn: ({ pageParam }) => api.runReviews(run.id, pageParam),
    getNextPageParam: page => page.next_before_id ?? undefined,
    refetchInterval: query => submitting || query.state.data?.pages.some(page => page.items.some(item => item.status === 'running' && !item.completion_overdue)) ? 3000 : false,
  });
  const review = useQuery({ queryKey: ['run-review', run.id, selected],
    queryFn: () => api.runReview(run.id, selected!), enabled: selected !== null,
    refetchInterval: query => query.state.data?.status === 'running' && !query.state.data.completion_overdue ? 3000 : false,
  });
  const create = useMutation({
    mutationFn: (key: string) => api.createRunReview(run.id, key), retry: false,
    onMutate: () => setSubmitting(true),
    onSuccess: row => { setSelected(row.id); setRequestKey(null); qc.setQueryData(['run-review', run.id, row.id], row); },
    onSettled: () => { setSubmitting(false); void qc.invalidateQueries({ queryKey: ['run-reviews', run.id] }); },
  });
  const download = useMutation({
    mutationFn: (reviewId: number) => api.exportRunReview(run.id, reviewId),
    onSuccess: (blob, reviewId) => {
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `run-${run.id}-review-${reviewId}.json`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
  });
  const close = useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) => api.closeRunReview(run.id, id, reason),
    retry: false,
    onSuccess: row => { qc.setQueryData(['run-review', run.id, row.id], row); setCloseReason(''); },
    onSettled: (_data, _error, input) => {
      void qc.invalidateQueries({ queryKey: ['run-reviews', run.id] });
      void qc.invalidateQueries({ queryKey: ['run-review', run.id, input.id] });
    },
  });
  function requestReview() {
    const key = requestKey ?? crypto.randomUUID();
    setRequestKey(key);
    create.mutate(key);
  }
  const items = history.data?.pages.flatMap(page => page.items) ?? [];
  return <section aria-label={t(`런 #${run.id} 저장된 AI 검토`, `Saved AI reviews for run #${run.id}`)} className="border-t border-[var(--border)] pt-3 space-y-3">
    <h3 className="font-semibold">{t('런에 저장되는 AI 검토', 'AI reviews saved to this run')}</h3>
    <p>{t('이 런의 보관된 근거를 Hermes가 검토하고 요청자·입력·의견을 서버에 저장합니다. 자동 검토와 별도로 직접 요청하며, 승인이나 원래 판정은 변경하지 않습니다.', "Hermes reviews this run's archived evidence and saves the requester, input and feedback on the server. You request it separately from automatic reviews, and it does not change approvals or the original verdict.")}</p>
    {auth.can(run.project_id, 'editor') && <button className="btn btn-ghost" disabled={create.isPending} onClick={requestReview}>{create.isPending ? t('검토 요청 처리 중…', 'Submitting review request…') : requestKey ? t('같은 요청 다시 확인', 'Recheck the same request') : t('AI 검토 요청 · 기록 저장', 'Request AI review · save record')}</button>}
    {create.isError && <p role="alert">{create.error.message} {t('같은 요청 다시 확인은 중복 검토를 실행하지 않습니다.', 'Rechecking the same request does not run a duplicate review.')}</p>}
    <button className="btn btn-ghost" onClick={() => { void history.refetch(); if (selected) void review.refetch(); }}>{t('검토 이력 새로고침', 'Refresh review history')}</button>
    {history.isPending && <p role="status">{t('검토 이력 불러오는 중…', 'Loading review history…')}</p>}
    {history.isError && <p role="alert">{t('검토 이력을 불러오지 못했습니다. 새로고침으로 다시 확인하세요.', 'Could not load review history. Refresh to try again.')}</p>}
    {history.isSuccess && !items.length && <p>{t('아직 저장된 AI 검토가 없습니다.', 'No saved AI reviews yet.')}</p>}
    <ul className="space-y-2">{items.map(item => <li key={item.id}><button className="btn btn-ghost text-left" aria-pressed={selected === item.id} onClick={() => { setSelected(item.id); setCloseReason(''); }}>{t('검토', 'Review')} #{item.id} · {stateLabel(item)} · {item.requester} · {formatDateTime(item.created_at)}</button></li>)}</ul>
    {history.hasNextPage && <button className="btn btn-ghost" disabled={history.isFetchingNextPage} onClick={() => void history.fetchNextPage()}>{t('이전 검토 더 보기', 'Show earlier reviews')}</button>}
    {selected !== null && <section aria-label={t('저장된 검토 상세', 'Saved review details')} className="rounded-lg bg-[var(--surface-2)] p-3 space-y-2">
      {review.isPending ? <p role="status">{t('검토 상세 불러오는 중…', 'Loading review details…')}</p> : review.isError ? <p role="alert">{t('상세를 불러오지 못했습니다. 검토 이력을 새로고침하세요.', 'Could not load details. Refresh the review history.')}</p> : <>
        <h4 className="font-semibold">{t('검토', 'Review')} #{review.data.id} · {stateLabel(review.data)}</h4>
        <div className="space-y-2">
          <button className="btn btn-ghost" disabled={download.isPending} onClick={() => download.mutate(review.data.id)}>{download.isPending ? t(`검토 #${download.variables} 파일 준비 중…`, `Preparing review #${download.variables} file…`) : t('검토·근거 JSON 다운로드', 'Download review and evidence JSON')}</button>
          <p>{t('서버의 현재 기록과 검토 당시 입력·지침을 함께 내보냅니다. 미완료·실패 상태도 그대로 포함합니다. 최대 2 MiB.', "Exports the server's current record together with the input and instructions used at review time. Incomplete and failed reviews are included as is. Up to 2 MiB.")}</p>
          {download.variables === selected && download.isError && <p role="alert">{download.error.message}</p>}
          {download.variables === selected && download.isSuccess && <p role="status">{t('검토 파일 다운로드를 시작했습니다.', 'Review file download started.')}</p>}
        </div>
        <p>{t('요청자', 'Requester')}: {review.data.requester} · {t('역할', 'Role')}: {review.data.role === 'a1_rtl' ? t('RTL 리뷰어', 'RTL reviewer') : t('타이밍 분석가', 'Timing analyst')} · {t('요청 모델 별칭', 'Requested model alias')}: {review.data.model_alias}</p>
        {review.data.status === 'running' && <p role="status">{review.data.completion_overdue ? t('접수 후 2분 이상 완료 기록이 없어 자동 조회를 멈췄습니다. 실행이 중단됐다는 뜻은 아닙니다. 검토 이력 새로고침으로 완료 여부를 확인하세요.', 'Automatic polling stopped because no completion was recorded for more than 2 minutes after the request. This does not mean the run was aborted. Refresh the review history to check whether it finished.') : t('완료 결과가 아직 저장되지 않았습니다. 서버가 중단되면 이 상태가 남을 수 있으며 자동 재실행되지 않습니다.', 'The completed result has not been saved yet. If the server stops, this state may remain and the review is not rerun automatically.')}</p>}
        {review.data.status === 'failed' && <p>{t('검토가 완료되지 않았습니다. 실패 기록은 보존됩니다. 새 검토는 별도 요청으로 기록됩니다.', 'The review did not complete. The failure record is kept. A new review is recorded as a separate request.')}</p>}
        {review.data.outcome.error === 'review_capacity' && <p>{t('동시 AI 검토 처리 한도로 모델 호출을 시작하지 못했습니다. 대기열에 등록되지 않았습니다. 잠시 후 새 AI 검토를 요청하세요. 같은 요청 키는 이 기록을 반환합니다.', 'The model call could not start because the concurrent AI review limit was reached. It was not queued. Request a new AI review shortly. The same request key returns this record.')}</p>}
        {review.data.completion_overdue && auth.can(run.project_id, 'owner') && <form className="space-y-2" onSubmit={event => { event.preventDefault(); if (closeReason.trim()) close.mutate({ id: review.data.id, reason: closeReason.trim() }); }}>
          <p>{t('미완료 종결은 이 요청을 실패 상태로 확정합니다. 모델 실행 취소를 보장하지 않으며, 이후 도착한 응답은 이 기록에 반영하지 않습니다. 재검토는 새 요청으로 진행하세요.', 'Closing as incomplete marks this request as failed. It does not guarantee the model run is cancelled, and responses that arrive later are not applied to this record. Submit a new request to review again.')}</p>
          <label className="block">{t('미완료 종결 사유', 'Reason for closing as incomplete')}<textarea className="input w-full" required maxLength={1000} value={closeReason} disabled={close.isPending} onChange={event => setCloseReason(event.target.value)} /></label>
          <button className="btn btn-ghost" disabled={close.isPending || !closeReason.trim()}>{close.isPending ? t(`검토 #${close.variables?.id} 종결 중…`, `Closing review #${close.variables?.id}…`) : t('미완료 검토 종결', 'Close incomplete review')}</button>
        </form>}
        {close.variables?.id === selected && close.isError && <p role="alert">{close.error.message}</p>}
        {review.data.outcome.closure && <div className="space-y-1">
          <p>{t('운영자 미완료 종결', 'Closed incomplete by operator')} · {review.data.outcome.closure.actor} · {formatDateTime(review.data.outcome.closure.closed_at)}</p>
          <p className="whitespace-pre-wrap break-words">{t('사유', 'Reason')}: {review.data.outcome.closure.reason}</p>
          <p>{t('모델 실행 취소 확인을 의미하지 않습니다. 종결 후 응답은 반영하지 않습니다.', 'This does not confirm the model run was cancelled. Responses after closing are not applied.')}</p>
        </div>}
        {review.data.outcome.review && <p className="whitespace-pre-wrap break-words leading-relaxed">{review.data.outcome.review}</p>}
        {review.data.outcome.completed_at && <p>{t('처리 종료', 'Finished')}: {formatDateTime(review.data.outcome.completed_at)} · {((review.data.outcome.duration_ms ?? 0) / 1000).toFixed(1)}{t('초', ' s')}</p>}
        <details><summary className="cursor-pointer">{t('실제 전달한 근거와 검토 지침', 'Evidence and review instructions actually sent')}</summary><p className="mt-2">{t('입력 스냅샷과 요청에 전달한 지침을 보존합니다. 공급자 시스템 설정과 실제 모델 버전은 포함하지 않습니다.', 'Keeps the input snapshot and the instructions sent with the request. Provider system settings and the actual model version are not included.')}</p><pre tabIndex={0} className="mt-2 max-h-80 overflow-auto">{JSON.stringify(review.data.input_snapshot, null, 2)}</pre><pre tabIndex={0} className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap break-words">{review.data.review_policy}</pre></details>
      </>}
    </section>}
  </section>;
}
