import { useState } from 'react';
import type { TimingPathPage } from '../api';
import { useLanguage } from './LanguageProvider';

export function TimingGroups({ groups, onSelect }: {
  groups: TimingPathPage['groups']; onSelect: (group: string, kind: 'min' | 'max') => void;
}) {
  const { t } = useLanguage();
  const [offset, setOffset] = useState(0);
  const emptyName = t('(빈 그룹 이름)', '(empty group name)');
  return <section aria-label={t('보고서 경로 그룹', 'Reported path groups')} className="rounded-xl border border-[var(--border)] p-4 space-y-3">
    <h2 className="font-semibold">{t('보고서 경로 그룹', 'Reported path groups')}</h2>
    <p className="text-xs text-[var(--text-secondary)]">{t('현재 검색 조건과 무관하게 보고된 전체 경로를 그룹·min/max별로 집계합니다. 중복 경로도 포함하며 전체 설계의 WNS·TNS를 의미하지 않습니다. 그룹 보기를 누르면 기존 검색 조건을 해당 그룹과 유형으로 바꿉니다. 이 집계에는 AI가 개입하지 않습니다.', 'Counts every reported path by group and min/max, regardless of the current search. Duplicate paths are included, and these figures are not the design-wide WNS or TNS. View group replaces the current search with that group and type. No AI is involved in this summary.')}</p>
    <ul className="grid gap-3 sm:grid-cols-2">{groups.slice(offset, offset + 10).map(group => <li key={JSON.stringify([group.path_group, group.path_type])} className="rounded-lg bg-[var(--surface-2)] p-3 space-y-2 min-w-0">
      <h3 className="text-sm font-semibold break-all">{group.path_group || emptyName} · {group.path_type}</h3>
      <p className="text-xs">{t(`보고 ${group.total}개 · 음수 ${group.violated_paths}개 · 0 이상 ${group.met_paths}개 · 제약 없음 ${group.unconstrained_paths}개`, `${group.total} reported · ${group.violated_paths} negative · ${group.met_paths} zero or positive · ${group.unconstrained_paths} unconstrained`)}</p>
      <p className="text-xs break-all">{t('최악 보고 슬랙', 'Worst reported slack')}: {group.worst_slack_ps === null ? t('없음', 'None') : `${group.worst_slack_ps} ps`}</p>
      <button className="btn btn-ghost" aria-label={t(`${group.path_group || emptyName} ${group.path_type} 그룹 보기`, `View group ${group.path_group || emptyName} ${group.path_type}`)} onClick={() => onSelect(group.path_group, group.path_type)}>{t('그룹 보기', 'View group')}</button>
    </li>)}</ul>
    {groups.length === 0 && <p className="text-sm">{t('보고된 경로 그룹이 없습니다.', 'No path groups were reported.')}</p>}
    {groups.length > 10 && <nav aria-label={t('경로 그룹 페이지', 'Path group pages')} className="flex flex-wrap gap-3 items-center text-xs">
      <button className="btn btn-ghost" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 10))}>{t('이전 그룹', 'Previous groups')}</button>
      <span>{offset + 1}–{Math.min(offset + 10, groups.length)} / {groups.length}</span>
      <button className="btn btn-ghost" disabled={offset + 10 >= groups.length} onClick={() => setOffset(offset + 10)}>{t('다음 그룹', 'Next groups')}</button>
    </nav>}
  </section>;
}
