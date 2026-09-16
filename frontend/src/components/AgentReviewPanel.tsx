import { Link } from 'react-router';
import type { AgentReview } from '../api';
import { AGENT_ROLES, type AgentRoleId } from '../agentRoles';
import { StatusBadge } from './ui';

export function AgentReviewPanel({ role, review, loading, failed, onRetry, waiting, scope, waitingLabel = '실행 전', retryLabel = '검토 다시 시도' }: {
  role: AgentRoleId;
  review: AgentReview | null | undefined;
  loading?: boolean;
  failed?: boolean;
  waiting?: string;
  scope?: string;
  waitingLabel?: string;
  retryLabel?: string;
  onRetry?: () => void;
}) {
  const info = AGENT_ROLES[role];
  const unavailable = !loading && (failed || review?.available === false);
  const busy = unavailable && !failed && review?.error === 'review_capacity';
  const completed = !loading && !unavailable && review?.triggered && review.available === true && !!review.review;
  const skipped = !loading && !unavailable && review?.triggered === false;
  const label = loading ? '검토 결과 대기' : busy ? '검토 처리 한도 도달' : unavailable ? '검토 미완료' : completed ? '검토 완료' : skipped ? '조건 미해당 · 실행 안 됨' : waitingLabel;
  const stateText = loading ? '조건 확인과 검토 요청을 처리하고 있습니다. 완료 후 결과를 표시합니다.'
    : busy ? '동시 AI 검토 처리 한도에 도달해 이 역할의 모델 호출을 시작하지 않았습니다. 대기열에 등록되지 않으며, 잠시 후 다시 시도하세요. 분석 결과는 그대로 유지됩니다.'
    : unavailable ? '검토 서비스에 연결하거나 응답을 받지 못했습니다. 분석 결과와 위반 검토는 계속 사용할 수 있습니다.'
    : skipped ? '이번 결과는 개입 조건에 해당하지 않아 에이전트를 호출하지 않았습니다.'
    : completed ? '현재 전달한 근거를 바탕으로 작성한 참고 의견입니다.'
    : waiting ?? '분석 결과가 나오면 개입 조건을 확인합니다.';
  return <section aria-label={unavailable ? '검토 서비스 상태' : `${info.name} 검토 의견`} aria-busy={!!loading}
    className="mt-4 rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-4 space-y-3">
    <header className="flex flex-wrap items-center justify-between gap-2">
      <h3 className="text-sm font-semibold"><span className="mr-2 text-[var(--series-1)]">{info.code}</span>{info.name}</h3>
      <StatusBadge status={unavailable ? 'warning' : 'neutral'} label={label} />
    </header>
    <p role="status" className="text-sm text-[var(--text-secondary)]">{stateText}</p>
    <dl className="grid gap-2 text-xs sm:grid-cols-2">
      <div><dt className="text-[var(--text-muted)]">개입 조건</dt><dd className="mt-1">{info.condition}</dd></div>
      <div><dt className="text-[var(--text-muted)]">검토 근거</dt><dd className="mt-1">{scope ? `${scope} · ` : ''}{info.evidence}</dd></div>
    </dl>
    {completed && <p className="border-t border-[var(--border)] pt-3 text-sm whitespace-pre-wrap break-words leading-relaxed text-[var(--text-secondary)]">{review.review}</p>}
    {!loading && review?.completed_at && <p className="text-xs text-[var(--text-muted)]">
      {completed ? '검토 완료' : '처리 종료'} <time dateTime={review.completed_at}>{new Date(review.completed_at).toLocaleString('ko-KR')}</time>
      {typeof review.duration_ms === 'number' && ` · ${(review.duration_ms / 1000).toFixed(1)}초`}
    </p>}
    {unavailable && onRetry && <button className="btn btn-ghost" onClick={onRetry}>{retryLabel}</button>}
    {unavailable && review?.error_id && <p className="text-xs break-all text-[var(--text-muted)]">문의 번호: {review.error_id}</p>}
    {completed && <details className="text-xs text-[var(--text-muted)]"><summary className="cursor-pointer">검토 기록 안내</summary>
      <p className="mt-2">의견은 현재 화면의 조회 결과이며 서버에 검토 이력으로 저장되지 않습니다. 보존할 의견은 런의 실행 근거에서 AI 검토를 별도 요청하세요. 승인·웨이버는 사람의 변경 이력으로 기록합니다.</p>
      {review.review_id && <p className="mt-1 break-all">검토 식별자: {review.review_id}</p>}
    </details>}
    <footer className="flex flex-wrap justify-between gap-2 text-xs text-[var(--text-muted)]">
      <span>Hermes 자동 검토 · 승인과 게이트 상태 변경은 별도</span>
      <Link className="underline" to={`/agents#${role}`}>개입 방식 보기</Link>
    </footer>
  </section>;
}
