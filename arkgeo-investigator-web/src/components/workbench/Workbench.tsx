/**
 * Workbench — the main THE ARK ISE investigation workstation.
 *
 * Information architecture is organized by INVESTIGATION WORKSPACES:
 *   THE ARK
 *   ├── IMAGE   — Image Intelligence Workspace (primary)
 *   │     Upload → Scan → Investigation (map-first) → Forensics → OCR/Vision
 *   │     → Source Discovery → Provenance → Evidence/Audit/Output → Report
 *   ├── NETWORK — Network Workspace (structural placeholder)
 *   ├── SECOPS  — Threat & SecOps Workspace (structural placeholder)
 *   │     SIEM · IDS/IPS · Threat Hunting · Detection & Correlation
 *   │     · Incident Management · Security Operations
 *   └── CASES   — Case Workspace (cross-domain saved sessions & audit vault)
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
import { api, ensureBaseUrl, type AiStatusResponse } from '../../api';
import type { AnalyzeResponse, NextStep } from '../../types';
import { TopBar, type ApiKeyStatus } from './TopBar';
import { ActivityBar } from './ActivityBar';
import type { ToolTabId } from './TabBar';
import { EvidenceExplorer } from './investigation/EvidenceExplorer';
import { InvestigationOverview } from './investigation/InvestigationOverview';
import { BottomPanel } from './BottomPanel';
import { StatusBar } from './StatusBar';
import { CommandPalette } from './CommandPalette';
import { DashboardView, recordSession, classifyRisk } from './DashboardView';
import { ArkBusProvider } from './ArkBusContext';
import { SpatialTool } from './tools/SpatialTool';
import { FileForensicsTool } from './tools/FileForensicsTool';
import { DiscoveryTool } from './tools/DiscoveryTool';
import { ProvenanceTool } from './tools/ProvenanceTool';
import { VisionTool } from './tools/VisionTool';
import { CaseReportView } from './tools/CaseReportView';
import { NetworkWorkbench, NETWORK_TABS, type NetworkTabId } from './NetworkWorkbench';
import { SecOpsPlaceholder } from './SecOpsPlaceholder';
import { CaseExplorer } from './CaseExplorer';
import { InvestigatorProfileModal } from './InvestigatorProfileModal';
import { ClientSettingsModal } from '../settings/ClientSettingsModal';
import { IngestionSweep } from '../IngestionSweep';
import { useToast, ToastContainer } from '../Toast';
import { exportCasePdf } from '../../pdfExport';
import { InvestigationProvider, useInvestigation, type SavedCase, type SavedCaseDomain } from './useInvestigation';
import { ByokProvider } from '../settings/ByokContext';
import { byokStore } from '../../core/byok/byokStore';
import type { ByokProviderId } from '../../types';
import { SUBVIEW_ICONS, SIDEBAR_ICONS, type LucideIcon } from './icons';
import type { DomainId } from './entities';
import { Upload, ChevronDown, ChevronRight, PanelLeft, Save, Tag } from 'lucide-react';

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

/** TopBar provider dots — unified admin + user (BYOK) API key status. */
const API_INDICATORS: { label: string; title: string; service: string; byok: ByokProviderId[] }[] = [
  { label: 'GS', title: 'GeoSpy Vision API', service: 'vision_geospy', byok: ['geospy'] },
  { label: 'GI', title: 'GeoInfer Vision API', service: 'vision_geoinfer', byok: ['geoinfer'] },
  { label: 'LLM', title: 'LLM / Vision Ensemble', service: 'llm', byok: ['openai'] },
  { label: 'GM', title: 'Gemini Vision API', service: 'gemini', byok: ['gemini'] },
  { label: 'AN', title: 'Anthropic Claude', service: 'anthropic', byok: ['anthropic'] },
  { label: 'MB', title: 'Mapbox Geocoding Token', service: 'mapbox', byok: ['mapbox'] },
  { label: 'RS', title: 'Reverse Source Search (TinEye/Serper)', service: 'reverse_search', byok: ['serper', 'tineye'] },
  { label: 'SV', title: 'Google Street View', service: 'streetview', byok: ['google_maps'] },
];

function WorkbenchInner() {
  const inv = useInvestigation();
  const [activeSubview, setActiveSubview] = useState<ToolTabId>('overview');
  const [networkTab, setNetworkTab] = useState<NetworkTabId>('discovery');
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [zeroRetention, setZeroRetention] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [thumbnailUrl, setThumbnailUrl] = useState<string | undefined>(undefined);
  const [connected, setConnected] = useState(true);
  const [bottomCollapsed, setBottomCollapsed] = useState(false);
  const [showPalette, setShowPalette] = useState(false);
  const [showProfile, setShowProfile] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [sidebarVisible, setSidebarVisible] = useState(true);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [explorerExpanded, setExplorerExpanded] = useState(true);
  const [apiStatuses, setApiStatuses] = useState<ApiKeyStatus[]>([]);
  const [sessionTick, setSessionTick] = useState(0);
  const [dashRefresh, setDashRefresh] = useState(0);
  const [cascadePhase, setCascadePhase] = useState<string | null>(null);
  const [savePromptOpen, setSavePromptOpen] = useState(false);
  const [saveName, setSaveName] = useState('');
  const [saveTags, setSaveTags] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const lastFileRef = useRef<File | null>(null);
  const { toasts, showToast, dismiss } = useToast();

  const result = inv.result;

  // TopBar API provider indicators — unified single source of truth. A dot is
  // "configured" when the ADMIN system key is set server-side (health), OR the
  // unified AI gateway route (GET /api/v1/ai/status) is live — the LLM badge
  // lights on cloud/local_ollama, the GS/GI vision badges on vision availability —
  // OR the user has an active BYOK override / env token in the client key store.
  // All three write/read the same chain, so keys saved in User Settings light up
  // across every module immediately (the ByokContext dispatches 'ark:byok-changed').
  const buildApiStatuses = useCallback((services: Record<string, string>, ai?: AiStatusResponse): ApiKeyStatus[] =>
    API_INDICATORS.map(({ label, title, service, byok }) => {
      const aiRoute = ai?.route?.status;
      let configured = service === 'reverse_search'
        ? services.tineye === 'configured' || services.serper === 'configured'
        : services[service] === 'configured';
      if (!configured) {
        // Unified AI gateway route state.
        if (service === 'llm') {
          configured = aiRoute === 'cloud' || aiRoute === 'local_ollama';
        } else if (service === 'vision_geospy' || service === 'vision_geoinfer') {
          configured = Boolean(ai?.vision);
        }
      }
      if (!configured) {
        configured = byok.some(id => {
          const k = byokStore.resolveKey(id);
          return k.source === 'byok' || (id === 'mapbox' && k.source === 'env');
        });
      }
      return { configured, label, title };
    }), []);

  // Health check + API key status
  const check = useCallback(async () => {
    try {
      await ensureBaseUrl(); // resolve Electron port before first request
      const [h, ai] = await Promise.all([
        api.health(),
        api.aiStatus().catch(() => null),
      ]);
      setConnected(true);
      setApiStatuses(buildApiStatuses(h.services || {}, ai ?? undefined));
    } catch {
      setConnected(false);
    }
  }, [buildApiStatuses]);

  useEffect(() => {
    check();
    const interval = setInterval(check, 30000);
    return () => clearInterval(interval);
  }, [check]);

  // Reflect BYOK changes from User Settings immediately (save/clear/override).
  useEffect(() => {
    const onByok = () => check();
    window.addEventListener('ark:byok-changed', onByok);
    return () => window.removeEventListener('ark:byok-changed', onByok);
  }, [check]);

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
        setShowSettings(false);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  const analyzeFile = useCallback(async (file: File) => {
    setAnalyzing(true);
    setError(null);
    setCascadePhase(null);
    const thumbUrl = URL.createObjectURL(file);
    setThumbnailUrl(thumbUrl);
    lastFileRef.current = file;
    try {
      const resp = await api.analyzeFile(file, zeroRetention);
      inv.loadFromAnalysis(resp, file.name);
      // Continuous image-intelligence cascade: classification → hashing/source
      // discovery → OCR/telemetry → visual geolocation → evidence fusion. Runs
      // client-side so every asset (even metadata-stripped) yields evidence.
      await inv.runPipeline(file, resp);
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
      setCascadePhase(null);
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

  /** Launch an ARK AI investigation from an "Investigate Next" recommendation.
   *  Builds the objective from the recommendation, runs plan → tools → evidence
   *  via the shared investigation context, and surfaces the console. */
  const handleInvestigateNext = useCallback(async (step: NextStep) => {
    const file = lastFileRef.current;
    if (!file) {
      showToast('Evidence file unavailable — re-ingest to investigate', 'warning');
      return;
    }
    await inv.startInvestigation(file, {
      goal: step.goal,
      subject: file.name,
      domain: 'image',
      claims_to_verify: step.claim ? [{ field: step.claim }] : [],
      natural_language: `Investigate next: ${step.action} — ${step.reason}`,
    });
    setBottomCollapsed(false);
  }, [inv, showToast]);

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
        return <InvestigationOverview result={result} onOpenTool={openTool} thumbnailUrl={thumbnailUrl} onCopyCoords={handleCopyCoords} onGeofenceViolation={handleGeofenceViolation} onInvestigateNext={handleInvestigateNext} />;
      case 'spatial':
        return <SpatialTool result={result} thumbnailUrl={thumbnailUrl} onCopyCoords={handleCopyCoords} onGeofenceViolation={handleGeofenceViolation} />;
      case 'fileforensics':
        return <FileForensicsTool result={result} thumbnailUrl={thumbnailUrl} file={lastFileRef.current} />;
      case 'discovery':
        return <DiscoveryTool result={result} />;
      case 'provenance':
        return <ProvenanceTool result={result} />;
      case 'vision':
        return <VisionTool result={result} />;
      case 'report':
        return <CaseReportView result={result} thumbnailUrl={thumbnailUrl} onExportPdf={handleExportPdf} />;
      default:
        return null;
    }
  };

  const newSession = useCallback(() => {
    inv.clear();
    lastFileRef.current = null;
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

  /** Save the current workspace observations into the unified Case Vault.
   *  Domain is inferred from the active workspace (Telecom tab → 'telecom'). */
  const handleSaveInvestigation = useCallback((name: string, tags: string) => {
    if (!inv.activeCase && !inv.activeEvidence && !inv.activeRun && inv.findings.length === 0) {
      showToast('Nothing to save — open a workspace first', 'warning');
      return;
    }
    const domain: SavedCaseDomain =
      inv.domain === 'network'
        ? (networkTab === 'telecom' ? 'telecom' : 'network')
        : inv.domain === 'secops' ? 'secops' : 'image';
    const saved = inv.saveCase({
      domain,
      caseName: name.trim() || undefined,
      tags: tags.trim() ? tags.split(/[\s,]+/).filter(Boolean) : undefined,
    });
    inv.pushTerminal('ok', `investigation saved — ${saved.caseId} → ${domain.toUpperCase()} vault (${inv.findings.length} findings · ${inv.auditTrail.length} audit)`);
    showToast(`Investigation saved ${saved.caseId} — now in Case Explorer`, 'success');
    inv.setDomain('cases');
    setSavePromptOpen(false);
    setSaveName('');
    setSaveTags('');
  }, [inv, networkTab, showToast]);

  const openSavePrompt = useCallback(() => {
    if (!inv.activeCase && !inv.activeEvidence && !inv.activeRun && inv.findings.length === 0) {
      showToast('Nothing to save — open a workspace first', 'warning');
      return;
    }
    setSaveName(inv.activeCase?.title ?? '');
    setSaveTags('');
    setSavePromptOpen(true);
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
        onSaveInvestigation={openSavePrompt}
      />

      <div className="workbench-body">
        <ActivityBar active={inv.domain} onNavigate={(d: DomainId) => inv.setDomain(d)} onOpenSettings={() => setShowSettings(true)} />

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
                      <div className="sidebar-header">IMAGE INTELLIGENCE WORKSPACE</div>

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

              {/* ---- NETWORK domain sidebar ---- */}
              {inv.domain === 'network' && !sidebarCollapsed && (
                <div className="sidebar-content">
                  <div className="sidebar-header">NETWORK INTELLIGENCE WORKSPACE</div>
                  <div className="sidebar-hint">
                    Passive OSINT tools for network, web, endpoint, traffic and
                    telecom investigation. Active security-testing engines are
                    risk-gated.
                  </div>
                  <div className="sidebar-subnav">
                    {NETWORK_TABS.map(t => {
                      const Icon = t.icon;
                      return (
                        <button
                          key={t.id}
                          className={`subnav-item ${networkTab === t.id ? 'subnav-item-active' : ''}`}
                          onClick={() => setNetworkTab(t.id)}
                          title={t.hint}
                        >
                          <span className="subnav-icon"><Icon className="w-4 h-4" /></span>
                          <span className="subnav-label">{t.label}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
              {inv.domain === 'network' && sidebarCollapsed && (
                <div className="sidebar-collapsed-nav">
                  {NETWORK_TABS.map(t => {
                    const Icon = t.icon;
                    return (
                      <button
                        key={t.id}
                        className={`subnav-icon-btn ${networkTab === t.id ? 'subnav-icon-btn-active' : ''}`}
                        onClick={() => setNetworkTab(t.id)}
                        title={t.label}
                      >
                        <Icon className="w-5 h-5" />
                      </button>
                    );
                  })}
                </div>
              )}

              {/* ---- SECOPS domain sidebar (placeholder) ---- */}
              {inv.domain === 'secops' && !sidebarCollapsed && (
                <div className="sidebar-content">
                  <div className="sidebar-header">THREAT &amp; SECOPS</div>
                  <div className="sidebar-hint">
                    Security-operations investigation domain. Sub-modules:
                    SIEM, IDS/IPS, Threat Hunting, Detection &amp; Correlation,
                    Incident Management, and the SecOps dashboard are reserved
                    for future tooling.
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
              result ? renderSubview(activeSubview) : <DashboardView key={sessionTick} onUpload={triggerUpload} onRestoreCase={handleRestoreCase} refreshKey={dashRefresh} />
            )}
            {inv.domain === 'network' && <NetworkWorkbench activeTab={networkTab} onTabChange={setNetworkTab} />}
            {inv.domain === 'secops' && <SecOpsPlaceholder />}
            {inv.domain === 'cases' && <CaseExplorer onRestoreCase={handleRestoreCase} />}
            <IngestionSweep
              active={analyzing}
              phase={
                inv.pipelineProgress
                  ? `CASCADE STEP ${inv.pipelineProgress.currentStep}/${inv.pipelineProgress.totalSteps} — ${inv.pipelineProgress.name}`
                  : cascadePhase
              }
            />
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
        onOpenAdmin={() => { window.location.hash = '/console-auth'; }}
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
      <ClientSettingsModal
        open={showSettings}
        onClose={() => setShowSettings(false)}
        apiStatuses={apiStatuses}
        connected={connected}
      />
      <ToastContainer toasts={toasts} onDismiss={dismiss} />

      {savePromptOpen && (
        <div className="save-prompt-overlay" onClick={() => setSavePromptOpen(false)}>
          <div className="save-prompt" onClick={e => e.stopPropagation()}>
            <div className="save-prompt-title-row">
              <Save className="w-4 h-4 save-prompt-icon" />
              <div className="save-prompt-title">SAVE INVESTIGATION TO CASE VAULT</div>
            </div>
            <div className="save-prompt-hint">
              Compiles current workspace observations ({inv.findings.length} findings · {inv.auditTrail.length} audit events) into a persistent case in the Explorer.
            </div>
            <label className="save-prompt-field">
              <span className="save-prompt-label">Case Name <em>optional</em></span>
              <input
                className="save-prompt-input mono"
                value={saveName}
                onChange={e => setSaveName(e.target.value)}
                placeholder="e.g. Suspicious CCTV frame — Mall carpark"
                autoFocus
                onKeyDown={e => { if (e.key === 'Enter') handleSaveInvestigation(saveName, saveTags); if (e.key === 'Escape') setSavePromptOpen(false); }}
              />
            </label>
            <label className="save-prompt-field">
              <span className="save-prompt-label">Tags <em>optional · comma / space separated</em></span>
              <input
                className="save-prompt-input mono"
                value={saveTags}
                onChange={e => setSaveTags(e.target.value)}
                placeholder="e.g. high-priority gps-spoof"
                onKeyDown={e => { if (e.key === 'Enter') handleSaveInvestigation(saveName, saveTags); if (e.key === 'Escape') setSavePromptOpen(false); }}
              />
            </label>
            <div className="save-prompt-actions">
              <button className="save-prompt-btn save-prompt-cancel" onClick={() => setSavePromptOpen(false)}>Cancel</button>
              <button className="save-prompt-btn save-prompt-confirm" onClick={() => handleSaveInvestigation(saveName, saveTags)}>
                <Tag className="w-3 h-3" /> Save &amp; Open Case Explorer
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export function Workbench() {
  return (
    <ByokProvider>
      <InvestigationProvider>
        <ArkBusProvider>
          <WorkbenchInner />
        </ArkBusProvider>
      </InvestigationProvider>
    </ByokProvider>
  );
}
