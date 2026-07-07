import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";
import { IrDropHeatmap, PowerStackBars, SlackBars } from "../components/charts";
import { Card, Meter, StatTile, StatusBadge } from "../components/ui";

/* Real design example: lowRISC Ibex RISC-V core hardened on SkyWater SKY130
   (the OpenROAD/OpenLane reference flow). VDD 1.8V, clk 10ns (100MHz), SKY130
   liberty corner names, Ibex module/net names. Values are representative of a
   100MHz Ibex build; deterministic so refetches don't repaint the story. */

function ibexFloorplanGrids(size = 10) {
  const density: number[][] = [];
  const activity: number[][] = [];
  const strength: number[][] = [];
  for (let r = 0; r < size; r++) {
    const dRow: number[] = [];
    const aRow: number[] = [];
    const sRow: number[] = [];
    for (let c = 0; c < size; c++) {
      // multdiv_fast cluster near (2,7): dense and busy; register file corner
      // near (7,2) sits far from the M4 power straps (weak PDN)
      const multdiv = Math.exp(-((r - 2) ** 2 + (c - 7) ** 2) / 6);
      const regfile = Math.exp(-((r - 7) ** 2 + (c - 2) ** 2) / 8);
      dRow.push(Math.min(1, 0.25 + 0.65 * multdiv + 0.2 * regfile));
      aRow.push(Math.min(1, 0.2 + 0.7 * multdiv + 0.3 * regfile));
      sRow.push(Math.max(0.35, 1.1 - 0.6 * regfile));
    }
    density.push(dRow);
    activity.push(aRow);
    strength.push(sRow);
  }
  return { cell_density: density, switching_activity: activity, pdn_strength: strength };
}

// Glitch-prone nets in ibex_multdiv_fast / ibex_alu (deep arithmetic logic)
const IBEX_NETS = [
  { name: "alu_adder_result_ex_o[31]", cap_ff: 22, functional_toggle_rate: 0.22, total_toggle_rate: 0.61 },
  { name: "multdiv/mac_res[15]", cap_ff: 26, functional_toggle_rate: 0.31, total_toggle_rate: 0.78, transport_fraction: 0.8 },
  { name: "multdiv/imd_val_d[0][7]", cap_ff: 14, functional_toggle_rate: 0.18, total_toggle_rate: 0.33 },
  { name: "alu/cmp_result", cap_ff: 9, functional_toggle_rate: 0.12, total_toggle_rate: 0.41, transport_fraction: 0.6 },
  { name: "multdiv/alu_operand_a[19]", cap_ff: 21, functional_toggle_rate: 0.28, total_toggle_rate: 0.84 },
];

// SKY130 liberty corners; 12 worst setup endpoints of the ID->EX stage @ 100MHz
const IBEX_CORNERS = [
  { name: "ss_100C_1v60", endpoint_slacks_ps: [-320, -145, 60, -85, 210, 310, -30, 140, 480, -230, 95, 170] },
  { name: "tt_025C_1v80", endpoint_slacks_ps: [-80, 25, 250, 90, 400, 450, 40, 280, 600, -60, 210, 330] },
  { name: "ff_n40C_1v95", endpoint_slacks_ps: [120, 45, 380, 200, 550, 610, 85, 420, 770, 30, 300, 440] },
];

export default function Analysis() {
  return (
    <div className="space-y-6">
      <IrDropSection />
      <TimingSection />
      <GlitchSection />
    </div>
  );
}

function IrDropSection() {
  const run = useMutation({
    mutationFn: () => api.irDrop({ ...ibexFloorplanGrids(), vdd: 1.8, scale: 0.06 }),
  });

  return (
    <Card
      title="IR-drop 사전 스크리닝 — Ibex @ SKY130"
      subtitle="물리 기반 서로게이트 (arXiv:2601.22707) · VDD 1.8V, 임계 5% (90mV) — 골든 EM/IR 사인오프 전 핫스팟 탐지"
      actions={
        <button className="btn btn-primary" onClick={() => run.mutate()} disabled={run.isPending}>
          Ibex 플로어플랜 분석
        </button>
      }
    >
      {run.data ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatTile
              label="최악 IR-drop"
              value={run.data.worst_drop_mv.toFixed(1)}
              suffix="mV"
              tone={run.data.passed ? "good" : "critical"}
            />
            <StatTile label="평균 IR-drop" value={run.data.mean_drop_mv.toFixed(1)} suffix="mV" />
            <StatTile label="핫스팟" value={run.data.hotspot_count} suffix="타일" />
            <StatTile label="임계값" value={run.data.threshold_mv.toFixed(0)} suffix="mV" />
          </div>
          <StatusBadge
            status={run.data.passed ? "good" : "critical"}
            label={run.data.passed ? "스크리닝 통과" : "핫스팟 검출 — 골든 사인오프 필요"}
          />
          <IrDropHeatmap map={run.data.drop_map_mv} thresholdMv={run.data.threshold_mv} />
        </div>
      ) : (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          Ibex RISC-V 코어(lowRISC)의 10×10 타일 플로어플랜 — multdiv_fast 고활동 클러스터와 M4
          파워 스트랩에서 먼 레지스터 파일 코너(취약 PDN)를 포함합니다.
        </p>
      )}
    </Card>
  );
}

function TimingSection() {
  const [credit, setCredit] = useState(15);
  const run = useMutation({
    mutationFn: () =>
      api.timingSummary({ corners: IBEX_CORNERS, pba_pessimism_credit_ps: credit }),
  });

  return (
    <Card
      title="MMMC 타이밍 요약 — Ibex @ SKY130, 100MHz"
      subtitle="SKY130 3코너(ss/tt/ff) WNS/TNS 집계 + 엔드포인트 머지 + GBA→PBA 비관성 크레딧 추정"
      actions={
        <div className="flex items-end gap-2">
          <label className="text-xs" style={{ color: "var(--text-secondary)" }}>
            PBA 크레딧 (ps)
            <input
              type="number"
              className="input ml-2 w-20"
              value={credit}
              min={0}
              onChange={(e) => setCredit(Number(e.target.value))}
            />
          </label>
          <button className="btn btn-primary" onClick={() => run.mutate()} disabled={run.isPending}>
            3코너 분석
          </button>
        </div>
      }
    >
      {run.data ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatTile
              label="머지 WNS"
              value={run.data.merged.wns_ps.toFixed(1)}
              suffix="ps"
              tone={run.data.merged.wns_ps < 0 ? "critical" : "good"}
            />
            <StatTile label="머지 TNS" value={run.data.merged.tns_ps.toFixed(1)} suffix="ps" />
            <StatTile
              label="위반 엔드포인트"
              value={`${run.data.merged.violating_endpoints}/${run.data.merged.total_endpoints}`}
            />
            {run.data.estimated_pba && (
              <StatTile
                label="PBA 크레딧 후 회복"
                value={run.data.estimated_pba.recovered_endpoints}
                suffix="EP"
                tone="good"
              />
            )}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm" style={{ fontVariantNumeric: "tabular-nums" }}>
              <thead>
                <tr className="text-left text-xs" style={{ color: "var(--text-muted)" }}>
                  <th className="py-1.5 font-medium">코너</th>
                  <th className="py-1.5 text-right font-medium">WNS (ps)</th>
                  <th className="py-1.5 text-right font-medium">TNS (ps)</th>
                  <th className="py-1.5 text-right font-medium">위반 EP</th>
                </tr>
              </thead>
              <tbody>
                {run.data.corners.map((c) => (
                  <tr key={c.name} className="hairline-t">
                    <td className="py-1.5">{c.name}</td>
                    <td
                      className="py-1.5 text-right"
                      style={{ color: c.wns_ps < 0 ? "var(--status-critical)" : "var(--delta-good-text)" }}
                    >
                      {c.wns_ps.toFixed(1)}
                    </td>
                    <td className="py-1.5 text-right">{c.tns_ps.toFixed(1)}</td>
                    <td className="py-1.5 text-right">
                      {c.violating_endpoints}/{c.total_endpoints}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div>
            <h3 className="mb-2 text-xs font-medium" style={{ color: "var(--text-muted)" }}>
              머지 엔드포인트 슬랙 (코너별 최악값)
            </h3>
            <SlackBars
              slacks={IBEX_CORNERS[0].endpoint_slacks_ps.map((_, i) =>
                Math.min(...IBEX_CORNERS.map((c) => c.endpoint_slacks_ps[i])),
              )}
            />
          </div>
        </div>
      ) : (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          SKY130 리버티 코너 ss_100C_1v60 / tt_025C_1v80 / ff_n40C_1v95, ID→EX 스테이지 최악
          셋업 엔드포인트 12개로 MMMC 머지를 실행합니다.
        </p>
      )}
    </Card>
  );
}

function GlitchSection() {
  const run = useMutation({
    mutationFn: () => api.glitchPower({ nets: IBEX_NETS, vdd: 1.8, clock_period_ns: 10 }),
  });

  return (
    <Card
      title="벡터리스 글리치 파워 추정 — Ibex ALU/MULTDIV"
      subtitle="토글률 초과분 기반 (Synopsys US 12,001,768 방식 단순화) · VDD 1.8V, clk 10ns — 깊은 연산 로직이 글리치에 취약"
      actions={
        <button className="btn btn-primary" onClick={() => run.mutate()} disabled={run.isPending}>
          Ibex 네트 분석
        </button>
      }
    >
      {run.data ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <StatTile
              label="총 동적 전력"
              value={(run.data.total_dynamic_power_mw * 1000).toFixed(2)}
              suffix="µW"
            />
            <StatTile
              label="글리치 전력"
              value={(run.data.glitch_power_mw * 1000).toFixed(2)}
              suffix="µW"
            />
            <StatTile
              label="글리치 비중"
              value={`${(run.data.glitch_share * 100).toFixed(1)}%`}
              tone={run.data.glitch_share >= 0.5 ? "critical" : undefined}
            />
          </div>
          <div>
            <div className="mb-1.5 flex justify-between text-xs" style={{ color: "var(--text-muted)" }}>
              <span>글리치 비중</span>
              <span>경고 30% · 위험 50%</span>
            </div>
            <Meter ratio={run.data.glitch_share} />
          </div>
          <PowerStackBars nets={run.data.nets} />
        </div>
      ) : (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          ibex_alu / ibex_multdiv_fast의 글리치 취약 네트 5개(가산기 출력, MAC 결과, 중간값
          레지스터 입력 등)로 추정을 실행합니다.
        </p>
      )}
    </Card>
  );
}
