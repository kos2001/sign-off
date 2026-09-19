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
  const auth = useAuth();
  const [logoutError, setLogoutError] = useState("");
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.listProjects });
  const [mobileOpen, setMobileOpen] = useState(false);
  const { pathname, hash } = useLocation();
  useEffect(() => setMobileOpen(false), [pathname, hash]);

  return (
    <aside className="sidebar">
      <div className="flex items-center gap-2.5 px-1 md:mb-6">
        <span
          aria-hidden
          className="flex h-8 w-8 items-center justify-center rounded-lg text-sm font-bold text-white"
          style={{ background: "linear-gradient(135deg, var(--series-1), var(--seq-600))" }}
        >
          S
        </span>
        <div>
          <h1 className="text-base font-bold leading-tight">Sign-off Hub</h1>
          <p className="text-xs leading-tight" style={{ color: "var(--text-muted)" }}>
            칩 설계 사인오프 관리 · 분석
          </p>
        </div>
        <button className="btn btn-ghost ml-auto md:hidden" aria-expanded={mobileOpen} aria-controls="main-navigation" onClick={() => setMobileOpen(!mobileOpen)}>{mobileOpen ? "메뉴 닫기" : "메뉴"}</button>
      </div>

      <nav id="main-navigation" aria-label="주 메뉴" className={mobileOpen ? "mt-5 md:mt-0" : "hidden md:block"}>
        <div className="mb-5 text-xs space-y-2">{auth.state.user ? <><p>로그인: {auth.state.user.username}{auth.state.user.is_admin ? " · 관리자" : ""}</p><button className="btn btn-ghost" onClick={() => auth.logout().catch(error => setLogoutError(error.message))}>로그아웃</button><NavLink className="btn btn-ghost" to="/account">계정 설정</NavLink>{logoutError && <p role="alert">{logoutError}</p>}</> : <p>로컬 모드 · 계정 인증 없음</p>}</div>
        <SidebarSection title="개요" items={[{ to: "/", label: "대시보드" }, { to: "/guide", label: "서비스 소개 · 한국어 / English" }, { to: "/agents", label: "에이전트 개입 안내" }]} />
        {auth.state.user?.is_admin && <SidebarSection title="운영 관리" items={[{ to: '/admin/security-events', label: '보안 이력 관리' }]} />}

        <SidebarSection
          title="프로젝트"
          items={(projects.data ?? []).map((p) => ({
            to: `/projects/${p.id}`,
            label: p.name,
          }))}
        />

        <SidebarSection
          title="분석 도구"
          items={[
            { to: "/analysis", label: "분석 도구 선택" },
            { to: "/analysis/rtl", label: "RTL 사인오프 래더" },
            { to: "/analysis/sta", label: "OpenSTA 타이밍 실행" },
            { to: "/analysis/ir-drop", label: "IR-drop 스크리닝" },
            { to: "/analysis/timing", label: "MMMC 타이밍" },
            { to: "/analysis/glitch-power", label: "글리치 파워" },
          ]}
        />
      </nav>
    </aside>
  );
}
