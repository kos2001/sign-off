import { useLanguage } from './LanguageProvider';
import { Component, useEffect, useRef, type ReactNode } from 'react';
import { Link, useLocation } from 'react-router';

/** A lazily loaded screen whose code the server no longer has (a newer version was deployed). */
function isStaleChunk(error: unknown) {
  const message = error instanceof Error ? `${error.name} ${error.message}` : String(error);
  return /dynamically imported module|Importing a module script failed|ChunkLoadError|Unable to preload CSS/i.test(message);
}

export function ScreenLoading() {
  const { t } = useLanguage();
  return <p role="status" aria-live="polite" className="p-5 text-sm text-[var(--text-secondary)]">{t("화면 불러오는 중…", "Loading screen…")}</p>;
}

function ScreenFailure({ inRouter, stale }: { inRouter: boolean; stale: boolean }) {
  const { t } = useLanguage();
  const Container = inRouter ? 'section' : 'main';
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, []);
  return <Container aria-label={t("화면 오류 복구", "Screen recovery")} className="max-w-xl space-y-4 p-5">
    <h1 ref={heading} tabIndex={-1} className="text-xl font-bold">{stale ? t("새 버전이 배포되었습니다", "A new version is available") : t("화면을 표시하지 못했습니다", "Unable to display this screen")}</h1>
    <p>{stale ? t("이 화면은 이전 버전으로 열려 있어 필요한 파일을 불러오지 못했습니다. 페이지를 새로 고쳐 최신 버전을 여세요.", "This tab is running an earlier version and could not load this screen. Reload the page to open the latest version.") : t("다른 화면으로 이동하거나 페이지를 새로 고쳐 다시 접속하세요.", "Open another screen or reload this page to reconnect.")}</p>
    <p className="text-sm text-[var(--text-secondary)]">{t("새로 고침하면 저장하지 않은 입력이 사라질 수 있습니다. 오류 직전에 저장·승인을 요청했다면 처리 이력을 확인한 뒤 다시 요청하세요.", "Reloading may discard unsaved input. If you requested a save or approval just before the error, check its history before trying again.")}</p>
    <div className="flex flex-wrap gap-2">
      {inRouter ? <Link className="btn btn-primary" to="/">{t("대시보드로 이동", "Go to dashboard")}</Link> : <a className="btn btn-primary" href="/">{t("대시보드로 이동", "Go to dashboard")}</a>}
      <button className="btn btn-ghost" onClick={() => window.location.reload()}>{t("페이지 새로 고침", "Reload page")}</button>
    </div>
  </Container>;
}

/** Rendering/lifecycle failures only; API and event-handler errors keep their local recovery. */
export class ScreenBoundary extends Component<{ children: ReactNode; resetKey?: string; inRouter?: boolean }, { failed: boolean; stale: boolean }> {
  state = { failed: false, stale: false };
  static getDerivedStateFromError(error: unknown) { return { failed: true, stale: isStaleChunk(error) }; }
  componentDidUpdate(previous: Readonly<{ resetKey?: string }>) {
    if (this.state.failed && previous.resetKey !== this.props.resetKey) this.setState({ failed: false, stale: false });
  }
  render() { return this.state.failed ? <ScreenFailure inRouter={!!this.props.inRouter} stale={this.state.stale} /> : this.props.children; }
}

export function RouteScreenBoundary({ children }: { children: ReactNode }) {
  const location = useLocation();
  return <ScreenBoundary resetKey={location.key} inRouter>{children}</ScreenBoundary>;
}
