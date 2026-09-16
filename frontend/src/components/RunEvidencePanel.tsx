import { RunReviewHistory } from "./RunReviewHistory";
import { SimulationDetails } from "./SimulationDetails";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, type SignoffRun } from "../api";
import { StatusBadge } from "./ui";

export const EVIDENCE_LABELS = { rtl_ladder: "서버 실행 · RTL 분석", klayout_report: "가져온 보고서 · KLayout DRC", opensta_report: "가져온 보고서 · OpenSTA", manual: "수동 입력", legacy: "이전 데이터 · 실행 근거 없음" };

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
        {(run.evidence_source === 'opensta_report' || run.evidence_source === 'rtl_ladder' || run.evidence_source === 'klayout_report') && <div className="space-y-2">
          <button className="btn btn-ghost" disabled={sourceDownload.isPending} onClick={() => sourceDownload.mutate({ runId: run.id, extension: run.evidence_source === 'klayout_report' ? 'lyrdb' : run.evidence_source === 'opensta_report' ? 'json' : 'sv' })}>{sourceDownload.isPending ? '원본 확인 중…' : '원본 파일 다운로드'}</button>
          <p className="text-[var(--text-muted)]">저장된 SHA-256과 일치하는 원본 입력을 UTF-8 파일로 내려받습니다. 파일 일치는 툴 실행의 진위나 전체 검증 완료를 증명하지 않습니다.</p>
          {sourceDownload.variables?.runId === run.id && sourceDownload.isError && <p role="alert">{sourceDownload.error.message}</p>}
          {sourceDownload.variables?.runId === run.id && sourceDownload.isSuccess && <p role="status">원본 일치 확인 · 파일 다운로드를 시작했습니다.</p>}
        </div>}
        {run.evidence_source === "manual" ? <p>수동으로 등록한 런입니다. 상태를 Pass로 바꾸어도 서버에서 툴을 실행하거나 결과를 검증한 것은 아닙니다.</p> : run.evidence_source === "klayout_report" ? <>
          <p className="font-semibold">KLayout DRC 보고서 · {evidence.data.result.metadata?.filename}</p>
          <p>설계 리비전: {evidence.data.design_revision} · 입력된 툴 버전: {evidence.data.result.metadata?.tool_version}</p>
          <p>룰덱 / 실행 조건: {evidence.data.result.metadata?.scenario} · 업로드: {evidence.data.result.submitted_by?.username ?? '로컬 모드'}</p>
          <p>보고된 마커 {evidence.data.result.metrics?.reported_items}개 · 중복 발생 수 합계 {evidence.data.result.metrics?.reported_multiplicity}</p>
          <p>보고된 마커만 보존합니다. 셀 좌표 원문은 계층 변환하지 않습니다. 전체 DRC 범위는 미확인이며 원본 태그는 승인으로 반영하지 않습니다. 마커는 보수적으로 error로 등록합니다.</p>
          <p className="break-all">원본 SHA-256: {evidence.data.source_sha256}</p>
          <button className="btn btn-ghost" onClick={download}>근거 JSON 다운로드</button>
          <details><summary className="cursor-pointer">원본 DRC 보고서</summary><pre className="max-h-80 overflow-auto" tabIndex={0}>{evidence.data.source_text}</pre></details>
        </> : run.evidence_source === "opensta_report" ? <>
          <p className="font-semibold">OpenSTA 보고서 · {evidence.data.result.metadata?.filename}</p>
          <p>입력된 툴 버전: {evidence.data.result.metadata?.tool_version} · 시나리오: {evidence.data.result.metadata?.scenario}</p>
          <p>설계 리비전: {evidence.data.design_revision} (입력된 식별자)</p>
          <p>업로드: {evidence.data.result.submitted_by?.username ?? "로컬 모드 · 인증 없음"}</p>
          <p>보고된 경로 {evidence.data.result.metrics?.reported_paths}개 · 위반 {evidence.data.result.metrics?.violating_paths}개 · 제약 없는 경로 {evidence.data.result.metrics?.unconstrained_paths}개</p>
          <p>외부에서 제출된 경로 보고서입니다. 전체 STA 검증 범위와 툴 실행의 진위는 확인되지 않았습니다. 위반 처리 후에도 이 보고서만으로 게이트를 통과하지 않습니다.</p>
          <p className="break-all">원본 SHA-256: {evidence.data.source_sha256}</p>
          <button className="btn btn-ghost" onClick={download}>근거 JSON 다운로드</button>
          <details><summary className="cursor-pointer font-semibold">원본 보고서</summary><pre tabIndex={0} aria-label="OpenSTA 원본 보고서" className="mt-2 max-h-80 overflow-auto rounded-lg bg-[var(--surface-2)] p-3">{evidence.data.source_text}</pre></details>
        </> : <>
          <div className="flex flex-wrap justify-between gap-2"><p className="font-semibold">원래 판정: {evidence.data.result.verdict}</p><button className="btn btn-ghost" onClick={download}>근거 JSON 다운로드</button></div>
          <p>설계 리비전: {evidence.data.design_revision ?? "미등록"} (입력된 식별자)</p>
          {evidence.data.result.execution?.backend === 'container' && <p className="break-all">실행 환경: 컨테이너 워커 · 이미지 {evidence.data.result.execution.image_id}</p>}
          <p className="break-all">실행 소스 SHA-256: {evidence.data.source_sha256}</p>
          <p>원래 결과는 읽기 전용입니다. 위반 처리 이력은 원래 분석 결과와 별도로 기록합니다.</p>
          <ul className="space-y-2">{evidence.data.result.stages?.map(stage => <li key={stage.name} className="rounded-lg bg-[var(--surface-2)] p-2">
            <div className="flex flex-wrap items-center gap-2"><strong>{stage.name}</strong><StatusBadge status={stage.status === "pass" ? "good" : stage.status === "fail" ? "critical" : "warning"} label={stage.status} /><span>{stage.gating ? "필수 단계" : "참고 단계"}</span></div>
            <p className="mt-1 whitespace-pre-wrap break-words">{stage.detail}</p>
          </li>)}</ul>
          {evidence.data.result.simulation && <SimulationDetails simulation={evidence.data.result.simulation} />}
          <details><summary className="cursor-pointer font-semibold">실행한 RTL 소스</summary><pre tabIndex={0} aria-label="실행한 RTL 코드" className="mt-2 max-h-80 overflow-auto rounded-lg bg-[var(--surface-2)] p-3">{evidence.data.source_text}</pre></details>
        </>}
        {(run.evidence_source === 'rtl_ladder' || run.evidence_source === 'opensta_report') && <RunReviewHistory key={run.id} run={run} />}
      </>}
    </section>}
  </div>;
}
