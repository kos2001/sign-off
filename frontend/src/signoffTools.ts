import type { Domain } from './api';

export interface SignoffToolOption {
  value: string;
  label: string;
  description: string;
  workflow: string;
}

export const SIGNOFF_TOOLS: Record<Domain, readonly SignoffToolOption[]> = {
  rtl: [
    { value: 'Verilator + Yosys', label: 'Verilator + Yosys · 추천', description: 'RTL 린트·폭 검사와 합성 구조 검증을 함께 기록할 때 적합합니다.', workflow: '실제 실행은 RTL 분석에서 제공됩니다.' },
    { value: 'Verilator', label: 'Verilator', description: 'RTL 린트 또는 시뮬레이션 결과를 수동 등록할 때 사용합니다.', workflow: '이 화면에서는 외부 결과의 출처만 기록합니다.' },
    { value: 'Yosys', label: 'Yosys', description: '합성·구조 검사 결과를 수동 등록할 때 사용합니다.', workflow: '이 화면에서는 외부 결과의 출처만 기록합니다.' },
    { value: 'Synopsys VCS', label: 'Synopsys VCS', description: '상용 RTL 시뮬레이션 결과의 출처를 기록합니다.', workflow: '현재 자동 실행이나 결과 가져오기는 연결되지 않았습니다.' },
    { value: 'Cadence Xcelium', label: 'Cadence Xcelium', description: '상용 RTL 시뮬레이션 결과의 출처를 기록합니다.', workflow: '현재 자동 실행이나 결과 가져오기는 연결되지 않았습니다.' },
  ],
  sta: [
    { value: 'OpenSTA', label: 'OpenSTA · 추천', description: '정적 타이밍 경로와 슬랙을 검토할 때 적합합니다.', workflow: 'OpenSTA JSON 보고서 가져오기를 지원합니다.' },
    { value: 'Synopsys PrimeTime', label: 'Synopsys PrimeTime', description: '상용 정적 타이밍 분석 결과의 출처를 기록합니다.', workflow: '검증된 상용 STA 경로 JSON 가져오기를 지원합니다.' },
    { value: 'Cadence Tempus', label: 'Cadence Tempus', description: '상용 정적 타이밍 분석 결과의 출처를 기록합니다.', workflow: '검증된 상용 STA 경로 JSON 가져오기를 지원합니다.' },
  ],
  emir: [
    { value: 'Ansys RedHawk-SC', label: 'Ansys RedHawk-SC · 추천', description: 'IR drop과 전자이동 분석 결과의 출처를 기록합니다.', workflow: '검증된 상용 EM/IR 결과 JSON 가져오기를 지원합니다.' },
    { value: 'Cadence Voltus', label: 'Cadence Voltus', description: '전압 강하와 전력 무결성 분석 결과의 출처를 기록합니다.', workflow: '검증된 상용 EM/IR 결과 JSON 가져오기를 지원합니다.' },
    { value: 'Ansys Totem', label: 'Ansys Totem', description: '아날로그·혼합신호 전력 무결성 결과의 출처를 기록합니다.', workflow: '검증된 상용 EM/IR 결과 JSON 가져오기를 지원합니다.' },
  ],
  pv: [
    { value: 'KLayout DRC', label: 'KLayout DRC · 추천', description: 'DRC 마커와 도형을 검토할 때 적합합니다.', workflow: 'KLayout LYRDB 보고서 가져오기를 지원합니다.' },
    { value: 'Siemens Calibre nmDRC', label: 'Siemens Calibre nmDRC', description: '상용 물리 검증 결과의 출처를 기록합니다.', workflow: '검증된 상용 DRC 마커 JSON 가져오기를 지원합니다.' },
    { value: 'Cadence Pegasus', label: 'Cadence Pegasus', description: '상용 DRC 결과의 출처를 기록합니다.', workflow: '검증된 상용 DRC 마커 JSON 가져오기를 지원합니다.' },
  ],
  glitch_power: [
    { value: 'Synopsys PrimePower', label: 'Synopsys PrimePower · 추천', description: '글리치와 동적 전력 분석 결과의 출처를 기록합니다.', workflow: '검증된 상용 전력 요약 JSON 가져오기를 지원합니다.' },
    { value: 'Cadence Joules', label: 'Cadence Joules', description: 'RTL·게이트 전력 분석 결과의 출처를 기록합니다.', workflow: '검증된 상용 전력 요약 JSON 가져오기를 지원합니다.' },
    { value: 'Ansys PowerArtist', label: 'Ansys PowerArtist', description: 'RTL 전력 분석 결과의 출처를 기록합니다.', workflow: '검증된 상용 전력 요약 JSON 가져오기를 지원합니다.' },
  ],
  thermal: [
    { value: 'Cadence Celsius', label: 'Cadence Celsius · 추천', description: '칩·패키지 열 분석 결과의 출처를 기록합니다.', workflow: '현재 자동 실행이나 결과 가져오기는 연결되지 않았습니다.' },
    { value: 'Ansys Icepak', label: 'Ansys Icepak', description: '전자 시스템 열·유동 분석 결과의 출처를 기록합니다.', workflow: '현재 자동 실행이나 결과 가져오기는 연결되지 않았습니다.' },
    { value: 'Siemens Calibre 3DSTACK', label: 'Siemens Calibre 3DSTACK', description: '3D IC 열·물리 검증 결과의 출처를 기록합니다.', workflow: '현재 자동 실행이나 결과 가져오기는 연결되지 않았습니다.' },
  ],
};

export function defaultSignoffTool(domain: Domain): string {
  return SIGNOFF_TOOLS[domain][0].value;
}

export function signoffTool(domain: Domain, value: string): SignoffToolOption {
  return SIGNOFF_TOOLS[domain].find(option => option.value === value) ?? SIGNOFF_TOOLS[domain][0];
}
