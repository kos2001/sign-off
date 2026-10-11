import type { OpenLaneDomainResult } from '../api';
import { formatNumber, useLanguage } from './LanguageProvider';

// OpenLane has no antenna checker; antenna counts are advisory, every other count blocks.
const WARNING_COUNTS = new Set(['antenna_nets', 'antenna_pins']);

function value(number: number | null | undefined, digits = 1) {
  return number === null || number === undefined ? '—' : formatNumber(number, { maximumFractionDigits: digits });
}

/** Design size, power and IR figures shared by every run of one OpenLane import. */
export function OpenLaneDesignSummary({ summary }: { summary: Record<string, number | null> }) {
  const { t } = useLanguage();
  const rows: [string, string, number | null | undefined, number][] = [
    ['instances', t('인스턴스', 'Instances'), summary.instances, 0],
    ['area', t('셀 면적 (µm²)', 'Cell area (µm²)'), summary.instance_area_um2, 0],
    ['utilization', t('배치 밀도', 'Utilization'), summary.utilization, 3],
    ['wirelength', t('배선 길이 (µm)', 'Wirelength (µm)'), summary.wirelength_um, 0],
    ['power', t('전체 전력 (mW)', 'Total power (mW)'), summary.total_power_mw, 3],
    ['ir', t('최악 IR drop (mV)', 'Worst IR drop (mV)'), summary.worst_ir_drop_mv, 3],
  ];
  return <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
    {rows.map(([key, label, number, digits]) => <div key={key} className="rounded-lg border p-2">
      <dt className="text-xs text-[var(--text-muted)]">{label}</dt><dd className="font-mono">{value(number, digits)}</dd>
    </div>)}
  </dl>;
}

/** One sign-off domain from an OpenLane metrics file: corner table or counts, then findings. */
export function OpenLaneDomainSummary({ result }: { result: OpenLaneDomainResult }) {
  const { t } = useLanguage();
  const countLabels: Record<string, string> = {
    route_drc: t('배선 DRC', 'Route DRC'), magic_drc: t('Magic DRC', 'Magic DRC'), klayout_drc: t('KLayout DRC', 'KLayout DRC'),
    illegal_overlap: t('셀 겹침', 'Illegal overlaps'), xor: t('XOR 차이', 'XOR differences'),
    disconnected_pin: t('끊어진 주요 핀', 'Critical disconnected pins'), power_grid: t('전원망(PDN) 위반', 'Power-grid (PDN) violations'),
    antenna_nets: t('안테나 위반 넷', 'Antenna-violating nets'), antenna_pins: t('안테나 위반 핀', 'Antenna-violating pins'),
    lvs_errors: t('LVS 오류', 'LVS errors'), device_difference: t('소자 수 차이', 'Device count differences'),
    net_difference: t('넷 수 차이', 'Net count differences'), unmatched_device: t('미매칭 소자', 'Unmatched devices'),
    unmatched_net: t('미매칭 넷', 'Unmatched nets'), unmatched_pin: t('미매칭 핀', 'Unmatched pins'),
    property_fail: t('속성 불일치', 'Property failures'),
  };
  const blocking = result.items.filter(item => item.severity === 'error').length;
  return <div className="space-y-2">
    {result.corners ? <div className="overflow-x-auto"><table className="w-full text-xs">
      <caption className="sr-only">{t('코너별 타이밍', 'Timing by corner')}</caption>
      <thead><tr className="text-left text-[var(--text-muted)]">
        <th scope="col" className="p-1">{t('코너', 'Corner')}</th>
        <th scope="col" className="p-1 text-right">{t('Setup WNS (ps)', 'Setup WNS (ps)')}</th>
        <th scope="col" className="p-1 text-right">{t('Setup 위반', 'Setup violations')}</th>
        <th scope="col" className="p-1 text-right">{t('Hold WNS (ps)', 'Hold WNS (ps)')}</th>
        <th scope="col" className="p-1 text-right">{t('Hold 위반', 'Hold violations')}</th>
        <th scope="col" className="p-1 text-right">{t('Slew / Cap / Fanout', 'Slew / Cap / Fanout')}</th>
      </tr></thead>
      <tbody>{result.corners.map(row => <tr key={row.corner} className="border-t font-mono">
        <th scope="row" className="p-1 text-left font-normal break-all">{row.corner}</th>
        <td className={`p-1 text-right ${(row.setup_ws_ps ?? 0) < 0 ? 'text-[var(--status-critical)]' : ''}`}>{value(row.setup_ws_ps)}</td>
        <td className="p-1 text-right">{value(row.setup_violations, 0)}</td>
        <td className={`p-1 text-right ${(row.hold_ws_ps ?? 0) < 0 ? 'text-[var(--status-critical)]' : ''}`}>{value(row.hold_ws_ps)}</td>
        <td className="p-1 text-right">{value(row.hold_violations, 0)}</td>
        <td className="p-1 text-right">{value(row.max_slew_violations, 0)} / {value(row.max_cap_violations, 0)} / {value(row.max_fanout_violations, 0)}</td>
      </tr>)}</tbody>
    </table></div> : <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
      {Object.entries(result.metrics).map(([key, number]) => <div key={key}>
        <dt className="text-xs text-[var(--text-muted)]">{countLabels[key] ?? key}</dt>
        <dd className={`font-mono ${!number ? '' : WARNING_COUNTS.has(key) ? 'text-[var(--status-warning)]' : 'text-[var(--status-critical)]'}`}>{value(number, 0)}</dd>
      </div>)}
    </dl>}
    <p className="text-sm">{blocking
      ? t(`차단 finding ${blocking}건 · 전체 ${result.items.length}건`, `${blocking} blocking finding${blocking === 1 ? '' : 's'} · ${result.items.length} total`)
      : result.items.length ? t(`경고 ${result.items.length}건, 차단 finding 없음`, `${result.items.length} warning${result.items.length === 1 ? '' : 's'}, no blocking findings`)
        : t('보고된 위반 없음', 'No violations reported')}</p>
    {result.missing.length > 0 && <p className="text-xs text-[var(--status-warning)]">{t('보고되지 않은 지표', 'Metrics not reported')}: {result.missing.join(', ')}</p>}
    <p className="text-xs text-[var(--text-muted)]">{{
      sta: t('플로우가 보고한 코너별 최악 슬랙만 포함합니다. 제약, 코너 구성, 기생 성분과 경로 상세는 확인되지 않았습니다.', 'Flow-reported worst slack per corner only. Constraints, corner set, parasitics and path detail are not established.'),
      pv: t('플로우가 보고한 위반 개수만 포함합니다. 마커 위치, 룰덱과 파운드리 사인오프 DRC는 확인되지 않았습니다.', 'Flow-reported violation counts only. Marker locations, rule decks and foundry sign-off DRC are not established.'),
      lvs: t('Netgen 비교 개수만 포함합니다. 추출 덱, 계층과 불일치 상세는 확인되지 않았습니다.', 'Netgen comparison counts only. Extraction deck, hierarchy and mismatch detail are not established.'),
    }[result.domain]}</p>
  </div>;
}
