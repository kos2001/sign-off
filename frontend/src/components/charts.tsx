import { useCallback, useState } from "react";

/* ---------- shared hover tooltip layer ---------- */

interface TooltipState {
  x: number;
  y: number;
  content: string;
}

export function useTooltip() {
  const [tip, setTip] = useState<TooltipState | null>(null);
  const show = useCallback(
    (e: { clientX: number; clientY: number }, content: string) =>
      setTip({ x: e.clientX + 12, y: e.clientY + 12, content }),
    [],
  );
  const hide = useCallback(() => setTip(null), []);
  const node = tip ? (
    <div className="viz-tooltip" style={{ left: tip.x, top: tip.y }}>
      {tip.content}
    </div>
  ) : null;
  return { show, hide, node };
}

/* ---------- sequential ramp (one hue, light -> dark) ---------- */

const SEQ_STEPS = [
  "var(--seq-100)",
  "var(--seq-200)",
  "var(--seq-300)",
  "var(--seq-400)",
  "var(--seq-500)",
  "var(--seq-600)",
  "var(--seq-700)",
];

function seqColor(value: number, max: number): string {
  if (max <= 0) return SEQ_STEPS[0];
  const idx = Math.min(
    SEQ_STEPS.length - 1,
    Math.floor((value / max) * SEQ_STEPS.length),
  );
  return SEQ_STEPS[idx];
}

/* ---------- IR-drop heatmap (sequential, magnitude) ---------- */

export function IrDropHeatmap({
  map,
  thresholdMv,
}: {
  map: number[][];
  thresholdMv: number;
}) {
  const { show, hide, node } = useTooltip();
  const [tableView, setTableView] = useState(false);
  const rows = map.length;
  const cols = map[0]?.length ?? 0;
  const max = Math.max(...map.flat(), thresholdMv);
  const cell = Math.min(44, Math.max(18, Math.floor(560 / Math.max(cols, 1))));
  const gap = 2; // surface gap between fills

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <ScaleLegend max={max} unit="mV" />
        <button className="btn btn-ghost" onClick={() => setTableView((v) => !v)}>
          {tableView ? "히트맵 보기" : "테이블 보기"}
        </button>
      </div>

      {tableView ? (
        <div className="overflow-x-auto">
          <table className="text-xs" style={{ fontVariantNumeric: "tabular-nums" }}>
            <tbody>
              {map.map((row, r) => (
                <tr key={r}>
                  {row.map((v, c) => (
                    <td
                      key={c}
                      className="px-2 py-1 text-right"
                      style={{
                        borderBottom: "1px solid var(--grid-hairline)",
                        color:
                          v > thresholdMv
                            ? "var(--status-critical)"
                            : "var(--text-secondary)",
                        fontWeight: v > thresholdMv ? 600 : 400,
                      }}
                    >
                      {v.toFixed(1)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <svg
          width={cols * (cell + gap)}
          height={rows * (cell + gap)}
          role="img"
          aria-label="IR-drop 히트맵"
        >
          {map.map((row, r) =>
            row.map((v, c) => (
              <rect
                key={`${r}-${c}`}
                x={c * (cell + gap)}
                y={r * (cell + gap)}
                width={cell}
                height={cell}
                rx={3}
                fill={seqColor(v, max)}
                onMouseMove={(e) =>
                  show(
                    e,
                    `타일 (${r}, ${c}) · ${v.toFixed(1)} mV${v > thresholdMv ? " · 핫스팟" : ""}`,
                  )
                }
                onMouseLeave={hide}
              />
            )),
          )}
        </svg>
      )}
      {node}
    </div>
  );
}

function ScaleLegend({ max, unit }: { max: number; unit: string }) {
  return (
    <div className="flex items-center gap-2 text-xs" style={{ color: "var(--text-muted)" }}>
      <span>0</span>
      <div className="flex h-2.5 overflow-hidden rounded-sm">
        {SEQ_STEPS.map((c) => (
          <div key={c} style={{ width: 18, background: c }} />
        ))}
      </div>
      <span>
        {max.toFixed(0)} {unit}
      </span>
    </div>
  );
}

/* ---------- diverging bars around a zero baseline (slack polarity) ---------- */

export function SlackBars({ slacks }: { slacks: number[] }) {
  const { show, hide, node } = useTooltip();
  const width = 640;
  const barH = 14; // thin marks
  const gap = 6;
  const labelW = 70;
  const height = slacks.length * (barH + gap);
  const maxAbs = Math.max(...slacks.map(Math.abs), 1);
  const plotW = width - labelW - 60;
  const zeroX = labelW + plotW / 2;
  const scale = plotW / 2 / maxAbs;
  const wnsIndex = slacks.indexOf(Math.min(...slacks));

  return (
    <div className="overflow-x-auto">
      <svg width={width} height={height + 22} role="img" aria-label="엔드포인트 슬랙">
        {/* zero baseline — solid hairline */}
        <line
          x1={zeroX}
          y1={0}
          x2={zeroX}
          y2={height}
          stroke="var(--baseline)"
          strokeWidth={1}
        />
        {slacks.map((s, i) => {
          const w = Math.abs(s) * scale;
          const x = s < 0 ? zeroX - w : zeroX;
          const y = i * (barH + gap);
          const isWns = i === wnsIndex;
          return (
            <g key={i}>
              <text
                x={labelW - 8}
                y={y + barH - 3}
                textAnchor="end"
                fontSize={11}
                fill="var(--text-muted)"
              >
                EP{i}
              </text>
              <rect
                x={x}
                y={y}
                width={Math.max(w, 1)}
                height={barH}
                fill={s < 0 ? "var(--div-neg)" : "var(--div-pos)"}
                rx={3}
                onMouseMove={(e) =>
                  show(e, `엔드포인트 ${i} · 슬랙 ${s.toFixed(1)} ps${isWns ? " · WNS" : ""}`)
                }
                onMouseLeave={hide}
              />
              {/* selective direct label: the WNS endpoint only */}
              {isWns && (
                <text
                  x={x - 6}
                  y={y + barH - 3}
                  textAnchor="end"
                  fontSize={11}
                  fontWeight={600}
                  fill="var(--text-primary)"
                >
                  {s.toFixed(1)} ps (WNS)
                </text>
              )}
            </g>
          );
        })}
        <text x={zeroX} y={height + 16} textAnchor="middle" fontSize={11} fill="var(--text-muted)">
          0 ps
        </text>
      </svg>
      {node}
    </div>
  );
}

/* ---------- run status distribution (stacked bar, single row) ---------- */

const RUN_STATUS_COLOR: Record<"passed" | "failed" | "running", string> = {
  passed: "var(--status-good)",
  failed: "var(--status-critical)",
  running: "var(--status-warning)",
};
const RUN_STATUS_LABEL: Record<"passed" | "failed" | "running", string> = {
  passed: "통과",
  failed: "실패",
  running: "진행 중",
};

export function RunStatusBar({
  counts,
}: {
  counts: Record<"passed" | "failed" | "running", number>;
}) {
  const { show, hide, node } = useTooltip();
  const total = counts.passed + counts.failed + counts.running;
  const order: ("passed" | "failed" | "running")[] = ["passed", "failed", "running"];

  if (total === 0) {
    return (
      <p className="text-xs" style={{ color: "var(--text-muted)" }}>
        아직 런이 없습니다.
      </p>
    );
  }

  return (
    <div>
      <div
        className="flex h-3 w-full overflow-hidden rounded-full"
        style={{ background: "var(--seq-100)" }}
        role="img"
        aria-label={`런 상태: 통과 ${counts.passed}, 실패 ${counts.failed}, 진행 중 ${counts.running}`}
      >
        {order.map(
          (k) =>
            counts[k] > 0 && (
              <div
                key={k}
                style={{ width: `${(counts[k] / total) * 100}%`, background: RUN_STATUS_COLOR[k] }}
                onMouseMove={(e) =>
                  show(e, `${RUN_STATUS_LABEL[k]} ${counts[k]}건 · ${((counts[k] / total) * 100).toFixed(0)}%`)
                }
                onMouseLeave={hide}
              />
            ),
        )}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-xs" style={{ color: "var(--text-secondary)" }}>
        {order.map(
          (k) =>
            counts[k] > 0 && (
              <span key={k} className="inline-flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-sm" style={{ background: RUN_STATUS_COLOR[k] }} />
                {RUN_STATUS_LABEL[k]} {counts[k]}
              </span>
            ),
        )}
      </div>
      {node}
    </div>
  );
}

/* ---------- readiness progress: fraction of gate domains ready ---------- */

export function ReadyProgress({ ready, total }: { ready: number; total: number }) {
  const ratio = total > 0 ? ready / total : 0;
  const fill = ratio >= 1 ? "var(--status-good)" : ratio > 0 ? "var(--status-warning)" : "var(--status-critical)";
  return (
    <div className="flex items-center gap-2">
      <div
        className="h-2 w-24 overflow-hidden rounded-full"
        style={{ background: "var(--seq-100)" }}
        role="meter"
        aria-valuenow={ready}
        aria-valuemin={0}
        aria-valuemax={total}
        aria-label="게이트 도메인 준비율"
      >
        <div className="h-full rounded-full" style={{ width: `${ratio * 100}%`, background: fill }} />
      </div>
      <span className="text-xs" style={{ color: "var(--text-muted)" }}>
        {ready}/{total} 준비됨
      </span>
    </div>
  );
}

/* ---------- stacked horizontal bars: functional vs glitch power ---------- */

export function PowerStackBars({
  nets,
}: {
  nets: { name: string; functional_power_uw: number; glitch_power_uw: number }[];
}) {
  const { show, hide, node } = useTooltip();
  const width = 640;
  const barH = 16;
  const gap = 10;
  const labelW = 90;
  const surfaceGap = 2;
  const maxTotal = Math.max(
    ...nets.map((n) => n.functional_power_uw + n.glitch_power_uw),
    1e-9,
  );
  const plotW = width - labelW - 80;
  const scale = plotW / maxTotal;

  return (
    <div>
      {/* legend — always present for two series */}
      <div className="mb-3 flex gap-4 text-xs" style={{ color: "var(--text-secondary)" }}>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: "var(--series-1)" }} />
          기능 전력
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: "var(--series-2)" }} />
          글리치 전력
        </span>
      </div>
      <svg
        width={width}
        height={nets.length * (barH + gap)}
        role="img"
        aria-label="네트별 전력 분해"
      >
        {nets.map((n, i) => {
          const y = i * (barH + gap);
          const fw = n.functional_power_uw * scale;
          const gw = n.glitch_power_uw * scale;
          const total = n.functional_power_uw + n.glitch_power_uw;
          return (
            <g key={n.name}>
              <text
                x={labelW - 8}
                y={y + barH - 4}
                textAnchor="end"
                fontSize={11}
                fill="var(--text-muted)"
              >
                {n.name}
              </text>
              <rect
                x={labelW}
                y={y}
                width={Math.max(fw, 1)}
                height={barH}
                rx={3}
                fill="var(--series-1)"
                onMouseMove={(e) =>
                  show(e, `${n.name} · 기능 ${n.functional_power_uw.toFixed(3)} µW`)
                }
                onMouseLeave={hide}
              />
              {gw > 0 && (
                <rect
                  x={labelW + fw + surfaceGap}
                  y={y}
                  width={Math.max(gw, 1)}
                  height={barH}
                  rx={3}
                  fill="var(--series-2)"
                  onMouseMove={(e) =>
                    show(e, `${n.name} · 글리치 ${n.glitch_power_uw.toFixed(3)} µW`)
                  }
                  onMouseLeave={hide}
                />
              )}
              {/* value at the bar tip (text tokens, not series color) */}
              <text
                x={labelW + fw + surfaceGap + gw + 6}
                y={y + barH - 4}
                fontSize={11}
                fill="var(--text-secondary)"
              >
                {total.toFixed(2)} µW
              </text>
            </g>
          );
        })}
      </svg>
      {node}
    </div>
  );
}
