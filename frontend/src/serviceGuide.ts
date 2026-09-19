export type GuideLanguage = 'ko' | 'en';
export const guideSections = ['overview', 'workflow', 'capabilities', 'agents', 'start'] as const;
export type GuideSection = typeof guideSections[number];
type Item = { title: string; body: string; detail?: string; to?: string };
type Page = { eyebrow: string; title: string; intro: string; items: Item[]; note: string };
type GuideCopy = {
  nav: Record<GuideSection, string>; workspace: string; skip: string; next: string;
  purpose: string; scope: string; flow: string[]; flowLabel: string;
  pages: Record<GuideSection, Page>;
};
export const guideCopy: Record<GuideLanguage, GuideCopy> = {
  ko: {
    nav: { overview: '서비스 개요', workflow: '개발 흐름 속 위치', capabilities: '기능과 검증 범위', agents: '에이전트와 사람', start: '시작하기' },
    workspace: '작업 공간 열기', skip: '본문으로 이동', next: '다음 안내',
    purpose: '설계 결과를 모아, 다음 단계로 진행할 근거를 만듭니다.',
    scope: 'RTL부터 최종 사인오프까지 · 근거 수집, 검토, 승인 이력',
    flow: ['RTL 설계', '합성', '배치', '배선', '최종 검토'], flowLabel: '각 단계에 걸쳐 검증 근거와 승인 결정을 연결합니다.',
    pages: {
      overview: {
        eyebrow: 'SIGN-OFF HUB / 서비스 소개', title: '칩 설계의 검증 근거를 하나의 결정으로.',
        intro: 'Sign-off Hub는 RTL·타이밍·물리 검증 결과를 설계 리비전에 묶고, 위반과 예외를 검토해 단계별 진행 여부를 판단하는 사인오프 관리·분석 서비스입니다. 설계자, 검증 담당자, 승인자가 같은 근거를 보고 협업합니다.',
        items: [
          { title: '무엇이 문제인가요?', body: '도구마다 흩어진 보고서와 서로 다른 설계 버전으로는 “이번 리비전이 다음 단계로 갈 준비가 됐는가”를 판단하기 어렵습니다.', detail: '검증 결과를 프로젝트·리비전·단계·도메인으로 연결합니다.' },
          { title: '어떤 결정을 돕나요?', body: '필수 검증이 모두 있는지, 차단 위반이 남았는지, 웨이버가 현재 설계에도 유효한지 확인합니다.', detail: '게이트는 규칙 기반 준비 상태이며, 최종 승인·차단은 권한을 가진 사람이 기록합니다.' },
          { title: '무엇이 남나요?', body: '실행 근거, 위반 처리 사유, 후보 리비전과 승인 당시 스냅샷을 보존합니다. 팀은 변경 전후를 비교하고 승인 결정을 추적할 수 있습니다.', detail: '결정 원장을 내보내 외부에서 무결성을 검증할 수 있습니다.' },
        ],
        note: '이 서비스는 설계·검증 도구를 연결하는 검토와 의사결정 계층입니다. 실제 제조 승인은 해당 공정의 검증된 도구, 파운드리 규칙과 조직의 승인 절차를 함께 충족해야 합니다.',
      },
      workflow: {
        eyebrow: 'DEVELOPMENT LIFECYCLE', title: '최종 검토 전부터, 개발의 각 단계에 함께.',
        intro: '설계와 구현은 EDA 도구에서 진행합니다. Sign-off Hub는 각 단계의 실행 결과를 받아 준비 상태를 평가하고, 문제를 수정한 뒤 다시 검증하는 반복 작업을 관리합니다. 마지막 단계에 결과를 모으는 대신 앞 단계부터 근거를 쌓습니다.',
        items: [
          { title: '01 / RTL 설계·검증', body: 'RTL 작성과 시뮬레이션 뒤에 린트, 구조 규칙, 합성 가능성 또는 외부 RTL·CDC·LEC 결과를 검토합니다.', detail: '입력: RTL·테스트벤치·보고서 → 출력: 위반과 실행 근거. 구조 기반 검사는 전체 CDC·형식 검증의 증명이 아닙니다.', to: '/analysis/rtl' },
          { title: '02 / 합성', body: '합성 넷리스트와 Liberty·SDC를 사용한 타이밍 결과를 연결하고, 리비전별 필수 검증 누락을 확인합니다.', detail: '입력: 넷리스트·타이밍 제약·라이브러리 → 출력: 타이밍 경로와 단계 게이트.', to: '/analysis/sta' },
          { title: '03 / 배치', body: '배치 도구의 결과를 바탕으로 타이밍·전력·전원망 위험을 조기에 검토합니다. 스크리닝 결과와 실제 도구의 검증 결과를 구분합니다.', detail: '입력: 배치 단계 보고서·스크리닝 입력 → 출력: 위험 영역과 재검증 항목.', to: '/analysis/ir-drop' },
          { title: '04 / 배선', body: '배선 후 기생 성분을 반영한 타이밍과 DRC·LVS·EM/IR 등 외부 도구 결과를 같은 설계 리비전에 연결합니다.', detail: '입력: 배선 단계 검증 보고서 → 출력: 도메인별 차단 사유와 위반 처리 이력.', to: '/' },
          { title: '05 / 최종 검토·인계', body: '필수 도메인과 시나리오, 미해결 위반, 웨이버 범위를 확인하고 릴리스 후보를 고정합니다. 승인자가 근거 스냅샷을 검토한 뒤 승인 또는 차단을 기록합니다.', detail: '출력: 보존된 승인 근거·결정 원장. 테이프아웃 제출과 제조는 별도 절차입니다.', to: '/' },
        ],
        note: '반복 흐름: 보고서 수집 → 게이트 평가 → 위반 검토 → 설계 수정 → 외부 도구 재실행 → 새 근거 수집. 설계 수정과 배치·배선 자체를 이 서비스가 자동 수행하지는 않습니다.',
      },
      capabilities: {
        eyebrow: 'CAPABILITIES & BOUNDARIES', title: '실행, 수집, 추정의 범위를 구분합니다.',
        intro: '모든 결과가 같은 수준의 검증을 의미하지는 않습니다. 실제 도구 실행의 근거, 외부 보고서, 빠른 추정 분석을 구분하고 프로젝트의 필수 검증 계획에 맞춰 사용하세요.',
        items: [
          { title: '실제 도구 실행 / RTL·OpenSTA', body: '설정된 실행 환경에서 RTL 린트·시뮬레이션·합성과 OpenSTA 타이밍을 수행하고 로그와 근거를 저장합니다.', detail: '도구·격리 실행 환경이 준비되어야 합니다. 입력 제약과 라이브러리의 정확성은 사용자가 검토합니다.', to: '/analysis' },
          { title: '외부 결과 수집 / 상용 EDA·KLayout', body: '지원되는 형식으로 타이밍, DRC, LVS, RTL, CDC, LEC, DFT, 저전력, 전력, EM/IR, 열 분석 결과를 가져옵니다.', detail: '원본 도구와 룰덱의 정확성을 인증하는 기능은 아닙니다. 지원되는 어댑터 형식과 검증 범위 근거가 필요합니다.', to: '/' },
          { title: '빠른 분석 / 위험 스크리닝', body: 'IR-drop 스크리닝, MMMC 요약·PBA 추정, 글리치 전력 분석으로 위험을 탐색합니다.', detail: '예제·추정 결과는 공정 검증이나 제조 승인 근거를 대신하지 않습니다.', to: '/analysis/ir-drop' },
          { title: '검토와 승인 / 근거의 연결', body: '리비전 매트릭스, 단계 게이트, 위반 처리, 웨이버, 후보 고정과 승인 패키지로 검토 과정을 관리합니다.', detail: '게이트 통과와 사람의 승인 기록은 별개입니다. 서명 기능은 운영 서명키를 설정한 경우에 사용됩니다.', to: '/' },
        ],
        note: '사인오프는 검증 근거를 확인하고 다음 단계 진행을 승인하는 절차입니다. 웨이버는 위험을 없애는 것이 아니라, 정해진 범위와 유효기간에서 예외를 승인하는 기록입니다.',
      },
      agents: {
        eyebrow: 'HERMES / REVIEW RESPONSIBILITIES', title: '에이전트는 해석을 돕고, 사람이 결정합니다.',
        intro: '수치와 위반은 분석 도구가 계산하고 게이트는 서비스 규칙으로 평가합니다. Hermes 에이전트는 조건에 해당하는 근거를 읽어 원인 가설과 다음 확인 항목을 제안합니다. AI 의견이 설계 승인으로 바뀌지는 않습니다.',
        items: [
          { title: 'A1 / RTL 리뷰어', body: 'RTL 규칙 위반이 있을 때 규칙·단계 상태와 검사 메시지를 읽습니다.', detail: '위반 원인 가설과 수정·재검증 방향을 제공합니다.', to: '/analysis/rtl' },
          { title: 'A2 / 타이밍 분석가', body: 'MMMC 분석의 머지 WNS가 0 ps보다 작을 때 코너별 WNS/TNS와 종점 정보를 읽습니다.', detail: '제한 코너와 타이밍 개선을 위한 확인 항목을 제안합니다.', to: '/analysis/timing' },
          { title: 'A3 / 파워·IR 분석가', body: 'IR 스크리닝 미통과 또는 글리치 비중 30% 이상일 때 현재 결과를 읽습니다.', detail: '핫스팟·전력 위험과 추가 검증 방향을 설명합니다.', to: '/analysis/ir-drop' },
          { title: 'A5 → V / 종합 검토와 대조', body: '단계 게이트가 통과 불가일 때 A5가 차단 사유를 검토합니다. A5가 완료되면 V가 의견을 원본 게이트 근거와 대조합니다.', detail: '검토 완료는 설계 통과를 뜻하지 않습니다. 연결 실패나 선행 검토 미완료는 화면에 표시됩니다.', to: '/' },
          { title: '사람 / 위반 처리·웨이버·승인', body: '담당자는 근거와 의견을 확인하고 수정·재검증을 진행합니다. 권한을 가진 승인자는 웨이버와 최종 결정을 기록합니다.', detail: 'A4 웨이버 심사관은 역할 정의만 있으며 자동 승인 과정에 연결되지 않았습니다.', to: '/agents' },
        ],
        note: '분석·게이트 화면의 자동 의견은 저장되지 않습니다. 보존할 의견은 실행 근거에서 「AI 검토 요청 · 기록 저장」으로 별도 요청하세요. 저장된 AI 검토와 사람의 승인 이력은 구분됩니다.',
      },
      start: {
        eyebrow: 'GETTING STARTED', title: '한 개의 리비전, 한 번의 검증부터.',
        intro: '처음에는 작은 설계로 입력과 결과의 연결을 확인하세요. 인증이 필요한 배포에서는 관리자가 발급한 계정으로 접속합니다.',
        items: [
          { title: '01 / 프로젝트와 검증 계획', body: '프로젝트를 선택하거나 만들고 공정·파운드리 정보를 확인합니다. 단계별 필수 도메인과 타이밍 시나리오를 정합니다.', detail: '팀에서는 조회·편집·승인 역할을 나누고 같은 검증 기준을 사용하세요.', to: '/' },
          { title: '02 / 실행하거나 보고서 가져오기', body: 'RTL·OpenSTA 도구를 실행하거나 프로젝트에서 외부 결과를 가져옵니다. 실제 설계 리비전을 지정하고 원본 보고서·로그를 함께 보존합니다.', detail: '예제 입력으로 흐름을 익힌 뒤 실제 입력으로 교체하세요.', to: '/analysis' },
          { title: '03 / 누락과 차단 사유 검토', body: '프로젝트의 리비전 검증 매트릭스와 단계 게이트를 확인합니다. 위반을 수정·재검증하거나 사유와 범위를 명시해 웨이버를 검토합니다.', detail: 'AI 의견을 사용할 때는 원본 근거와 대조하고 저장 필요 여부를 결정하세요.', to: '/' },
          { title: '04 / 후보 고정과 승인 기록', body: '승인자가 후보 리비전을 고정하고 현재 근거 스냅샷을 확인합니다. 승인·차단을 기록한 뒤 근거 패키지와 감사 원장을 보존합니다.', detail: '근거가 변경되면 새 스냅샷을 다시 검토해야 합니다.', to: '/' },
        ],
        note: '준비물: 설계 리비전 식별자, 검증 대상과 제약, 도구 실행 환경 또는 지원 형식의 보고서, 팀의 검증·승인 기준. Hermes 연결은 선택 사항이며 실제 개입 여부는 각 검토 카드에서 확인합니다.',
      },
    },
  },
  en: {
    nav: { overview: 'Overview', workflow: 'Development workflow', capabilities: 'Capabilities & scope', agents: 'Agents & people', start: 'Getting started' },
    workspace: 'Open workspace', skip: 'Skip to content', next: 'Next guide',
    purpose: 'Bring design results together to support the next decision.',
    scope: 'From RTL to final sign-off · evidence, review and decision history',
    flow: ['RTL design', 'Synthesis', 'Placement', 'Routing', 'Final review'], flowLabel: 'Connect verification evidence and approval decisions across every stage.',
    pages: {
      overview: {
        eyebrow: 'SIGN-OFF HUB / INTRODUCTION', title: 'From chip verification evidence to an accountable decision.',
        intro: 'Sign-off Hub connects RTL, timing and physical verification results to a design revision. Design engineers, verification teams and approvers use the same evidence to review violations, manage exceptions and decide whether a design is ready for the next stage.',
        items: [
          { title: 'The problem', body: 'Reports spread across tools and mismatched design versions make it difficult to answer: is this revision ready to move forward?', detail: 'Connect results by project, revision, stage and verification domain.' },
          { title: 'The decision', body: 'Check whether required verification is present, blocking violations remain, and waivers still apply to the current design.', detail: 'Gates express rule-based readiness. Authorized people record approval or rejection.' },
          { title: 'The record', body: 'Preserve execution evidence, violation dispositions, the candidate revision and the evidence snapshot used for a decision. Compare changes and trace decisions over time.', detail: 'Export the decision ledger for independent integrity verification.' },
        ],
        note: 'This service is the review and decision layer connecting design and verification tools. Manufacturing approval also requires qualified tools, foundry rules and your organization’s approval process.',
      },
      workflow: {
        eyebrow: 'DEVELOPMENT LIFECYCLE', title: 'Build evidence throughout development, before final review.',
        intro: 'Design and implementation happen in EDA tools. Sign-off Hub receives results at each stage, evaluates readiness and manages the review–fix–verify loop. Evidence accumulates from early development through final sign-off.',
        items: [
          { title: '01 / RTL design & verification', body: 'After writing and simulating RTL, review lint, structural rules, synthesis readiness or imported RTL, CDC and LEC results.', detail: 'Inputs: RTL, testbench, reports → outputs: violations and execution evidence. Structural checks do not prove complete CDC or formal correctness.', to: '/analysis/rtl' },
          { title: '02 / Synthesis', body: 'Connect timing results from the synthesized netlist, Liberty and SDC, then check for missing verification on that revision.', detail: 'Inputs: netlist, timing constraints, libraries → outputs: timing paths and stage readiness.', to: '/analysis/sta' },
          { title: '03 / Placement', body: 'Review early timing, power and power-grid risks using placement results. Keep screening estimates distinct from tool-generated verification.', detail: 'Inputs: placement reports, screening inputs → outputs: risk areas and re-verification tasks.', to: '/analysis/ir-drop' },
          { title: '04 / Routing', body: 'Connect timing with post-route parasitics and external DRC, LVS and EM/IR results to the same design revision.', detail: 'Inputs: routed-design verification reports → outputs: domain blockers and violation review history.', to: '/' },
          { title: '05 / Final review & handoff', body: 'Check required domains and scenarios, unresolved violations and waiver scope. Pin a release candidate, then have an approver review its evidence snapshot and record approval or rejection.', detail: 'Outputs: retained decision evidence and ledger. Tapeout submission and manufacturing remain separate processes.', to: '/' },
        ],
        note: 'The loop: collect reports → evaluate gates → review violations → fix the design → rerun external tools → collect new evidence. Design edits, placement and routing are performed outside this service.',
      },
      capabilities: {
        eyebrow: 'CAPABILITIES & BOUNDARIES', title: 'Understand what was executed, imported or estimated.',
        intro: 'Results carry different levels of verification. Distinguish actual tool execution, imported reports and fast estimates, then use them according to your project’s verification plan.',
        items: [
          { title: 'Tool execution / RTL & OpenSTA', body: 'Run RTL lint, simulation, synthesis and OpenSTA timing in a configured execution environment, retaining logs and evidence.', detail: 'Tools and isolated workers must be available. Users must review the validity of constraints and libraries.', to: '/analysis' },
          { title: 'Report ingestion / commercial EDA & KLayout', body: 'Import supported formats for timing, DRC, LVS, RTL, CDC, LEC, DFT, low-power, power, EM/IR and thermal results.', detail: 'Ingestion does not certify the source tool or rule deck. Supported adapter formats and verification coverage evidence are required.', to: '/' },
          { title: 'Fast analysis / risk screening', body: 'Explore risks with IR-drop screening, MMMC summaries and PBA estimates, and glitch power analysis.', detail: 'Example and estimated results cannot replace process-qualified verification or manufacturing approval.', to: '/analysis/ir-drop' },
          { title: 'Review & approval / connected evidence', body: 'Manage revision coverage, stage gates, violation dispositions, waivers, pinned candidates and approval packages.', detail: 'A passing gate is distinct from a human approval record. Decision signing requires an operational signing key.', to: '/' },
        ],
        note: 'Sign-off is the process of reviewing verification evidence and authorizing progress. A waiver records an accepted exception within a defined scope and validity period; it does not remove the underlying risk.',
      },
      agents: {
        eyebrow: 'HERMES / REVIEW RESPONSIBILITIES', title: 'Agents help interpret. People make decisions.',
        intro: 'Analysis tools compute metrics and violations; service rules evaluate gates. Hermes agents read evidence when their trigger conditions are met and suggest hypotheses and next checks. An AI opinion does not approve a design.',
        items: [
          { title: 'A1 / RTL reviewer', body: 'Reads rule results, stage status and diagnostic messages when RTL rule violations exist.', detail: 'Suggests possible causes and directions for fixes and re-verification.', to: '/analysis/rtl' },
          { title: 'A2 / Timing analyst', body: 'Reads corner and merged WNS/TNS and endpoint information when merged MMMC WNS is below 0 ps.', detail: 'Identifies limiting corners and checks for timing improvement.', to: '/analysis/timing' },
          { title: 'A3 / Power & IR analyst', body: 'Reads current results when IR screening fails or glitch power accounts for at least 30%.', detail: 'Explains hotspots, power risks and additional verification needs.', to: '/analysis/ir-drop' },
          { title: 'A5 → V / Synthesis of findings & cross-check', body: 'A5 reviews blockers when a stage gate cannot pass. After A5 completes, V compares the opinion with the original gate evidence.', detail: 'A completed review does not mean a passing design. Connection failures and incomplete upstream reviews are displayed.', to: '/' },
          { title: 'People / dispositions, waivers & approval', body: 'Engineers check evidence and opinions, fix issues and rerun verification. Authorized approvers record waivers and final decisions.', detail: 'A4 is a defined waiver-review role but is not connected to the automatic approval workflow.', to: '/agents' },
        ],
        note: 'Automatic opinions on analysis and gate screens are not saved. For a retained review, use “Request AI review · save record” in execution evidence. Saved AI reviews and human approval history are separate records.',
      },
      start: {
        eyebrow: 'GETTING STARTED', title: 'Start with one revision and one verification run.',
        intro: 'Use a small design to confirm the link between inputs and results. Authenticated deployments require an account issued by your administrator.',
        items: [
          { title: '01 / Project & verification plan', body: 'Select or create a project and check its process and foundry information. Define required verification domains and timing scenarios for each stage.', detail: 'Assign viewer, editor and approver roles around a shared verification policy.', to: '/' },
          { title: '02 / Execute or import', body: 'Run RTL or OpenSTA tools, or import external results within a project. Specify the actual design revision and retain source reports and logs.', detail: 'Try example inputs to learn the workflow, then replace them with actual design inputs.', to: '/analysis' },
          { title: '03 / Review gaps & blockers', body: 'Inspect revision coverage and stage gates. Fix and re-verify violations, or review a waiver with an explicit rationale and scope.', detail: 'Cross-check AI opinions against source evidence and decide whether a retained review is needed.', to: '/' },
          { title: '04 / Pin the candidate & record a decision', body: 'An approver pins the candidate revision and reviews the current evidence snapshot. Record approval or rejection and retain the evidence package and audit ledger.', detail: 'If evidence changes, the new snapshot must be reviewed again.', to: '/' },
        ],
        note: 'Prepare a revision identifier, verification targets and constraints, a tool environment or supported reports, and your team’s verification and approval policy. Hermes is optional; review cards show whether it actually participated.',
      },
    },
  },
};
