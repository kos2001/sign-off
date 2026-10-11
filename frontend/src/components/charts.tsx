import { useLanguage } from "./LanguageProvider";
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
  const { t } = useLanguage();
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
          {tableView ? t("히트맵 보기", "Show heatmap") : t("테이블 보기", "Show table")}
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
          aria-label={t("IR-drop 히트맵", "IR-drop heatmap")}
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
                    t(
                      `타일 (${r}, ${c}) · ${v.toFixed(1)} mV${v > thresholdMv ? " · 핫스팟" : ""}`,
                      `Tile (${r}, ${c}) · ${v.toFixed(1)} mV${v > thresholdMv ? " · hotspot" : ""}`,
                    ),
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

export function SlackBars({ slacks, endpointIds }: { slacks: number[]; endpointIds?: string[] | null }) {
  const { t } = useLanguage();
  const [selected, setSelected] = useState<number | null>(null);
  const valid = slacks.every(Number.isFinite);
  const maxAbs = Math.max(...slacks.map(Math.abs), Number.MIN_VALUE);
  const minimum = Math.min(...slacks);
  const format = (value: number) => {
    const scientific = Math.abs(value) >= 1e6 || (value !== 0 && Math.abs(value) < 0.001);
    return new Intl.NumberFormat(undefined, {
      maximumSignificantDigits: scientific ? 4 : 6,
      notation: scientific ? 'scientific' : 'standard',
    }).format(value === 0 ? 0 : value);
  };
  return <figure aria-label={t("엔드포인트 슬랙", "Endpoint slack")} className="space-y-3">
    <figcaption className="text-xs text-[var(--text-muted)]">{t("왼쪽은 음수, 오른쪽은 0 이상입니다. 종점을 선택하면 ID와 값을 확인할 수 있습니다.", "Negative slack extends left, zero or positive extends right. Select an endpoint to see its ID and value.")}</figcaption>
    {!slacks.length || !valid ? <p role="status" className="text-sm">{t("차트로 표시할 유효한 슬랙이 없습니다.", "No valid slack values to chart.")}</p> : <>
      <div className="grid grid-cols-[2.5rem_minmax(0,1fr)_5.5rem] gap-2 text-xs text-[var(--text-muted)]" aria-hidden="true"><span>{t("종점", "Endpoint")}</span><span className="text-center">0 ps</span><span className="text-right">{t("슬랙 (ps)", "Slack (ps)")}</span></div>
      <ol className="space-y-1">
        {slacks.map((slack, index) => {
          const width = Math.abs(slack) / maxAbs * 50;
          const isMinimum = slack === minimum;
          const id = endpointIds?.[index];
          return <li key={index}>
            <button type="button" aria-expanded={selected === index}
              aria-label={`EP${index}${id ? ` · ${id}` : ''} · ${t('슬랙', 'Slack')} ${slack} ps${isMinimum ? t(' · 표시된 종점 중 최소 슬랙', ' · lowest slack among shown endpoints') : ''}`}
              className="grid w-full grid-cols-[2.5rem_minmax(0,1fr)_5.5rem] items-center gap-2 rounded-md px-1 py-2 text-left focus-visible:outline-2 focus-visible:outline-[var(--series-1)] hover:bg-[var(--surface-2)]"
              onClick={() => setSelected(selected === index ? null : index)}>
              <span className="text-xs text-[var(--text-secondary)]">EP{index}</span>
              <span className="relative block h-4" aria-hidden="true">
                <span className="absolute inset-y-0 left-1/2 border-l border-[var(--baseline)]" />
                <span className="absolute inset-y-0 rounded-sm" style={{ left: `${slack < 0 ? 50 - width : 50}%`, width: `${width}%`, minWidth: 1, background: slack < 0 ? 'var(--div-neg)' : 'var(--div-pos)' }} />
              </span>
              <span className={`min-w-0 break-all text-right text-xs tabular-nums ${isMinimum ? 'font-bold' : ''}`} style={{ color: slack < 0 ? 'var(--status-critical)' : 'var(--text-primary)' }}>{format(slack)}</span>
            </button>
            {selected === index && <div role="region" aria-label={t(`EP${index} 슬랙 상세`, `EP${index} slack details`)} className="mb-2 rounded-lg border border-[var(--border)] p-3 text-xs space-y-1 break-all">
              <p className="font-semibold">EP{index} · {id ?? t('종점 ID 미제공', 'Endpoint ID not provided')}</p>
              <p>{t('슬랙', 'Slack')} {slack} ps{isMinimum ? t(' · 표시된 종점 중 최소 슬랙', ' · lowest slack among shown endpoints') : ''}</p>
            </div>}
          </li>;
        })}
      </ol>
    </>}
  </figure>;
}

/* ---------- run status distribution (stacked bar, single row) ---------- */

const RUN_STATUS_COLOR: Record<"passed" | "failed" | "running" | "incomplete", string> = {
  passed: "var(--status-good)",
  failed: "var(--status-critical)",
  running: "var(--status-warning)",
  incomplete: "var(--text-muted)",
};

export function RunStatusBar({
  counts,
}: {
  counts: Record<"passed" | "failed" | "running" | "incomplete", number>;
}) {
  const { t } = useLanguage();
  const labels = { passed: t('통과', 'Passed'), failed: t('실패', 'Failed'), running: t('진행 중', 'Running'), incomplete: t('검증 미완료', 'Incomplete') };
  const { show, hide, node } = useTooltip();
  const total = counts.passed + counts.failed + counts.running + counts.incomplete;
  const order: ("passed" | "failed" | "running" | "incomplete")[] = ["passed", "failed", "running", "incomplete"];

  if (total === 0) {
    return (
      <p className="text-xs" style={{ color: "var(--text-muted)" }}>
        {t('아직 런이 없습니다.', 'No runs yet.')}
      </p>
    );
  }

  return (
    <div>
      <div
        className="flex h-3 w-full overflow-hidden rounded-full"
        style={{ background: "var(--seq-100)" }}
        role="img"
        aria-label={`${t('런 상태', 'Run status')}: ${order.map(key => `${labels[key]} ${counts[key]}`).join(', ')}`}
      >
        {order.map(
          (k) =>
            counts[k] > 0 && (
              <div
                key={k}
                style={{ width: `${(counts[k] / total) * 100}%`, background: RUN_STATUS_COLOR[k] }}
                onMouseMove={(e) =>
                  show(e, `${labels[k]} ${counts[k]} · ${((counts[k] / total) * 100).toFixed(0)}%`)
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
                {labels[k]} {counts[k]}
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
  const { t } = useLanguage();
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
        aria-label={t("게이트 도메인 준비율", "Gate domain readiness")}
      >
        <div className="h-full rounded-full" style={{ width: `${ratio * 100}%`, background: fill }} />
      </div>
      <span className="text-xs" style={{ color: "var(--text-muted)" }}>
        {ready}/{total} {t("준비됨", "ready")}
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
  const { t } = useLanguage();
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
          {t("기능 전력", "Functional power")}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: "var(--series-2)" }} />
          {t("글리치 전력", "Glitch power")}
        </span>
      </div>
      <svg
        width={width}
        height={nets.length * (barH + gap)}
        role="img"
        aria-label={t("네트별 전력 분해", "Power breakdown by net")}
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
                  show(e, `${n.name} · ${t("기능", "Functional")} ${n.functional_power_uw.toFixed(3)} µW`)
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
                    show(e, `${n.name} · ${t("글리치", "Glitch")} ${n.glitch_power_uw.toFixed(3)} µW`)
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
