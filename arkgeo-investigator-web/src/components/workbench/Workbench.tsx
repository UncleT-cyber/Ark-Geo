/** The ARK investigation workbench and its shared workspace context. */
import React, { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { adminAuth, api, ensureBaseUrl, type AiStatusResponse } from '../../api';
import type { AnalyzeResponse, NextStep } from '../../types';
import { TopBar, type ApiKeyStatus } from './TopBar';
import { WorkspaceTabs, WorkspaceTabPanels } from './WorkspaceTabs';
import { InvestigationNavigation, USE_CASES } from './InvestigationNavigation';
import type { ToolTabId } from './TabBar';
import { EvidenceExplorer } from './investigation/EvidenceExplorer';
import { InvestigationOverview } from './investigation/InvestigationOverview';
import { ArkControl } from './ArkControl';
import { useImageReview } from './useImageReview';
import './workspace.css';
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
import { DOMAIN_ICONS, SUBVIEW_ICONS, type LucideIcon } from './icons';
import { Upload, ChevronDown, ChevronRight, Save, Tag } from 'lucide-react';

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
  const imageReview = useImageReview();
  const [dockWidth, setDockWidth] = useState(() => {
    try { return Number(localStorage.getItem('ark.dockWidth')) || 420; }
    catch { return 420; }
  });
  const [resizingDock, setResizingDock] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  const resizeOrigin = useRef<{ x: number; width: number }>();
  const updateDockWidth = (width: number) => {
    const limit = Math.min(800, (bodyRef.current?.clientWidth ?? window.innerWidth) * .55);
    setDockWidth(Math.round(Math.min(limit, Math.max(280, width))));
  };
  useEffect(() => {
    try { localStorage.setItem('ark.dockWidth', String(dockWidth)); } catch { /* private storage */ }
  }, [dockWidth]);
  const [activeSubview, setActiveSubview] = useState<ToolTabId>('overview');
  const [networkTab, setNetworkTab] = useState<NetworkTabId>('discovery');
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [zeroRetention, setZeroRetention] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [thumbnailUrl, setThumbnailUrl] = useState<string | undefined>(undefined);
  const [connected, setConnected] = useState(true);
  const [showPalette, setShowPalette] = useState(false);
  const [showProfile, setShowProfile] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => window.matchMedia('(max-width: 860px)').matches);
  const [explorerExpanded, setExplorerExpanded] = useState(false);
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

  useEffect(() => () => {
    if (thumbnailUrl) URL.revokeObjectURL(thumbnailUrl);
  }, [thumbnailUrl]);

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
    const reviewId = imageReview.begin(file.name);
    setAnalyzing(true);
    setError(null);
    setCascadePhase(null);
    const thumbUrl = URL.createObjectURL(file);
    setThumbnailUrl(thumbUrl);
    lastFileRef.current = file;
    try {
      const resp = await api.analyzeFile(file, zeroRetention);
      inv.loadFromAnalysis(resp, file.name, zeroRetention);
      // Continuous image-intelligence cascade: classification → hashing/source
      // discovery → OCR/telemetry → visual geolocation → evidence fusion. Runs
      // client-side so every asset (even metadata-stripped) yields evidence.
      imageReview.stage(reviewId, 'ARK Core analysis received');
      const pipeline = await inv.runPipeline(file, resp, progress => {
        imageReview.stage(reviewId, `${progress.currentStep}/${progress.totalSteps} · ${progress.name}`);
      });
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
      void imageReview.report(reviewId, resp, pipeline, zeroRetention);
      return resp;
    } catch (err) {
      imageReview.fail(reviewId);
      setError(err instanceof Error ? err.message : 'Analysis failed');
      showToast('Analysis failed', 'error');
    } finally {
      setAnalyzing(false);
      setCascadePhase(null);
    }
  }, [zeroRetention, showToast, inv, imageReview]);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (file && !analyzing) {
      if (['image/jpeg', 'image/png'].includes(file.type)) void analyzeFile(file);
      else setError('Choose a JPEG or PNG image.');
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file && !analyzing) {
      if (['image/jpeg', 'image/png'].includes(file.type)) void analyzeFile(file);
      else setError('Choose a JPEG or PNG image.');
    }
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
    imageReview.clear();
    inv.clear();
    lastFileRef.current = null;
    setError(null);
    setThumbnailUrl(undefined);
    setActiveSubview('overview');
    inv.setDomain('image');
  }, [inv, imageReview]);

  const triggerUpload = useCallback(() => {
    inv.setDomain('image');
    fileInputRef.current?.click();
  }, [inv]);

  const handleRestoreCase = useCallback((saved: SavedCase) => {
    imageReview.clear();
    const snapshot = inv.restoreCase(saved);
    if (!saved.domain || saved.domain === 'image') {
      const id = imageReview.begin(saved.filename, true);
      if (snapshot) void imageReview.report(id, snapshot.result, null, zeroRetention || !!saved.zeroRetention, snapshot);
      else imageReview.fail(id, 'This saved case has no evidence snapshot to review.');
    }
    lastFileRef.current = null;
    setActiveSubview('overview');
    setThumbnailUrl(undefined);
    setError(null);
    showToast(`Restored case ${saved.caseId}`, 'success');
  }, [inv, showToast, imageReview, zeroRetention]);

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

  const openUseCase = (id: typeof USE_CASES[number]['id']) => {
    if (id === 'forensics') {
      openTool(result ? 'fileforensics' : 'overview');
    } else if (id === 'hunting') {
      inv.setDomain('secops');
    } else if (id === 'assessment' || id === 'discovery' || id === 'web') {
      inv.setDomain('network');
      setNetworkTab(id === 'web' ? 'webapp' : 'discovery');
    }
  };

  const activeCaseId = inv.activeCase?.id || null;
  const imageView = IMAGE_SUBVIEWS.find(view => view.id === activeSubview);
  const networkView = NETWORK_TABS.find(view => view.id === networkTab);
  const workspace = {
    image: {
      label: 'Image intelligence',
      title: result ? imageView?.title ?? 'Investigation' : 'System overview',
      description: result ? imageView?.hint : 'Review investigation activity, risk, and saved sessions.',
    },
    network: {
      label: 'Network intelligence',
      title: networkView?.label ?? 'Network workspace',
      description: networkView?.hint,
    },
    secops: {
      label: 'Security operations',
      title: 'Threat & SecOps',
      description: 'Planned capabilities for detection, triage, and incident response.',
    },
    cases: {
      label: 'Case vault',
      title: 'Case explorer',
      description: 'Find saved investigations and review the active case audit trail.',
    },
  }[inv.domain];
  const WorkspaceIcon = DOMAIN_ICONS[inv.domain];

  return (
    <div className="workbench ark-command-center">
      <TopBar
        activeCaseId={activeCaseId}
        apiStatuses={apiStatuses}
        connected={connected}
        onOpenPalette={() => setShowPalette(true)}
        onOpenProfile={() => setShowProfile(true)}
        onSaveInvestigation={openSavePrompt}
      />

      <div ref={bodyRef} className={`workbench-body ${resizingDock ? 'ark-dock-resizing' : ''}`}
        style={{ '--ark-dock-width': `${dockWidth}px` } as React.CSSProperties}>
        <InvestigationNavigation
          collapsed={sidebarCollapsed}
          domain={inv.domain}
          activeCaseId={activeCaseId}
          analyzing={analyzing}
          history={inv.history}
          onToggle={() => setSidebarCollapsed(value => !value)}
          onNew={newSession}
          onNavigate={inv.setDomain}
          onRestore={handleRestoreCase}
          onUseCase={openUseCase}
          onTools={() => setShowPalette(true)}
          onSettings={() => setShowSettings(true)}
          onAdmin={adminAuth.isAuthenticated() ? () => { window.location.hash = `${ADMIN_LOGIN_PATH}/console`; } : undefined}
        />

        {/* Investigation viewport */}
        <main className="workbench-main" aria-labelledby="workspace-title">
          <header className="workspace-heading">
            <div className="workspace-heading-icon"><WorkspaceIcon size={20} aria-hidden="true" /></div>
            <div className="workspace-heading-copy">
              <div className="workspace-heading-domain">{workspace.label}</div>
              <h1 id="workspace-title">{workspace.title}</h1>
              <p>{workspace.description}</p>
            </div>
            {activeCaseId && <span className="workspace-heading-case mono">{activeCaseId}</span>}
          </header>
          {inv.domain === 'network' && <WorkspaceTabs scope="network" tabs={NETWORK_TABS.map(tab => ({
            ...tab, label: ({ discovery: 'Discovery', webapp: 'HTTP / Web', testing: 'Security Testing' } as Partial<Record<NetworkTabId, string>>)[tab.id] ?? tab.label,
          }))} active={networkTab} onSelect={setNetworkTab} />}
          {inv.domain === 'image' && result && <WorkspaceTabs scope="image"
            tabs={IMAGE_SUBVIEWS.map(tab => ({ ...tab, label: tab.title }))}
            active={activeSubview} onSelect={openTool} />}
          <div className="workbench-viewport">
            {inv.domain === 'image' && <>
              <div className="workspace-image-intake">
                {!analyzing && <button type="button" className={`dropzone ${dragOver ? 'dropzone-active' : ''}`}
                  onDragOver={event => { event.preventDefault(); setDragOver(true); }}
                  onDragLeave={() => setDragOver(false)} onDrop={handleDrop} onClick={triggerUpload}>
                  <Upload size={16} /> {result ? 'Upload another image' : 'Upload or drop an image'} <small>JPEG / PNG</small>
                </button>}
                <label className="toggle-row">
                  <input type="checkbox" checked={zeroRetention} disabled={analyzing} onChange={event => setZeroRetention(event.target.checked)} />
                  <span className="toggle-label">Zero-Retention Mode</span>
                </label>
                {zeroRetention && <small className="retention-note">Automatic AI review is paused in this mode.</small>}
                {error && <p className="error-detail" role="alert">{error}</p>}
              </div>
              {result && <details className="workspace-evidence" open={explorerExpanded}
                onToggle={event => setExplorerExpanded(event.currentTarget.open)}>
                <summary>Evidence Explorer</summary>
                <EvidenceExplorer result={result} onOpenTool={openTool} thumbnailUrl={thumbnailUrl} />
              </details>}
              {result ? <WorkspaceTabPanels key={result.request_id} scope="image"
                ids={IMAGE_SUBVIEWS.map(tab => tab.id)} active={activeSubview} render={renderSubview} />
                : <DashboardView key={sessionTick} onUpload={triggerUpload} onRestoreCase={handleRestoreCase} refreshKey={dashRefresh} />}
            </>}
            {inv.domain === 'network' && <NetworkWorkbench activeTab={networkTab} />}
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

        </main>
        <div className="ark-dock-divider" role="separator" aria-label="Resize ARK-CAI dock" aria-orientation="vertical" tabIndex={0}
          onPointerDown={event => {
            if (event.button !== 0) return;
            const dock = event.currentTarget.nextElementSibling;
            if (!dock) return;
            event.currentTarget.setPointerCapture(event.pointerId);
            resizeOrigin.current = { x: event.clientX, width: dock.getBoundingClientRect().width };
            setResizingDock(true);
          }}
          onPointerMove={event => {
            const origin = resizeOrigin.current;
            if (origin && event.currentTarget.hasPointerCapture(event.pointerId)) {
              updateDockWidth(origin.width + origin.x - event.clientX);
            }
          }}
          onLostPointerCapture={() => { resizeOrigin.current = undefined; setResizingDock(false); }}
          onKeyDown={event => {
            if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
            event.preventDefault();
            const width = event.currentTarget.nextElementSibling?.getBoundingClientRect().width ?? dockWidth;
            updateDockWidth(width + (event.key === 'ArrowLeft' ? 24 : -24));
          }}
          onDoubleClick={() => setDockWidth(420)}
        />
        <ArkControl workspaceTitle={workspace.title} imageReview={imageReview.review} onImage={file => { inv.setDomain('image'); return analyzeFile(file); }} analyzing={analyzing} onOpenTool={openTool} evidenceFile={lastFileRef.current} />
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

      <InvestigatorProfileModal
        open={showProfile}
        onClose={() => setShowProfile(false)}
        apiStatuses={apiStatuses}
        onRestoreCase={handleRestoreCase}
      />
      <ClientSettingsModal
        onRestoreCase={handleRestoreCase}
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
