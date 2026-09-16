import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, type MarkerDetail } from '../api';
import { ViolationActions } from './ViolationActions';

const labels = { open: '미해결', fixed: '수정 완료', waived: '웨이버 승인' };
export function MarkerViolationReview({ runId, projectId, matches, onChange }: {
  runId: number; projectId: number; matches: MarkerDetail['violation_matches']; onChange: () => void;
}) {
  const qc = useQueryClient();
  const [selected, setSelected] = useState<number | null>(matches.status === 'unique' ? matches.items[0].id : null);
  const [offset, setOffset] = useState(0);
  const pageOffset = Math.min(offset, Math.floor(Math.max(0, matches.items.length-1)/25)*25);
  const valid = selected !== null && matches.items.some(item => item.id === selected);
  const current = useQuery({ queryKey: ['marker-violation', runId, selected],
    queryFn: () => api.getViolation(selected!), enabled: valid, refetchInterval: valid ? 5000 : false });
  function refresh() {
    void current.refetch();
    void qc.invalidateQueries({ queryKey: ['gate', projectId] });
    void qc.invalidateQueries({ queryKey: ['project-violations', projectId] });
    onChange();
  }
  return <section aria-label="마커에 연결된 위반 검토" className="border-t border-[var(--border)] pt-4 space-y-3">
    <h3 className="font-semibold">현재 위반 처리 상태</h3>
    <p>같은 런의 규칙·셀·마커 값 지문으로 연결합니다. 원본 태그와 현재 처리 상태는 별개입니다.</p>
    {matches.status === 'ambiguous' && <p role="status">동일 지문의 원본 마커 {matches.source_marker_count}개, 위반 기록 {matches.items.length}개가 있어 일대일 대응을 확정할 수 없습니다. 위반 번호·설명·이력을 확인하고 개별 기록을 선택하세요. 일괄 변경하지 않습니다.</p>}
    {matches.status === 'missing' && <p>연결된 위반 기록이 없습니다. 원본 마커를 해결된 것으로 판단하지 않습니다.</p>}
    <button className="btn btn-ghost" onClick={refresh}>위반 상태 새로고침</button>
    <ul className="space-y-2">{matches.items.slice(pageOffset, pageOffset+25).map(item => <li key={item.id}><button className="btn btn-ghost" aria-pressed={selected === item.id} onClick={() => setSelected(item.id)}>위반 #{item.id} · {labels[item.status]} · 버전 {item.version}</button></li>)}</ul>
    {matches.items.length > 25 && <div className="flex gap-2"><button className="btn btn-ghost" disabled={pageOffset === 0} onClick={() => setOffset(pageOffset-25)}>이전 연결 위반</button><button className="btn btn-ghost" disabled={pageOffset+25 >= matches.items.length} onClick={() => setOffset(pageOffset+25)}>다음 연결 위반</button></div>}
    {valid && (current.isPending ? <p role="status">위반 불러오는 중…</p> : current.isError ? <p role="alert">{current.error.message}</p> : current.data.run_id !== runId ? <p role="alert">해당 런의 위반이 아닙니다.</p> : <section aria-label={`위반 #${current.data.id} 처리`} className="rounded border border-[var(--border)] p-3 break-words">
      <h4 className="font-semibold mb-2">위반 #{current.data.id} · 현재 버전 {current.data.version}</h4>
      <ViolationActions key={current.data.id} violation={current.data} projectId={projectId} onChange={refresh} />
    </section>)}
  </section>;
}
