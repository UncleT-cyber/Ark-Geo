/** The ARK investigation workbench and its shared workspace context. */
import React, { useState, useCallback, useRef, useEffect, useLayoutEffect, useMemo } from 'react';
import { adminAuth, api, ensureBaseUrl, type AiStatusResponse } from '../../api';
import type { AnalyzeResponse, NextStep } from '../../types';
import { TopBar, type ApiKeyStatus } from './TopBar';
import { WorkspaceTabs, WorkspaceTabPanels } from './WorkspaceTabs';
import { InvestigationNavigation, USE_CASES } from './InvestigationNavigation';
import { UseCasesView } from './UseCasesView';
import type { ToolTabId } from './TabBar';
import { EvidenceExplorer } from './investigation/EvidenceExplorer';
import { InvestigationOverview } from './investigation/InvestigationOverview';
import { ArkControl } from './ArkControl';
import { CaiBrowserProvider, useCaiBrowser } from './caiBrowserBus';
import { BrowserWorkspace } from './BrowserWorkspace';
import { isWorkspaceTool, type OperationalToolId } from './operationalTools';
import { useImageReview } from './useImageReview';
import './workspace.css';
import './browser-workspace.css';
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
import { SystemOverviewWorkspace } from './SystemOverviewWorkspace';
import { CaseExplorer } from './CaseExplorer';
import { SettingsWorkspace, type SettingsSectionId } from '../settings/SettingsWorkspace';
import { IngestionSweep } from '../IngestionSweep';
import { useToast, ToastContainer } from '../Toast';
import { exportCasePdf } from '../../pdfExport';
import { InvestigationProvider, useInvestigation, type SavedCase, type SavedCaseDomain } from './useInvestigation';
import { useInvestigationTabs } from '../../core/tabs/useInvestigationTabs';
import { TabsProvider, useTabs } from '../../core/tabs/TabsContext';
import { InvestigationStoreProvider, useInvestigationStore, useInvestigationSlice } from '../../core/investigation/InvestigationStoreContext';
import { defaultWorkspaceSelection, type InvestigationRunStatus } from '../../core/investigation/investigationStore';
import { NeutralWorkspace, type NeutralWorkspaceId } from './NeutralWorkspace';
import {
  notificationFromEvent, pushNotification, unreadCount, type AppNotification,
} from '../../core/notifications';
import { ByokProvider } from '../settings/ByokContext';
import { byokStore } from '../../core/byok/byokStore';
import type { ByokProviderId } from '../../types';
import { SUBVIEW_ICONS, type LucideIcon } from './icons';
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
  const tabApi = useTabs();
  const invStore = useInvestigationStore();
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const unread = unreadCount(notifications);
  const [dockWidth, setDockWidth] = useState(() => {
    try { return Number(localStorage.getItem('ark.dockWidth')) || 420; }
    catch { return 420; }
  });
  const [resizingDock, setResizingDock] = useState(false);
  const [caiExpanded, setCaiExpanded] = useState(false);
  const caiBrowser = useCaiBrowser();
  // A workspace tool (e.g. Browser) takes over the central application area,
  // replacing the active investigation view. This selection is owned by the
  // active investigation, so two investigations can be in different workspaces.
  const activeInvId = tabApi.activeId;
  const activeWorkspace = activeInvId ? invStore.metaFor(activeInvId)?.workspace : undefined;
  const workspaceTool = (activeWorkspace?.workspaceTool ?? null) as OperationalToolId | null;
  // A new investigation starts neutral: no workspace chosen yet. It is NOT the
  // Image Intelligence System Overview — that belongs to Image Intelligence.
  const isNeutralWorkspace = activeWorkspace ? activeWorkspace.neutral : false;
  const setWorkspaceTool = useCallback((value: OperationalToolId | null) => {
    if (activeInvId) invStore.patchWorkspace(activeInvId, { workspaceTool: value, neutral: false });
  }, [activeInvId, invStore]);
  // Whether the managed browser runtime is reachable — gates the Browser tool
  // in the operational inspector so the menu never offers a dead action.
  const [browserAvailable, setBrowserAvailable] = useState(false);
  useEffect(() => {
    let cancelled = false;
    api.browserStatus()
      .then(status => { if (!cancelled) setBrowserAvailable(status.available); })
      .catch(() => { if (!cancelled) setBrowserAvailable(false); });
    return () => { cancelled = true; };
  }, []);
  const bodyRef = useRef<HTMLDivElement>(null);
  const resizeOrigin = useRef<{ x: number; width: number }>();
  // Remembers the docked width so Restore returns to it rather than a default.
  const dockWidthBeforeExpand = useRef(420);
  // The control that asked to expand, so Restore can return focus to it.
  const expandReturnFocus = useRef<HTMLElement | null>(null);
  const updateDockWidth = (width: number) => {
    const limit = Math.min(800, (bodyRef.current?.clientWidth ?? window.innerWidth) * .55);
    setDockWidth(Math.round(Math.min(limit, Math.max(280, width))));
  };
  useEffect(() => {
    try { localStorage.setItem('ark.dockWidth', String(dockWidth)); } catch { /* private storage */ }
  }, [dockWidth]);
  // --- ARK expand / restore (layout-driven, no remount) ---
  const expandCai = useCallback(() => {
    const active = document.activeElement;
    expandReturnFocus.current = active instanceof HTMLElement ? active : null;
    dockWidthBeforeExpand.current = dockWidth;
    setCaiExpanded(true);
  }, [dockWidth]);
  const restoreCai = useCallback(() => {
    setCaiExpanded(false);
    // Return to the exact docked width the operator had (never a reset default).
    setDockWidth(dockWidthBeforeExpand.current);
    requestAnimationFrame(() => expandReturnFocus.current?.focus?.());
  }, []);
  // Mirror for the (stable) global Escape listener.
  const caiExpandedRef = useRef(false);
  useEffect(() => { caiExpandedRef.current = caiExpanded; }, [caiExpanded]);
  // Workspace sub-selections are owned by the active investigation.
  const activeSubview = (activeWorkspace?.imageSubview ?? 'overview') as ToolTabId;
  const networkTab = (activeWorkspace?.networkTab ?? 'discovery') as NetworkTabId;
  const setActiveSubview = useCallback((value: ToolTabId) => {
    if (activeInvId) invStore.patchWorkspace(activeInvId, { imageSubview: value, neutral: false });
  }, [activeInvId, invStore]);
  const setNetworkTab = useCallback((value: NetworkTabId) => {
    if (activeInvId) invStore.patchWorkspace(activeInvId, { networkTab: value, neutral: false });
  }, [activeInvId, invStore]);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [connected, setConnected] = useState(true);
  const [showPalette, setShowPalette] = useState(false);
  const [settingsSection, setSettingsSection] = useState<SettingsSectionId>('keys');
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
  const { toasts, showToast, dismiss } = useToast();

  // Evidence-ingest state is per investigation: the thumbnail, the source file
  // handle, the in-flight analysis flag and the zero-retention choice must not
  // leak from one investigation's evidence into another's view. The file handle
  // itself stays in a ref map (never in React state) so no content is retained
  // beyond the live session.
  const [thumbnailUrl, setThumbnailUrl] = useInvestigationSlice<string | undefined>('thumbnailUrl', () => undefined);
  const [analyzing, setAnalyzing] = useInvestigationSlice<boolean>('analyzing', () => false);
  const [zeroRetention, setZeroRetention] = useInvestigationSlice<boolean>('zeroRetention', () => false);
  const lastFilesRef = useRef<Record<string, File | null>>({});
  const sliceKey = activeInvId ?? '__none__';
  const lastFileRef = useMemo(() => ({
    get current() { return lastFilesRef.current[sliceKey] ?? null; },
    set current(file: File | null) { lastFilesRef.current[sliceKey] = file; },
  }), [sliceKey]);
  // Live object URLs, per investigation, so a superseded thumbnail is revoked
  // immediately and every remaining one is revoked when the workbench unmounts
  // (never on investigation switch — the other investigation may return to it).
  const thumbUrlsRef = useRef<Record<string, string | undefined>>({});

  const result = inv.result;

  useEffect(() => () => {
    Object.values(thumbUrlsRef.current).forEach(url => { if (url) URL.revokeObjectURL(url); });
    thumbUrlsRef.current = {};
  }, []);

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
        // Escape restores an expanded dock only when it is not needed to dismiss
        // a dialog, command palette or an open menu first. Settings is a normal
        // tab now, so it is closed via its tab, not Escape.
        const overlayOpen = !!document.querySelector(
          '.cmd-palette-overlay, .profile-modal-overlay, .save-prompt-overlay, .ark-model-popover, .ark-menu',
        );
        if (!overlayOpen && caiExpandedRef.current) restoreCai();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [restoreCai]);

  // Navigating to another main workspace docks the dock again — the active task
  // is untouched (no cancellation, no remount).
  const lastDomain = useRef(inv.domain);
  useEffect(() => {
    if (lastDomain.current !== inv.domain) {
      lastDomain.current = inv.domain;
      setCaiExpanded(false);
    }
  }, [inv.domain]);

  const analyzeFile = useCallback(async (file: File) => {
    const reviewId = imageReview.begin(file.name);
    setAnalyzing(true);
    setError(null);
    setCascadePhase(null);
    const thumbUrl = URL.createObjectURL(file);
    const prevThumb = thumbUrlsRef.current[sliceKey];
    if (prevThumb && prevThumb !== thumbUrl) URL.revokeObjectURL(prevThumb);
    thumbUrlsRef.current[sliceKey] = thumbUrl;
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
  }, [zeroRetention, showToast, inv, imageReview, lastFileRef, sliceKey]);

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
    // Leaving a workspace tool (Browser) returns to the investigation surface.
    setWorkspaceTool(null);
    inv.setDomain('image');
    setActiveSubview(toolId);
  }, [inv, setWorkspaceTool, setActiveSubview]);

  /** Activity-bar domain navigation also dismisses a workspace tool. */
  const handleNavigateDomain = useCallback((domain: Parameters<typeof inv.setDomain>[0]) => {
    setWorkspaceTool(null);
    inv.setDomain(domain);
  }, [inv, setWorkspaceTool]);

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
    setError(null);
    // A new investigation is a NEW identity with its own conversation, execution
    // context and workspace selection — it does NOT wipe the shared context, and
    // it does NOT create a case record. The previous investigation is untouched.
    // Its own ingest state (thumbnail, file handle, retention) starts at the
    // keyed defaults, so nothing is cleared here.
    const id = tabApi.createTab({ title: 'New investigation', domain: 'image' });
    invStore.ensure(id, { workspace: { ...defaultWorkspaceSelection() } });
  }, [imageReview, tabApi, invStore]);

  /** Select a tab and, for full-page destinations (System Overview, Settings),
   *  publish their domain directly. `inv.domain` is derived from the active
   *  investigation's stored workspace, so re-selecting the tab that is already
   *  active does not change `activeId` and the activation effect never re-runs
   *  — leaving the click a no-op once the domain has drifted (the operator
   *  navigated elsewhere, which only patches the workspace). Publishing the
   *  domain here makes the destination reachable from the tab strip too. */
  const activateTab = useCallback((id: string) => {
    const tab = tabApi.tabs.find(t => t.id === id);
    if (tab && (tab.domain === 'system' || tab.domain === 'settings')) {
      invStore.patchWorkspace(id, { domain: tab.domain, neutral: false });
    }
    tabApi.selectTab(id);
  }, [tabApi, invStore]);

  /** Open Settings as a normal, single application tab and activate it.
   *  Repeated opens reuse the same tab (never duplicate); the user's open
   *  investigations, their runs and the conversation history are untouched. */
  const openSettings = useCallback(() => {
    setShowPalette(false);
    const existing = tabApi.tabs.find(t => t.domain === 'settings');
    if (existing) {
      activateTab(existing.id);
      return;
    }
    tabApi.createTab({ title: 'Settings', domain: 'settings' });
  }, [tabApi, activateTab]);

  /** Open the standalone System Overview as a single application tab.
   *  System Overview is a system-level destination, not an investigation: it
   *  never creates a case, never binds a session and never overwrites the
   *  active investigation's workspace. Repeated opens reuse the same tab. */
  const openSystemOverview = useCallback(() => {
    setShowPalette(false);
    const existing = tabApi.tabs.find(t => t.domain === 'system');
    if (existing) {
      activateTab(existing.id);
      return;
    }
    const id = tabApi.createTab({ title: 'System Overview', domain: 'system' });
    invStore.ensure(id, { workspace: { ...defaultWorkspaceSelection(), domain: 'system', neutral: false } });
  }, [tabApi, activateTab, invStore]);

  // Default landing destination: a window with no active investigation opens
  // the System Overview (a system-level destination) rather than dropping
  // straight into Image Intelligence. A restored investigation is left
  // untouched, and the overview stays an ordinary, closable tab afterwards.
  // Runs once, before paint, so the first frame is already the overview.
  const landed = useRef(false);
  useLayoutEffect(() => {
    if (landed.current) return;
    landed.current = true;
    // `activeTab` (resolved), not `activeId`: a stale active id whose tab was
    // closed must still land on the overview rather than an orphaned image view.
    if (tabApi.activeTab) return;
    const existing = tabApi.tabs.find(t => t.domain === 'system');
    const id = existing ? existing.id : tabApi.createTab({ title: 'System Overview', domain: 'system' });
    // Seed the workspace selection now so the domain resolves to 'system' on
    // the first render instead of flashing the Image Intelligence landing.
    invStore.ensure(id, { workspace: { ...defaultWorkspaceSelection(), domain: 'system', neutral: false } });
    if (existing) tabApi.selectTab(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Map a live CAI event to a notification + tab run-status update. */
  const handleInvestigationEvent = useCallback((ev: Record<string, any>) => {
    const sid: string | null = ev.session_id ?? null;
    // The tab that owns this run. The `session` event arrives as the first
    // event of a run, before any operator can switch tabs, so the active tab is
    // the run's investigation. Status events resolve by session id below.
    const tab = tabApi.activeTab;
    if (sid && ev.event === 'session') {
      // Bind the backend session id to the active investigation *in place*.
      // A live session event must never create or activate a tab: that would
      // re-key the investigation store mid-run and orphan the streaming reply
      // (the P0 "send → no response" defect).
      tabApi.bindSession(sid, { title: inv.activeCase?.title || inv.activeEvidence?.filename || 'Investigation', domain: inv.domain as any, caseId: inv.activeCase?.id ?? null });
      if (tab) invStore.patchMeta(tab.id, { sessionId: sid, caseId: inv.activeCase?.id ?? null });
      return;
    }
    if (sid && ev.event === 'run_created') {
      tabApi.setRunStatus(sid, 'running');
      if (tab) invStore.setRunStatus(tab.id, 'running', ev.run_id ?? null);
    }
    if (sid && (ev.event === 'run_completed')) {
      tabApi.setRunStatus(sid, 'completed');
      if (tab) invStore.setRunStatus(tab.id, 'completed');
    }
    if (sid && (ev.event === 'run_failed' || (ev.event === 'scope_checked' && ev.allowed === false))) {
      tabApi.setRunStatus(sid, 'failed');
      if (tab) invStore.setRunStatus(tab.id, 'failed');
    }

    // CAI-driven browsing: when ARK invokes a browser.* tool, surface the
    // operator Browser workspace and follow the session it is driving.
    const toolId: string = ev.tool ?? ev.function?.name ?? '';
    if ((ev.event === 'tool_call' || ev.event === 'tool') && toolId.startsWith('browser.')) {
      caiBrowser.noteToolCall(toolId, ev.args, ev.result);
      setWorkspaceTool('browser');
    }

    const n = notificationFromEvent(ev);
    if (n) setNotifications(prev => pushNotification(prev, n));

    // C.1 — fold case-affecting events into the shared investigation slices so
    // the AI run and manual edits write the same findings/audit state. The
    // mapper ignores timeline-only events and does nothing when no case is
    // active, so this is a no-op for ordinary chat.
    if (ev.event === 'tool' || ev.event === 'evidence_recorded' || ev.event === 'result_verified') {
      inv.foldInvestigationEvent(ev);
    }
  }, [inv.activeCase, inv.activeEvidence, inv.domain, inv.foldInvestigationEvent, tabApi, caiBrowser, invStore, setWorkspaceTool]);

  const handleMarkAllRead = useCallback(() => {
    setNotifications(prev => prev.map(item => item.read ? item : { ...item, read: true }));
  }, []);

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
  }, [inv, showToast, imageReview, zeroRetention, lastFileRef]);

  const handleSelectTab = useCallback((id: string) => { activateTab(id); }, [activateTab]);

  const handleCloseTab = useCallback((id: string) => {
    tabApi.closeTab(id);
    // Release the closed investigation's live UI state (conversation, run
    // timeline, queue, thumbnail object URL, file handle). Durable metadata is
    // retained so a still-running backend session is not orphaned.
    const url = thumbUrlsRef.current[id];
    if (url) URL.revokeObjectURL(url);
    delete thumbUrlsRef.current[id];
    delete lastFilesRef.current[id];
    invStore.drop(id);
  }, [tabApi, invStore]);

  // Tab activation seeds the investigation store from the tab descriptor and,
  // when the investigation has no case context yet, rehydrates its saved case.
  // Because case context is now investigation-keyed, switching back to a tab
  // restores that investigation's own workspace and conversation untouched —
  // this effect only has to handle the *first* activation of an investigation.
  const appliedTab = useRef<string | null>(null);
  useEffect(() => {
    const tab = tabApi.activeTab;
    if (!tab) {
      // Nothing active (e.g. the Settings or System Overview tab was closed
      // with no investigation open) → return to the IMAGE landing state.
      if (inv.domain === 'settings' || inv.domain === 'system') inv.setDomain('image');
      appliedTab.current = null;
      return;
    }
    // Ensure the investigation exists in the store (idempotent) and keep its
    // durable metadata in step with the tab descriptor. Only defined values are
    // merged, so a re-activated tab never clobbers a session id the store
    // already holds (e.g. a run started before the tab was closed).
    invStore.ensure(tab.id, {
      title: tab.title,
      ...(tab.sessionId ? { sessionId: tab.sessionId } : {}),
      ...(tab.caseId ? { caseId: tab.caseId } : {}),
      runStatus: (tab.runStatus as InvestigationRunStatus) ?? 'idle',
    });
    if (appliedTab.current === tab.id) return;
    appliedTab.current = tab.id;

    // Settings and System Overview are full-page surfaces, not investigations:
    // switch the domain and leave the underlying investigation state untouched
    // for when we return.
    if (tab.domain === 'settings') {
      inv.setDomain('settings');
      return;
    }
    if (tab.domain === 'system') {
      inv.setDomain('system');
      return;
    }
    // Rehydrate this investigation's saved case only if it has no case context
    // of its own yet (first activation).
    const saved = inv.history.find(h => h.caseId === tab.caseId);
    if (saved && inv.activeCase?.id !== saved.caseId) handleRestoreCase(saved);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tabApi.activeId, tabApi.activeTab]);

  const handleOpenNotification = useCallback((n: AppNotification) => {
    setNotifications(prev => prev.map(item => item.id === n.id ? { ...item, read: true } : item));
    const match = n.sessionId ? tabApi.tabs.find(t => t.sessionId === n.sessionId) : undefined;
    if (match) tabApi.selectTab(match.id);
    else if (n.sessionId) tabApi.ensureTab(n.sessionId, { title: 'Investigation', domain: 'image' });
  }, [tabApi]);

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
  const isSettings = inv.domain === 'settings';
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
    usecases: {
      label: 'Investigations',
      title: 'Use cases',
      description: 'Quick-start surfaces for common investigation workflows.',
    },
    system: {
      label: 'System',
      title: 'System Overview',
      description: 'Operational posture across investigations, agents, inference and evidence.',
    },
    settings: {
      label: 'Settings',
      title: 'Settings',
      description: 'Providers, keys, model, privacy and support.',
    },
  }[inv.domain];

  return (
    <div className="workbench ark-command-center">
      <TopBar
        tabs={tabApi.tabs}
        activeTabId={tabApi.activeId}
        onSelectTab={handleSelectTab}
        onCloseTab={handleCloseTab}
        onNewTab={newSession}
        notifications={notifications}
        unread={unread}
        onOpenNotification={handleOpenNotification}
        onMarkAllRead={handleMarkAllRead}
      />

      <div ref={bodyRef} className={`workbench-body ${resizingDock ? 'ark-dock-resizing' : ''} ${caiExpanded ? 'ark-cai-expanded' : ''} ${isSettings ? 'workbench-body-settings' : ''}`}
        style={{ '--ark-dock-width': `${dockWidth}px` } as React.CSSProperties}>
        {isSettings ? (
          <SettingsWorkspace
            section={settingsSection}
            onSection={setSettingsSection}
            onRestoreCase={handleRestoreCase}
            apiStatuses={apiStatuses}
            connected={connected}
          />
        ) : (
        <>
        <InvestigationNavigation
          collapsed={sidebarCollapsed}
          domain={inv.domain}
          onToggle={() => setSidebarCollapsed(value => !value)}
          onNavigate={handleNavigateDomain}
          onUseCases={() => handleNavigateDomain('usecases')}
          onSystem={openSystemOverview}
          onSettings={openSettings}
          onAdmin={adminAuth.isAuthenticated() ? () => { window.location.hash = `${ADMIN_LOGIN_PATH}/console`; } : undefined}
        />

        {/* Investigation viewport */}
        {inv.domain === 'system' ? (
          <main className="workbench-main" aria-labelledby="workspace-title">
            <div className="workbench-viewport ark-workspace-system">
              <SystemOverviewWorkspace />
            </div>
          </main>
        ) : workspaceTool === 'browser' ? (
          <main className="workbench-main" aria-labelledby="workspace-title">
            <header className="workspace-heading">
              <div className="workspace-heading-copy">
                <div className="workspace-heading-domain">Managed browser</div>
                <h1 id="workspace-title">Browser</h1>
                <p>Embedded browsing workspace — screenshot-first, driven by ARK or taken over by the operator.</p>
              </div>
              {activeCaseId && <span className="workspace-heading-case mono">{activeCaseId}</span>}
            </header>
            <div className="workbench-viewport ark-workspace-browser">
              <BrowserWorkspace onClose={() => setWorkspaceTool(null)} caseId={activeCaseId ?? ''} />
            </div>
          </main>
        ) : isNeutralWorkspace ? (
          <main className="workbench-main" aria-labelledby="workspace-title">
            <NeutralWorkspace
              title={tabApi.activeTab?.title || 'New investigation'}
              investigationId={activeInvId ?? ''}
              caseId={activeCaseId}
              browserAvailable={browserAvailable}
              onSelectWorkspace={(id: NeutralWorkspaceId) => {
                if (id === 'browser') { setWorkspaceTool('browser'); return; }
                if (id === 'cases') { inv.setDomain('cases'); return; }
                inv.setDomain(id);
              }}
            />
          </main>
        ) : (
        <main className="workbench-main" aria-labelledby="workspace-title">
          <header className="workspace-heading">
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
            {inv.domain === 'usecases' && <UseCasesView onUseCase={openUseCase} />}
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
        )}
        <section className="ark-cai-region" aria-label="ARK workspace">
          <div className="ark-dock-divider" role="separator" aria-label="Resize ARK dock" aria-orientation="vertical" tabIndex={0}
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
          <ArkControl workspaceTitle={workspace.title} imageReview={imageReview.review} onImage={file => { inv.setDomain('image'); return analyzeFile(file); }} analyzing={analyzing} onOpenTool={openTool} evidenceFile={lastFileRef.current}
            expanded={caiExpanded} onToggleExpand={() => (caiExpanded ? restoreCai() : expandCai())} onEvent={handleInvestigationEvent} browserAvailable={browserAvailable}
            onOpenWorkspaceTool={id => { if (isWorkspaceTool(id)) setWorkspaceTool(id); }} />
        </section>
        </>
        )}
      </div>

      {!isSettings && <StatusBar result={result} connected={connected} analyzing={analyzing} activeCaseId={activeCaseId} />}

      <CommandPalette
        open={showPalette}
        onClose={() => setShowPalette(false)}
        onOpenTool={openTool}
        onExportPdf={handleExportPdf}
        onUpload={() => { inv.setDomain('image'); fileInputRef.current?.click(); }}
        onOpenAdmin={() => { window.location.hash = '/console-auth'; }}
        onNewInvestigation={newSession}
        onSaveInvestigation={() => { setShowPalette(false); openSavePrompt(); }}
        onOpenSettings={openSettings}
        hasResult={!!result}
      />

      <input ref={fileInputRef} type="file" accept="image/jpeg,image/png" onChange={handleFileSelect} style={{ display: 'none' }} />

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
      <TabsProvider>
        <InvestigationStoreProviderHost>
          <ArkBusProvider>
            <CaiBrowserProvider>
              <WorkbenchInner />
            </CaiBrowserProvider>
          </ArkBusProvider>
        </InvestigationStoreProviderHost>
      </TabsProvider>
    </ByokProvider>
  );
}

/** Bridges the tab surface (the active investigation) to the investigation
 *  store, then mounts the investigation-keyed case-context provider. */
function InvestigationStoreProviderHost({ children }: { children: React.ReactNode }) {
  const tabs = useTabs();
  const activeId = tabs.activeId;
  return (
    <InvestigationStoreProvider activeId={activeId}>
      <InvestigationProvider>{children}</InvestigationProvider>
    </InvestigationStoreProvider>
  );
}
