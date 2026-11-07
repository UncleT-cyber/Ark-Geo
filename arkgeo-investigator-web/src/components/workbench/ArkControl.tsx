import { useEffect, useMemo, useRef, useState } from 'react';
import { Activity, Mic, Plus, Send, Square, X, Play, StopCircle, CheckCircle, AlertCircle, RefreshCw, Copy, ChevronDown, ChevronUp, Trash2, Rocket, Maximize2, Minimize2, Loader2 } from 'lucide-react';
import type { AnalyzeResponse } from '../../types';
import { api } from '../../api';
import type { ToolTabId } from './TabBar';
import { caseIdFromRequest } from './entities';
import { useInvestigation } from './useInvestigation';
import { useInvestigationStore, useInvestigationSlice } from '../../core/investigation/InvestigationStoreContext';
import { useDictation } from './useDictation';
import { type ImageReview } from './useImageReview';
import { BottomPanel } from './BottomPanel';
import { ExecutionActivity, InvestigationReport } from './ExecutionPanels';
import {
  summarizeRun, toolDisplayName,
  type ExecutionEvent,
} from './executionPresentation';
import {
  OPERATIONAL_TOOLS, operationalTool, isConsoleTool, isWorkspaceTool,
  type OperationalToolId,
} from './operationalTools';
import './ark-control.css';

const commands = ['/help', '/agent', '/case', '/tools', '/investigate', '/forensics', '/osint', '/clear'];
const roster = ['Operator', 'Forensics', 'OSINT', 'Tracker', 'Malware Analyst', 'Provenance'];
const noRoster = 'mode: advisory — Detected 0 advisory cue(s) vs 0 operational cue(s). I have no visibility into an agents list. If you require enumeration, provide scope and authorization.';

type Message = {
  user?: boolean;
  text: string;
  image?: string;
  tools?: string[];
  approval?: { session: string; execution?: string; tool: string };
};

type QueueEntry = {
  id: string;
  session_id: string;
  conversation_id: string;
  run_id?: string;
  prompt: string;
  status: 'pending' | 'delivered' | 'cancelled';
  created_at: string;
  delivered_at?: string | null;
  error?: string | null;
};

type SteerEntry = {
  id: string;
  run_id: string;
  session_id: string;
  message: string;
  instruction_type: string;
  status: 'submitted' | 'accepted' | 'awaiting_checkpoint' | 'applied' | 'rejected' | 'superseded';
  created_at: string;
  applied_at?: string | null;
  applied: boolean;
};

type ModelInfo = {
  id: string;
  name: string;
  display_name?: string;
  provider: string;
  provider_group?: string;
  logo?: string;
  pricing: string;
  pricing_detail: string;
  tool_calling: boolean | 'unknown';
  context_window: number | null;
  available: boolean;
  availability?: string;
  availability_reason?: string;
  local: boolean;
  vision?: boolean;
  image_input?: boolean | 'unknown';
  reasoning?: boolean | 'unknown';
  structured_output?: boolean | 'unknown';
  configured?: boolean;
  is_active?: boolean;
};

type ExecutionState = {
  run_id: string | null;
  objective: string | null;
  objective_outcome: 'pending' | 'succeeded' | 'failed' | null;
  engagement: string | null;
  target: string | null;
  active_agent: string | null;
  lifecycle_status: 'idle' | 'running' | 'completed' | 'failed' | 'approval_pending' | 'stopped';
  mode: 'auto' | 'manual';
  events: ExecutionEvent[];
  current_tool: { id: string; name: string; status: 'running' | 'completed' | 'failed'; args: Record<string, any>; result: any; elapsed_ms: number | null; verified: boolean; error: string | null } | null;
  evidence_ref: string | null;
  objective_expanded: boolean;
  /** Set once the backend confirms the run stopped at a safe checkpoint. */
  stop_requested?: boolean;
};

export function ArkControl({ onImage, analyzing, onOpenTool, evidenceFile, imageReview, workspaceTitle, expanded = false, onToggleExpand, onEvent, browserAvailable = false, onOpenWorkspaceTool }: {
  onImage: (file: File) => Promise<AnalyzeResponse | undefined>;
  analyzing: boolean;
  evidenceFile: File | null;
  imageReview?: ImageReview;
  workspaceTitle: string;
  onOpenTool: (tool: ToolTabId) => void;
  expanded?: boolean;
  onToggleExpand?: () => void;
  /** Emit investigation lifecycle events (used for notifications + tab status). */
  onEvent?: (ev: Record<string, any>) => void;
  /** Whether the managed browser runtime is reachable (gates the Browser tool). */
  browserAvailable?: boolean;
  /** Open a tool that presents in the central workspace (e.g. Browser). */
  onOpenWorkspaceTool?: (id: OperationalToolId) => void;
}) {
  const inv = useInvestigation();
  const invStore = useInvestigationStore();
  const caseId = inv.activeCase?.id;
  // --- Investigation-keyed conversation state -----------------------------
  // The conversation, execution timeline, queue and inspector belong to the
  // investigation, not to the ArkControl instance (which is mounted once and
  // never remounted per tab). Switching tabs therefore swaps these slices
  // without unmounting, and a run in Investigation A keeps writing to A even
  // while Investigation B is displayed.
  const [draft, setDraft] = useInvestigationSlice<string>('draft', () => '');
  const [attachment, setAttachment] = useInvestigationSlice<{ file: File; url: string } | undefined>('attachment', () => undefined);
  const [messages, setMessages] = useInvestigationSlice<Message[]>('messages', () => []);
  const [busy, setBusy] = useInvestigationSlice<boolean>('busy', () => false);
  const [notice, setNotice] = useInvestigationSlice<string>('notice', () => '');
  // One unified conversation is the primary execution surface. The operational
  // inspector is a dismissible overlay over it — never a second permanent view.
  const [inspectorTool, setInspectorTool] = useInvestigationSlice<OperationalToolId | null>('inspectorTool', () => null);
  const [toolsMenuOpen, setToolsMenuOpen] = useState(false);
  const toolsMenuRef = useRef<HTMLDivElement>(null);
  const toolsTriggerRef = useRef<HTMLButtonElement>(null);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [execution, setExecution] = useInvestigationSlice<ExecutionState>('execution', () => ({
    run_id: null,
    objective: null,
    objective_outcome: null,
    engagement: null,
    target: null,
    active_agent: null,
    lifecycle_status: 'idle',
    mode: 'auto',
    events: [],
    current_tool: null,
    evidence_ref: null,
    objective_expanded: false,
  }));
  const [queue, setQueue] = useInvestigationSlice<QueueEntry[]>('queue', () => []);
  const [steerings, setSteerings] = useInvestigationSlice<SteerEntry[]>('steerings', () => []);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [modelsLoaded, setModelsLoaded] = useState(false);
  const [selectedModel, setSelectedModel] = useState<string | null>(null);
  // Administrator default, used to label the picker when the user has no
  // explicit preference (the effective model is still the admin default).
  const [adminDefaultModel, setAdminDefaultModel] = useState<string | null>(null);
  const [modelSearch, setModelSearch] = useState('');
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const modelPopover = useRef<HTMLDivElement>(null);
  const modelTrigger = useRef<HTMLButtonElement>(null);
  const [steeringText, setSteeringText] = useState('');
  const [steeringPending, setSteeringPending] = useState(false);
  const [steerOpen, setSteerOpen] = useState(false);
  const [queueLoaded, setQueueLoaded] = useState(false);
  // Set once the backend confirms the run stopped at a safe checkpoint; cleared
  // when a new run starts. Distinguishes "stop requested" from "stopped".
  const [stopping, setStopping] = useState(false);

  const reviewId = imageReview?.id;
  useEffect(() => {
    if (reviewId !== undefined) setReviewOpen(true);
  }, [reviewId]);

  // A plan awaiting approval surfaces the Plan inspector — the operator still
  // approves from the conversation; the inspector only shows the detail.
  useEffect(() => {
    if (inv.session?.status === 'proposed') setInspectorTool('plan');
  }, [inv.session?.plan.revision_id, inv.session?.status]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.caiModels(),
      api.caiGetPreference().catch(() => ({ selected_model: null, model_pins: {} as Record<string, string> })),
    ]).then(([data, pref]) => {
      if (cancelled) return;
      const providers = data.providers || {};
      const allModels: ModelInfo[] = [];
      Object.values(providers).forEach((prov: any) => {
        if (Array.isArray(prov)) prov.forEach((m: any) => allModels.push({ ...m, name: m.display_name || m.name || m.id }));
      });
      setModels(allModels);
      setModelsLoaded(true);
      // The user's saved preference is authoritative for them; the admin
      // default is only the fallback when they have not chosen (Phase 2).
      setAdminDefaultModel(data.active_model || null);
      setSelectedModel(pref.selected_model || data.selected_model || data.active_model || null);
    }).catch(() => {
      if (!cancelled) setModelsLoaded(true);
    });
    return () => { cancelled = true; };
  }, []);

  // Dismiss the picker on outside click / Escape, and keep it in the viewport.
  useEffect(() => {
    if (!modelMenuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (modelPopover.current?.contains(e.target as Node)) return;
      if (modelTrigger.current?.contains(e.target as Node)) return;
      setModelMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setModelMenuOpen(false); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    const node = modelPopover.current;
    if (node) {
      const rect = node.getBoundingClientRect();
      if (rect.left < 8) node.style.left = '0';
      else if (rect.right > window.innerWidth - 8) node.style.right = '0';
      if (rect.top < 8) { node.style.bottom = 'auto'; node.style.top = 'calc(100% + 6px)'; }
    }
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [modelMenuOpen]);

  // Dismiss the operational tools menu on outside click / Escape, and keep it
  // inside the viewport (repositions if it would overflow either edge).
  useEffect(() => {
    if (!toolsMenuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (toolsMenuRef.current?.contains(e.target as Node)) return;
      if (toolsTriggerRef.current?.contains(e.target as Node)) return;
      setToolsMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setToolsMenuOpen(false); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    const node = toolsMenuRef.current;
    if (node) {
      const rect = node.getBoundingClientRect();
      if (rect.right > window.innerWidth - 8) node.style.right = '0';
      else if (rect.left < 8) node.style.left = '0';
    }
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [toolsMenuOpen]);

  // Close the inspector when the active investigation changes so records from
  // one case can never bleed into another via stale component state.
  useEffect(() => { setInspectorTool(null); }, [caseId]);

  const openInspector = (id: OperationalToolId) => {
    setToolsMenuOpen(false);
    // Workspace tools take over the central application area — they are never
    // squeezed into the dock. Hand off to the workbench that owns that region.
    if (isWorkspaceTool(id)) {
      onOpenWorkspaceTool?.(id);
      return;
    }
    // Console-backed tools share the existing BottomPanel tab state so the
    // inspector reads the same store as the docked console — no duplicate data.
    if (isConsoleTool(id)) inv.setBottomTab(id);
    setInspectorTool(id);
  };

  const chooseModel = async (id: string) => {
    setSelectedModel(id);
    setModelMenuOpen(false);
    setModelSearch('');
    try {
      await api.caiSetPreference(id);
    } catch {
      // Selection is still used for the next run; persistence retries next time.
    }
  };

  const [approving, setApproving] = useState(false);
  const feed = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const request = useRef<AbortController | null>(null);
  // Backend CAI session handle — per investigation. The in-flight `send` closure
  // captures the investigation that was active when the run started, so its
  // writes keep landing on that investigation even after a tab switch.
  const activeInvId = invStore.activeId ?? '__none__';
  const sessionsRef = useRef<Record<string, { id: string; caseId?: string; domain: string } | undefined>>({});
  const session = useMemo(() => ({
    get current() { return sessionsRef.current[activeInvId]; },
    set current(value: { id: string; caseId?: string; domain: string } | undefined) {
      sessionsRef.current[activeInvId] = value;
    },
  }), [activeInvId]);
  const urls = useRef(new Set<string>());

  // Restore an investigation's transcript from the backend encrypted session
  // store the first time it is opened with no live conversation. Content lives
  // in the backend (Zero-Retention honoured); nothing is persisted locally.
  const restoredSessions = useRef(new Set<string>());
  useEffect(() => {
    const sid = invStore.metaFor(activeInvId)?.sessionId;
    if (!sid || restoredSessions.current.has(sid)) return;
    restoredSessions.current.add(sid);
    if (messages.length > 0) return;
    let cancelled = false;
    api.caiSession(sid).then(res => {
      if (cancelled || !res?.transcript_available || !res.messages?.length) return;
      setMessages(res.messages
        .filter(m => m.role === 'user' || m.role === 'assistant')
        .map(m => ({ user: m.role === 'user', text: m.content })));
    }).catch(() => { /* transcript unavailable — start clean */ });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeInvId]);

  useEffect(() => () => {
    request.current?.abort();
    urls.current.forEach(url => URL.revokeObjectURL(url));
  }, []);

  useEffect(() => {
    if (feed.current) feed.current.scrollTop = feed.current.scrollHeight;
  }, [messages, inspectorTool, execution.events]);

  const release = (url: string) => {
    URL.revokeObjectURL(url);
    urls.current.delete(url);
  };

  function extractTarget(args: Record<string, any> | undefined): string | null {
    if (!args) return null;
    for (const key of ['url', 'host', 'target', 'address', 'ip', 'domain', 'hostname', 'base_url']) {
      const v = args[key];
      if (typeof v === 'string' && v) return v;
    }
    return null;
  }

  async function copyRunId() {
    if (!execution.run_id) return;
    try {
      await navigator.clipboard.writeText(execution.run_id);
    } catch { /* clipboard unavailable */ }
  }

  const enqueue = async (prompt: string) => {
    if (!session.current?.id) return;
    try {
      const res = await api.caiEnqueue({
        session_id: session.current.id,
        prompt,
        run_id: execution.run_id ?? undefined,
      });
      setDraft('');
      setNotice(`Queued (position ${res?.queue_position ?? 1}) — runs after the current objective.`);
      void loadQueue();
    } catch (err) {
      setNotice(err instanceof Error ? err.message : 'Queue failed');
    }
  };

  const send = async (raw: string, withAttachment = false) => {
    const text = raw.trim();
    const image = withAttachment ? attachment : undefined;
    // If a run is already active, the composer's job is to queue the message for
    // execution after the current run completes — not to start a second run.
    if (request.current && text && !image) {
      void enqueue(text);
      return;
    }
    if (request.current || (image && analyzing) || (!text && !image)) return;
    setInspectorTool(null);
    setDraft('');
    setNotice('');
    setStopping(false);
    setExecution(prev => ({
      run_id: null,
      objective: text,
      objective_outcome: null,
      engagement: null,
      target: null,
      active_agent: null,
      lifecycle_status: 'idle',
      // Mode is backend-owned; carry the operator's current selection forward.
      mode: prev.mode,
      events: [],
      current_tool: null,
      evidence_ref: null,
      objective_expanded: false,
      stop_requested: false,
    }));
    if (text === '/clear') {
      messages.forEach(message => { if (message.image) release(message.image); });
      setMessages([]);
      session.current = undefined;
      return;
    }

    const controller = new AbortController();
    request.current = controller;
    setBusy(true);
    if (image) setAttachment(undefined);
    const index = messages.length + 1;
    setMessages(prev => [...prev, { user: true, text: text || image!.file.name, image: image?.url }, { text: '' }]);
    const update = (change: (message: Message) => Message) => {
      if (!controller.signal.aborted) {
        setMessages(prev => prev.map((message, i) => i === index ? change(message) : message));
      }
    };
    const reply = (answer: string) => update(message => ({ ...message, text: answer }));
    try {
      const analysis = image ? await onImage(image.file) : inv.result;
      if (image && !analysis) { reply('Image analysis failed.'); return; }
      const activeCase = image && analysis ? caseIdFromRequest(analysis.request_id) : caseId;
      if (/^(?:@agents|\/agent|(?:agants?|agents?)\s+lists?)$/i.test(text)) reply(noRoster);
      else if (text === '/help') reply(commands.join(' · '));
      else if (text === '/case') reply(inv.activeCase ? `${inv.activeCase.title} · ${caseId}` : 'No active case.');
      else if (text === '/investigate') {
        const file = image?.file ?? evidenceFile;
        if (!file) reply('Attach the original image to start an investigation.');
        else {
          await inv.startInvestigation(file, {
            goal: 'verify_location_credibility',
            subject: file.name,
            domain: 'image',
            claims_to_verify: [{ field: 'gps.latitude' }],
          });
          reply('See Plan in the operational inspector.');
          inv.setBottomTab('plan');
          setInspectorTool('plan');
        }
      } else if (text === '/forensics' || text === '/osint') {
        if (!inv.result && !image) reply('Upload image evidence to open this workspace.');
        else {
          onOpenTool(text === '/forensics' ? 'fileforensics' : 'discovery');
          reply('Opened the investigation workspace.');
        }
      } else if (text === '/tools') {
        const result = await api.caiCommand('/tools');
        const tools = Array.isArray(result.tools) ? result.tools.map((tool: { name?: string; id?: string } | string) =>
          typeof tool === 'string' ? tool : tool.name || tool.id).filter(Boolean) : Object.keys(result.tools ?? {});
        update(message => ({ ...message, text: tools.length ? 'Available tools' : 'No tools returned.', tools }));
      } else if (!text) reply('Image submitted to the evidence pipeline.');
      else {
        await api.caiTerminalStream(text, {
          model: selectedModel || undefined,
          sessionId: !image && session.current?.caseId === activeCase && session.current?.domain === inv.domain ? session.current?.id : undefined,
          caseId: activeCase,
          caseContext: {
            workspace_context: {
              domain: image ? 'image' : inv.domain,
              view: image ? 'Investigation' : workspaceTitle,
              findings: image ? [] : inv.findings.slice(-8).map(finding => ({
                type: finding.type, severity: finding.severity, message: finding.message.slice(0, 200),
              })),
              activity: image ? [] : inv.auditTrail.slice(-8).map(event => ({
                action: event.action.slice(0, 100), detail: event.detail.slice(0, 160),
              })),
              analysis_state: image ? 'complete' : analyzing ? 'running' : inv.activeRun ? 'complete' : 'idle',
            },
            filename: image?.file.name ?? inv.activeEvidence?.filename,
            image_sha256: analysis?.image_sha256 ?? inv.activeEvidence?.sha256,
            source: analysis?.source ?? inv.activeRun?.source,
            consensus: analysis?.consensus,
            coordinates: analysis?.coordinates,
            consistency_findings: analysis?.consistency_findings?.slice(0, 8),
            contradictions: analysis?.contradictions?.slice(0, 8),
          },
          executionMode: execution.mode,
        }, event => {
          if (event.event === 'session') {
            session.current = { id: event.session_id, caseId: activeCase, domain: image ? 'image' : inv.domain };
            onEvent?.(event);
          }

          if (event.event === 'run_created') {
            setExecution(prev => ({ ...prev, run_id: event.run_id ?? null, lifecycle_status: 'running' }));
            onEvent?.(event);
            return;
          }
          if (event.event === 'execution_mode') {
            // The backend owns the mode; reflect what it actually reports.
            if (event.mode === 'auto' || event.mode === 'manual') {
              setExecution(prev => ({ ...prev, mode: event.mode }));
            }
            setExecution(prev => ({ ...prev, events: [...prev.events, event] }));
            return;
          }
          if (event.event === 'steer_ack') {
            setSteerings(prev => prev.map(s => s.id === event.steering_id
              ? { ...s, status: event.status, applied: event.status === 'accepted' } : s));
            setExecution(prev => ({ ...prev, events: [...prev.events, event] }));
            return;
          }
          if (event.event === 'run_cancelled') {
            setStopping(false);
            setExecution(prev => ({
              ...prev,
              lifecycle_status: 'stopped',
              objective_outcome: 'failed',
              stop_requested: true,
              events: [...prev.events, event],
            }));
            onEvent?.(event);
            return;
          }
          if (event.event === 'agent_selected') {
            setExecution(prev => ({ ...prev, active_agent: event.role ?? null, lifecycle_status: 'running' }));
            setExecution(prev => ({ ...prev, events: [...prev.events, event] }));
            return;
          }
          if (event.event === 'scope_checked') {
            const tgt = extractTarget(event.args);
            if (tgt) setExecution(prev => ({ ...prev, target: tgt }));
            setExecution(prev => ({ ...prev, events: [...prev.events, event] }));
            if (!event.allowed) {
              setExecution(prev => ({ ...prev, lifecycle_status: 'failed', objective_outcome: 'failed' }));
              onEvent?.(event);
            }
            return;
          }
          if (event.event === 'hitl') {
            setExecution(prev => ({ ...prev, lifecycle_status: 'approval_pending' }));
            const approval = { session: event.session_id, execution: event.execution_id, tool: event.tool };
            update(message => ({ ...message, approval }));
            onEvent?.(event);
            return;
          }
          if (event.event === 'tool_call') {
            setExecution(prev => ({
              ...prev,
              current_tool: {
                id: event.tool,
                name: toolDisplayName(event.tool),
                status: 'running',
                args: event.args ?? {},
                result: null,
                elapsed_ms: null,
                verified: false,
                error: null,
              },
            }));
            setExecution(prev => ({ ...prev, events: [...prev.events, event] }));
            return;
          }
          if (event.event === 'tool_started') {
            setExecution(prev => ({
              ...prev,
              current_tool: {
                id: event.tool,
                name: toolDisplayName(event.tool),
                status: 'running',
                args: event.args ?? {},
                result: null,
                elapsed_ms: null,
                verified: false,
                error: null,
              },
            }));
            setExecution(prev => ({ ...prev, events: [...prev.events, event] }));
            return;
          }
          if (event.event === 'tool') {
            const isError = typeof event.result === 'object' && event.result !== null && (event.result.status === 'error' || event.result.status === 'denied');
            const verified = event.verified === true;
            setExecution(prev => ({
              ...prev,
              current_tool: prev.current_tool && prev.current_tool.id === event.tool
                ? { ...prev.current_tool, status: isError ? 'failed' : 'completed', result: event.result, elapsed_ms: event.elapsed_ms ?? null, verified, error: isError ? String((event.result as any)?.error ?? 'failed') : null }
                : prev.current_tool,
            }));
            setExecution(prev => ({ ...prev, events: [...prev.events, event] }));
            if (!verified) {
              setExecution(prev => ({ ...prev, lifecycle_status: 'completed', objective_outcome: 'failed' }));
            }
            return;
          }
          if (event.event === 'result_verified') {
            setExecution(prev => ({
              ...prev,
              current_tool: prev.current_tool && prev.current_tool.id === event.tool
                ? { ...prev.current_tool, verified: event.verified === true }
                : prev.current_tool,
            }));
            return;
          }
          if (event.event === 'evidence_recorded') {
            setExecution(prev => ({ ...prev, evidence_ref: event.evidence_path ?? null }));
            return;
          }
          if (event.event === 'run_completed') {
            const toolSucceeded = execution.current_tool ? execution.current_tool.status === 'completed' && execution.current_tool.verified : false;
            setExecution(prev => ({ ...prev, lifecycle_status: 'completed', objective_outcome: toolSucceeded ? 'succeeded' : 'failed' }));
            onEvent?.(event);
            return;
          }
          if (event.event === 'run_failed') {
            setExecution(prev => ({ ...prev, lifecycle_status: 'failed', objective_outcome: 'failed' }));
            onEvent?.(event);
            return;
          }

          if (event.event === 'token') update(message => ({ ...message, text: message.text + event.text }));
          if (['final', 'local_command'].includes(event.event) && event.text) reply(event.text);
          if (event.event === 'error') reply(event.message || 'ARK returned an error.');
          const tool = String(event.tool?.name ?? event.tool_name ?? event.name ?? event.tool ?? 'Tool');
          if (event.event === 'tool' || event.event === 'tool_call') {
            const label = event.result?.status === 'error' ? `${tool} · failed` : tool;
            update(message => ({
              ...message,
              tools: [...new Set([...(message.tools ?? []).filter(name => name !== tool), label])],
            }));
          }
          if (event.event === 'hitl' && session.current) {
            const approval = { session: event.session_id, execution: event.execution_id, tool };
            update(message => ({ ...message, approval }));
          }
        }, undefined, controller.signal);
        update(message => message.text || message.approval ? message : { ...message, text: 'ARK returned no response.' });
      }
    } catch (err) {
      reply(err instanceof Error ? err.message : 'ARK request failed.');
    } finally {
      request.current = null;
      setBusy(false);
    }
  };

  const approve = async (index: number, approval: NonNullable<Message['approval']>, allow: boolean) => {
    setApproving(true);
    try {
      const response = await api.caiTerminalApprove(approval.session, allow, false, approval.execution);
      if (!response.ok) throw new Error('Approval is no longer pending.');
      setMessages(prev => prev.map((message, i) => i === index && message.approval === approval ? { ...message, approval: undefined } : message));
      setExecution(prev => ({ ...prev, lifecycle_status: allow ? 'running' : 'failed', objective_outcome: allow ? null : 'failed' }));
    } catch (err) {
      setNotice(err instanceof Error ? err.message : 'Could not submit decision.');
    } finally {
      setApproving(false);
    }
  };

  const loadQueue = async () => {
    if (!session.current?.id) return;
    try {
      const data = await api.caiQueue(session.current.id);
      setQueue(data.queue || []);
    } catch {
      setQueue([]);
    }
  };

  // Load the pending queue when a run starts so the composer can surface the
  // Queue control; reset when idle.
  useEffect(() => {
    if (execution.lifecycle_status === 'running') {
      if (!queueLoaded) setQueueLoaded(true);
      void loadQueue();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [execution.run_id, execution.lifecycle_status]);

  // Execution mode is a composer-level directive. Advisory (Manual) requires
  // operator confirmation at the checkpoints; Autonomous (Automatic) lets the
  // agent sequence permitted tools inside the active scope. Neither mode can
  // bypass scope validation, approvals or the policy guard.
  const toggleExecutionMode = async () => {
    const next = execution.mode === 'auto' ? 'manual' : 'auto';
    setExecution(prev => ({ ...prev, mode: next }));
    // Persist the mode server-side so it is enforced by the orchestrator on the
    // next dispatch, and applies mid-run when a run is active.
    try {
      const res = await api.caiMode({
        session_id: session.current?.id || '',
        run_id: execution.run_id ?? undefined,
        mode: next,
      });
      if (res?.ok === false) {
        setExecution(prev => ({ ...prev, mode: next === 'auto' ? 'manual' : 'auto' }));
        setNotice(res.error || 'Could not set execution mode.');
      }
    } catch (err) {
      setExecution(prev => ({ ...prev, mode: next === 'auto' ? 'manual' : 'auto' }));
      setNotice(err instanceof Error ? err.message : 'Could not set execution mode.');
    }
  };

  const cancelQueueItem = async (queueId: string) => {
    try {
      await api.caiStop({ session_id: session.current?.id || '', stop_type: 'cancel_pending' });
      setQueue(prev => prev.map(q => q.id === queueId ? { ...q, status: 'cancelled', error: 'cancelled by operator' } : q));
    } catch {
      // ignore
    }
  };

  const cancelQueue = async () => {
    if (!session.current?.id) return;
    try {
      await api.caiStop({ session_id: session.current.id, stop_type: 'cancel_pending' });
      setQueue(prev => prev.map(q => q.status === 'pending' ? { ...q, status: 'cancelled', error: 'cancelled by operator' } : q));
    } catch {
      // ignore
    }
  };

  const sendSteer = async () => {
    if (!steeringText.trim() || !session.current?.id) return;
    setSteeringPending(true);
    try {
      const res = await api.caiSteer({
        session_id: session.current.id,
        run_id: execution.run_id ?? undefined,
        message: steeringText,
        instruction_type: 'steer',
      });
      if (res?.ok === false) {
        setNotice(res.error || 'No active run to steer.');
        setSteeringPending(false);
        return;
      }
      // Optimistically show the instruction as submitted; the orchestrator's
      // steer_ack event replaces this with accepted/deferred/rejected.
      setSteerings(prev => [...prev, {
        id: res?.steering_id ?? `steer-${Date.now()}`,
        run_id: execution.run_id ?? '',
        session_id: session.current!.id,
        message: steeringText,
        instruction_type: 'steer',
        status: 'awaiting_checkpoint',
        created_at: new Date().toISOString(),
        applied: false,
      }]);
      setSteeringText('');
      setSteeringPending(false);
      loadQueue();
    } catch (err) {
      setNotice(err instanceof Error ? err.message : 'Steer failed');
      setSteeringPending(false);
    }
  };

  const stopRun = async () => {
    if (!session.current?.id) return;
    setStopping(true);
    try {
      const res = await api.caiStop({
        session_id: session.current.id,
        run_id: execution.run_id ?? undefined,
        stop_type: 'stop',
      });
      // The backend honours the stop at its next safe checkpoint and streams
      // run_cancelled; until then the run is "stopping", never "stopped".
      if (res?.stop_requested === false) {
        setNotice('No active run to stop.');
        setStopping(false);
      } else {
        setExecution(prev => ({ ...prev, stop_requested: true }));
      }
    } catch (err) {
      setStopping(false);
      setNotice(err instanceof Error ? err.message : 'Stop failed');
    }
  };

  const dictation = useDictation(transcript => {
    setDraft(prev => `${prev.trimEnd()} ${transcript}`);
    input.current?.focus();
  }, setNotice);
  const recording = dictation.state === 'recording';

  const menu = /^\/\w*$/.test(draft) ? commands.filter(command => command.startsWith(draft))
    : /^@[\w ]*$/.test(draft) ? roster.filter(role => role.toLowerCase().startsWith(draft.slice(1).toLowerCase())) : [];

  const statusLabels: Record<string, string> = {
    idle: 'Idle',
    running: 'Executing',
    completed: 'Completed',
    failed: 'Failed',
    approval_pending: 'Awaiting Approval',
  };

  const outcomeLabels: Record<string, string> = {
    pending: 'Pending',
    succeeded: 'Succeeded',
    failed: 'Failed',
  };

  const providerLabels: Record<string, string> = {
    openrouter: 'OpenRouter', openai: 'OpenAI', anthropic: 'Anthropic',
    gemini: 'Google Gemini', huggingface: 'Hugging Face', ollama: 'Ollama (Local)',
    ark: 'ARK Managed',
  };
  const query = modelSearch.trim().toLowerCase();
  const filteredModels = query
    ? models.filter(m => m.name.toLowerCase().includes(query) || m.id.toLowerCase().includes(query))
    : models;
  const providerGroups: Record<string, ModelInfo[]> = {};
  filteredModels.forEach(m => {
    const group = providerLabels[m.provider] || m.provider;
    if (!providerGroups[group]) providerGroups[group] = [];
    providerGroups[group].push(m);
  });

  // When the user has no explicit preference, the admin default is what runs —
  // reflect it in the trigger label so the picker never reads "Select model"
  // while a model is actually in effect.
  const effectiveModelId = selectedModel || adminDefaultModel;

  return (
    <aside className={`ark-control ${expanded ? 'ark-control-expanded' : ''}`} aria-label="ARK Control" data-expanded={expanded || undefined}>
      <header className="ark-dock-header">
        <div className="ark-dock-identity">
          <small className="ark-dock-mode">
            <span className={`ark-dock-mode-dot ${execution.lifecycle_status !== 'idle' ? 'ark-dock-mode-dot-live' : ''}`} aria-hidden="true" />
            {execution.lifecycle_status === 'running' ? 'Executing'
              : execution.lifecycle_status === 'approval_pending' ? 'Awaiting approval'
              : execution.lifecycle_status === 'stopped' ? 'Stopped'
              : execution.lifecycle_status === 'completed' ? 'Completed'
              : execution.lifecycle_status === 'failed' ? 'Failed'
              : 'Advisory'}
          </small>
        </div>
        <div className="ark-dock-actions">
          <div className="ark-tools-menu-wrap">
            <button
              ref={toolsTriggerRef}
              type="button"
              className="ark-dock-tool-btn"
              aria-haspopup="menu"
              aria-expanded={toolsMenuOpen}
              aria-label="Operational tools"
              title="Operational tools"
              onClick={() => setToolsMenuOpen(v => !v)}
            >
              <Plus size={18} />
            </button>
            {toolsMenuOpen && (
              <div className="ark-tools-menu" ref={toolsMenuRef} role="menu" aria-label="Operational tools">
                {OPERATIONAL_TOOLS.map(tool => {
                  const Icon = tool.icon;
                  const disabled = Boolean(tool.requiresBrowser) && !browserAvailable;
                  return (
                    <button
                      key={tool.id}
                      type="button"
                      role="menuitem"
                      className={`ark-tools-item ${inspectorTool === tool.id ? 'ark-tools-item-active' : ''}`}
                      disabled={disabled}
                      title={disabled ? 'Managed browser runtime unavailable' : tool.description}
                      onClick={() => !disabled && openInspector(tool.id)}
                    >
                      <Icon size={15} className="ark-tools-item-icon" />
                      <span className="ark-tools-item-text">
                        <span className="ark-tools-item-label">{tool.label}</span>
                        <span className="ark-tools-item-desc">{disabled ? 'Unavailable' : tool.description}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
          {onToggleExpand && (
            <button type="button" className="ark-dock-expand" aria-pressed={expanded}
              aria-label={expanded ? 'Restore ARK to docked panel' : 'Expand ARK to workspace'}
              title={expanded ? 'Restore panel (Esc)' : 'Expand to workspace' }
              onClick={onToggleExpand}>
              {expanded ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
            </button>
          )}
        </div>
      </header>

      <div className="ark-conversation-region">
        <div className="ark-output-scroll ark-conversation" ref={feed} role="log" aria-label="Investigation conversation">
        {(execution.run_id || execution.lifecycle_status !== 'idle') && (
          <details className="ark-run-details">
            <summary>Execution details · {execution.lifecycle_status === 'idle' ? 'Ready' : execution.lifecycle_status.replace(/_/g, ' ')}</summary>
            <ExecutionActivity execution={execution} />
            {execution.lifecycle_status !== 'idle' && execution.lifecycle_status !== 'running'
              && execution.lifecycle_status !== 'approval_pending' && execution.events.length > 0 && (
              <InvestigationReport summary={summarizeRun(execution)} onCopyRunId={() => void copyRunId()} />
            )}
          </details>
        )}

        {reviewOpen && imageReview && (
          <section className="ark-review" aria-label="Image advisory review">
            <div className="ark-review-head">
              <span>Image advisory review</span>
              <button type="button" className="ark-review-close" aria-label="Close review" title="Close review" onClick={() => setReviewOpen(false)}>
                <X size={14} />
              </button>
            </div>
            <div className="ark-review-heading">
              <span>IMAGE ADVISORY REVIEW</span>
              <h2>{imageReview.filename}</h2>
              <p>ARK Core evidence summary · ARK interpretation</p>
            </div>
            <div className="ark-review-card">
              <h3>Activity</h3>
              <ol>{imageReview.steps.map((step, index) => <li key={index}>{step}</li>)}</ol>
              {imageReview.status === 'waiting' && <p role="status">Waiting for ARK Core evidence…</p>}
              {imageReview.status === 'reviewing' && <p role="status">Advisory review in progress…</p>}
              {imageReview.status === 'complete' && <p role="status">Advisory report ready</p>}
              {imageReview.status === 'skipped' && <p role="status">Automatic AI review skipped in Zero-Retention Mode.</p>}
              {imageReview.error && <p role="status">{imageReview.error}</p>}
              {imageReview.retry && <button type="button" onClick={imageReview.retry}>Retry AI report</button>}
            </div>
            {imageReview.report && <div className="ark-review-card">
              <h3>{imageReview.status === 'complete' ? 'Advisory report' : 'Draft advisory report'}</h3>
              <div className="ark-review-report">{imageReview.report}</div>
            </div>}
          </section>
        )}

        <>
            {!messages.length && <div className="ark-idle"><img className="ark-idle-logo" src="/branding/ark/ark-emblem-256.png" alt="ARK emblem" width={112} height={112} /><span className="ark-idle-sub">Cybersecurity Super Intelligence</span><p>Ask a question, attach evidence, or run a command to begin an investigation.</p></div>}
            {messages.map((message, i) => <article key={i} className={message.user ? 'ark-message ark-user' : 'ark-message'}>
              {message.image && <img src={message.image} alt="Attached evidence" />}
              {message.text || (busy && i === messages.length - 1 && !message.approval && !message.tools?.length ? 'Working…' : '')}
              {message.tools?.map(tool => <span key={tool} className="ark-tool-chip">{tool}</span>)}
              {message.approval && <div>Approve {message.approval.tool}? <button disabled={approving} onClick={() => void approve(i, message.approval!, true)}>Approve</button> <button disabled={approving} onClick={() => void approve(i, message.approval!, false)}>Deny</button></div>}
            </article>)}
        </>
        </div>
      </div>

      {inspectorTool && (
        <section className="ark-inspector" aria-label="ARK operational inspector">
          <header className="ark-inspector-head">
            <span className="ark-inspector-title">
              {(() => { const Icon = operationalTool(inspectorTool).icon; return <Icon size={14} />; })()}
              {operationalTool(inspectorTool).label}
            </span>
            <button type="button" className="ark-inspector-close" onClick={() => setInspectorTool(null)} title="Close inspector" aria-label="Close inspector">
              <X size={14} />
            </button>
          </header>
          <div className="ark-inspector-body">
            <BottomPanel inspector collapsed={false} onToggle={() => {}} result={inv.result} />
          </div>
        </section>
      )}

      <form className="ark-composer" onSubmit={event => { event.preventDefault(); void send(draft, true); }}>
        {!!menu.length && (
          <div className="ark-menu" aria-label={draft.startsWith('@') ? 'Agent roles' : 'Commands'}>
            {menu.map(item => (
              <button key={item} type="button" onClick={() => {
                if (item.startsWith('/')) void send(item);
                else { setDraft(`@${item} `); input.current?.focus(); }
              }}>{item}</button>
            ))}
          </div>
        )}
        <div className="ark-input-box">
          {attachment && (
            <div className="ark-attachment">
              <img src={attachment.url} alt="Evidence preview" />
              <span>{attachment.file.name}</span>
              <button type="button" aria-label="Remove attachment" onClick={() => { release(attachment.url); setAttachment(undefined); }}>
                <X size={16} />
              </button>
            </div>
          )}
          <textarea
            ref={input}
            value={draft}
            rows={2}
            aria-label="Message ARK"
            placeholder="Ask ARK anything, or describe an investigation…"
            onChange={e => setDraft(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                void send(draft, true);
              }
              if (e.key === 'Escape' && menu.length) setDraft('');
            }}
          />
          <div className="ark-toolbar">
            <input
              ref={picker}
              hidden
              type="file"
              accept="image/jpeg,image/png"
              onChange={event => {
                const file = event.target.files?.[0];
                (event.target as HTMLInputElement).value = '';
                if (!file) return;
                if (!['image/jpeg', 'image/png'].includes(file.type)) {
                  setNotice('Choose a JPEG or PNG image.');
                  return;
                }
                if (attachment) release(attachment.url);
                const url = URL.createObjectURL(file);
                urls.current.add(url);
                setAttachment({ file, url });
                setNotice('');
              }}
            />
            <button type="button" aria-label="Attach image" onClick={() => picker.current?.click()}>
              <Plus size={18} />
            </button>
            <button
              type="button"
              aria-label={recording ? 'Stop recording' : 'Start voice transcription'}
              title={dictation.backendAvailable ? 'Dictation via the configured OpenAI transcription provider' : 'Browser dictation'}
              aria-pressed={recording}
              disabled={dictation.state === 'starting' || dictation.state === 'transcribing'}
              onClick={() => void dictation.toggle()}
            >
              {recording ? <Square size={16} /> : <Mic size={17} />}
            </button>
            {dictation.state === 'starting' && <small role="status">Opening microphone…</small>}
            {dictation.state === 'transcribing' && <small role="status">Transcribing…</small>}
            {recording && (
              <span className="ark-wave" role="status" aria-label="Recording">
                {[1, 2, 3, 4, 5].map((i) => (
                  <i key={i} style={{ animationDelay: `${i * 90}ms` }} />
                ))}
              </span>
            )}
            {modelsLoaded && (
              <div className="ark-model-selector-compact">
                <button
                  ref={modelTrigger}
                  type="button"
                  className="ark-model-pill"
                  aria-haspopup="listbox"
                  aria-expanded={modelMenuOpen}
                  onClick={() => setModelMenuOpen(v => !v)}
                  title={effectiveModelId ? `${models.find(m => m.id === effectiveModelId)?.name || effectiveModelId} · ${effectiveModelId}` : 'Select model'}
                >
                  <span className="ark-model-name">{effectiveModelId ? (models.find(m => m.id === effectiveModelId)?.name || effectiveModelId.split('/').pop() || effectiveModelId).replace(/[-_]/g, ' ').replace(/:free$/i, '').replace(/\b\w/g, c => c.toUpperCase()) : 'Choose model'}</span>
                  <ChevronDown size={14} />
                </button>
                {modelMenuOpen && (
                  <div className="ark-model-popover" ref={modelPopover} role="listbox" aria-label="Select model">
                    <input
                      type="text"
                      className="ark-model-search"
                      placeholder="Search models…"
                      value={modelSearch}
                      autoFocus
                      onChange={e => setModelSearch(e.target.value)}
                    />
                    <div className="ark-model-list">
                      {Object.entries(providerGroups).map(([provider, groupModels]) => (
                        <div key={provider} className="ark-model-group">
                          <div className="ark-model-group-label">{provider}</div>
                          {groupModels.map(m => {
                            const unknown = m.tool_calling === 'unknown';
                            return (
                              <button
                                key={m.id}
                                type="button"
                                role="option"
                                aria-selected={m.id === effectiveModelId}
                                className={`ark-model-item ${m.id === effectiveModelId ? 'selected' : ''} ${!m.available ? 'disabled' : ''}`}
                                disabled={!m.available}
                                title={m.availability_reason || m.id}
                                onClick={() => m.available && chooseModel(m.id)}
                              >
                                <span className="ark-model-item-name">{m.name}</span>
                                <span className="ark-model-meta">
                                  {unknown ? null : m.tool_calling ? <span className="ark-model-badge" title="Tool calling">⚙</span> : null}
                                  {m.image_input === true && <span className="ark-model-badge" title="Vision">◉</span>}
                                  {m.pricing === 'free' && <span className="ark-model-badge free" title="Free">free</span>}
                                  {m.local && <span className="ark-model-badge local" title="Local">local</span>}
                                </span>
                                <span className={`ark-model-status ${m.available ? 'available' : 'unavailable'}`}>
                                  {m.available ? (m.id === effectiveModelId ? 'Selected' : 'Available') : 'Unavailable'}
                                </span>
                              </button>
                            );
                          })}
                        </div>
                      ))}
                      {filteredModels.length === 0 && (
                        <div className="ark-model-empty">No models match “{modelSearch}”</div>
                      )}
                    </div>
                    {selectedModel && (
                      <div className="ark-model-footer">
                        <button type="button" className="ark-model-clear" onClick={() => { setSelectedModel(null); setModelMenuOpen(false); setModelSearch(''); api.caiSetPreference(null).catch(() => {}); }}>
                          Use administrator default
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
            {execution.lifecycle_status === 'running' && queue.some(q => q.status === 'pending') && (
              <button type="button" className="ark-queue-pill" title="Cancel queued messages" onClick={cancelQueue}>
                <Trash2 size={13} /> Queue {queue.filter(q => q.status === 'pending').length}
              </button>
            )}
            {execution.lifecycle_status === 'running' && (
              <button
                type="button"
                className="ark-steer-pill"
                aria-pressed={steerOpen}
                title="Steer the active run"
                onClick={() => setSteerOpen(v => !v)}
              >
                <Rocket size={13} /> Steer
              </button>
            )}
            <button
              type="button"
              className="ark-mode-toggle"
              aria-pressed={execution.mode === 'auto'}
              title={execution.mode === 'auto'
                ? 'Automatic — ARK sequences permitted tools within the active scope'
                : 'Manual — operator confirms at each execution checkpoint'}
              onClick={toggleExecutionMode}
            >
              {execution.mode === 'auto' ? 'Auto' : 'Manual'}
            </button>
            {busy || execution.lifecycle_status === 'running' ? (
              <button
                className="ark-stop"
                type="button"
                aria-label="Stop execution"
                title="Stop the active run at the next safe checkpoint"
                onClick={() => void stopRun()}
                disabled={stopping}
              >
                <Square size={15} />
              </button>
            ) : (
              <button className="ark-send" type="submit" aria-label="Send" disabled={Boolean(attachment && analyzing) || (!draft.trim() && !attachment)}>
                <Send size={16} />
              </button>
            )}
          </div>
          {steerOpen && execution.lifecycle_status === 'running' && (
            <div className="ark-steer-inline">
              <textarea
                value={steeringText}
                rows={2}
                placeholder="Steer the active run (e.g. 'focus on port 443', 'pivot to web enumeration')…"
                onChange={e => setSteeringText(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    void sendSteer();
                  }
                }}
              />
              <button type="button" className="ark-steer-send" onClick={sendSteer} disabled={steeringPending || !steeringText.trim() || !execution.run_id}>
                {steeringPending ? 'Sending…' : 'Send steer'}
              </button>
            </div>
          )}
          {steerings.length > 0 && execution.lifecycle_status === 'running' && (
            <div className="ark-steer-list">
              {steerings.slice(-3).map(s => (
                <div key={s.id} className="ark-steer-item">
                  <span className="ark-steer-msg">{s.message}</span>
                  <span className={`ark-steer-status ${s.status}`}>{s.status}</span>
                </div>
              ))}
            </div>
          )}
          {notice && <small role="status">{notice}</small>}
        </div>
      </form>
    </aside>
  );
}