import { useQuery } from "@tanstack/react-query";
import { NavLink, useLocation } from "react-router";

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
            : pathname === item.to;
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
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.listProjects });

  return (
    <aside className="sidebar">
      <div className="mb-6 flex items-center gap-2.5 px-1">
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
      </div>

      <nav>
        <SidebarSection title="개요" items={[{ to: "/", label: "대시보드" }]} />

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
            { to: "/analysis#rtl-signoff", label: "RTL 사인오프 래더" },
            { to: "/analysis#ir-drop", label: "IR-drop 스크리닝" },
            { to: "/analysis#timing", label: "MMMC 타이밍" },
            { to: "/analysis#glitch-power", label: "글리치 파워" },
          ]}
        />
      </nav>
    </aside>
  );
}
