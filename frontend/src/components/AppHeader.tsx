import { Link, NavLink } from 'react-router';
import { useLanguage } from './LanguageProvider';

/** One language preference and one control for the public guide and workspace. */
export function AppHeader() {
  const { language, setLanguage, t } = useLanguage();
  return <header className="global-header">
    <Link className="guide-brand" to="/guide/overview"><span aria-hidden="true">S</span> Sign-off Hub</Link>
    <div className="guide-header-actions">
      <nav className="global-navigation" aria-label={t('서비스 메뉴', 'Service navigation')}>
        <NavLink to="/guide/overview">{t('서비스 소개', 'Service guide')}</NavLink>
        <NavLink to="/" end>{t('작업 공간', 'Workspace')}</NavLink>
      </nav>
      <div className="guide-languages" role="group" aria-label={t('서비스 언어', 'Service language')}>
        <button type="button" lang="ko" aria-pressed={language === 'ko'} onClick={() => setLanguage('ko')}>한국어</button>
        <button type="button" lang="en" aria-pressed={language === 'en'} onClick={() => setLanguage('en')}>English</button>
      </div>
    </div>
  </header>;
}
