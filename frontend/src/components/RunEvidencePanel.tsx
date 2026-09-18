import { Link } from "react-router";
import { RtlSourceInspector } from "./RtlSourceInspector";
import { RunReviewHistory } from "./RunReviewHistory";
import { SimulationDetails } from "./SimulationDetails";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, type SignoffRun } from "../api";
import { StatusBadge } from "./ui";

export const EVIDENCE_LABELS = { rtl_ladder: "서버 실행 · RTL 분석", commercial_rtl_report: "가져온 보고서 · VCS / Xcelium 회귀", klayout_report: "가져온 보고서 · KLayout DRC", commercial_drc_report: "가져온 보고서 · Calibre / Pegasus", commercial_emir_report: "가져온 보고서 · RedHawk / Voltus / Totem", commercial_power_report: "가져온 보고서 · PrimePower / Joules / PowerArtist", commercial_thermal_report: "가져온 보고서 · Celsius / Icepak / 3DSTACK", opensta_report: "가져온 보고서 · OpenSTA", opensta_execution: "서버 실행 · OpenSTA", commercial_sta_report: "가져온 보고서 · PrimeTime / Tempus", manual: "수동 입력", legacy: "이전 데이터 · 실행 근거 없음" };

export function RunEvidencePanel({ run }: { run: SignoffRun }) {
  const [open, setOpen] = useState(false);
  const evidence = useQuery({ queryKey: ["run-evidence", run.id], queryFn: () => api.runEvidence(run.id), enabled: open && run.evidence_source !== "legacy" });
  const sourceDownload = useMutation({
    mutationFn: (target: { runId: number; extension: string }) => api.runSource(target.runId),
    onSuccess: (blob, target) => {
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `run-${target.runId}-source.${target.extension}`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
  });
  const netlistDownload = useMutation({
    mutationFn: (runId: number) => api.runNetlist(runId),
    onSuccess: (blob, runId) => {
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url; link.download = `run-${runId}-netlist.v`; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
  });
  const artifactDownload = useMutation({
    mutationFn: (target: { runId: number; kind: 'netlist' | 'liberty' | 'sdc' | 'spef'; extension: string }) => api.runArtifact(target.runId, target.kind),
    onSuccess: (blob, target) => {
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url; link.download = `run-${target.runId}-${target.kind}.${target.extension}`; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
  });
  function download() {
    if (!evidence.data) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(evidence.data, null, 2)], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `run-${run.id}-evidence.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <div className="mt-3 space-y-3">
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <span className="text-[var(--text-secondary)]">{EVIDENCE_LABELS[run.evidence_source]}</span>
      <button className="btn btn-ghost" aria-expanded={open} onClick={() => setOpen(!open)}>실행 근거 {open ? "접기" : "보기"}</button>
    </div>
    {open && <section className="rounded-lg border border-[var(--border)] p-3 text-xs space-y-3" aria-label={`런 #${run.id} 실행 근거`}>
      {run.evidence_source === "legacy" ? <p>이 실행은 원본 입력과 판정 근거가 보존되기 전에 등록되었습니다. RTL 분석을 다시 실행하면 근거를 기록할 수 있습니다.</p> : evidence.isPending ? <p role="status">실행 근거 불러오는 중…</p> : evidence.isError ? <p role="alert">{evidence.error.message} <button className="btn btn-ghost" onClick={() => evidence.refetch()}>다시 시도</button></p> : <>
        {(run.evidence_source === 'opensta_report' || run.evidence_source === 'opensta_execution' || run.evidence_source === 'commercial_sta_report' || run.evidence_source === 'rtl_ladder' || run.evidence_source === 'commercial_rtl_report' || run.evidence_source === 'klayout_report' || run.evidence_source === 'commercial_drc_report' || run.evidence_source === 'commercial_emir_report' || run.evidence_source === 'commercial_power_report' || run.evidence_source === 'commercial_thermal_report') && <div className="space-y-2">
          <button className="btn btn-ghost" disabled={sourceDownload.isPending} onClick={() => sourceDownload.mutate({ runId: run.id, extension: run.evidence_source === 'klayout_report' ? 'lyrdb' : run.evidence_source === 'rtl_ladder' ? 'sv' : 'json' })}>{sourceDownload.isPending ? '원본 확인 중…' : '원본 파일 다운로드'}</button>
          <p className="text-[var(--text-muted)]">저장된 SHA-256과 일치하는 원본 입력을 UTF-8 파일로 내려받습니다. 파일 일치는 툴 실행의 진위나 전체 검증 완료를 증명하지 않습니다.</p>
          {sourceDownload.variables?.runId === run.id && sourceDownload.isError && <p role="alert">{sourceDownload.error.message}</p>}
          {sourceDownload.variables?.runId === run.id && sourceDownload.isSuccess && <p role="status">원본 일치 확인 · 파일 다운로드를 시작했습니다.</p>}
        </div>}
        {run.evidence_source === "manual" ? <p>수동으로 등록한 런입니다. 상태를 Pass로 바꾸어도 서버에서 툴을 실행하거나 결과를 검증한 것은 아닙니다.</p> : run.evidence_source === 'commercial_rtl_report' ? <><p className="font-semibold">{run.tool} 회귀 보고서 · {evidence.data.result.metadata?.filename}</p><p>테스트 {evidence.data.result.metrics?.reported_tests}개 · 실패 {evidence.data.result.metrics?.failed_tests}개 · assertion 실패 {evidence.data.result.metrics?.failed_assertions}개</p>{evidence.data.result.coverage_attestation?.verified ? <div className="rounded-lg border border-[var(--status-good)] p-2 space-y-1"><p className="font-semibold">신뢰된 수집기 전체 RTL 회귀 범위 증명</p><p>키 ID: {evidence.data.result.coverage_attestation.key_id} · 유효 기간: {new Date(evidence.data.result.coverage_attestation.issued_at).toLocaleString()} – {new Date(evidence.data.result.coverage_attestation.expires_at).toLocaleString()}</p><p className="break-all">증명 ID: {evidence.data.result.coverage_attestation.attestation_id}</p><p>서버가 테스트 계획·컴파일·시뮬레이션·assertion·코드/기능 커버리지 범위와 서명을 검증했습니다. 등록 수집기의 선언이며 벤더 서명이나 호스트 무결성 증명은 아닙니다. AI는 판정에 개입하지 않습니다.</p></div> : <p>제출된 회귀만 보존하며 전체 테스트 계획·커버리지와 실행 진위는 확인되지 않았습니다. AI는 개입하지 않습니다.</p>}<p className="break-all">원본 SHA-256: {evidence.data.source_sha256}</p></> : run.evidence_source === 'commercial_thermal_report' ? <><p className="font-semibold">{run.tool} 열 보고서 · {evidence.data.result.metadata?.filename}</p><p>핫스폿 {evidence.data.result.metrics?.reported_hotspots}개 · 제한 초과 {evidence.data.result.metrics?.violated_hotspots}개 · 최고 {evidence.data.result.metrics?.maximum_temperature_c} °C</p>{evidence.data.result.coverage_attestation?.verified ? <div className="rounded-lg border border-[var(--status-good)] p-2 space-y-1"><p className="font-semibold">신뢰된 수집기 전체 열 해석 범위 증명</p><p>키 ID: {evidence.data.result.coverage_attestation.key_id} · 유효 기간: {new Date(evidence.data.result.coverage_attestation.issued_at).toLocaleString()} – {new Date(evidence.data.result.coverage_attestation.expires_at).toLocaleString()}</p><p className="break-all">증명 ID: {evidence.data.result.coverage_attestation.attestation_id}</p><p>서버가 재료·경계·전력 맵·패키지·해석·메시 범위와 서명을 검증했습니다. 등록 수집기의 선언이며 벤더 서명이나 호스트 무결성 증명은 아닙니다. AI는 판정에 개입하지 않습니다.</p></div> : <p>제출된 핫스폿만 보존하며 전체 열 해석 범위나 툴 실행 진위는 확인되지 않았습니다. AI는 개입하지 않습니다.</p>}<p className="break-all">원본 SHA-256: {evidence.data.source_sha256}</p></> : run.evidence_source === 'commercial_power_report' ? <><p className="font-semibold">{run.tool} 전력 보고서 · {evidence.data.result.metadata?.filename}</p><p>설계 리비전: {evidence.data.design_revision} · 모드/코너/활동도: {evidence.data.result.metadata?.scenario}</p><p>총 전력 {evidence.data.result.metrics?.total_power_mw} mW · 글리치 {evidence.data.result.metrics?.glitch_power_mw} mW</p>{evidence.data.result.coverage_attestation?.verified ? <div className="rounded-lg border border-[var(--status-good)] p-2 space-y-1"><p className="font-semibold">신뢰된 수집기 전체 전력 분석 범위 증명</p><p>키 ID: {evidence.data.result.coverage_attestation.key_id} · 유효 기간: {new Date(evidence.data.result.coverage_attestation.issued_at).toLocaleString()} – {new Date(evidence.data.result.coverage_attestation.expires_at).toLocaleString()}</p><p className="break-all">증명 ID: {evidence.data.result.coverage_attestation.attestation_id}</p><p>서버가 모드·코너·활동도·전력 모델·계층 범위와 서명을 검증했습니다. 등록 수집기의 선언이며 벤더 서명이나 호스트 무결성 증명은 아닙니다. AI는 판정에 개입하지 않습니다.</p></div> : <p>제출된 요약만 보존하며 전체 활동도와 모드 커버리지, 툴 실행 진위는 확인되지 않았습니다. AI는 개입하지 않습니다.</p>}<p className="break-all">원본 SHA-256: {evidence.data.source_sha256}</p><button className="btn btn-ghost" onClick={download}>근거 JSON 다운로드</button></> : run.evidence_source === 'commercial_emir_report' ? <>
          <p className="font-semibold">{run.tool} 전력 무결성 보고서 · {evidence.data.result.metadata?.filename}</p>
          <p>설계 리비전: {evidence.data.design_revision} · 툴 버전: {evidence.data.result.metadata?.tool_version}</p>
          <p>모드 / 코너 / 전원 조건: {evidence.data.result.metadata?.scenario}</p>
          <p>보고된 결과 {evidence.data.result.metrics?.reported_findings}개 · 제한 초과 {evidence.data.result.metrics?.violated_findings}개</p>
          {evidence.data.result.coverage_attestation?.verified ? <div className="rounded-lg border border-[var(--status-good)] p-2 space-y-1"><p className="font-semibold">신뢰된 수집기 전체 EM/IR 범위 증명</p><p>키 ID: {evidence.data.result.coverage_attestation.key_id} · 유효 기간: {new Date(evidence.data.result.coverage_attestation.issued_at).toLocaleString()} – {new Date(evidence.data.result.coverage_attestation.expires_at).toLocaleString()}</p><p className="break-all">증명 ID: {evidence.data.result.coverage_attestation.attestation_id}</p><p>서버가 rail·모드·벡터·추출·검사 범위와 서명을 검증했습니다. 등록 수집기의 선언이며 벤더 서명이나 호스트 무결성 증명은 아닙니다. AI는 판정에 개입하지 않습니다.</p></div> : <p>제출된 결과만 보존하며 전체 EM/IR 검증 범위와 상용 툴 실행 진위는 확인되지 않았습니다. 조회와 위반 생성에는 AI가 개입하지 않습니다.</p>}
          <p className="break-all">원본 SHA-256: {evidence.data.source_sha256}</p><button className="btn btn-ghost" onClick={download}>근거 JSON 다운로드</button>
          <details><summary className="cursor-pointer">원본 EM/IR 보고서</summary><pre className="max-h-80 overflow-auto" tabIndex={0}>{evidence.data.source_text}</pre></details>
        </> : (run.evidence_source === "klayout_report" || run.evidence_source === "commercial_drc_report") ? <>
          <p className="font-semibold">{run.evidence_source === 'commercial_drc_report' ? run.tool : 'KLayout DRC'} 보고서 · {evidence.data.result.metadata?.filename}</p>
          <p>설계 리비전: {evidence.data.design_revision} · 입력된 툴 버전: {evidence.data.result.metadata?.tool_version}</p>
          <p>룰덱 / 실행 조건: {evidence.data.result.metadata?.scenario} · 업로드: {evidence.data.result.submitted_by?.username ?? '로컬 모드'}</p>
          <p>보고된 마커 {evidence.data.result.metrics?.reported_items}개 · 중복 발생 수 합계 {evidence.data.result.metrics?.reported_multiplicity}</p>
          {evidence.data.result.coverage_attestation?.verified ? <div className="rounded-lg border border-[var(--status-good)] p-2 space-y-1"><p className="font-semibold">신뢰된 수집기 전체 DRC 범위 증명</p><p>키 ID: {evidence.data.result.coverage_attestation.key_id} · 유효 기간: {new Date(evidence.data.result.coverage_attestation.issued_at).toLocaleString()} – {new Date(evidence.data.result.coverage_attestation.expires_at).toLocaleString()}</p><p className="break-all">증명 ID: {evidence.data.result.coverage_attestation.attestation_id}</p><p>서버가 서명과 DRC 범위 선언을 검증했습니다. 등록 수집기의 선언이며 EDA 벤더 서명이나 호스트 무결성 증명은 아닙니다. AI는 판정에 개입하지 않습니다.</p></div> : <p>보고된 마커만 보존합니다. 셀 좌표는 계층 변환하지 않습니다. 전체 DRC 범위는 미확인이며 보고된 심각도나 원본 태그는 승인으로 반영하지 않습니다.</p>}
          <p className="break-all">원본 SHA-256: {evidence.data.source_sha256}</p>
          <button className="btn btn-ghost" onClick={download}>근거 JSON 다운로드</button>
          <details><summary className="cursor-pointer">원본 DRC 보고서</summary><pre className="max-h-80 overflow-auto" tabIndex={0}>{evidence.data.source_text}</pre></details>
        </> : (run.evidence_source === "opensta_report" || run.evidence_source === "opensta_execution" || run.evidence_source === "commercial_sta_report") ? <>
          <p className="font-semibold">{run.tool} 보고서 · {evidence.data.result.metadata?.filename}</p>
          <p>입력된 툴 버전: {evidence.data.result.metadata?.tool_version} · 시나리오: {evidence.data.result.metadata?.scenario}</p>
          <p>설계 리비전: {evidence.data.design_revision} (입력된 식별자)</p>
          <p>업로드: {evidence.data.result.submitted_by?.username ?? "로컬 모드 · 인증 없음"}</p>
          <p>보고된 경로 {evidence.data.result.metrics?.reported_paths}개 · 위반 {evidence.data.result.metrics?.violating_paths}개 · 제약 없는 경로 {evidence.data.result.metrics?.unconstrained_paths}개</p>
          {run.evidence_source === 'opensta_execution' ? <><p className="break-all">서버 실행: 격리 컨테이너 · 이미지 {evidence.data.result.execution?.image_id} · OpenSTA {evidence.data.result.execution?.opensta_commit}</p><p>배선 기생성분: {evidence.data.result.metadata?.parasitics === 'spef' ? 'SPEF 반영' : '미제공'}</p><p>이 런 생성에는 AI가 개입하지 않았습니다. 저장된 입력으로 서버가 OpenSTA를 실행했습니다. 경로 표본만 생성하므로 이 결과만으로 전체 STA 게이트를 통과하지 않습니다.</p></> : evidence.data.result.coverage_attestation?.verified ? <div className="rounded-lg border border-[var(--status-good)] p-2 space-y-1"><p className="font-semibold">신뢰된 수집기 전체 STA 범위 증명</p><p>키 ID: {evidence.data.result.coverage_attestation.key_id} · 유효 기간: {new Date(evidence.data.result.coverage_attestation.issued_at).toLocaleString()} – {new Date(evidence.data.result.coverage_attestation.expires_at).toLocaleString()}</p><p className="break-all">증명 ID: {evidence.data.result.coverage_attestation.attestation_id}</p><p>서버가 서명과 여섯 범위 선언을 검증했습니다. 이는 등록 수집기의 선언이며 EDA 벤더 서명이나 호스트 무결성 증명은 아닙니다. AI는 판정에 개입하지 않습니다.</p></div> : <p>외부에서 제출된 경로 보고서입니다. 전체 STA 검증 범위와 툴 실행의 진위는 확인되지 않았습니다. 위반 처리 후에도 이 보고서만으로 게이트를 통과하지 않습니다.</p>}
          {run.evidence_source === 'opensta_execution' && <section className="space-y-2" aria-label="OpenSTA 입력 아티팩트"><h4 className="font-semibold">실행 입력 아티팩트</h4><p>대형 입력 원문은 근거 메타데이터와 분리해 저장하며, 다운로드할 때 SHA-256과 바이트 길이를 다시 확인합니다.</p><ul className="space-y-2">{(['netlist', 'liberty', 'sdc', 'spef'] as const).filter(kind => kind !== 'spef' || evidence.data.result.input_artifacts?.spef).map(kind => { const item = evidence.data.result.input_artifacts?.[kind]; const label = { netlist: '게이트 넷리스트', liberty: 'Liberty 라이브러리', sdc: 'SDC 제약', spef: 'SPEF 기생성분' }[kind]; const extension = { netlist: 'v', liberty: 'lib', sdc: 'sdc', spef: 'spef' }[kind]; return <li key={kind} className="rounded-lg bg-[var(--surface-2)] p-2"><p><strong>{label}</strong> · {item?.byte_length?.toLocaleString() ?? '알 수 없음'} bytes</p><p className="break-all">SHA-256: {item?.sha256 ?? '이전 실행 · 메타데이터 없음'}</p><button className="btn btn-ghost mt-1" disabled={artifactDownload.isPending} onClick={() => artifactDownload.mutate({ runId: run.id, kind, extension })}>{artifactDownload.isPending && artifactDownload.variables?.kind === kind ? '확인 중…' : '원본 다운로드'}</button></li>; })}</ul>{artifactDownload.isError && <p role="alert">{artifactDownload.error.message}</p>}</section>}
          <p className="break-all">원본 SHA-256: {evidence.data.source_sha256}</p>
          <button className="btn btn-ghost" onClick={download}>근거 JSON 다운로드</button>
          <details><summary className="cursor-pointer font-semibold">원본 보고서</summary><pre tabIndex={0} aria-label="OpenSTA 원본 보고서" className="mt-2 max-h-80 overflow-auto rounded-lg bg-[var(--surface-2)] p-3">{evidence.data.source_text}</pre></details>
        </> : <>
          <div className="flex flex-wrap justify-between gap-2"><p className="font-semibold">원래 판정: {evidence.data.result.verdict}</p><button className="btn btn-ghost" onClick={download}>근거 JSON 다운로드</button></div>
          <p>설계 리비전: {evidence.data.design_revision ?? "미등록"} (입력된 식별자)</p>
          {evidence.data.result.execution?.backend === 'container' && <p className="break-all">실행 환경: 컨테이너 워커 · 이미지 {evidence.data.result.execution.image_id}</p>}
          <p className="break-all">린트·합성 최상위: {evidence.data.result.module ?? '미확인'} · {evidence.data.result.top_module_requested === undefined ? '선택 방식 미보관' : evidence.data.result.top_module_requested === null ? '첫 모듈 자동 선택' : '사용자 지정'}</p>
          <p className="break-all">실행 소스 SHA-256: {evidence.data.source_sha256}</p>
          <p>원래 결과는 읽기 전용입니다. 위반 처리 이력은 원래 분석 결과와 별도로 기록합니다.</p>
          <ul className="space-y-2">{evidence.data.result.stages?.map(stage => <li key={stage.name} className="rounded-lg bg-[var(--surface-2)] p-2">
            <div className="flex flex-wrap items-center gap-2"><strong>{stage.name}</strong><StatusBadge status={stage.status === "pass" ? "good" : stage.status === "fail" ? "critical" : "warning"} label={stage.status} /><span>{stage.gating ? "필수 단계" : "참고 단계"}</span></div>
            <p className="mt-1 whitespace-pre-wrap break-words">{stage.detail}</p>
          </li>)}</ul>
          <section aria-label="합성 넷리스트" className="space-y-2">
            <h4 className="font-semibold">합성 넷리스트</h4>
            {evidence.data.result.netlist ? <>
              <p>일반 Verilog · {evidence.data.result.netlist.byte_length.toLocaleString()} bytes</p>
              <p className="break-all">SHA-256: {evidence.data.result.netlist.sha256}</p>
              <button className="btn btn-ghost" disabled={netlistDownload.isPending} onClick={() => netlistDownload.mutate(run.id)}>{netlistDownload.isPending ? '넷리스트 확인 중…' : '합성 넷리스트 다운로드'}</button>
              {netlistDownload.variables === run.id && netlistDownload.isError && <p role="alert">{netlistDownload.error.message}</p>}
              {netlistDownload.variables === run.id && netlistDownload.isSuccess && <p role="status">넷리스트 일치 확인 · 다운로드를 시작했습니다.</p>}
            </> : <p>넷리스트 미보관 · 합성 미완료 또는 이전 실행입니다.</p>}
            <p className="text-[var(--text-muted)]">Yosys가 생성한 합성 결과입니다. 라이브러리 매핑·배치배선·타이밍 검증 전이며, 다운로드는 전체 사인오프 통과를 의미하지 않습니다. 조회에는 AI가 개입하지 않습니다.</p>
          </section>
          {evidence.data.result.structure ? <Link className="btn btn-ghost inline-block" to={`/runs/${run.id}/structure`}>합성 구조 탐색</Link> : <p>{evidence.data.result.structure_error ?? '합성 구조 미보관 · 이전 실행 또는 구조 미생성'}</p>}
          <RtlSourceInspector key={run.id} evidence={evidence.data} />
          <section aria-label="RTL 도구 실행 로그" className="space-y-2">
            <h3 className="font-semibold">도구 명령과 실행 로그</h3>
            <p>서버가 실행한 기본 린트·폭 검사·합성 기록입니다. 로그는 도구별 최대 128 KiB이며 출력 한도 초과는 실행 오류로 기록합니다. 조회에는 AI가 개입하지 않습니다.</p>
            {(['lint', 'width', 'synthesize'] as const).map(name => {
              const record = evidence.data.result.tool_runs?.[name];
              const label = { lint: '기본 린트', width: '폭 검사 린트', synthesize: '합성' }[name];
              return record ? <details key={name}><summary className="cursor-pointer font-semibold">{label} · 종료 코드 {record.exit_code ?? '없음'}</summary>
                <p className="mt-2 whitespace-pre-wrap break-words">실행 제한 또는 시작 오류: {record.error ?? '없음'}</p>
                <p className="text-xs">명령 인수 배열 (실행 기능 없음)</p>
                <pre className="whitespace-pre-wrap break-words">{JSON.stringify(record.command)}</pre>
                <pre tabIndex={0} aria-label={`${label} 실행 로그`} className="mt-2 max-h-80 overflow-auto rounded-lg bg-[var(--surface-2)] p-3">{record.log || '출력 없음'}</pre>
              </details> : <p key={name}>{label}: 실행 로그 미보관 · 미실행 또는 이전 결과</p>;
            })}
          </section>
          {evidence.data.result.simulation && <SimulationDetails simulation={evidence.data.result.simulation} />}
          <details><summary className="cursor-pointer font-semibold">실행한 RTL 소스</summary><pre tabIndex={0} aria-label="실행한 RTL 코드" className="mt-2 max-h-80 overflow-auto rounded-lg bg-[var(--surface-2)] p-3">{evidence.data.source_text}</pre></details>
        </>}
        {(run.evidence_source === 'rtl_ladder' || run.evidence_source === 'opensta_report' || run.evidence_source === 'opensta_execution' || run.evidence_source === 'commercial_sta_report') && <RunReviewHistory key={run.id} run={run} />}
      </>}
    </section>}
  </div>;
}
