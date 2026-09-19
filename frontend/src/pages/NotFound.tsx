import { useLanguage } from '../components/LanguageProvider';
import { useEffect, useRef } from 'react';
import { Link } from 'react-router';

export default function NotFound() {
  const { t } = useLanguage();
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, []);
  return <section aria-label={t("없는 페이지", "Page not found")} className="max-w-xl space-y-4">
    <h1 ref={heading} tabIndex={-1} className="text-xl font-bold">{t("페이지를 찾을 수 없습니다", "Page not found")}</h1>
    <p>{t("링크 주소를 확인하거나 대시보드에서 프로젝트를 다시 선택하세요.", "Check the URL or select a project from the dashboard.")}</p>
    <Link className="btn btn-primary" to="/">{t("대시보드로 이동", "Go to dashboard")}</Link>
  </section>;
}
