import { NavLink, Route, Routes } from "react-router";

import Analysis from "./pages/Analysis";
import Dashboard from "./pages/Dashboard";
import ProjectDetail from "./pages/ProjectDetail";

export default function App() {
  return (
    <div className="mx-auto min-h-screen max-w-4xl px-5 pb-16">
      <header className="mb-8 flex items-center justify-between pt-8">
        <div className="flex items-center gap-2.5">
          <span
            aria-hidden
            className="flex h-8 w-8 items-center justify-center rounded-lg text-sm font-bold text-white"
            style={{ background: "var(--series-1)" }}
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
        <nav className="flex gap-1">
          {[
            { to: "/", label: "대시보드" },
            { to: "/analysis", label: "분석 도구" },
          ].map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className="rounded-lg px-3 py-1.5 text-sm font-medium"
              style={({ isActive }) =>
                isActive
                  ? { background: "var(--surface-1)", border: "1px solid var(--border)" }
                  : { color: "var(--text-secondary)" }
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>

      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/projects/:id" element={<ProjectDetail />} />
        <Route path="/analysis" element={<Analysis />} />
      </Routes>
    </div>
  );
}
