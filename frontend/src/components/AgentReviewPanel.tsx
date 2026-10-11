import { Link } from 'react-router';
import type { AgentReview } from '../api';
import { AGENT_ROLES, type AgentRoleId } from '../agentRoles';
import { formatDateTime, useLanguage } from './LanguageProvider';
import { StatusBadge } from './ui';

export function AgentReviewPanel({ role, review, loading, failed, onRetry, waiting, scope, waitingLabel, retryLabel }: {
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
  const { t } = useLanguage();
  const info = AGENT_ROLES[role];
  const unavailable = !loading && (failed || review?.available === false);
  const busy = unavailable && !failed && review?.error === 'review_capacity';
  const completed = !loading && !unavailable && review?.triggered && review.available === true && !!review.review;
  const skipped = !loading && !unavailable && review?.triggered === false;
  const label = loading ? t('검토 결과 대기', 'Awaiting review result') : busy ? t('검토 처리 한도 도달', 'Review capacity reached') : unavailable ? t('검토 미완료', 'Review incomplete') : completed ? t('검토 완료', 'Review complete') : skipped ? t('조건 미해당 · 실행 안 됨', 'Condition not met · not run') : waitingLabel ?? t('실행 전', 'Not run yet');
  const stateText = loading ? t('조건 확인과 검토 요청을 처리하고 있습니다. 완료 후 결과를 표시합니다.', 'Checking conditions and processing the review request. Results appear when complete.')
    : busy ? t('동시 AI 검토 처리 한도에 도달해 이 역할의 모델 호출을 시작하지 않았습니다. 대기열에 등록되지 않으며, 잠시 후 다시 시도하세요. 분석 결과는 그대로 유지됩니다.', 'The concurrent AI review limit was reached, so the model call for this role did not start. It is not queued; try again shortly. Analysis results are unaffected.')
    : unavailable ? t('검토 서비스에 연결하거나 응답을 받지 못했습니다. 분석 결과와 위반 검토는 계속 사용할 수 있습니다.', 'Could not connect to the review service or get a response. Analysis results and violation review remain available.')
    : skipped ? t('이번 결과는 개입 조건에 해당하지 않아 에이전트를 호출하지 않았습니다.', 'This result did not meet the involvement condition, so the agent was not called.')
    : completed ? t('현재 전달한 근거를 바탕으로 작성한 참고 의견입니다.', 'A reference opinion based on the evidence currently provided.')
    : waiting ?? t('분석 결과가 나오면 개입 조건을 확인합니다.', 'The involvement condition is checked once analysis results are available.');
  return <section aria-label={unavailable ? t('검토 서비스 상태', 'Review service status') : t(`${info.name} 검토 의견`, `${info.name} review opinion`)} aria-busy={!!loading}
    className="mt-4 rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-4 space-y-3">
    <header className="flex flex-wrap items-center justify-between gap-2">
      <h3 className="text-sm font-semibold"><span className="mr-2 text-[var(--series-1)]">{info.code}</span>{info.name}</h3>
      <StatusBadge status={unavailable ? 'warning' : 'neutral'} label={label} />
    </header>
    <p role="status" className="text-sm text-[var(--text-secondary)]">{stateText}</p>
    <dl className="grid gap-2 text-xs sm:grid-cols-2">
      <div><dt className="text-[var(--text-muted)]">{t('개입 조건', 'Involvement condition')}</dt><dd className="mt-1">{info.condition}</dd></div>
      <div><dt className="text-[var(--text-muted)]">{t('검토 근거', 'Review evidence')}</dt><dd className="mt-1">{scope ? `${scope} · ` : ''}{info.evidence}</dd></div>
    </dl>
    {completed && <p className="border-t border-[var(--border)] pt-3 text-sm whitespace-pre-wrap break-words leading-relaxed text-[var(--text-secondary)]">{review.review}</p>}
    {!loading && review?.completed_at && <p className="text-xs text-[var(--text-muted)]">
      {completed ? t('검토 완료', 'Review complete') : t('처리 종료', 'Processing ended')} <time dateTime={review.completed_at}>{formatDateTime(review.completed_at)}</time>
      {typeof review.duration_ms === 'number' && t(` · ${(review.duration_ms / 1000).toFixed(1)}초`, ` · ${(review.duration_ms / 1000).toFixed(1)} s`)}
    </p>}
    {unavailable && onRetry && <button className="btn btn-ghost" onClick={onRetry}>{retryLabel ?? t('검토 다시 시도', 'Retry review')}</button>}
    {unavailable && review?.error_id && <p className="text-xs break-all text-[var(--text-muted)]">{t('문의 번호:', 'Support reference:')} {review.error_id}</p>}
    {completed && <details className="text-xs text-[var(--text-muted)]"><summary className="cursor-pointer">{t('검토 기록 안내', 'About review records')}</summary>
      <p className="mt-2">{t('의견은 현재 화면의 조회 결과이며 서버에 검토 이력으로 저장되지 않습니다. 보존할 의견은 런의 실행 근거에서 AI 검토를 별도 요청하세요. 승인·웨이버는 사람의 변경 이력으로 기록합니다.', 'This opinion is a result shown on the current screen and is not saved on the server as review history. To keep an opinion, request an AI review separately from the run evidence. Approvals and waivers are recorded as human change history.')}</p>
      {review.review_id && <p className="mt-1 break-all">{t('검토 식별자:', 'Review ID:')} {review.review_id}</p>}
    </details>}
    <footer className="flex flex-wrap justify-between gap-2 text-xs text-[var(--text-muted)]">
      <span>{t('Hermes 자동 검토 · 승인과 게이트 상태 변경은 별도', 'Hermes automatic review · approvals and gate status changes are separate')}</span>
      <Link className="underline" to={`/agents#${role}`}>{t('개입 방식 보기', 'How involvement works')}</Link>
    </footer>
  </section>;
}
