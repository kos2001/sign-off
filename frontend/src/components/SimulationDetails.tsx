import type { SimulationEvidence } from "../api";
import { useLanguage } from "./LanguageProvider";

export function SimulationDetails({ simulation: s }: { simulation: SimulationEvidence }) {
  const { t } = useLanguage();
  if (!s.testbench_source) return null;
  return <details className="mt-3 rounded-lg border border-[var(--border)] p-3 text-xs">
    <summary className="cursor-pointer font-semibold">{t('테스트벤치 실행 근거', 'Testbench run evidence')} · {s.status}</summary>
    <p className="mt-2">{s.engine} · {t('최상위 모듈', 'Top module')}: {s.top}</p>
    <p className="mt-2">{s.detail}</p>
    <p className="mt-2 break-all">{t('테스트벤치 SHA-256', 'Testbench SHA-256')}: {s.testbench_sha256}</p>
    <p className="mt-2">{t('Pass는 제출한 테스트벤치의 완료 결과입니다. 기능 커버리지나 모든 입력 조합의 검증을 의미하지 않습니다.', 'Pass means the submitted testbench ran to completion. It does not imply functional coverage or verification of every input combination.')}</p>
    <details className="mt-2"><summary className="cursor-pointer">{t('실행한 테스트벤치 소스', 'Executed testbench source')}</summary><pre tabIndex={0} aria-label={t('실행한 테스트벤치 코드', 'Executed testbench code')} className="mt-2 max-h-80 overflow-auto bg-[var(--surface-2)] p-2">{s.testbench_source}</pre></details>
    {([['compile', t('컴파일', 'Compile'), s.compile], ['simulation', t('시뮬레이션', 'Simulation'), s.runtime]] as const).map(([key, label, execution]) => execution && <details className="mt-2" key={key}>
      <summary className="cursor-pointer">{t(`${label} 로그`, `${label} log`)} · {t('종료 코드', 'Exit code')} {execution.exit_code ?? t('없음', 'none')}</summary>
      {execution.error && <p>{execution.error}</p>}
      <pre tabIndex={0} aria-label={t(`${label} 로그`, `${label} log`)} className="mt-2 max-h-64 overflow-auto bg-[var(--surface-2)] p-2">{execution.log || t('출력 없음', 'No output')}</pre>
    </details>)}
    {s.tool_version && <details className="mt-2"><summary className="cursor-pointer">{t('실행 툴 버전', 'Tool version')}</summary><pre className="mt-2 max-h-40 overflow-auto" tabIndex={0}>{s.tool_version}</pre></details>}
  </details>;
}
