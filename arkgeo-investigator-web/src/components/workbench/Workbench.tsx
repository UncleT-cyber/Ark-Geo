/**
 * Workbench — the main THE ARK investigation workstation.
 *
 * Information architecture is organized by INVESTIGATION DOMAINS:
 *   THE ARK
 *   ├── IMAGE   — complete image-intelligence lifecycle (primary)
 *   │     Upload → Scan → Investigation (map-first) → Forensics → OCR/Vision
 *   │     → Source Discovery → Provenance → Evidence/Audit/Output → Report
 *   ├── NETWORK — network telemetry (structural placeholder)
 *   └── CASES   — cross-domain case layer (saved sessions & audit vault)
 *
 * The PROFILE icon (TopBar + ActivityBar footer) opens the Investigator
 * Profile Modal — it NEVER links to Admin. Admin is a protected control
 * plane reachable only via the stealth hotkey Cmd/Ctrl+Shift+P (handled in
 * App.tsx) plus server-side authorization at /console-auth.
 *
 * Every important entity has a stable ID and relationships
 * (Tenant → Workspace → Case → Evidence → AnalysisRun → Finding → Report →
 * AuditEvent). The shared investigation context (useInvestigation) holds these
 * and feeds the universal contextual bottom console, which works for IMAGE now
 * and NETWORK later without being rewritten.
 */
import React, { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { api } from '../../api';
import type { AnalyzeResponse } from '../../types';
import { TopBar, type ApiKeyStatus } from './TopBar';
import { ActivityBar } from './ActivityBar';
import type { ToolTabId } from './TabBar';
import { EvidenceExplorer } from './investigation/EvidenceExplorer';
import { InvestigationOverview } from './investigation/InvestigationOverview';
import { BottomPanel } from './BottomPanel';
import { StatusBar } from './StatusBar';
import { CommandPalette } from './CommandPalette';
import { DashboardView, recordSession, classifyRisk } from './DashboardView';
import { SpatialTool } from './tools/SpatialTool';
import { FileForensicsTool } from './tools/FileForensicsTool';
import { DiscoveryTool } from './tools/DiscoveryTool';
import { ProvenanceTool } from './tools/ProvenanceTool';
import { VisionTool } from './tools/VisionTool';
import { ReportTool } from './tools/ReportTool';
import { NetworkPlaceholder } from './NetworkPlaceholder';
import { CaseExplorer } from './CaseExplorer';
import { InvestigatorProfileModal } from './InvestigatorProfileModal';
import { IngestionSweep } from '../IngestionSweep';
import { useToast, ToastContainer } from '../Toast';
import { exportCasePdf } from '../../pdfExport';
import { InvestigationProvider, useInvestigation, type SavedCase } from './useInvestigation';
import { SUBVIEW_ICONS, SIDEBAR_ICONS, type LucideIcon } from './icons';
import type { DomainId } from './entities';
import { Upload, ChevronDown, ChevronRight, PanelLeft } from 'lucide-react';

/** Ordered IMAGE investigation sub-views — one continuous workflow. */
const IMAGE_SUBVIEWS: { id: ToolTabId; title: string; icon: LucideIcon; hint: string }[] = [
  { id: 'overview', title: 'Investigation', icon: SUBVIEW_ICONS.overview, hint: 'Assessment & map command center' },
  { id: 'spatial', title: 'Spatial / Map', icon: SUBVIEW_ICONS.spatial, hint: 'Geolocation, satellite, fusion' },
  { id: 'fileforensics', title: 'File Forensics', icon: SUBVIEW_ICONS.fileforensics, hint: 'ExifTool, Hex, ELA, JPEG' },
  { id: 'vision', title: 'OCR & Vision', icon: SUBVIEW_ICONS.vision, hint: 'Text, objects, landmarks' },
  { id: 'discovery', title: 'Source Discovery', icon: SUBVIEW_ICONS.discovery, hint: 'Reverse search, footprint' },
  { id: 'provenance', title: 'Provenance / C2PA', icon: SUBVIEW_ICONS.provenance, hint: 'Signatures, edit manifests' },
  { id: 'report', title: 'Case / Report', icon: SUBVIEW_ICONS.report, hint: 'Custody, overrides, PDF' },
];

/** Admin login path — obfuscated slug configurable via env (mirrors App.tsx). */
const ADMIN_ROUTE_SLUG = (import.meta as any).env?.VITE_ADMIN_ROUTE_SLUG || 'console-auth';
const ADMIN_LOGIN_PATH = `/${ADMIN_ROUTE_SLUG}`;

function WorkbenchInner() {
  const inv = useInvestigation();
  const [activeSubview, setActiveSubview] = useState<ToolTabId>('overview');
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [zeroRetention, setZeroRetention] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [thumbnailUrl, setThumbnailUrl] = useState<string | undefined>(undefined);
  const [connected, setConnected] = useState(true);
  const [bottomCollapsed, setBottomCollapsed] = useState(false);
  const [showPalette, setShowPalette] = useState(false);
  const [showProfile, setShowProfile] = useState(false);
  const [sidebarVisible, setSidebarVisible] = useState(true);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [explorerExpanded, setExplorerExpanded] = useState(true);
  const [apiStatuses, setApiStatuses] = useState<ApiKeyStatus[]>([]);
  const [sessionTick, setSessionTick] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { toasts, showToast, dismiss } = useToast();

  const result = inv.result;

  // Health check + API key status
  useEffect(() => {
    const check = async () => {
      try {
        const h = await api.health();
        setConnected(true);
        setApiStatuses([
          { configured: h.services?.vision_geospy === 'configured', label: 'GS', title: 'GeoSpy Vision API' },
          { configured: h.services?.vision_geoinfer === 'configured', label: 'GI', title: 'GeoInfer Vision API' },
          { configured: h.services?.llm === 'configured', label: 'LLM', title: 'LLM / Vision Ensemble' },
        ]);
      } catch {
        setConnected(false);
      }
    };
    check();
    const interval = setInterval(check, 30000);
    return () => clearInterval(interval);
  }, []);

  // Command palette hotkey: Cmd/Ctrl+K (Shift+P is the stealth admin hotkey
  // handled globally in App.tsx and never opens anything here).
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const modKey = e.metaKey || e.ctrlKey;
      if (modKey && (e.key === 'k' || e.key === 'K') && !e.shiftKey) {
        e.preventDefault();
        setShowPalette(true);
      }
      if (e.key === 'Escape') {
        setShowPalette(false);
        setShowProfile(false);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  const analyzeFile = useCallback(async (file: File) => {
    setAnalyzing(true);
    setError(null);
    const thumbUrl = URL.createObjectURL(file);
    setThumbnailUrl(thumbUrl);
    try {
      const resp = await api.analyzeFile(file, zeroRetention);
      inv.loadFromAnalysis(resp, file.name);
      const anomalyCount =
        (resp.steganography_detected ? 1 : 0) +
        (resp.gps_spoofing_detected ? 1 : 0) +
        (resp.exif_missing ? 1 : 0) +
        (resp.consistency_findings?.filter(f => f.status !== 'OK').length || 0) +
        (resp.contradictions?.length || 0);
      recordSession({
        request_id: resp.request_id,
        filename: file.name,
        sha256_short: resp.image_sha256.slice(0, 12),
        source: resp.source,
        confidence: resp.consensus.confidence_score,
        timestamp: Date.now(),
        anomaly_count: anomalyCount,
        risk: classifyRisk(anomalyCount),
      });
      setSessionTick(t => t + 1);
      setActiveSubview('overview');
      showToast(`Analysis complete — ${resp.source}`, 'success');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Analysis failed');
      showToast('Analysis failed', 'error');
    } finally {
      setAnalyzing(false);
    }
  }, [zeroRetention, showToast, inv]);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) analyzeFile(file);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) analyzeFile(file);
  };

  /** Navigate to an image sub-view (the sidebar is the primary navigator). */
  const openTool = useCallback((toolId: ToolTabId) => {
    inv.setDomain('image');
    setActiveSubview(toolId);
  }, [inv]);

  const handleCopyCoords = useCallback(() => {
    if (!result?.coordinates) return;
    const s = `${result.coordinates.lat.toFixed(5)}, ${result.coordinates.lon.toFixed(5)}`;
    navigator.clipboard?.writeText(s).then(
      () => showToast(`Coordinates copied: ${s}`, 'success'),
      () => showToast('Copy failed', 'error'),
    );
  }, [result, showToast]);

  const handleGeofenceViolation = useCallback(async (point: { lat: number; lon: number }) => {
    showToast('GEOFENCE VIOLATION', 'error');
    try {
      await api.dispatchThreatAlert({
        alert_type: 'geofence_violation',
        coordinates: { lat: point.lat, lon: point.lon },
        description: 'Target marker intersected a high-risk geofence polygon',
        contacts: [{ name: 'SOC Team', phone: '+15551234567' }],
      });
    } catch { /* non-blocking */ }
  }, [showToast]);

  const handleExportPdf = useCallback(() => {
    if (!result) { showToast('No analysis to export', 'warning'); return; }
    try {
      exportCasePdf(result, thumbnailUrl);
      showToast('Case evidence PDF exported', 'success');
    } catch {
      showToast('PDF export failed', 'error');
    }
  }, [result, thumbnailUrl, showToast]);

  const renderSubview = (subview: ToolTabId): React.ReactNode => {
    if (!result) return null;
    switch (subview) {
      case 'overview':
        return <InvestigationOverview result={result} onOpenTool={openTool} thumbnailUrl={thumbnailUrl} onCopyCoords={handleCopyCoords} onGeofenceViolation={handleGeofenceViolation} />;
      case 'spatial':
        return <SpatialTool result={result} thumbnailUrl={thumbnailUrl} onCopyCoords={handleCopyCoords} onGeofenceViolation={handleGeofenceViolation} />;
      case 'fileforensics':
        return <FileForensicsTool result={result} thumbnailUrl={thumbnailUrl} />;
      case 'discovery':
        return <DiscoveryTool result={result} />;
      case 'provenance':
        return <ProvenanceTool result={result} />;
      case 'vision':
        return <VisionTool result={result} />;
      case 'report':
        return <ReportTool result={result} onExportPdf={handleExportPdf} />;
      default:
        return null;
    }
  };

  const newSession = useCallback(() => {
    inv.clear();
    setError(null);
    setThumbnailUrl(undefined);
    setActiveSubview('overview');
    inv.setDomain('image');
  }, [inv]);

  const triggerUpload = useCallback(() => {
    inv.setDomain('image');
    fileInputRef.current?.click();
  }, [inv]);

  const handleRestoreCase = useCallback((saved: SavedCase) => {
    inv.restoreCase(saved);
    setActiveSubview('overview');
    setThumbnailUrl(undefined);
    setError(null);
    showToast(`Restored case ${saved.caseId}`, 'success');
  }, [inv, showToast]);

  const CollapseIcon = sidebarCollapsed ? SIDEBAR_ICONS.expand : SIDEBAR_ICONS.collapse;
  const activeCaseId = inv.activeCase?.id || null;

  return (
    <div className="workbench">
      <TopBar
        activeCaseId={activeCaseId}
        apiStatuses={apiStatuses}
        connected={connected}
        onOpenPalette={() => setShowPalette(true)}
        onOpenProfile={() => setShowProfile(true)}
      />

      <div className="workbench-body">
        <ActivityBar active={inv.domain} onNavigate={(d: DomainId) => inv.setDomain(d)} onOpenProfile={() => setShowProfile(true)} />

        {sidebarVisible && (
          <>
            <div className={`workbench-sidebar ${sidebarCollapsed ? 'workbench-sidebar-collapsed' : ''}`}>
              <div className="sidebar-collapse-bar">
                <button
                  className="sidebar-collapse-btn"
                  onClick={() => setSidebarCollapsed(c => !c)}
                  title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
                >
                  <CollapseIcon className="w-4 h-4" />
                </button>
                {!sidebarCollapsed && <span className="sidebar-collapse-label">Collapse</span>}
              </div>

              {/* ---- IMAGE domain sidebar ---- */}
              {inv.domain === 'image' && (
                <>
                  {!sidebarCollapsed && (
                    <div className="sidebar-content">
                      <div className="sidebar-header">IMAGE INTELLIGENCE</div>

                      {!result && !analyzing && (
                        <>
                          <div
                            className={`dropzone ${dragOver ? 'dropzone-active' : ''} ${analyzing ? 'dropzone-busy' : ''}`}
                            onDragOver={e => { e.preventDefault(); setDragOver(true); }}
                            onDragLeave={() => setDragOver(false)}
                            onDrop={handleDrop}
                            onClick={() => fileInputRef.current?.click()}
                          >
                            <div className="dropzone-icon"><Upload className="w-7 h-7" /></div>
                            <div className="dropzone-text">Drag & drop image here</div>
                            <div className="dropzone-subtext">JPEG / PNG · high-res supported</div>
                          </div>
                          <input ref={fileInputRef} type="file" accept="image/jpeg,image/png" onChange={handleFileSelect} style={{ display: 'none' }} />
                          <div className="sidebar-options">
                            <label className="toggle-row">
                              <input type="checkbox" checked={zeroRetention} onChange={e => setZeroRetention(e.target.checked)} />
                              <span className="toggle-label">Zero-Retention Mode</span>
                            </label>
                          </div>
                          {error && (
                            <div className="error-box">
                              <div className="error-title">ANALYSIS ERROR</div>
                              <div className="error-detail">{error}</div>
                            </div>
                          )}
                          {!error && (
                            <div className="sidebar-hint">
                              Upload an image to begin. The full image investigation — map, forensics, OCR, source discovery, provenance, report — lives inside this one domain.
                            </div>
                          )}
                        </>
                      )}

                      {result && (
                        <>
                          <div className="sidebar-case-header">
                            <div className="sidebar-case-thumb">
                              {thumbnailUrl ? (
                                <img src={thumbnailUrl} alt="target" />
                              ) : (
                                <span className="sidebar-case-thumb-placeholder"><Upload className="w-4 h-4" /></span>
                              )}
                            </div>
                            <div className="sidebar-case-meta">
                              <div className="sidebar-case-id mono">{activeCaseId}</div>
                              <div className="sidebar-case-source">{result.source}</div>
                            </div>
                          </div>

                          <div className="sidebar-subnav">
                            {IMAGE_SUBVIEWS.map(sv => {
                              const Icon = sv.icon;
                              return (
                                <button
                                  key={sv.id}
                                  className={`subnav-item ${activeSubview === sv.id ? 'subnav-item-active' : ''}`}
                                  onClick={() => openTool(sv.id)}
                                  title={sv.hint}
                                >
                                  <span className="subnav-icon"><Icon className="w-4 h-4" /></span>
                                  <span className="subnav-label">{sv.title}</span>
                                </button>
                              );
                            })}
                          </div>

                          <button className="sidebar-new-session" onClick={newSession}>+ New Investigation</button>

                          <div className="sidebar-explorer-section">
                            <button
                              className="sidebar-explorer-toggle"
                              onClick={() => setExplorerExpanded(e => !e)}
                            >
                              <span className="explorer-chevron">{explorerExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}</span>
                              <span className="explorer-section-label">Evidence Explorer</span>
                            </button>
                            {explorerExpanded && (
                              <EvidenceExplorer result={result} onOpenTool={openTool} thumbnailUrl={thumbnailUrl} />
                            )}
                          </div>
                        </>
                      )}

                      {analyzing && (
                        <div className="sidebar-scanning">
                          <div className="dropzone-scanning"><div className="radar-pulse" /><span>SCANNING...</span></div>
                          <div className="sidebar-hint">Processing target asset through the cascade pipeline.</div>
                        </div>
                      )}
                    </div>
                  )}

                  {sidebarCollapsed && result && (
                    <div className="sidebar-collapsed-nav">
                      {IMAGE_SUBVIEWS.map(sv => {
                        const Icon = sv.icon;
                        return (
                          <button
                            key={sv.id}
                            className={`subnav-icon-btn ${activeSubview === sv.id ? 'subnav-icon-btn-active' : ''}`}
                            onClick={() => openTool(sv.id)}
                            title={sv.title}
                          >
                            <Icon className="w-5 h-5" />
                          </button>
                        );
                      })}
                    </div>
                  )}
                  {sidebarCollapsed && !result && (
                    <div className="sidebar-collapsed-nav">
                      <button
                        className="subnav-icon-btn subnav-icon-btn-active"
                        onClick={() => fileInputRef.current?.click()}
                        title="Upload image"
                      >
                        <Upload className="w-5 h-5" />
                      </button>
                    </div>
                  )}
                </>
              )}

              {/* ---- NETWORK domain sidebar (placeholder) ---- */}
              {inv.domain === 'network' && !sidebarCollapsed && (
                <div className="sidebar-content">
                  <div className="sidebar-header">NETWORK TELEMETRY</div>
                  <div className="sidebar-hint">
                    The network-security investigation domain is reserved for
                    future tooling. No tools are configured yet.
                  </div>
                </div>
              )}

              {/* ---- CASES domain sidebar ---- */}
              {inv.domain === 'cases' && !sidebarCollapsed && (
                <div className="sidebar-content">
                  <div className="sidebar-header">CASE EXPLORER</div>
                  <div className="sidebar-hint">
                    Cross-domain case layer. Saved investigations and the audit
                    vault live here. Restore a past case to continue work.
                  </div>
                </div>
              )}
            </div>
            <div className="resize-handle resize-handle-v" />
          </>
        )}

        {/* Main area: Viewport + BottomPanel */}
        <div className="workbench-main">
          <div className="workbench-viewport">
            {inv.domain === 'image' && (
              result ? renderSubview(activeSubview) : <DashboardView key={sessionTick} onUpload={triggerUpload} />
            )}
            {inv.domain === 'network' && <NetworkPlaceholder />}
            {inv.domain === 'cases' && <CaseExplorer onRestoreCase={handleRestoreCase} />}
            <IngestionSweep active={analyzing} />
          </div>

          <BottomPanel result={result} collapsed={bottomCollapsed} onToggle={() => setBottomCollapsed(!bottomCollapsed)} />
        </div>
      </div>

      <StatusBar result={result} connected={connected} analyzing={analyzing} activeCaseId={activeCaseId} />

      <CommandPalette
        open={showPalette}
        onClose={() => setShowPalette(false)}
        onOpenTool={openTool}
        onExportPdf={handleExportPdf}
        onUpload={() => { inv.setDomain('image'); fileInputRef.current?.click(); }}
        hasResult={!!result}
      />

      <input ref={fileInputRef} type="file" accept="image/jpeg,image/png" onChange={handleFileSelect} style={{ display: 'none' }} />

      {!sidebarVisible && (
        <button className="sidebar-restore" onClick={() => setSidebarVisible(true)} title="Show sidebar">
          <PanelLeft className="w-4 h-4" />
        </button>
      )}

      <InvestigatorProfileModal
        open={showProfile}
        onClose={() => setShowProfile(false)}
        apiStatuses={apiStatuses}
        onRestoreCase={handleRestoreCase}
      />
      <ToastContainer toasts={toasts} onDismiss={dismiss} />
    </div>
  );
}

export function Workbench() {
  return (
    <InvestigationProvider>
      <WorkbenchInner />
    </InvestigationProvider>
  );
}
