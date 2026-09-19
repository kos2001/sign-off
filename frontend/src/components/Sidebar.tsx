import { useLanguage } from './LanguageProvider';
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router";

import { useAuth } from "./AuthProvider";
import { api } from "../api";

interface NavItem {
  to: string;
  label: string;
}

function SidebarSection({ title, items }: { title: string; items: NavItem[] }) {
  const { pathname, hash } = useLocation();
  if (items.length === 0) return null;
  return (
    <div className="mb-5">
      <h2 className="sidebar-section-title">{title}</h2>
      <ul className="mt-1.5 space-y-0.5">
        {items.map((item) => {
          const [itemPath, itemHash] = item.to.split("#");
          const isActive = itemHash
            ? pathname === itemPath && hash === `#${itemHash}`
            : pathname === item.to || (item.to !== "/analysis" && pathname.startsWith(`${item.to}/`));
          return (
            <li key={item.to}>
              <NavLink to={item.to} className={`sidebar-link ${isActive ? "sidebar-link-active" : ""}`}>
                {item.label}
              </NavLink>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function Sidebar() {
  const { t } = useLanguage();
  const auth = useAuth();
  const [logoutError, setLogoutError] = useState("");
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.listProjects });
  const [mobileOpen, setMobileOpen] = useState(false);
  const { pathname, hash } = useLocation();
  useEffect(() => setMobileOpen(false), [pathname, hash]);

  return (
    <aside className="sidebar">
      <div className="flex items-center justify-between px-1 md:hidden">
        <span className="text-sm font-medium">{t("작업 메뉴", "Workspace menu")}</span>
        <button className="btn btn-ghost ml-auto md:hidden" aria-expanded={mobileOpen} aria-controls="main-navigation" onClick={() => setMobileOpen(!mobileOpen)}>{mobileOpen ? t("메뉴 닫기", "Close menu") : t("메뉴", "Menu")}</button>
      </div>

      <nav id="main-navigation" aria-label={t("주 메뉴", "Main navigation")} className={mobileOpen ? "mt-5 md:mt-0" : "hidden md:block"}>
        <div className="mb-5 text-xs space-y-2">{auth.state.user ? <><p>{t("로그인:", "Signed in:")} {auth.state.user.username}{auth.state.user.is_admin ? " · 관리자" : ""}</p><button className="btn btn-ghost" onClick={() => auth.logout().catch(error => setLogoutError(error.message))}>{t("로그아웃", "Sign out")}</button><NavLink className="btn btn-ghost" to="/account">{t("계정 설정", "Account settings")}</NavLink>{logoutError && <p role="alert">{logoutError}</p>}</> : <p>{t("로컬 모드 · 계정 인증 없음", "Local mode · no account authentication")}</p>}</div>
        <SidebarSection title={t("개요", "Overview")} items={[{ to: "/", label: t("대시보드", "Dashboard") }, { to: "/guide", label: t("서비스 소개", "Service guide") }, { to: "/agents", label: t("에이전트 개입 안내", "Agent responsibilities") }]} />
        {auth.state.user?.is_admin && <SidebarSection title={t("운영 관리", "Administration")} items={[{ to: '/admin/security-events', label: t("보안 이력 관리", "Security events") }]} />}

        <SidebarSection
          title={t("프로젝트", "Projects")}
          items={(projects.data ?? []).map((p) => ({
            to: `/projects/${p.id}`,
            label: p.name,
          }))}
        />

        <SidebarSection
          title={t("분석 도구", "Analysis tools")}
          items={[
            { to: "/analysis", label: t("분석 도구 선택", "Choose an analysis tool") },
            { to: "/analysis/rtl", label: t("RTL 사인오프 래더", "RTL sign-off ladder") },
            { to: "/analysis/sta", label: t("OpenSTA 타이밍 실행", "OpenSTA timing execution") },
            { to: "/analysis/ir-drop", label: t("IR-drop 스크리닝", "IR-drop screening") },
            { to: "/analysis/timing", label: t("MMMC 타이밍", "MMMC timing") },
            { to: "/analysis/glitch-power", label: t("글리치 파워", "Glitch power") },
          ]}
        />
      </nav>
    </aside>
  );
}
