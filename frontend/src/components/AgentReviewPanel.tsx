import type { AgentReview } from "../api";

const ROBOT = "🤖";

/** Renders one agent's intervention state explicitly — not-triggered, hermes
 * unreachable, and live review are three visually distinct states, so
 * "did an agent look at this?" never has to be inferred from a blank area. */
export function AgentReviewPanel({
  review,
  loading,
}: {
  review: AgentReview | null | undefined;
  loading?: boolean;
}) {
  if (loading) {
    return (
      <p className="mt-3 text-xs" style={{ color: "var(--text-muted)" }}>
        {ROBOT} agent 개입 여부 확인 중…
      </p>
    );
  }
  if (!review) return null;

  if (!review.triggered) {
    return (
      <div
        className="mt-3 rounded-lg px-3 py-2 text-xs"
        style={{ border: "1px solid var(--grid-hairline)", color: "var(--text-muted)" }}
      >
        {ROBOT} <strong style={{ color: "var(--text-secondary)" }}>{review.role_name}</strong> 미개입 —
        이번 결과는 개입 기준을 넘지 않았습니다.
        <div className="mt-1" style={{ color: "var(--text-muted)" }}>
          개입 기준: {review.trigger}
        </div>
      </div>
    );
  }

  if (review.available === false) {
    return (
      <div
        className="mt-3 rounded-lg px-3 py-2.5 text-xs"
        style={{ border: "1px solid var(--status-warning)", color: "var(--text-secondary)" }}
      >
        <div className="font-semibold" style={{ color: "var(--text-primary)" }}>
          {ROBOT} {review.role_name} 개입함 — hermes 연결 안 됨
        </div>
        <div className="mt-1" style={{ color: "var(--text-muted)" }}>
          개입 기준: {review.trigger}
        </div>
        <div className="mt-1.5">
          이 결과는 agent 검토가 필요하지만, hermes-agent &apos;sign-off&apos; 프로파일 api_server에
          연결할 수 없습니다. <code>scripts/setup_hermes_profile.sh --apply</code> 실행 후{" "}
          <code>hermes -p sign-off gateway restart</code>로 기동하세요.
        </div>
        {review.error && (
          <div className="mt-1 font-mono" style={{ color: "var(--text-muted)" }}>
            {review.error}
          </div>
        )}
      </div>
    );
  }

  return (
    <div
      className="mt-3 rounded-lg px-3 py-2.5 text-sm"
      style={{ border: "1px solid var(--series-1)", background: "var(--surface-2)" }}
    >
      <div className="mb-1 flex items-center gap-2">
        <span className="font-semibold">
          {ROBOT} {review.role_name} 개입함
        </span>
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>
          {review.trigger}
        </span>
      </div>
      <p className="whitespace-pre-wrap" style={{ color: "var(--text-secondary)" }}>
        {review.review}
      </p>
    </div>
  );
}
