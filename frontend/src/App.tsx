import { NavLink, Route, Routes } from "react-router";

import Analysis from "./pages/Analysis";
import Dashboard from "./pages/Dashboard";
import ProjectDetail from "./pages/ProjectDetail";

export default function App() {
  return (
    <div className="min-h-screen">
      <header className="app-header">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-3.5">
          <div className="flex items-center gap-2.5">
            <span
              aria-hidden
              className="flex h-8 w-8 items-center justify-center rounded-lg text-sm font-bold text-white"
              style={{
                background: "linear-gradient(135deg, var(--series-1), var(--seq-600))",
              }}
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
                className={({ isActive }) =>
                  `nav-pill ${isActive ? "nav-pill-active" : ""}`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 pb-20 pt-8">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/projects/:id" element={<ProjectDetail />} />
          <Route path="/analysis" element={<Analysis />} />
        </Routes>
      </main>
    </div>
  );
}
