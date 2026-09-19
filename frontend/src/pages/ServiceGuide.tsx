import { useEffect, useRef } from 'react';
import { Link, Navigate, NavLink, useParams } from 'react-router';
import { guideCopy, guideSections, preferredGuideLanguage, type GuideLanguage, type GuideSection } from '../serviceGuide';

export function GuideEntry() {
  return <Navigate replace to={`/guide/${preferredGuideLanguage()}/overview`} />;
}

export default function ServiceGuide() {
  const { language, section } = useParams();
  if ((language !== 'ko' && language !== 'en') || !guideSections.includes(section as GuideSection)) return <GuideEntry />;
  return <GuideContent language={language} section={section as GuideSection} />;
}

function GuideContent({ language, section }: { language: GuideLanguage; section: GuideSection }) {
  const copy = guideCopy[language];
  const page = copy.pages[section];
  const heading = useRef<HTMLHeadingElement>(null);
  const next = guideSections[(guideSections.indexOf(section) + 1) % guideSections.length];
  useEffect(() => {
    const oldLang = document.documentElement.lang;
    const oldTitle = document.title;
    document.documentElement.lang = language;
    document.title = `${copy.nav[section]} · Sign-off Hub`;
    try { localStorage.setItem('signoff-guide-language', language); } catch { /* Storage is optional. */ }
    heading.current?.focus({ preventScroll: true });
    window.scrollTo(0, 0);
    return () => { document.documentElement.lang = oldLang; document.title = oldTitle; };
  }, [language, section, copy]);
  return <div className="guide-shell" lang={language}>
    <a className="guide-skip" href="#guide-content">{copy.skip}</a>
    <header className="guide-header">
      <Link className="guide-brand" to={`/guide/${language}/overview`}><span aria-hidden="true">S</span> Sign-off Hub</Link>
      <div className="guide-header-actions">
        <nav className="guide-languages" aria-label={language === 'ko' ? '언어 선택' : 'Language selection'}>
          {(['ko', 'en'] as const).map(lang => <Link key={lang} to={`/guide/${lang}/${section}`} lang={lang} hrefLang={lang} aria-current={language === lang ? 'page' : undefined}>{lang === 'ko' ? '한국어' : 'English'}</Link>)}
        </nav>
        <Link className="btn btn-primary" to="/">{copy.workspace} <span aria-hidden="true">↗</span></Link>
      </div>
    </header>
    <nav className="guide-nav" aria-label={language === 'ko' ? '서비스 안내' : 'Service guide'}>
      {guideSections.map(key => <NavLink key={key} to={`/guide/${language}/${key}`} className={({ isActive }) => isActive ? 'guide-tab active' : 'guide-tab'}>{copy.nav[key]}</NavLink>)}
    </nav>
    <main id="guide-content" className="guide-main" tabIndex={-1}>
      <header className="guide-hero">
        <p className="guide-eyebrow">{page.eyebrow}</p>
        <h1 ref={heading} tabIndex={-1}>{page.title}</h1>
        <p className="guide-intro">{page.intro}</p>
        {section === 'overview' && <div className="guide-hero-links">
          <Link className="btn btn-primary" to={`/guide/${language}/workflow`}>{copy.nav.workflow} <span aria-hidden="true">→</span></Link>
          <Link className="btn btn-ghost" to={`/guide/${language}/start`}>{copy.nav.start}</Link>
        </div>}
      </header>
      {(section === 'overview' || section === 'workflow') && <section className="guide-flow" aria-label={copy.nav.workflow}>
        <p className="guide-eyebrow">{copy.scope}</p>
        <ol>{copy.flow.map((stage, index) => <li key={stage}><span className="guide-step-number">0{index + 1}</span><span>{stage}</span></li>)}</ol>
        <div className="guide-flow-caption"><strong>Sign-off Hub</strong><span>{copy.flowLabel}</span></div>
      </section>}
      <section className={`guide-cards ${section === 'workflow' || section === 'start' ? 'guide-sequence' : ''}`} aria-label={copy.nav[section]}>
        {page.items.map((item, index) => <article className="guide-card" key={item.title}>
          <span className="guide-card-index" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
          <div><h2>{item.title}</h2><p>{item.body}</p>{item.detail && <p className="guide-detail">{item.detail}</p>}
            {item.to && <Link className="guide-action" to={item.to}>{language === 'ko' ? '관련 작업 화면' : 'Open related workspace (Korean)'} <span aria-hidden="true">↗</span></Link>}
          </div>
        </article>)}
      </section>
      <aside className="guide-note"><h2>{language === 'ko' ? '사용 전에 알아두세요' : 'Before you use it'}</h2><p>{page.note}</p></aside>
      <footer className="guide-footer"><p>{copy.purpose}</p><Link to={`/guide/${language}/${next}`}>{copy.next}: {copy.nav[next]} <span aria-hidden="true">→</span></Link></footer>
    </main>
  </div>;
}
