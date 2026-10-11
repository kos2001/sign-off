import type { Domain } from './api';
import { tr } from './components/LanguageProvider';

export interface SignoffToolOption {
  value: string;
  label: string;
  description: string;
  workflow: string;
}

export const SIGNOFF_TOOLS: Record<Domain, readonly SignoffToolOption[]> = {
  rtl: [
    { value: 'Verilator + Yosys', get label() { return tr('Verilator + Yosys · 추천', 'Verilator + Yosys · Recommended'); }, get description() { return tr('RTL 린트·폭 검사와 합성 구조 검증을 함께 기록할 때 적합합니다.', 'Suited to recording RTL lint and width checks together with synthesis structure checks.'); }, get workflow() { return tr('실제 실행은 RTL 분석에서 제공됩니다.', 'Actual runs are available in RTL analysis.'); } },
    { value: 'Verilator', label: 'Verilator', get description() { return tr('RTL 린트 또는 시뮬레이션 결과를 수동 등록할 때 사용합니다.', 'Use when manually registering RTL lint or simulation results.'); }, get workflow() { return tr('이 화면에서는 외부 결과의 출처만 기록합니다.', 'This screen only records the source of external results.'); } },
    { value: 'Yosys', label: 'Yosys', get description() { return tr('합성·구조 검사 결과를 수동 등록할 때 사용합니다.', 'Use when manually registering synthesis and structure check results.'); }, get workflow() { return tr('이 화면에서는 외부 결과의 출처만 기록합니다.', 'This screen only records the source of external results.'); } },
    { value: 'Synopsys VCS', label: 'Synopsys VCS', get description() { return tr('상용 RTL 시뮬레이션 결과의 출처를 기록합니다.', 'Records the source of commercial RTL simulation results.'); }, get workflow() { return tr('검증된 상용 RTL 회귀 JSON 가져오기를 지원합니다.', 'Supports importing validated commercial RTL regression JSON.'); } },
    { value: 'Cadence Xcelium', label: 'Cadence Xcelium', get description() { return tr('상용 RTL 시뮬레이션 결과의 출처를 기록합니다.', 'Records the source of commercial RTL simulation results.'); }, get workflow() { return tr('검증된 상용 RTL 회귀 JSON 가져오기를 지원합니다.', 'Supports importing validated commercial RTL regression JSON.'); } },
  ],
  cdc: [
    { value: 'Synopsys VC SpyGlass CDC/RDC', get label() { return tr('Synopsys VC SpyGlass CDC/RDC · 추천', 'Synopsys VC SpyGlass CDC/RDC · Recommended'); }, get description() { return tr('Clock/reset domain crossing의 구조·기능·제약 문제를 정적 검증합니다.', 'Statically verifies structural, functional and constraint issues in clock/reset domain crossings.'); }, get workflow() { return tr('검증된 상용 CDC/RDC 결과 JSON 가져오기를 지원합니다.', 'Supports importing validated commercial CDC/RDC result JSON.'); } },
    { value: 'Cadence Jasper CDC', label: 'Cadence Jasper CDC', get description() { return tr('CDC와 RDC crossing 및 protocol 문제를 검증합니다.', 'Verifies CDC and RDC crossings and protocol issues.'); }, get workflow() { return tr('검증된 상용 CDC/RDC 결과 JSON 가져오기를 지원합니다.', 'Supports importing validated commercial CDC/RDC result JSON.'); } },
  ],
  dft: [
    { value: 'Synopsys TestMAX ATPG', get label() { return tr('Synopsys TestMAX ATPG · 추천', 'Synopsys TestMAX ATPG · Recommended'); }, get description() { return tr('Scan 구조와 ATPG fault coverage 및 pattern을 검증합니다.', 'Verifies scan structure, ATPG fault coverage and patterns.'); }, get workflow() { return tr('검증된 상용 DFT 결과 JSON 가져오기를 지원합니다.', 'Supports importing validated commercial DFT result JSON.'); } },
    { value: 'Siemens Tessent TestKompress', label: 'Siemens Tessent TestKompress', get description() { return tr('압축 scan과 ATPG 결과를 기록합니다.', 'Records compressed scan and ATPG results.'); }, get workflow() { return tr('검증된 상용 DFT 결과 JSON 가져오기를 지원합니다.', 'Supports importing validated commercial DFT result JSON.'); } },
    { value: 'Cadence Modus ATPG', label: 'Cadence Modus ATPG', get description() { return tr('DFT rule, scan chain, ATPG coverage 결과를 기록합니다.', 'Records DFT rule, scan chain and ATPG coverage results.'); }, get workflow() { return tr('검증된 상용 DFT 결과 JSON 가져오기를 지원합니다.', 'Supports importing validated commercial DFT result JSON.'); } },
  ],
  low_power: [
    { value: 'Synopsys VC LP', get label() { return tr('Synopsys VC LP · 추천', 'Synopsys VC LP · Recommended'); }, get description() { return tr('UPF 전력 의도와 저전력 구조·기능·PG 연결을 검증합니다.', 'Verifies UPF power intent and low-power structure, function and PG connectivity.'); }, get workflow() { return tr('검증된 상용 저전력 결과 JSON 가져오기를 지원합니다.', 'Supports importing validated commercial low-power result JSON.'); } },
    { value: 'Cadence Conformal Low Power', label: 'Cadence Conformal Low Power', get description() { return tr('Power domain, isolation, level shifter, retention 구현을 검증합니다.', 'Verifies power domain, isolation, level shifter and retention implementation.'); }, get workflow() { return tr('검증된 상용 저전력 결과 JSON 가져오기를 지원합니다.', 'Supports importing validated commercial low-power result JSON.'); } },
  ],
  sta: [
    { value: 'OpenSTA', get label() { return tr('OpenSTA · 추천', 'OpenSTA · Recommended'); }, get description() { return tr('정적 타이밍 경로와 슬랙을 검토할 때 적합합니다.', 'Suited to reviewing static timing paths and slack.'); }, get workflow() { return tr('OpenSTA JSON 보고서 가져오기를 지원합니다.', 'Supports importing OpenSTA JSON reports.'); } },
    { value: 'Synopsys PrimeTime', label: 'Synopsys PrimeTime', get description() { return tr('상용 정적 타이밍 분석 결과의 출처를 기록합니다.', 'Records the source of commercial static timing analysis results.'); }, get workflow() { return tr('검증된 상용 STA 경로 JSON 가져오기를 지원합니다.', 'Supports importing validated commercial STA path JSON.'); } },
    { value: 'Cadence Tempus', label: 'Cadence Tempus', get description() { return tr('상용 정적 타이밍 분석 결과의 출처를 기록합니다.', 'Records the source of commercial static timing analysis results.'); }, get workflow() { return tr('검증된 상용 STA 경로 JSON 가져오기를 지원합니다.', 'Supports importing validated commercial STA path JSON.'); } },
  ],
  emir: [
    { value: 'Ansys RedHawk-SC', get label() { return tr('Ansys RedHawk-SC · 추천', 'Ansys RedHawk-SC · Recommended'); }, get description() { return tr('IR drop과 전자이동 분석 결과의 출처를 기록합니다.', 'Records the source of IR drop and electromigration analysis results.'); }, get workflow() { return tr('검증된 상용 EM/IR 결과 JSON 가져오기를 지원합니다.', 'Supports importing validated commercial EM/IR result JSON.'); } },
    { value: 'Cadence Voltus', label: 'Cadence Voltus', get description() { return tr('전압 강하와 전력 무결성 분석 결과의 출처를 기록합니다.', 'Records the source of voltage drop and power integrity analysis results.'); }, get workflow() { return tr('검증된 상용 EM/IR 결과 JSON 가져오기를 지원합니다.', 'Supports importing validated commercial EM/IR result JSON.'); } },
    { value: 'Ansys Totem', label: 'Ansys Totem', get description() { return tr('아날로그·혼합신호 전력 무결성 결과의 출처를 기록합니다.', 'Records the source of analog and mixed-signal power integrity results.'); }, get workflow() { return tr('검증된 상용 EM/IR 결과 JSON 가져오기를 지원합니다.', 'Supports importing validated commercial EM/IR result JSON.'); } },
  ],
  pv: [
    { value: 'KLayout DRC', get label() { return tr('KLayout DRC · 추천', 'KLayout DRC · Recommended'); }, get description() { return tr('DRC 마커와 도형을 검토할 때 적합합니다.', 'Suited to reviewing DRC markers and shapes.'); }, get workflow() { return tr('KLayout LYRDB 보고서 가져오기를 지원합니다.', 'Supports importing KLayout LYRDB reports.'); } },
    { value: 'Siemens Calibre nmDRC', label: 'Siemens Calibre nmDRC', get description() { return tr('상용 물리 검증 결과의 출처를 기록합니다.', 'Records the source of commercial physical verification results.'); }, get workflow() { return tr('검증된 상용 DRC 마커 JSON 가져오기를 지원합니다.', 'Supports importing validated commercial DRC marker JSON.'); } },
    { value: 'Cadence Pegasus', label: 'Cadence Pegasus', get description() { return tr('상용 DRC 결과의 출처를 기록합니다.', 'Records the source of commercial DRC results.'); }, get workflow() { return tr('검증된 상용 DRC 마커 JSON 가져오기를 지원합니다.', 'Supports importing validated commercial DRC marker JSON.'); } },
  ],
  lvs: [
    { value: 'Siemens Calibre nmLVS', get label() { return tr('Siemens Calibre nmLVS · 추천', 'Siemens Calibre nmLVS · Recommended'); }, get description() { return tr('레이아웃과 회로도 넷리스트의 연결·소자 일치를 검증합니다.', 'Verifies that connectivity and devices match between the layout and the schematic netlist.'); }, get workflow() { return tr('검증된 상용 LVS 결과 JSON 가져오기를 지원합니다.', 'Supports importing validated commercial LVS result JSON.'); } },
    { value: 'Cadence Pegasus LVS', label: 'Cadence Pegasus LVS', get description() { return tr('Pegasus LVS 비교 결과의 출처를 기록합니다.', 'Records the source of Pegasus LVS comparison results.'); }, get workflow() { return tr('검증된 상용 LVS 결과 JSON 가져오기를 지원합니다.', 'Supports importing validated commercial LVS result JSON.'); } },
  ],
  lec: [
    { value: 'Synopsys Formality', get label() { return tr('Synopsys Formality · 추천', 'Synopsys Formality · Recommended'); }, get description() { return tr('RTL reference와 합성·ECO implementation의 논리 등가성을 검증합니다.', 'Verifies logical equivalence between the RTL reference and the synthesis/ECO implementation.'); }, get workflow() { return tr('검증된 상용 LEC 결과 JSON 가져오기를 지원합니다.', 'Supports importing validated commercial LEC result JSON.'); } },
    { value: 'Cadence Conformal', label: 'Cadence Conformal', get description() { return tr('compare point별 논리 등가성 결과를 기록합니다.', 'Records logical equivalence results per compare point.'); }, get workflow() { return tr('검증된 상용 LEC 결과 JSON 가져오기를 지원합니다.', 'Supports importing validated commercial LEC result JSON.'); } },
  ],
  glitch_power: [
    { value: 'Synopsys PrimePower', get label() { return tr('Synopsys PrimePower · 추천', 'Synopsys PrimePower · Recommended'); }, get description() { return tr('글리치와 동적 전력 분석 결과의 출처를 기록합니다.', 'Records the source of glitch and dynamic power analysis results.'); }, get workflow() { return tr('검증된 상용 전력 요약 JSON 가져오기를 지원합니다.', 'Supports importing validated commercial power summary JSON.'); } },
    { value: 'Cadence Joules', label: 'Cadence Joules', get description() { return tr('RTL·게이트 전력 분석 결과의 출처를 기록합니다.', 'Records the source of RTL and gate-level power analysis results.'); }, get workflow() { return tr('검증된 상용 전력 요약 JSON 가져오기를 지원합니다.', 'Supports importing validated commercial power summary JSON.'); } },
    { value: 'Ansys PowerArtist', label: 'Ansys PowerArtist', get description() { return tr('RTL 전력 분석 결과의 출처를 기록합니다.', 'Records the source of RTL power analysis results.'); }, get workflow() { return tr('검증된 상용 전력 요약 JSON 가져오기를 지원합니다.', 'Supports importing validated commercial power summary JSON.'); } },
  ],
  thermal: [
    { value: 'Cadence Celsius', get label() { return tr('Cadence Celsius · 추천', 'Cadence Celsius · Recommended'); }, get description() { return tr('칩·패키지 열 분석 결과의 출처를 기록합니다.', 'Records the source of chip and package thermal analysis results.'); }, get workflow() { return tr('검증된 상용 열 핫스폿 JSON 가져오기를 지원합니다.', 'Supports importing validated commercial thermal hotspot JSON.'); } },
    { value: 'Ansys Icepak', label: 'Ansys Icepak', get description() { return tr('전자 시스템 열·유동 분석 결과의 출처를 기록합니다.', 'Records the source of electronic system thermal and flow analysis results.'); }, get workflow() { return tr('검증된 상용 열 핫스폿 JSON 가져오기를 지원합니다.', 'Supports importing validated commercial thermal hotspot JSON.'); } },
    { value: 'Siemens Calibre 3DSTACK', label: 'Siemens Calibre 3DSTACK', get description() { return tr('3D IC 열·물리 검증 결과의 출처를 기록합니다.', 'Records the source of 3D IC thermal and physical verification results.'); }, get workflow() { return tr('검증된 상용 열 핫스폿 JSON 가져오기를 지원합니다.', 'Supports importing validated commercial thermal hotspot JSON.'); } },
  ],
};

export function defaultSignoffTool(domain: Domain): string {
  return SIGNOFF_TOOLS[domain][0].value;
}

export function signoffTool(domain: Domain, value: string): SignoffToolOption {
  return SIGNOFF_TOOLS[domain].find(option => option.value === value) ?? SIGNOFF_TOOLS[domain][0];
}
