/**
 * Workbench — the main THE ARK forensic investigation workstation.
 *
 * VS Code-style layout:
 *   ActivityBar (far left) → Explorer/Upload sidebar → TabBar → MainViewport → BottomPanel → StatusBar
 *
 * Preserves all existing analysis capabilities (MapWorkspace, FeatureInspector,
 * ExifViewer, ChainOfCustody, IngestionSweep) inside the new tab architecture.
 * The backend remains the source of truth — the workbench displays and interacts.
 */
import React, { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { api } from '../../api';
import type { AnalyzeResponse } from '../../types';
import { TopBar, type ApiKeyStatus } from './TopBar';
import { ActivityBar, type ActivityView } from './ActivityBar';
import { TabBar, type ToolTabId, type TabInstance } from './TabBar';
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
import { IngestionSweep } from '../IngestionSweep';
import { useToast, ToastContainer } from '../Toast';
import { exportCasePdf } from '../../pdfExport';
import { TOOL_ICONS, type LucideIcon } from './icons';
import { Upload } from 'lucide-react';

const TOOL_META: Record<ToolTabId, { title: string; icon: LucideIcon }> = {
  overview: { title: 'Investigation', icon: TOOL_ICONS.overview },
  spatial: { title: 'Spatial Canvas', icon: TOOL_ICONS.spatial },
  fileforensics: { title: 'File Forensics', icon: TOOL_ICONS.fileforensics },
  discovery: { title: 'Source Discovery', icon: TOOL_ICONS.discovery },
  provenance: { title: 'Provenance & C2PA', icon: TOOL_ICONS.provenance },
  vision: { title: 'OCR & Vision', icon: TOOL_ICONS.vision },
  report: { title: 'Case Report', icon: TOOL_ICONS.report },
};

/** Admin login path — obfuscated slug configurable via env (mirrors App.tsx). */
const ADMIN_ROUTE_SLUG = (import.meta as any).env?.VITE_ADMIN_ROUTE_SLUG || 'console-auth';
const ADMIN_LOGIN_PATH = `/${ADMIN_ROUTE_SLUG}`;

let tabIdCounter = 0;
const nextTabId = () => `tab-${++tabIdCounter}`;

export function Workbench() {
  const [activityView, setActivityView] = useState<ActivityView>('upload');
  const [tabs, setTabs] = useState<TabInstance[]>([]);
  const [activeTabId, setActiveTabId] = useState<string | null>(null);
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
          setActivityView('upload');
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
      // Open investigation overview tab automatically
      const overviewTab: TabInstance = {
        id: nextTabId(), toolId: 'overview', title: 'Investigation', icon: TOOL_META.overview.icon,
      };
      setTabs([overviewTab]);
      setActiveTabId(overviewTab.id);
      setActivityView('explorer');
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

  const openTool = useCallback((toolId: ToolTabId) => {
    setTabs(prev => {
      // Duplicate prevention: switch to existing tab of same tool
      const existing = prev.find(t => t.toolId === toolId);
      if (existing) {
        setActiveTabId(existing.id);
        return prev;
      }
      const meta = TOOL_META[toolId];
      const newTab: TabInstance = {
        id: nextTabId(),
        toolId,
        title: meta.title,
        icon: meta.icon,
      };
      setActiveTabId(newTab.id);
      return [...prev, newTab];
    });
  }, []);

  const closeTab = useCallback((id: string) => {
    setTabs(prev => {
      const idx = prev.findIndex(t => t.id === id);
      if (idx === -1) return prev;
      const next = prev.filter(t => t.id !== id);
      if (activeTabId === id) {
        setActiveTabId(next.length ? (next[Math.max(0, idx - 1)].id) : null);
      }
      return next;
    });
  }, [activeTabId]);

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

  // Render the active tool view
  const renderTool = (tab: TabInstance | undefined) => {
    if (!tab || !result) return null;
    switch (tab.toolId) {
      case 'overview':
        return <InvestigationOverview result={result} onOpenTool={openTool} thumbnailUrl={thumbnailUrl} />;
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

  const activeTab = tabs.find(t => t.id === activeTabId);

  // Malicious / review badge counts are derived from the current result's
  // anomaly signals (TopBar reflects the active investigation).
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
    setTabs([]);
    setActiveTabId(null);
    setError(null);
    setThumbnailUrl(undefined);
    setActivityView('upload');
  }, []);

  const triggerUpload = useCallback(() => {
    setActivityView('upload');
    fileInputRef.current?.click();
  }, []);

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
        {/* Activity Bar (far-left navigation) */}
        <ActivityBar active={activityView} onNavigate={setActivityView} evidenceCount={result ? 1 : 0} />

        {/* Sidebar (Explorer or Upload) */}
        {sidebarVisible && (
          <>
            <div className="workbench-sidebar">
              {activityView === 'upload' && (
                <div className="sidebar-content">
                  <div className="sidebar-header">TARGET UPLOAD</div>
                  <div
                    className={`dropzone ${dragOver ? 'dropzone-active' : ''} ${analyzing ? 'dropzone-busy' : ''}`}
                    onDragOver={e => { e.preventDefault(); setDragOver(true); }}
                    onDragLeave={() => setDragOver(false)}
                    onDrop={handleDrop}
                    onClick={() => fileInputRef.current?.click()}
                  >
                    {analyzing ? (
                      <div className="dropzone-scanning"><div className="radar-pulse" /><span>SCANNING...</span></div>
                    ) : (
                      <>
                        <div className="dropzone-icon"><Upload className="w-7 h-7" /></div>
                        <div className="dropzone-text">Drag & drop image here</div>
                        <div className="dropzone-subtext">JPEG / PNG · high-res supported</div>
                      </>
                    )}
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
                  {!result && !analyzing && !error && (
                    <div className="sidebar-hint">
                      Upload an image to begin a forensic investigation. Results are unique to each image's actual bytes and metadata.
                    </div>
                  )}
                  {result && (
                    <button className="sidebar-new-session" onClick={newSession}>+ New Investigation</button>
                  )}
                </div>
              )}
              {activityView === 'explorer' && (
                <EvidenceExplorer result={result} onOpenTool={openTool} thumbnailUrl={thumbnailUrl} />
              )}
              {activityView === 'analysis' && (
                <div className="sidebar-content">
                  <div className="sidebar-header">ANALYSIS TOOLS</div>
                  {result ? (
                    <div className="tool-launcher-list">
                      {(['spatial', 'fileforensics', 'discovery', 'provenance', 'vision', 'report'] as ToolTabId[]).map(tid => {
                        const Icon = TOOL_META[tid].icon;
                        return (
                          <button key={tid} className="tool-launcher-btn" onClick={() => openTool(tid)}>
                            <span className="tool-launcher-icon"><Icon className="w-4 h-4" /></span>
                            <span className="tool-launcher-label">{TOOL_META[tid].title}</span>
                          </button>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="sidebar-hint">Upload an image first to access analysis tools.</div>
                  )}
                </div>
              )}
              {activityView === 'settings' && (
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
                      <button className="settings-btn" onClick={() => setSidebarVisible(false)}>Hide sidebar</button>
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

        {/* Main area: TabBar + Viewport + BottomPanel */}
        <div className="workbench-main">
          <TabBar
            tabs={tabs}
            activeTabId={activeTabId}
            onSelectTab={setActiveTabId}
            onCloseTab={closeTab}
            onOpenTool={openTool}
          />

          <div className="workbench-viewport">
            {activeTab && result ? (
              renderTool(activeTab)
            ) : (
              <DashboardView key={sessionTick} onUpload={triggerUpload} />
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
        onUpload={() => { setActivityView('upload'); fileInputRef.current?.click(); }}
        hasResult={!!result}
      />

      {/* Hidden file input accessible from command palette */}
      <input ref={fileInputRef} type="file" accept="image/jpeg,image/png" onChange={handleFileSelect} style={{ display: 'none' }} />

      {!sidebarVisible && (
        <button className="sidebar-restore" onClick={() => setSidebarVisible(true)} title="Show sidebar">▸</button>
      )}
      <ToastContainer toasts={toasts} onDismiss={dismiss} />
    </div>
  );
}
