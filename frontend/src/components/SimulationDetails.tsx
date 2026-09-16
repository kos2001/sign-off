import type { SimulationEvidence } from "../api";

export function SimulationDetails({ simulation: s }: { simulation: SimulationEvidence }) {
  if (!s.testbench_source) return null;
  return <details className="mt-3 rounded-lg border border-[var(--border)] p-3 text-xs">
    <summary className="cursor-pointer font-semibold">테스트벤치 실행 근거 · {s.status}</summary>
    <p className="mt-2">{s.engine} · 최상위 모듈: {s.top}</p>
    <p className="mt-2">{s.detail}</p>
    <p className="mt-2 break-all">테스트벤치 SHA-256: {s.testbench_sha256}</p>
    <p className="mt-2">Pass는 제출한 테스트벤치의 완료 결과입니다. 기능 커버리지나 모든 입력 조합의 검증을 의미하지 않습니다.</p>
    <details className="mt-2"><summary className="cursor-pointer">실행한 테스트벤치 소스</summary><pre tabIndex={0} aria-label="실행한 테스트벤치 코드" className="mt-2 max-h-80 overflow-auto bg-[var(--surface-2)] p-2">{s.testbench_source}</pre></details>
    {([['컴파일', s.compile], ['시뮬레이션', s.runtime]] as const).map(([label, execution]) => execution && <details className="mt-2" key={label}>
      <summary className="cursor-pointer">{label} 로그 · 종료 코드 {execution.exit_code ?? "없음"}</summary>
      {execution.error && <p>{execution.error}</p>}
      <pre tabIndex={0} aria-label={`${label} 로그`} className="mt-2 max-h-64 overflow-auto bg-[var(--surface-2)] p-2">{execution.log || "출력 없음"}</pre>
    </details>)}
    {s.tool_version && <details className="mt-2"><summary className="cursor-pointer">실행 툴 버전</summary><pre className="mt-2 max-h-40 overflow-auto" tabIndex={0}>{s.tool_version}</pre></details>}
  </details>;
}
