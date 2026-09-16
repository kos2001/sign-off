import { useId, useRef, useState } from 'react';
import type { MarkerDetail } from '../api';

const initial = { x: 100, y: 100, zoom: 1 };
const clamp = (value: number) => Math.min(200, Math.max(0, value));
export function MarkerGeometryViewer({ geometry, index }: { geometry: MarkerDetail['geometry']; index: number }) {
  const [view, setView] = useState(initial);
  const drag = useRef<{ id: number; x: number; y: number; scale: number; start: typeof initial } | null>(null);
  const help = useId();
  function zoom(factor: number) {
    drag.current = null;
    setView(previous => ({ ...previous, zoom: Math.min(32, Math.max(1, previous.zoom * factor)) }));
  }
  function fit() { drag.current = null; setView(initial); }
  function pan(x: number, y: number) {
    drag.current = null;
    setView(previous => ({ ...previous, x: clamp(previous.x + x / previous.zoom), y: clamp(previous.y + y / previous.zoom) }));
  }
  const size = 200 / view.zoom;
  return <section aria-label="마커 도형 탐색" className="space-y-2 max-w-md">
    <div className="flex flex-wrap gap-2 items-center">
      <button className="btn btn-ghost" disabled={view.zoom >= 32} onClick={() => zoom(2)}>도형 확대</button>
      <button className="btn btn-ghost" disabled={view.zoom <= 1} onClick={() => zoom(0.5)}>도형 축소</button>
      <button className="btn btn-ghost" onClick={fit}>전체 도형 맞춤</button>
      <output aria-live="polite" className="text-xs tabular-nums">확대율 {view.zoom}배</output>
    </div>
    <p id={help} className="text-xs text-[var(--text-secondary)]">도형을 드래그해 이동합니다. 도형에 키보드 초점을 두고 방향키로 이동, +/−로 확대·축소, Home으로 전체 맞춤을 사용할 수 있습니다. 화면 배율만 바뀌며 원본 좌표는 유지됩니다.</p>
    <svg role="img" tabIndex={0} aria-label={`마커 #${index} 셀 좌표 미리보기`} aria-describedby={help}
      viewBox={`${view.x - size / 2} ${view.y - size / 2} ${size} ${size}`}
      className="w-full aspect-square border border-[var(--border)] bg-[var(--surface-2)] focus-visible:outline-2 focus-visible:outline-[var(--series-1)]"
      style={{ touchAction: 'none', cursor: 'grab' }}
      onKeyDown={event => {
        if (event.altKey || event.ctrlKey || event.metaKey) return;
        const actions: Record<string, () => void> = { '+': () => zoom(2), '=': () => zoom(2), '-': () => zoom(0.5), Home: fit,
          ArrowLeft: () => pan(-20, 0), ArrowRight: () => pan(20, 0), ArrowUp: () => pan(0, -20), ArrowDown: () => pan(0, 20) };
        if (actions[event.key]) { event.preventDefault(); actions[event.key](); }
      }}
      onPointerDown={event => {
        if (event.button !== 0 || !event.isPrimary || drag.current) return;
        const width = event.currentTarget.getBoundingClientRect().width;
        if (width <= 0) return;
        event.currentTarget.focus({ preventScroll: true });
        event.currentTarget.setPointerCapture(event.pointerId);
        drag.current = { id: event.pointerId, x: event.clientX, y: event.clientY, scale: size / width, start: view };
      }}
      onPointerMove={event => {
        const active = drag.current;
        if (!active || active.id !== event.pointerId) return;
        setView({ ...active.start, x: clamp(active.start.x - (event.clientX - active.x) * active.scale), y: clamp(active.start.y - (event.clientY - active.y) * active.scale) });
      }}
      onPointerUp={event => { if (drag.current?.id === event.pointerId) drag.current = null; }}
      onPointerCancel={() => { drag.current = null; }} onLostPointerCapture={() => { drag.current = null; }}>
      <title>선택한 마커의 셀 좌표 도형 · µm</title>
      {geometry.shapes.map(shape => <g key={shape.value_index}>
        <path d={shape.contours.map(contour => contour.map((point, i) => `${i ? 'L' : 'M'} ${point[0]} ${point[1]}`).join(' ') + (shape.closed ? ' Z' : '')).join(' ')} fill={shape.closed ? 'var(--series-1)' : 'none'} fillOpacity={0.15} fillRule="evenodd" stroke="var(--series-1)" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
        {!shape.closed && shape.contours.flatMap((contour, ci) => contour.map((point, pi) => <circle key={`${ci}-${pi}`} cx={point[0]} cy={point[1]} r={2 / view.zoom} fill="var(--series-1)" />))}
        {shape.closed && shape.contours.flat().every(point => point[0] === shape.contours[0][0][0] && point[1] === shape.contours[0][0][1]) && <circle cx={shape.contours[0][0][0]} cy={shape.contours[0][0][1]} r={2 / view.zoom} fill="var(--series-1)" />}
      </g>)}
    </svg>
  </section>;
}
