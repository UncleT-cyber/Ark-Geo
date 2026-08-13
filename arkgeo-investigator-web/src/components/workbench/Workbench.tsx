/**
 * Workbench — the main ArkGeo forensic investigation workstation.
 *
 * VS Code-style layout:
 *   ActivityBar (far left) → Explorer/Upload sidebar → TabBar → MainViewport → BottomPanel → StatusBar
 *
 * Preserves all existing analysis capabilities (MapWorkspace, FeatureInspector,
 * ExifViewer, ChainOfCustody, IngestionSweep) inside the new tab architecture.
 * The backend remains the source of truth — the workbench displays and interacts.
 */
import React, { useState, useCallback, useRef, useEffect } from 'react';
import { api } from '../../api';
import type { AnalyzeResponse } from '../../types';
import { ActivityBar, type ActivityView } from './ActivityBar';
import { TabBar, type ToolTabId, type TabInstance } from './TabBar';
import { EvidenceExplorer } from './investigation/EvidenceExplorer';
import { InvestigationOverview } from './investigation/InvestigationOverview';
import { BottomPanel } from './BottomPanel';
import { StatusBar } from './StatusBar';
import { CommandPalette } from './CommandPalette';
import { SpatialTool } from './tools/SpatialTool';
import { FileForensicsTool } from './tools/FileForensicsTool';
import { DiscoveryTool } from './tools/DiscoveryTool';
import { ProvenanceTool } from './tools/ProvenanceTool';
import { VisionTool } from './tools/VisionTool';
import { ReportTool } from './tools/ReportTool';
import { IngestionSweep } from '../IngestionSweep';
import { useToast, ToastContainer } from '../Toast';
import { exportCasePdf } from '../../pdfExport';

const TOOL_META: Record<ToolTabId, { title: string; icon: string }> = {
  overview: { title: 'Investigation', icon: '🔬' },
  spatial: { title: 'Spatial Canvas', icon: '🗺' },
  fileforensics: { title: 'File Forensics', icon: '📦' },
  discovery: { title: 'Source Discovery', icon: '🔍' },
  provenance: { title: 'Provenance & C2PA', icon: '🔐' },
  vision: { title: 'OCR & Vision', icon: '👁' },
  report: { title: 'Case Report', icon: '📋' },
};

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
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { toasts, showToast, dismiss } = useToast();

  // Health check
  useEffect(() => {
    api.health().then(() => setConnected(true)).catch(() => setConnected(false));
  }, []);

  // Command palette hotkey: Cmd/Ctrl+Shift+P
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const modKey = e.metaKey || e.ctrlKey;
      if (modKey && e.shiftKey && (e.key === 'P' || e.key === 'p')) {
        e.preventDefault();
        if (result) {
          setShowPalette(true);
        } else {
          // No case open — go to upload
          setActivityView('upload');
        }
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
      // Open investigation overview tab automatically
      const overviewTab: TabInstance = {
        id: nextTabId(), toolId: 'overview', title: 'Investigation', icon: '🔬',
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
    showToast('⚠ GEOFENCE VIOLATION', 'error');
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

  return (
    <div className="workbench">
      <ActivityBar active={activityView} onNavigate={setActivityView} evidenceCount={result ? 1 : 0} />

      <div className="workbench-body">
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
                        <div className="dropzone-icon">📁</div>
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
                      {(['spatial', 'fileforensics', 'discovery', 'provenance', 'vision', 'report'] as ToolTabId[]).map(tid => (
                        <button key={tid} className="tool-launcher-btn" onClick={() => openTool(tid)}>
                          <span className="tool-launcher-icon">{TOOL_META[tid].icon}</span>
                          <span className="tool-launcher-label">{TOOL_META[tid].title}</span>
                        </button>
                      ))}
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
                    <div className="settings-note">
                      API providers are configured through the Admin control plane.
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
            {activeTab ? (
              renderTool(activeTab)
            ) : (
              <div className="viewport-empty">
                <div className="viewport-empty-icon">⬡</div>
                <div className="viewport-empty-title">No Investigation Open</div>
                <div className="viewport-empty-text">
                  Upload a target image to begin. Use Cmd/Ctrl+Shift+P for the command palette.
                </div>
                <button className="viewport-empty-btn" onClick={() => fileInputRef.current?.click()}>
                  Upload Target Image
                </button>
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
