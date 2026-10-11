import { AppHeader } from "./components/AppHeader";
import { RouteScreenBoundary, ScreenLoading } from "./components/ScreenBoundary";
import { AuthProvider } from "./components/AuthProvider";
import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router";

import { Sidebar } from "./components/Sidebar";
import { ReviewDraftProvider } from "./components/ReviewDrafts";

const ServiceGuide = lazy(() => import("./pages/ServiceGuide"));
const GuideEntry = lazy(() => import("./pages/ServiceGuide").then(module => ({ default: module.GuideEntry })));
const LegacyGuideEntry = lazy(() => import("./pages/ServiceGuide").then(module => ({ default: module.LegacyGuideEntry })));
const DesignStructure = lazy(() => import("./pages/DesignStructure"));
const NotFound = lazy(() => import("./pages/NotFound"));
const AgentGuide = lazy(() => import("./pages/AgentGuide"));
const Account = lazy(() => import("./pages/Account"));
const SecurityEvents = lazy(() => import("./pages/SecurityEvents"));
const ReportImport = lazy(() => import("./pages/ReportImport"));
const TimingPaths = lazy(() => import("./pages/TimingPaths"));
const Markers = lazy(() => import("./pages/Markers"));
const PowerIntegrityImport = lazy(() => import("./pages/PowerIntegrityImport"));
const PowerIntegrityFindings = lazy(() => import("./pages/PowerIntegrityFindings"));
const CommercialPowerImport = lazy(() => import("./pages/CommercialPowerImport"));
const PowerBreakdown = lazy(() => import("./pages/PowerBreakdown"));
const CommercialThermalImport = lazy(() => import("./pages/CommercialThermalImport"));
const ThermalHotspots = lazy(() => import("./pages/ThermalHotspots"));
const CommercialRtlImport = lazy(() => import("./pages/CommercialRtlImport"));
const RtlRegression = lazy(() => import("./pages/RtlRegression"));
const CommercialLvsImport = lazy(() => import("./pages/CommercialLvsImport"));
const LvsMismatches = lazy(() => import("./pages/LvsMismatches"));
const CommercialLecImport = lazy(() => import("./pages/CommercialLecImport"));
const LecFailures = lazy(() => import("./pages/LecFailures"));
const CommercialCdcImport = lazy(() => import("./pages/CommercialCdcImport"));
const CdcFindings = lazy(() => import("./pages/CdcFindings"));
const CommercialDftImport = lazy(() => import("./pages/CommercialDftImport"));
const DftFindings = lazy(() => import("./pages/DftFindings"));
const CommercialLowPowerImport = lazy(() => import("./pages/CommercialLowPowerImport"));
const LowPowerFindings = lazy(() => import("./pages/LowPowerFindings"));
const ProjectMembers = lazy(() => import("./pages/ProjectMembers"));
const ProjectCollectors = lazy(() => import("./pages/ProjectCollectors"));
const OpenLaneImport = lazy(() => import("./pages/OpenLaneImport"));
const Analysis = lazy(() => import("./pages/Analysis"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const ProjectDetail = lazy(() => import("./pages/ProjectDetail"));
const Violations = lazy(() => import("./pages/Violations"));
const RunComparison = lazy(() => import("./pages/RunComparison"));
const RunWorkspace = lazy(() => import("./pages/RunWorkspace"));
const StaMatrix = lazy(() => import("./pages/StaMatrix"));
const RevisionCoverage = lazy(() => import("./pages/RevisionCoverage"));

export default function App() {
  return <><AppHeader /><Suspense fallback={<ScreenLoading />}><Routes>
    <Route path="/guide" element={<GuideEntry />} />
    <Route path="/guide/:section" element={<ServiceGuide />} />
    <Route path="/guide/:language/:section" element={<LegacyGuideEntry />} />
    <Route path="*" element={<Workspace />} />
  </Routes></Suspense></>;
}

function Workspace() {
  return (
    <AuthProvider><ReviewDraftProvider><div className="app-shell">
      <Sidebar />
      <main className="app-main">
        <RouteScreenBoundary><Suspense fallback={<ScreenLoading />}><Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/projects/:id" element={<ProjectDetail />} />
          <Route path="/projects/:id/violations" element={<Violations />} />
          <Route path="/projects/:id/compare" element={<RunComparison />} />
          <Route path="/projects/:id/sta-matrix" element={<StaMatrix />} />
          <Route path="/projects/:id/revision-coverage" element={<RevisionCoverage />} />
          <Route path="/projects/:id/import" element={<ReportImport />} />
          <Route path="/projects/:id/import/commercial-sta" element={<ReportImport commercialSta />} />
          <Route path="/projects/:id/import/commercial-drc" element={<ReportImport commercialDrc />} />
          <Route path="/projects/:id/import/klayout" element={<ReportImport klayout />} />
          <Route path="/projects/:id/import/commercial-emir" element={<PowerIntegrityImport />} />
          <Route path="/projects/:id/import/commercial-power" element={<CommercialPowerImport />} />
          <Route path="/projects/:id/import/commercial-thermal" element={<CommercialThermalImport />} />
          <Route path="/projects/:id/import/openlane" element={<OpenLaneImport />} />
          <Route path="/projects/:id/import/commercial-rtl" element={<CommercialRtlImport />} />
          <Route path="/projects/:id/import/commercial-lvs" element={<CommercialLvsImport />} />
          <Route path="/projects/:id/import/commercial-lec" element={<CommercialLecImport />} />
          <Route path="/projects/:id/import/commercial-cdc" element={<CommercialCdcImport />} />
          <Route path="/projects/:id/import/commercial-dft" element={<CommercialDftImport />} />
          <Route path="/projects/:id/import/commercial-low-power" element={<CommercialLowPowerImport />} />
          <Route path="/runs/:runId/structure" element={<DesignStructure />} />
          <Route path="/runs/:runId" element={<RunWorkspace />} />
          <Route path="/runs/:runId/paths" element={<TimingPaths />} />
          <Route path="/runs/:runId/markers" element={<Markers />} />
          <Route path="/runs/:runId/power-integrity" element={<PowerIntegrityFindings />} />
          <Route path="/runs/:runId/power-breakdown" element={<PowerBreakdown />} />
          <Route path="/runs/:runId/thermal-hotspots" element={<ThermalHotspots />} />
          <Route path="/runs/:runId/rtl-regression" element={<RtlRegression />} />
          <Route path="/runs/:runId/lvs-mismatches" element={<LvsMismatches />} />
          <Route path="/runs/:runId/lec-failures" element={<LecFailures />} />
          <Route path="/runs/:runId/cdc-findings" element={<CdcFindings />} />
          <Route path="/runs/:runId/dft-findings" element={<DftFindings />} />
          <Route path="/runs/:runId/low-power-findings" element={<LowPowerFindings />} />
          <Route path="/projects/:id/members" element={<ProjectMembers />} />
          <Route path="/projects/:id/collectors" element={<ProjectCollectors />} />
          <Route path="/account" element={<Account />} />
          <Route path="/admin/security-events" element={<SecurityEvents />} />
          <Route path="/agents" element={<AgentGuide />} />
          <Route path="/analysis" element={<Analysis />} />
          <Route path="/analysis/:tool" element={<Analysis />} />
          <Route path="*" element={<NotFound />} />
        </Routes></Suspense></RouteScreenBoundary>
      </main>
    </div></ReviewDraftProvider></AuthProvider>
  );
}
