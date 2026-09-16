import NotFound from "./pages/NotFound";
import { RouteScreenBoundary } from "./components/ScreenBoundary";
import { AuthProvider } from "./components/AuthProvider";
import AgentGuide from "./pages/AgentGuide";
import Account from "./pages/Account";
import SecurityEvents from './pages/SecurityEvents';
import ReportImport from "./pages/ReportImport";
import TimingPaths from "./pages/TimingPaths";
import Markers from './pages/Markers';
import ProjectMembers from "./pages/ProjectMembers";
import { Route, Routes } from "react-router";

import { Sidebar } from "./components/Sidebar";
import Analysis from "./pages/Analysis";
import Dashboard from "./pages/Dashboard";
import ProjectDetail from "./pages/ProjectDetail";
import Violations from "./pages/Violations";
import RunComparison from "./pages/RunComparison";
import { ReviewDraftProvider } from "./components/ReviewDrafts";

export default function App() {
  return (
    <AuthProvider><ReviewDraftProvider><div className="app-shell">
      <Sidebar />
      <main className="app-main">
        <RouteScreenBoundary><Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/projects/:id" element={<ProjectDetail />} />
          <Route path="/projects/:id/violations" element={<Violations />} />
          <Route path="/projects/:id/compare" element={<RunComparison />} />
          <Route path="/projects/:id/import" element={<ReportImport />} />
          <Route path="/projects/:id/import/klayout" element={<ReportImport klayout />} />
          <Route path="/runs/:runId/paths" element={<TimingPaths />} />
          <Route path="/runs/:runId/markers" element={<Markers />} />
          <Route path="/projects/:id/members" element={<ProjectMembers />} />
          <Route path="/account" element={<Account />} />
          <Route path="/admin/security-events" element={<SecurityEvents />} />
          <Route path="/agents" element={<AgentGuide />} />
          <Route path="/analysis" element={<Analysis />} />
          <Route path="*" element={<NotFound />} />
        </Routes></RouteScreenBoundary>
      </main>
    </div></ReviewDraftProvider></AuthProvider>
  );
}
