import { useLanguage } from './LanguageProvider';
import { Component, useEffect, useRef, type ReactNode } from 'react';
import { Link, useLocation } from 'react-router';

function ScreenFailure({ inRouter }: { inRouter: boolean }) {
  const { t } = useLanguage();
  const Container = inRouter ? 'section' : 'main';
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, []);
  return <Container aria-label={t("화면 오류 복구", "Screen recovery")} className="max-w-xl space-y-4 p-5">
    <h1 ref={heading} tabIndex={-1} className="text-xl font-bold">{t("화면을 표시하지 못했습니다", "Unable to display this screen")}</h1>
    <p>{t("다른 화면으로 이동하거나 페이지를 새로 고쳐 다시 접속하세요.", "Open another screen or reload this page to reconnect.")}</p>
    <p className="text-sm text-[var(--text-secondary)]">{t("새로 고침하면 저장하지 않은 입력이 사라질 수 있습니다. 오류 직전에 저장·승인을 요청했다면 처리 이력을 확인한 뒤 다시 요청하세요.", "Reloading may discard unsaved input. If you requested a save or approval just before the error, check its history before trying again.")}</p>
    <div className="flex flex-wrap gap-2">
      {inRouter ? <Link className="btn btn-primary" to="/">{t("대시보드로 이동", "Go to dashboard")}</Link> : <a className="btn btn-primary" href="/">{t("대시보드로 이동", "Go to dashboard")}</a>}
      <button className="btn btn-ghost" onClick={() => window.location.reload()}>{t("페이지 새로 고침", "Reload page")}</button>
    </div>
  </Container>;
}

/** Rendering/lifecycle failures only; API and event-handler errors keep their local recovery. */
export class ScreenBoundary extends Component<{ children: ReactNode; resetKey?: string; inRouter?: boolean }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidUpdate(previous: Readonly<{ resetKey?: string }>) {
    if (this.state.failed && previous.resetKey !== this.props.resetKey) this.setState({ failed: false });
  }
  render() { return this.state.failed ? <ScreenFailure inRouter={!!this.props.inRouter} /> : this.props.children; }
}

export function RouteScreenBoundary({ children }: { children: ReactNode }) {
  const location = useLocation();
  return <ScreenBoundary resetKey={location.key} inRouter>{children}</ScreenBoundary>;
}
