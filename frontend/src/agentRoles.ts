export const AGENT_ROLES = {
  a1_rtl: { code: 'A1', name: 'RTL 리뷰어', condition: 'RTL 규칙 위반이 1건 이상일 때', evidence: '현재 RTL 결과의 규칙·단계 상태와 검사 메시지', output: '위반 원인 가설과 RTL 수정·재검증 방향', location: 'RTL 사인오프 래더', to: '/analysis/rtl' },
  a2_timing: { code: 'A2', name: '타이밍 분석가', condition: '머지 WNS가 0 ps보다 작을 때', evidence: '현재 코너별·머지 WNS/TNS, 종점 정보, PBA 추정', output: '제한 코너와 종점, 타이밍 개선을 위한 확인 항목', location: 'MMMC 타이밍', to: '/analysis/timing' },
  a3_power_ir: { code: 'A3', name: '파워/IR 무결성 분석가', condition: 'IR 스크리닝 미통과 또는 글리치 비중 30% 이상일 때', evidence: '현재 IR-drop 결과 또는 글리치 전력·네트별 분석', output: '핫스팟·전력 위험 해석과 추가 검증 방향', location: 'IR-drop · 글리치 파워', to: '/analysis/ir-drop' },
  a5_synth: { code: 'A5', name: '사인오프 종합 판정관', condition: '선택한 스테이지의 게이트가 통과 불가일 때', evidence: '현재 스테이지의 도메인별 준비 상태·런·차단 사유', output: '게이트 차단 사유와 우선순위별 조치', location: '프로젝트 상세 · 스테이지 게이트', to: '/' },
  v_verify: { code: 'V', name: '검증 에이전트', condition: 'A5 종합 검토가 성공적으로 끝난 뒤', evidence: 'A5에 전달한 원본 게이트 근거와 A5의 검토 의견', output: '원본 근거와 종합 의견의 일치·이견·검증 한계', location: '프로젝트 상세 · 종합 검토 다음 단계', to: '/' },
} as const;
export type AgentRoleId = keyof typeof AGENT_ROLES;
