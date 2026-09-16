import { useState } from 'react';
import type { TimingPathPage } from '../api';

export function TimingGroups({ groups, onSelect }: {
  groups: TimingPathPage['groups']; onSelect: (group: string, kind: 'min' | 'max') => void;
}) {
  const [offset, setOffset] = useState(0);
  return <section aria-label="보고서 경로 그룹" className="rounded-xl border border-[var(--border)] p-4 space-y-3">
    <h2 className="font-semibold">보고서 경로 그룹</h2>
    <p className="text-xs text-[var(--text-secondary)]">현재 검색 조건과 무관하게 보고된 전체 경로를 그룹·min/max별로 집계합니다. 중복 경로도 포함하며 전체 설계의 WNS·TNS를 의미하지 않습니다. 그룹 보기를 누르면 기존 검색 조건을 해당 그룹과 유형으로 바꿉니다. 이 집계에는 AI가 개입하지 않습니다.</p>
    <ul className="grid gap-3 sm:grid-cols-2">{groups.slice(offset, offset + 10).map(group => <li key={JSON.stringify([group.path_group, group.path_type])} className="rounded-lg bg-[var(--surface-2)] p-3 space-y-2 min-w-0">
      <h3 className="text-sm font-semibold break-all">{group.path_group || '(빈 그룹 이름)'} · {group.path_type}</h3>
      <p className="text-xs">보고 {group.total}개 · 음수 {group.violated_paths}개 · 0 이상 {group.met_paths}개 · 제약 없음 {group.unconstrained_paths}개</p>
      <p className="text-xs break-all">최악 보고 슬랙: {group.worst_slack_ps === null ? '없음' : `${group.worst_slack_ps} ps`}</p>
      <button className="btn btn-ghost" aria-label={`${group.path_group || '(빈 그룹 이름)'} ${group.path_type} 그룹 보기`} onClick={() => onSelect(group.path_group, group.path_type)}>그룹 보기</button>
    </li>)}</ul>
    {groups.length === 0 && <p className="text-sm">보고된 경로 그룹이 없습니다.</p>}
    {groups.length > 10 && <nav aria-label="경로 그룹 페이지" className="flex flex-wrap gap-3 items-center text-xs">
      <button className="btn btn-ghost" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 10))}>이전 그룹</button>
      <span>{offset + 1}–{Math.min(offset + 10, groups.length)} / {groups.length}</span>
      <button className="btn btn-ghost" disabled={offset + 10 >= groups.length} onClick={() => setOffset(offset + 10)}>다음 그룹</button>
    </nav>}
  </section>;
}
