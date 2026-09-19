import { useEffect } from 'react';
import { Link, useLocation } from 'react-router';
import { AGENT_ROLES } from '../agentRoles';
import { Card, StatusBadge } from '../components/ui';

export default function AgentGuide() {
  const { hash } = useLocation();
  useEffect(() => {
    if (hash) document.getElementById(hash.slice(1))?.scrollIntoView({ block: 'start' });
  }, [hash]);
  return <div className="space-y-6">
    <header className="space-y-2">
      <p className="text-xs tracking-widest text-[var(--series-1)]">HERMES · 검토 가이드</p>
      <h1 className="text-2xl font-semibold">에이전트 개입 안내</h1>
      <p className="text-sm text-[var(--text-secondary)]">분석에서 승인까지, 자동 검토가 맡는 일과 사람이 결정하는 일을 확인하세요.</p>
    </header>
    <section aria-label="검토와 승인 흐름" className="grid gap-3 md:grid-cols-3">
      {[
        ['01', '분석과 규칙 판정', '분석 도구가 수치와 위반을 계산하고, 서비스가 스테이지 게이트를 판정합니다.'],
        ['02', '조건부 에이전트 검토', '조건에 해당하는 결과만 Hermes가 해석합니다. 게이트는 A5 종합 검토 후 V가 원본과 대조합니다.'],
        ['03', '사람의 검토와 결정', '담당자가 근거와 AI 의견을 확인한 뒤 위반 처리·웨이버를 결정합니다. 변경은 이력에 기록됩니다.'],
      ].map(([n, title, text]) => <div key={n} className="card p-5"><p className="text-xs text-[var(--series-1)]">{n}</p><h2 className="mt-2 font-semibold">{title}</h2><p className="mt-2 text-sm text-[var(--text-secondary)]">{text}</p></div>)}
    </section>
    <div className="flex flex-wrap items-end justify-between gap-2"><div><h2 className="font-semibold">자동 연결된 역할</h2><p className="mt-1 text-xs text-[var(--text-muted)]">아래는 기능 안내입니다. 실제 실행 여부는 각 분석·프로젝트 화면의 검토 카드에서 확인합니다.</p></div><StatusBadge status="neutral" label="5개 역할 · 조건부 실행" /></div>
    <div className="grid gap-4 xl:grid-cols-2">
      {Object.entries(AGENT_ROLES).map(([id, role]) => <Card key={id} id={id} title={`${role.code} · ${role.name}`} subtitle={role.location}>
        <dl className="space-y-3 text-sm">
          <div><dt className="text-xs text-[var(--text-muted)]">언제 개입하나요?</dt><dd className="mt-1">{role.condition}</dd></div>
          <div><dt className="text-xs text-[var(--text-muted)]">무엇을 읽나요?</dt><dd className="mt-1 text-[var(--text-secondary)]">{role.evidence}</dd></div>
          <div><dt className="text-xs text-[var(--text-muted)]">무엇을 제공하나요?</dt><dd className="mt-1 text-[var(--text-secondary)]">{role.output}</dd></div>
        </dl>
        <Link className="btn btn-ghost mt-4" to={role.to}>{role.to === '/' ? '대시보드에서 프로젝트 선택' : '분석 화면 열기'}</Link>
        {id === 'a3_power_ir' && <Link className="btn btn-ghost mt-4 ml-2" to="/analysis/glitch-power">글리치 분석 열기</Link>}
      </Card>)}
      <Card title="A4 · 웨이버 심사관" subtitle="역할 정의만 제공"><StatusBadge status="neutral" label="자동 연결 안 됨" /><p className="mt-3 text-sm text-[var(--text-secondary)]">현재 웨이버 승인 과정에는 에이전트가 자동 개입하지 않습니다. 승인 권한을 가진 사람이 사유와 잔여 위험을 검토하고 결정합니다.</p></Card>
    </div>
    <Card title="검토 의견을 기록하려면">
      <p className="text-sm text-[var(--text-secondary)]">프로젝트 또는 타이밍 경로에서 실행 근거를 열고 「AI 검토 요청 · 기록 저장」을 누르세요. 저장된 RTL·OpenSTA 근거로 별도 검토를 실행하고 요청자, 입력과 의견을 보존합니다. 편집자 이상이 요청하고 조회자는 저장된 의견을 볼 수 있습니다.</p>
      <Link className="btn btn-ghost mt-3" to="/">프로젝트 선택</Link>
    </Card>
    <Card title="검토 상태를 읽는 방법">
      <dl className="grid gap-4 text-sm sm:grid-cols-2">
        {[
          ['실행 전', '분석 결과 또는 선행 검토를 기다리는 상태입니다.'],
          ['검토 결과 대기', '서비스가 조건을 확인하거나 검토 응답을 기다립니다. 게이트의 A5·V 결과는 함께 도착합니다.'],
          ['조건 미해당 · 실행 안 됨', '이번 결과는 자동 검토 조건에 해당하지 않아 LLM 호출을 생략했습니다.'],
          ['검토 완료', '의견 작성이 끝났다는 뜻입니다. 설계 통과나 승인 완료를 의미하지 않습니다.'],
          ['검토 미완료', '연결 실패·시간 초과 등으로 의견이 없습니다. 다시 시도할 수 있습니다.'],
          ['진행 확인 불가', '요청 결과를 받지 못해 후속 검증의 실행 여부를 확인할 수 없습니다.'],
          ['선행 검토 미완료', 'A5가 완료되지 않으면 V를 실행하지 않습니다. 종합 검토부터 다시 시도합니다.'],
        ].map(([state, text]) => <div key={state}><dt className="font-medium">{state}</dt><dd className="mt-1 text-[var(--text-secondary)]">{text}</dd></div>)}
      </dl>
    </Card>
    <p className="text-xs text-[var(--text-muted)]">현재 요청의 결과만 검토하며 원본 데이터에 없는 사실은 확인이 필요합니다. 분석·게이트의 자동 의견은 저장되지 않습니다. 보존할 의견은 런의 실행 근거에서 「AI 검토 요청 · 기록 저장」으로 별도 요청하세요. 저장된 AI 의견과 승인·웨이버 변경 이력은 구분됩니다.</p>
  </div>;
}
