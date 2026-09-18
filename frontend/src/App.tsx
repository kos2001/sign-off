import DesignStructure from "./pages/DesignStructure";
import NotFound from "./pages/NotFound";
import { RouteScreenBoundary } from "./components/ScreenBoundary";
import { AuthProvider } from "./components/AuthProvider";
import AgentGuide from "./pages/AgentGuide";
import Account from "./pages/Account";
import SecurityEvents from './pages/SecurityEvents';
import ReportImport from "./pages/ReportImport";
import TimingPaths from "./pages/TimingPaths";
import Markers from './pages/Markers';
import PowerIntegrityImport from './pages/PowerIntegrityImport';
import PowerIntegrityFindings from './pages/PowerIntegrityFindings';
import CommercialPowerImport from './pages/CommercialPowerImport';
import PowerBreakdown from './pages/PowerBreakdown';
import CommercialThermalImport from './pages/CommercialThermalImport';
import ThermalHotspots from './pages/ThermalHotspots';
import CommercialRtlImport from './pages/CommercialRtlImport';
import RtlRegression from './pages/RtlRegression';
import CommercialLvsImport from './pages/CommercialLvsImport';
import LvsMismatches from './pages/LvsMismatches';
import ProjectMembers from "./pages/ProjectMembers";
import { Route, Routes } from "react-router";

import { Sidebar } from "./components/Sidebar";
import Analysis from "./pages/Analysis";
import Dashboard from "./pages/Dashboard";
import ProjectDetail from "./pages/ProjectDetail";
import Violations from "./pages/Violations";
import RunComparison from "./pages/RunComparison";
import RunWorkspace from "./pages/RunWorkspace";
import StaMatrix from "./pages/StaMatrix";
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
          <Route path="/projects/:id/sta-matrix" element={<StaMatrix />} />
          <Route path="/projects/:id/import" element={<ReportImport />} />
          <Route path="/projects/:id/import/commercial-sta" element={<ReportImport commercialSta />} />
          <Route path="/projects/:id/import/commercial-drc" element={<ReportImport commercialDrc />} />
          <Route path="/projects/:id/import/klayout" element={<ReportImport klayout />} />
          <Route path="/projects/:id/import/commercial-emir" element={<PowerIntegrityImport />} />
          <Route path="/projects/:id/import/commercial-power" element={<CommercialPowerImport />} />
          <Route path="/projects/:id/import/commercial-thermal" element={<CommercialThermalImport />} />
          <Route path="/projects/:id/import/commercial-rtl" element={<CommercialRtlImport />} />
          <Route path="/projects/:id/import/commercial-lvs" element={<CommercialLvsImport />} />
          <Route path="/runs/:runId/structure" element={<DesignStructure />} />
          <Route path="/runs/:runId" element={<RunWorkspace />} />
          <Route path="/runs/:runId/paths" element={<TimingPaths />} />
          <Route path="/runs/:runId/markers" element={<Markers />} />
          <Route path="/runs/:runId/power-integrity" element={<PowerIntegrityFindings />} />
          <Route path="/runs/:runId/power-breakdown" element={<PowerBreakdown />} />
          <Route path="/runs/:runId/thermal-hotspots" element={<ThermalHotspots />} />
          <Route path="/runs/:runId/rtl-regression" element={<RtlRegression />} />
          <Route path="/runs/:runId/lvs-mismatches" element={<LvsMismatches />} />
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
