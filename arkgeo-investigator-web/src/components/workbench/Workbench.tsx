/**
 * Workbench — the main THE ARK forensic investigation workstation.
 *
 * THE ARK is organized by INVESTIGATION DOMAINS, not individual tools.
 * Each domain contains every tool required to complete that investigation.
 *
 *   THE ARK
 *   ├── IMAGE   — full image intelligence & forensic investigation domain
 *   │     Upload → Scan → Investigation (map-first) → Forensics → OCR/Vision
 *   │     → Source Discovery → Provenance → Evidence/Audit/Output → Report
 *   ├── NETWORK — reserved for future network-security tools (placeholder)
 *   └── ADMIN   — admin control plane
 *
 * IMAGE is ONE continuous investigation. Every image-intelligence function
 * (Spatial, File Forensics, OCR, Source Discovery, Provenance, Report) is a
 * sub-view of the IMAGE domain, sharing the same case/evidence context.
 * The sidebar is the primary navigator; the [+] launcher only re-opens
 * additional analysis views and is never required for the core workflow.
 *
 * The backend remains the source of truth — the workbench displays and
 * interacts.
 */
import React, { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { api } from '../../api';
import type { AnalyzeResponse } from '../../types';
import { TopBar, type ApiKeyStatus } from './TopBar';
import { ActivityBar, type ActivityView } from './ActivityBar';
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
import { IngestionSweep } from '../IngestionSweep';
import { useToast, ToastContainer } from '../Toast';
import { exportCasePdf } from '../../pdfExport';
import { SUBVIEW_ICONS, SIDEBAR_ICONS, type LucideIcon } from './icons';
import { Upload, ChevronDown, ChevronRight } from 'lucide-react';

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

export function Workbench() {
  const [activityView, setActivityView] = useState<ActivityView>('image');
  const [activeSubview, setActiveSubview] = useState<ToolTabId>('overview');
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [zeroRetention, setZeroRetention] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [thumbnailUrl, setThumbnailUrl] = useState<string | undefined>(undefined);
  const [connected, setConnected] = useState(true);
  const [bottomCollapsed, setBottomCollapsed] = useState(false);
  const [showPalette, setShowPalette] = useState(false);
  const [sidebarVisible, setSidebarVisible] = useState(true);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [explorerExpanded, setExplorerExpanded] = useState(true);
  const [apiStatuses, setApiStatuses] = useState<ApiKeyStatus[]>([]);
  const [sessionTick, setSessionTick] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { toasts, showToast, dismiss } = useToast();

  // Health check + API key status
  useEffect(() => {
    const check = async () => {
      try {
        const h = await api.health();
        setConnected(true);
        const statuses: ApiKeyStatus[] = [
          { configured: h.services?.vision_geospy === 'configured', label: 'GS', title: 'GeoSpy Vision API' },
          { configured: h.services?.vision_geoinfer === 'configured', label: 'GI', title: 'GeoInfer Vision API' },
          { configured: h.services?.llm === 'configured', label: 'LLM', title: 'LLM / Vision Ensemble' },
        ];
        setApiStatuses(statuses);
      } catch {
        setConnected(false);
      }
    };
    check();
    const interval = setInterval(check, 30000);
    return () => clearInterval(interval);
  }, []);

  // Command palette hotkeys: Cmd/Ctrl+Shift+P and Cmd/Ctrl+K
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const modKey = e.metaKey || e.ctrlKey;
      if (modKey && e.shiftKey && (e.key === 'P' || e.key === 'p')) {
        e.preventDefault();
        if (result) {
          setShowPalette(true);
        } else {
          setActivityView('image');
        }
      }
      if (modKey && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault();
        setShowPalette(true);
      }
      if (e.key === 'Escape') {
        setShowPalette(false);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [result]);

  const analyzeFile = useCallback(async (file: File) => {
    setAnalyzing(true);
    setError(null);
    const thumbUrl = URL.createObjectURL(file);
    setThumbnailUrl(thumbUrl);
    try {
      const resp = await api.analyzeFile(file, zeroRetention);
      setResult(resp);
      // Record the session for the dashboard analytics
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
      // After scanning completes, automatically open the Investigation view
      // (map-first) for that image — the user does not click + to discover it.
      setActiveSubview('overview');
      showToast(`Analysis complete — ${resp.source}`, 'success');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Analysis failed');
      showToast('Analysis failed', 'error');
    } finally {
      setAnalyzing(false);
    }
  }, [zeroRetention, showToast]);

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
    setActivityView('image');
    setActiveSubview(toolId);
  }, []);

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

  // Render the active image sub-view — all operate on the same evidence/case.
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

  // Malicious / review badge counts are derived from the current result.
  const { maliciousCount, reviewCount } = useMemo(() => {
    if (!result) return { maliciousCount: 0, reviewCount: 0 };
    const critical =
      (result.steganography_detected ? 1 : 0) +
      (result.gps_spoofing_detected ? 1 : 0) +
      (result.contradictions?.filter(c => c.severity === 'HIGH').length || 0);
    const medium =
      (result.exif_missing ? 1 : 0) +
      (result.consistency_findings?.filter(f => f.status === 'WARNING').length || 0) +
      (result.contradictions?.filter(c => c.severity === 'MEDIUM').length || 0);
    return { maliciousCount: critical, reviewCount: medium };
  }, [result]);

  const newSession = useCallback(() => {
    setResult(null);
    setError(null);
    setThumbnailUrl(undefined);
    setActiveSubview('overview');
    setActivityView('image');
  }, []);

  const triggerUpload = useCallback(() => {
    setActivityView('image');
    fileInputRef.current?.click();
  }, []);

  /** Domain navigation handler. ADMIN navigates to the admin route. */
  const handleDomainNavigate = useCallback((view: ActivityView) => {
    if (view === 'admin') {
      window.location.href = ADMIN_LOGIN_PATH;
      return;
    }
    setActivityView(view);
  }, []);

  const CollapseIcon = sidebarCollapsed ? SIDEBAR_ICONS.expand : SIDEBAR_ICONS.collapse;

  return (
    <div className="workbench">
      <TopBar
        maliciousCount={maliciousCount}
        reviewCount={reviewCount}
        apiStatuses={apiStatuses}
        connected={connected}
        onOpenPalette={() => setShowPalette(true)}
        onOpenSettings={() => setActivityView('settings')}
        onOpenAdmin={() => { window.location.href = ADMIN_LOGIN_PATH; }}
      />

      <div className="workbench-body">
        {/* Activity Bar (far-left DOMAIN navigation) */}
        <ActivityBar active={activityView} onNavigate={handleDomainNavigate} evidenceCount={result ? 1 : 0} />

        {/* Sidebar — contextual to the active domain */}
        {sidebarVisible && (
          <>
            <div className={`workbench-sidebar ${sidebarCollapsed ? 'workbench-sidebar-collapsed' : ''}`}>
              {/* Sidebar collapse control — directly on the sidebar, not in Settings */}
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
              {activityView === 'image' && (
                <>
                  {!sidebarCollapsed && (
                    <div className="sidebar-content">
                      <div className="sidebar-header">IMAGE INVESTIGATION</div>

                      {/* No case loaded → upload is the first step of the workflow */}
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
                              Upload an image to begin a forensic investigation. All image
                              tools — map, forensics, OCR, source discovery, provenance, report —
                              live inside this one continuous investigation.
                            </div>
                          )}
                        </>
                      )}

                      {/* Case loaded → continuous investigation sub-view navigation */}
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
                              <div className="sidebar-case-id mono">ARK-{result.request_id.slice(0, 8).toUpperCase()}</div>
                              <div className="sidebar-case-source">{result.source}</div>
                            </div>
                          </div>

                          {/* Vertical nav of all investigation stages — never requires [+] */}
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

                          {/* Collapsible Evidence Explorer tree (kept — useful OSINT detail) */}
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

                      {/* Analyzing state — scanning is part of the workflow */}
                      {analyzing && (
                        <div className="sidebar-scanning">
                          <div className="dropzone-scanning"><div className="radar-pulse" /><span>SCANNING...</span></div>
                          <div className="sidebar-hint">Processing target asset through the cascade pipeline.</div>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Collapsed sidebar — icon-only quick nav between sub-views */}
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
              {activityView === 'network' && !sidebarCollapsed && (
                <div className="sidebar-content">
                  <div className="sidebar-header">NETWORK INVESTIGATION</div>
                  <div className="sidebar-hint">
                    The network-security investigation domain is reserved for
                    future tooling. No tools are configured yet.
                  </div>
                </div>
              )}

              {/* ---- Settings sidebar ---- */}
              {activityView === 'settings' && !sidebarCollapsed && (
                <div className="sidebar-content">
                  <div className="sidebar-header">SETTINGS</div>
                  <div className="settings-list">
                    <div className="settings-row">
                      <span className="settings-label">Backend:</span>
                      <span className={`settings-value ${connected ? 'settings-ok' : 'settings-err'}`}>
                        {connected ? 'Connected' : 'Offline'}
                      </span>
                    </div>
                    <div className="settings-row">
                      <span className="settings-label">Sidebar:</span>
                      <button className="settings-btn" onClick={() => setSidebarCollapsed(c => !c)}>
                        {sidebarCollapsed ? 'Expand' : 'Collapse'}
                      </button>
                    </div>
                    <div className="settings-row">
                      <span className="settings-label">Sidebar Panel:</span>
                      <button className="settings-btn" onClick={() => setSidebarVisible(false)}>Hide panel</button>
                    </div>
                    <div className="settings-row">
                      <span className="settings-label">Bottom Panel:</span>
                      <button className="settings-btn" onClick={() => setBottomCollapsed(!bottomCollapsed)}>
                        {bottomCollapsed ? 'Show' : 'Hide'}
                      </button>
                    </div>
                    <div className="settings-api-header">API PROVIDERS</div>
                    {apiStatuses.map(s => (
                      <div key={s.label} className="settings-row">
                        <span className="settings-label">{s.title}</span>
                        <span className={`settings-value ${s.configured ? 'settings-ok' : 'settings-err'}`}>
                          {s.configured ? 'Configured' : 'Not Set'}
                        </span>
                      </div>
                    ))}
                    <div className="settings-note">
                      ExifTool, hash, and ELA forensics run fully offline. Vision AI providers require keys configured via the Admin control plane.
                    </div>
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
            {activityView === 'image' && (
              result ? renderSubview(activeSubview) : <DashboardView key={sessionTick} onUpload={triggerUpload} />
            )}
            {activityView === 'network' && <NetworkPlaceholder />}
            {activityView === 'settings' && (
              <div className="viewport-empty">
                <div className="viewport-empty-title">Settings</div>
                <div className="viewport-empty-text">Configure THE ARK from the sidebar.</div>
              </div>
            )}
            <IngestionSweep active={analyzing} />
          </div>

          <BottomPanel result={result} collapsed={bottomCollapsed} onToggle={() => setBottomCollapsed(!bottomCollapsed)} />
        </div>
      </div>

      <StatusBar result={result} connected={connected} analyzing={analyzing} />

      <CommandPalette
        open={showPalette}
        onClose={() => setShowPalette(false)}
        onOpenTool={openTool}
        onExportPdf={handleExportPdf}
        onUpload={() => { setActivityView('image'); fileInputRef.current?.click(); }}
        hasResult={!!result}
      />

      {/* Hidden file input accessible from command palette / sidebar */}
      <input ref={fileInputRef} type="file" accept="image/jpeg,image/png" onChange={handleFileSelect} style={{ display: 'none' }} />

      {!sidebarVisible && (
        <button className="sidebar-restore" onClick={() => setSidebarVisible(true)} title="Show sidebar">▸</button>
      )}
      <ToastContainer toasts={toasts} onDismiss={dismiss} />
    </div>
  );
}
