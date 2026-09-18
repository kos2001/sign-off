import { useQuery } from '@tanstack/react-query';
import { Link, useParams, useSearchParams } from 'react-router';
import { api, type LvsKind } from '../api';
import { RunEvidencePanel } from '../components/RunEvidencePanel';

const labels: Record<'all' | LvsKind, string> = { all: '전체', open: 'Open', short: 'Short', missing_device: '누락 소자', extra_device: '추가 소자', device_mismatch: '소자 불일치', port_mismatch: '포트 불일치', property_mismatch: '속성 불일치' };
export default function LvsMismatches() {
  const runId = Number(useParams().runId), [params, setParams] = useSearchParams();
  const offset = Math.max(0, Number(params.get('offset')) || 0), kind = params.get('kind') || 'all', search = params.get('q') || '';
  const query = useQuery({ queryKey: ['lvs-mismatches', runId, kind, search, offset], queryFn: () => api.lvsMismatches(runId, { kind, q: search, offset: String(offset), limit: '25' }) });
  function change(key: string, value: string) { setParams(previous => { const next = new URLSearchParams(previous); value ? next.set(key, value) : next.delete(key); if (key !== 'offset') next.delete('offset'); return next; }); }
  if (query.isPending) return <p>LVS 결과 불러오는 중…</p>;
  if (query.isError) return <p role="alert">{query.error.message}</p>;
  const data = query.data;
  return <section className="max-w-6xl space-y-5"><header><Link className="underline" to={`/projects/${data.run.project_id}`}>프로젝트로 돌아가기</Link><h1 className="mt-2 text-xl font-bold">LVS 불일치 탐색 · 런 #{runId}</h1></header><RunEvidencePanel run={data.run}/><p>판정 {data.lvs_status} · Layout/Schematic TOP {data.layout_top} / {data.schematic_top}</p><p>소자 {data.summary.layout_devices} / {data.summary.schematic_devices} · Net {data.summary.layout_nets} / {data.summary.schematic_nets}</p>{data.error_message && <p role="alert">실행 오류: {data.error_message}</p>}<div className="flex flex-wrap gap-3"><label>종류<select className="input" value={kind} onChange={event => change('kind', event.target.value)}>{Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>검색<input className="input" value={search} onChange={event => change('q', event.target.value)} placeholder="이름·layout·schematic·메시지"/></label></div><p>검색 결과 {data.total} / 불일치 {data.reported_total}개</p><ul className="space-y-2">{data.items.map(item => <li className="rounded border p-3" key={item.index}><strong>{labels[item.kind]} · {item.name} · {item.severity}</strong><p>Layout: {item.layout_object || '미보고'} · Schematic: {item.schematic_object || '미보고'}</p><p className="whitespace-pre-wrap">{item.message}</p></li>)}</ul>{data.items.length === 0 && <p>조건에 맞는 불일치가 없습니다.</p>}<nav className="flex gap-2"><button className="btn btn-ghost" disabled={!offset} onClick={() => change('offset', String(Math.max(0, offset - 25)))}>이전</button><button className="btn btn-ghost" disabled={offset + 25 >= data.total} onClick={() => change('offset', String(offset + 25))}>다음</button></nav><p className="text-xs">서버가 보존한 LVS 결과만 표시하며 AI는 판정이나 탐색에 개입하지 않습니다.</p></section>;
}
