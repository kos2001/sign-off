import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, type MarkerDetail } from '../api';
import { ViolationActions } from './ViolationActions';
import { tr, useLanguage } from './LanguageProvider';

const labels = {
  get open() { return tr('미해결', 'Open'); },
  get fixed() { return tr('수정 완료', 'Fixed'); },
  get waived() { return tr('웨이버 승인', 'Waiver approved'); },
};
export function MarkerViolationReview({ runId, projectId, matches, onChange }: {
  runId: number; projectId: number; matches: MarkerDetail['violation_matches']; onChange: () => void;
}) {
  const { t } = useLanguage();
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
  return <section aria-label={t('마커에 연결된 위반 검토', 'Review violations linked to this marker')} className="border-t border-[var(--border)] pt-4 space-y-3">
    <h3 className="font-semibold">{t('현재 위반 처리 상태', 'Current violation status')}</h3>
    <p>{t('같은 런의 규칙·셀·마커 값 지문으로 연결합니다. 원본 태그와 현재 처리 상태는 별개입니다.', 'Linked by the rule, cell and marker-value fingerprint within the same run. Source tags are separate from the current resolution status.')}</p>
    {matches.status === 'ambiguous' && <p role="status">{t(`동일 지문의 원본 마커 ${matches.source_marker_count}개, 위반 기록 ${matches.items.length}개가 있어 일대일 대응을 확정할 수 없습니다. 위반 번호·설명·이력을 확인하고 개별 기록을 선택하세요. 일괄 변경하지 않습니다.`, `There are ${matches.source_marker_count} source markers and ${matches.items.length} violation records with the same fingerprint, so a one-to-one match cannot be confirmed. Check the violation number, description and history, then select an individual record. Records are not changed in bulk.`)}</p>}
    {matches.status === 'missing' && <p>{t('연결된 위반 기록이 없습니다. 원본 마커를 해결된 것으로 판단하지 않습니다.', 'No linked violation record. The source marker is not treated as resolved.')}</p>}
    <button className="btn btn-ghost" onClick={refresh}>{t('위반 상태 새로고침', 'Refresh violation status')}</button>
    <ul className="space-y-2">{matches.items.slice(pageOffset, pageOffset+25).map(item => <li key={item.id}><button className="btn btn-ghost" aria-pressed={selected === item.id} onClick={() => setSelected(item.id)}>{t('위반', 'Violation')} #{item.id} · {labels[item.status]} · {t('버전', 'version')} {item.version}</button></li>)}</ul>
    {matches.items.length > 25 && <div className="flex gap-2"><button className="btn btn-ghost" disabled={pageOffset === 0} onClick={() => setOffset(pageOffset-25)}>{t('이전 연결 위반', 'Previous linked violations')}</button><button className="btn btn-ghost" disabled={pageOffset+25 >= matches.items.length} onClick={() => setOffset(pageOffset+25)}>{t('다음 연결 위반', 'Next linked violations')}</button></div>}
    {valid && (current.isPending ? <p role="status">{t('위반 불러오는 중…', 'Loading violation…')}</p> : current.isError ? <p role="alert">{current.error.message}</p> : current.data.run_id !== runId ? <p role="alert">{t('해당 런의 위반이 아닙니다.', 'This violation does not belong to this run.')}</p> : <section aria-label={t(`위반 #${current.data.id} 처리`, `Resolve violation #${current.data.id}`)} className="rounded border border-[var(--border)] p-3 break-words">
      <h4 className="font-semibold mb-2">{t(`위반 #${current.data.id} · 현재 버전 ${current.data.version}`, `Violation #${current.data.id} · current version ${current.data.version}`)}</h4>
      <ViolationActions key={current.data.id} violation={current.data} projectId={projectId} onChange={refresh} />
    </section>)}
  </section>;
}
