import { useQuery } from '@tanstack/react-query';
import { Link, useParams, useSearchParams } from 'react-router';
import { api, type LecKind } from '../api';
import { RunEvidencePanel } from '../components/RunEvidencePanel';

const labels: Record<'all' | LecKind, string> = { all: '전체', non_equivalent: '비등가', unmapped: '미매핑', aborted: '중단', black_box: 'Black box', setup: 'Setup' };
export default function LecFailures() {
  const runId = Number(useParams().runId), [params, setParams] = useSearchParams();
  const offset = Math.max(0, Number(params.get('offset')) || 0), kind = params.get('kind') || 'all', search = params.get('q') || '';
  const query = useQuery({ queryKey: ['lec-failures', runId, kind, search, offset], queryFn: () => api.lecFailures(runId, { kind, q: search, offset: String(offset), limit: '25' }) });
  function change(key: string, value: string) { setParams(previous => { const next = new URLSearchParams(previous); value ? next.set(key, value) : next.delete(key); if (key !== 'offset') next.delete('offset'); return next; }); }
  if (query.isPending) return <p>LEC 결과 불러오는 중…</p>;
  if (query.isError) return <p role="alert">{query.error.message}</p>;
  const data = query.data;
  return <section className="max-w-6xl space-y-5"><header><Link className="underline" to={`/projects/${data.run.project_id}`}>프로젝트로 돌아가기</Link><h1 className="mt-2 text-xl font-bold">LEC 실패 탐색 · 런 #{runId}</h1></header><RunEvidencePanel run={data.run}/><p>판정 {data.lec_status} · Reference/Implementation TOP {data.reference_top} / {data.implementation_top}</p><p>Compare point {data.summary.reference_compare_points} / {data.summary.implementation_compare_points} · 일치 {data.summary.matched_points}</p>{data.error_message && <p role="alert">실행 오류: {data.error_message}</p>}<div className="flex flex-wrap gap-3"><label>종류<select className="input" value={kind} onChange={event => change('kind', event.target.value)}>{Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>검색<input className="input" value={search} onChange={event => change('q', event.target.value)} placeholder="이름·reference·implementation·메시지"/></label></div><p>검색 결과 {data.total} / 실패 {data.reported_total}개</p><ul className="space-y-2">{data.items.map(item => <li className="rounded border p-3" key={item.index}><strong>{labels[item.kind]} · {item.name} · {item.severity}</strong><p>Reference: {item.reference_object || '미보고'} · Implementation: {item.implementation_object || '미보고'}</p><p className="whitespace-pre-wrap">{item.message}</p></li>)}</ul>{data.items.length === 0 && <p>조건에 맞는 실패가 없습니다.</p>}<nav className="flex gap-2"><button className="btn btn-ghost" disabled={!offset} onClick={() => change('offset', String(Math.max(0, offset - 25)))}>이전</button><button className="btn btn-ghost" disabled={offset + 25 >= data.total} onClick={() => change('offset', String(offset + 25))}>다음</button></nav><p className="text-xs">서버가 보존한 LEC 결과만 표시하며 AI는 판정이나 탐색에 개입하지 않습니다.</p></section>;
}
