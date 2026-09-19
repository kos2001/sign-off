import { useEffect, useRef } from 'react';
import { Link, Navigate, NavLink, useParams } from 'react-router';
import { useLanguage } from '../components/LanguageProvider';
import { guideCopy, guideSections, type GuideLanguage, type GuideSection } from '../serviceGuide';

export function GuideEntry() {
  return <Navigate replace to="/guide/overview" />;
}

// Preserve previously shared links while normalizing to language-independent routes.
export function LegacyGuideEntry() {
  const { language, section } = useParams();
  const { setLanguage } = useLanguage();
  useEffect(() => {
    if (language === 'ko' || language === 'en') setLanguage(language);
  }, [language, setLanguage]);
  return <Navigate replace to={`/guide/${guideSections.includes(section as GuideSection) ? section : 'overview'}`} />;
}

export default function ServiceGuide() {
  const { section } = useParams();
  const { language } = useLanguage();
  if (!guideSections.includes(section as GuideSection)) return <GuideEntry />;
  return <GuideContent language={language} section={section as GuideSection} />;
}

function GuideContent({ language, section }: { language: GuideLanguage; section: GuideSection }) {
  const copy = guideCopy[language];
  const page = copy.pages[section];
  const heading = useRef<HTMLHeadingElement>(null);
  const next = guideSections[(guideSections.indexOf(section) + 1) % guideSections.length];
  useEffect(() => {
    const oldTitle = document.title;
    document.title = `${copy.nav[section]} · Sign-off Hub`;
    heading.current?.focus({ preventScroll: true });
    window.scrollTo(0, 0);
    return () => { document.title = oldTitle; };
  }, [language, section, copy]);
  return <div className="guide-shell" lang={language}>
    <a className="guide-skip" href="#guide-content">{copy.skip}</a>
    <nav className="guide-nav" aria-label={language === 'ko' ? '서비스 안내' : 'Service guide'}>
      {guideSections.map(key => <NavLink key={key} to={`/guide/${key}`} className={({ isActive }) => isActive ? 'guide-tab active' : 'guide-tab'}>{copy.nav[key]}</NavLink>)}
    </nav>
    <main id="guide-content" className="guide-main" tabIndex={-1}>
      <header className="guide-hero">
        <p className="guide-eyebrow">{page.eyebrow}</p>
        <h1 ref={heading} tabIndex={-1}>{page.title}</h1>
        <p className="guide-intro">{page.intro}</p>
        {section === 'overview' && <div className="guide-hero-links">
          <Link className="btn btn-primary" to={`/guide/workflow`}>{copy.nav.workflow} <span aria-hidden="true">→</span></Link>
          <Link className="btn btn-ghost" to={`/guide/start`}>{copy.nav.start}</Link>
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
            {item.to && <Link className="guide-action" to={item.to}>{language === 'ko' ? '관련 작업 화면' : 'Open related workspace'} <span aria-hidden="true">↗</span></Link>}
          </div>
        </article>)}
      </section>
      <aside className="guide-note"><h2>{language === 'ko' ? '사용 전에 알아두세요' : 'Before you use it'}</h2><p>{page.note}</p></aside>
      <footer className="guide-footer"><p>{copy.purpose}</p><Link to={`/guide/${next}`}>{copy.next}: {copy.nav[next]} <span aria-hidden="true">→</span></Link></footer>
    </main>
  </div>;
}
