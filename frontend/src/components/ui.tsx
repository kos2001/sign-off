import type { ReactNode } from "react";

export function Card({
  title,
  subtitle,
  actions,
  children,
}: {
  title?: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="card p-5">
      {(title || actions) && (
        <header className="mb-4 flex items-start justify-between gap-3">
          <div>
            {title && <h2 className="text-sm font-semibold">{title}</h2>}
            {subtitle && (
              <p className="mt-0.5 text-xs" style={{ color: "var(--text-muted)" }}>
                {subtitle}
              </p>
            )}
          </div>
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

export function StatTile({
  label,
  value,
  suffix,
  tone,
}: {
  label: string;
  value: string | number;
  suffix?: string;
  tone?: "good" | "critical";
}) {
  const color =
    tone === "good"
      ? "var(--delta-good-text)"
      : tone === "critical"
        ? "var(--status-critical)"
        : "var(--text-primary)";
  return (
    <div className="card px-4 py-3">
      <div className="text-xs" style={{ color: "var(--text-muted)" }}>
        {label}
      </div>
      <div className="mt-1 text-2xl font-semibold" style={{ color }}>
        {value}
        {suffix && (
          <span className="ml-1 text-sm font-normal" style={{ color: "var(--text-muted)" }}>
            {suffix}
          </span>
        )}
      </div>
    </div>
  );
}

const STATUS_STYLES = {
  good: { color: "var(--status-good)", icon: "✓" },
  warning: { color: "var(--status-warning)", icon: "!" },
  serious: { color: "var(--status-serious)", icon: "▲" },
  critical: { color: "var(--status-critical)", icon: "✕" },
  neutral: { color: "var(--text-muted)", icon: "–" },
} as const;

export function StatusBadge({
  status,
  label,
}: {
  status: keyof typeof STATUS_STYLES;
  label: string;
}) {
  const s = STATUS_STYLES[status];
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium"
      style={{ border: `1px solid ${s.color}`, color: "var(--text-primary)" }}
    >
      <span aria-hidden style={{ color: s.color, fontWeight: 700 }}>
        {s.icon}
      </span>
      {label}
    </span>
  );
}

/** Meter: fill carries severity; the unfilled track is a lighter step of the same ramp. */
export function Meter({
  ratio,
  warnAt = 0.3,
  dangerAt = 0.5,
}: {
  ratio: number;
  warnAt?: number;
  dangerAt?: number;
}) {
  const clamped = Math.max(0, Math.min(1, ratio));
  const fill =
    clamped >= dangerAt
      ? "var(--status-critical)"
      : clamped >= warnAt
        ? "var(--status-warning)"
        : "var(--series-1)";
  return (
    <div
      className="h-2.5 w-full overflow-hidden rounded-full"
      style={{ background: "var(--seq-100)" }}
      role="meter"
      aria-valuenow={Math.round(clamped * 100)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className="h-full rounded-full"
        style={{ width: `${clamped * 100}%`, background: fill }}
      />
    </div>
  );
}

export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs" style={{ color: "var(--text-secondary)" }}>
      {label}
      {children}
    </label>
  );
}
