import { useEffect, useRef } from 'react';
import { Link } from 'react-router';

export default function NotFound() {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, []);
  return <section aria-label="없는 페이지" className="max-w-xl space-y-4">
    <h1 ref={heading} tabIndex={-1} className="text-xl font-bold">페이지를 찾을 수 없습니다</h1>
    <p>링크 주소를 확인하거나 대시보드에서 프로젝트를 다시 선택하세요.</p>
    <Link className="btn btn-primary" to="/">대시보드로 이동</Link>
  </section>;
}
