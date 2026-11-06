import { useEffect, useRef, useState } from 'react';
import { Activity, ScanLine, MessageSquare, Mic, Plus, Send, Square, X, Play, StopCircle, CheckCircle, AlertCircle, RefreshCw, Copy, ChevronDown, ChevronUp, Trash2, Rocket } from 'lucide-react';
import type { AnalyzeResponse } from '../../types';
import { api } from '../../api';
import type { ToolTabId } from './TabBar';
import { caseIdFromRequest } from './entities';
import { useInvestigation } from './useInvestigation';
import { useDictation } from './useDictation';
import { ARK_CAI_MODEL, type ImageReview } from './useImageReview';
import { BottomPanel } from './BottomPanel';
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

type ExecutionEvent = {
  event: string;
  run_id?: string;
  timestamp?: string;
  source?: string;
  tool?: string;
  args?: Record<string, any>;
  allowed?: boolean;
  reason?: string;
  risk?: string;
  execution_id?: string;
  session_id?: string;
  result?: any;
  elapsed_ms?: number;
  verified?: boolean;
  verification_basis?: string;
  path?: string;
  role?: string;
  prompt?: string;
  [key: string]: any;
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
  provider: string;
  provider_group: string;
  pricing: string;
  pricing_detail: string;
  tool_calling: boolean;
  context_window: number;
  available: boolean;
  local: boolean;
  vision?: boolean;
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
  lifecycle_status: 'idle' | 'running' | 'completed' | 'failed' | 'approval_pending';
  events: ExecutionEvent[];
  current_tool: { id: string; name: string; status: 'running' | 'completed' | 'failed'; args: Record<string, any>; result: any; elapsed_ms: number | null; verified: boolean; error: string | null } | null;
  evidence_ref: string | null;
  objective_expanded: boolean;
};

export function ArkControl({ onImage, analyzing, onOpenTool, evidenceFile, imageReview, workspaceTitle }: {
  onImage: (file: File) => Promise<AnalyzeResponse | undefined>;
  analyzing: boolean;
  evidenceFile: File | null;
  imageReview?: ImageReview;
  workspaceTitle: string;
  onOpenTool: (tool: ToolTabId) => void;
}) {
  const inv = useInvestigation();
  const caseId = inv.activeCase?.id;
  const [draft, setDraft] = useState('');
  const [attachment, setAttachment] = useState<{ file: File; url: string }>();
  const [messages, setMessages] = useState<Message[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [view, setView] = useState<'chat' | 'console' | 'review'>('chat');
  const [execution, setExecution] = useState<ExecutionState>({
    run_id: null,
    objective: null,
    objective_outcome: null,
    engagement: null,
    target: null,
    active_agent: null,
    lifecycle_status: 'idle',
    events: [],
    current_tool: null,
    evidence_ref: null,
    objective_expanded: false,
  });
  const [queue, setQueue] = useState<QueueEntry[]>([]);
  const [steerings, setSteerings] = useState<SteerEntry[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [modelsLoaded, setModelsLoaded] = useState(false);
  const [selectedModel, setSelectedModel] = useState<string | null>(null);
  const [steeringText, setSteeringText] = useState('');
  const [steeringPending, setSteeringPending] = useState(false);
  const [queueLoaded, setQueueLoaded] = useState(false);
  const [modelMenuOpen, setModelMenuOpen] = useState(false);

  const reviewId = imageReview?.id;
  useEffect(() => {
    if (reviewId !== undefined) setView('review');
    else setView(prev => prev === 'review' ? 'chat' : prev);
  }, [reviewId]);

  useEffect(() => {
    if (inv.session?.status === 'proposed') setView('console');
  }, [inv.session?.plan.revision_id, inv.session?.status]);

  useEffect(() => {
    api.caiModels().then((data: any) => {
      const providers = data.providers || {};
      const allModels: ModelInfo[] = [];
      Object.values(providers).forEach((prov: any) => {
        if (Array.isArray(prov)) {
          prov.forEach((m: any) => allModels.push(m));
        }
      });
      setModels(allModels);
      setModelsLoaded(true);
      const active = data.active_model;
      if (active) setSelectedModel(active);
    }).catch(() => {
      setModelsLoaded(true);
    });
  }, []);

  const [approving, setApproving] = useState(false);
  const feed = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const request = useRef<AbortController | null>(null);
  const session = useRef<{ id: string; caseId?: string; domain: string }>();
  const urls = useRef(new Set<string>());

  useEffect(() => () => {
    request.current?.abort();
    urls.current.forEach(url => URL.revokeObjectURL(url));
  }, []);

  useEffect(() => {
    if (feed.current) feed.current.scrollTop = feed.current.scrollHeight;
  }, [messages, view, execution.events]);

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

  function toolDisplayName(toolId: string): string {
    const map: Record<string, string> = {
      'net.curl_probe': 'HTTP Probe',
      'net.nmap_scan': 'Nmap Scan',
      'net.dns_lookup': 'DNS Lookup',
      'net.whois': 'WHOIS Lookup',
      'net.ssl_check': 'SSL/TLS Check',
      'net.dir_enum': 'Directory Enumeration',
      'net.subdomain_enum': 'Subdomain Enumeration',
      'pentest.nmap_scan': 'Pentest Nmap Scan',
      'pentest.ssh_identity': 'SSH Identity Verification',
      'pentest.priv_esc': 'Privilege Escalation Analysis',
      'pentest.webshell_scan': 'Webshell Scan',
      'pentest.hash_crack': 'Hash Cracking',
      'pentest.default_creds': 'Default Credential Test',
      'recon.web_search': 'Web Search',
      'recon.web_fetch': 'Web Fetch',
      'system.diagnostics': 'System Diagnostics',
    };
    return map[toolId] || toolId.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }

  function formatRole(role: string | null | undefined): string {
    if (!role) return '—';
    const stripped = role.replace(/^SpecialistRole\./, '');
    const words = stripped.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase());
    return words.join(' ');
  }

  function eventLabel(ev: ExecutionEvent): string {
    switch (ev.event) {
      case 'run_created': return 'Run created';
      case 'agent_selected': return 'Agent selected';
      case 'scope_checked': return 'Scope checked';
      case 'hitl': return 'Approval required';
      case 'approval_required': return 'Approval required';
      case 'tool_call': return 'Tool invoked';
      case 'tool_started': return 'Tool started';
      case 'tool_completed': return 'Tool completed';
      case 'tool_failed': return 'Tool failed';
      case 'result_verified': return 'Result verified';
      case 'evidence_recorded': return 'Evidence recorded';
      case 'run_completed': return 'Run completed';
      case 'run_failed': return 'Run failed';
      case 'queue_delivered': return 'Queued message delivered';
      default: return ev.event;
    }
  }

  function eventDetail(ev: ExecutionEvent): string {
    if (ev.event === 'agent_selected') return `Agent: ${formatRole(ev.role)} · Path: ${ev.path ?? '—'}`;
    if (ev.event === 'scope_checked') return `Scope ${ev.allowed ? 'approved' : 'denied'} · ${ev.reason ?? ''}`;
    if (ev.event === 'tool_call') return `Tool: ${toolDisplayName(ev.tool ?? 'unknown')}`;
    if (ev.event === 'tool_completed' || ev.event === 'tool_failed') {
      return `Tool: ${toolDisplayName(ev.tool ?? 'unknown')} · ${ev.elapsed_ms ?? 0} ms · ${ev.verified ? 'verified' : 'unverified'}`;
    }
    if (ev.event === 'hitl' || ev.event === 'approval_required') return `Approval required: ${ev.tool ?? 'unknown'}`;
    if (ev.event === 'run_completed') return 'Run completed successfully';
    if (ev.event === 'run_failed') return `Run failed: ${ev.reason ?? ''}`;
    if (ev.event === 'queue_delivered') return 'Queued message delivered';
    return '';
  }

  async function copyRunId() {
    if (!execution.run_id) return;
    try {
      await navigator.clipboard.writeText(execution.run_id);
    } catch { /* clipboard unavailable */ }
  }

  const send = async (raw: string, withAttachment = false) => {
    const text = raw.trim();
    const image = withAttachment ? attachment : undefined;
    if (request.current || (image && analyzing) || (!text && !image)) return;
    setView('chat');
    setDraft('');
    setNotice('');
    setExecution({
      run_id: null,
      objective: text,
      objective_outcome: null,
      engagement: null,
      target: null,
      active_agent: null,
      lifecycle_status: 'idle',
      events: [],
      current_tool: null,
      evidence_ref: null,
      objective_expanded: false,
    });
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
          reply('See Plan in the investigation console.');
          inv.setBottomTab('plan');
          setView('console');
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
          model: selectedModel || ARK_CAI_MODEL,
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
        }, event => {
          if (event.event === 'session') session.current = { id: event.session_id, caseId: activeCase, domain: image ? 'image' : inv.domain };

          if (event.event === 'run_created') {
            setExecution(prev => ({ ...prev, run_id: event.run_id ?? null, lifecycle_status: 'running' }));
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
            }
            return;
          }
          if (event.event === 'hitl') {
            setExecution(prev => ({ ...prev, lifecycle_status: 'approval_pending' }));
            const approval = { session: event.session_id, execution: event.execution_id, tool: event.tool };
            update(message => ({ ...message, approval }));
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
            return;
          }
          if (event.event === 'run_failed') {
            setExecution(prev => ({ ...prev, lifecycle_status: 'failed', objective_outcome: 'failed' }));
            return;
          }

          if (event.event === 'token') update(message => ({ ...message, text: message.text + event.text }));
          if (['final', 'local_command'].includes(event.event) && event.text) reply(event.text);
          if (event.event === 'error') reply(event.message || 'ARK-CAI returned an error.');
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
        update(message => message.text || message.approval ? message : { ...message, text: 'ARK-CAI returned no response.' });
      }
    } catch (err) {
      reply(err instanceof Error ? err.message : 'ARK-CAI request failed.');
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
    if (!steeringText.trim() || !session.current?.id || !execution.run_id) return;
    setSteeringPending(true);
    try {
      await api.caiSteer({
        session_id: session.current.id,
        run_id: execution.run_id,
        message: steeringText,
        instruction_type: 'steer',
      });
      setSteeringText('');
      setSteeringPending(false);
      loadQueue();
    } catch (err) {
      setNotice(err instanceof Error ? err.message : 'Steer failed');
      setSteeringPending(false);
    }
  };

  const stopRun = async () => {
    if (!session.current?.id || !execution.run_id) return;
    try {
      await api.caiStop({ session_id: session.current.id, run_id: execution.run_id, stop_type: 'stop' });
      setExecution(prev => ({ ...prev, lifecycle_status: 'failed', objective_outcome: 'failed' }));
      setBusy(false);
    } catch {
      // ignore
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

  const providerGroups: Record<string, ModelInfo[]> = {};
  models.forEach(m => {
    if (!providerGroups[m.provider]) providerGroups[m.provider] = [];
    providerGroups[m.provider].push(m);
  });

  return (
    <aside className="ark-control" aria-label="ARK-CAI Control">
      <header className="ark-dock-header">
        <div><strong>ARK-CAI</strong><small>Operator · {execution.lifecycle_status !== 'idle' ? 'Autonomous' : 'Advisory'}</small></div>
        <nav aria-label="Dock views">
          <button type="button" aria-pressed={view === 'chat'} onClick={() => setView('chat')}><MessageSquare size={14} /> Chat{view !== 'chat' && messages.some(message => message.approval) && <span className="ark-view-indicator" aria-label="Approval pending" />}</button>
          {imageReview && <button type="button" aria-pressed={view === 'review'} onClick={() => setView('review')}><ScanLine size={14} /> Review</button>}
          <button type="button" aria-pressed={view === 'console'} onClick={() => setView('console')}><Activity size={14} /> Console{view !== 'console' && inv.session?.status === 'proposed' && <span className="ark-view-indicator" aria-label="Plan approval pending" />}</button>
        </nav>
      </header>

      <div className="ark-output-scroll" ref={feed}>
        {(execution.run_id || execution.lifecycle_status !== 'idle') && (
          <section className="ark-investigation-header">
            <div className="ark-header-row">
              <span className="ark-header-label">Objective</span>
              <button type="button" className="ark-objective-toggle" onClick={() => setExecution(prev => ({ ...prev, objective_expanded: !prev.objective_expanded }))}>
                {execution.objective_expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                {execution.objective || '—'}
              </button>
            </div>
            {execution.objective_expanded && (
              <div className="ark-objective-full">{execution.objective}</div>
            )}
            <div className="ark-header-row">
              <span className="ark-header-label">Engagement</span>
              <span className="ark-header-value">{execution.engagement || 'A2-LAB-001'}</span>
            </div>
            <div className="ark-header-row">
              <span className="ark-header-label">Target</span>
              <span className="ark-header-value">{execution.target || '—'}</span>
            </div>
            <div className="ark-header-row">
              <span className="ark-header-label">Active Specialist</span>
              <span className="ark-header-value">{formatRole(execution.active_agent)}</span>
            </div>
            <div className="ark-header-row">
              <span className="ark-header-label">Lifecycle</span>
              <span className={`ark-status ${execution.lifecycle_status}`}>{statusLabels[execution.lifecycle_status]}</span>
            </div>
            {execution.objective_outcome && (
              <div className="ark-header-row">
                <span className="ark-header-label">Objective Outcome</span>
                <span className={`ark-outcome ${execution.objective_outcome}`}>{outcomeLabels[execution.objective_outcome]}</span>
              </div>
            )}
            <div className="ark-header-row">
              <span className="ark-header-label">Run ID</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span className="ark-header-value ark-mono">{execution.run_id || '—'}</span>
                {execution.run_id && (
                  <button type="button" className="ark-copy-btn" title="Copy run ID" onClick={copyRunId} aria-label="Copy run ID">
                    <Copy size={12} />
                  </button>
                )}
              </div>
            </div>
            {execution.evidence_ref && (
              <div className="ark-header-row">
                <span className="ark-header-label">Evidence</span>
                <span className="ark-header-value ark-mono">{execution.evidence_ref}</span>
              </div>
            )}
          </section>
        )}

        {execution.events.length > 0 && (
          <section className="ark-execution-timeline">
            <h3 className="ark-section-title">Execution Timeline</h3>
            <ol className="ark-timeline-list">
              {execution.events.map((ev, i) => {
                const iconMap: Record<string, { icon: React.ReactNode; color: string }> = {
                  run_created: { icon: <Play size={14} />, color: '#38BDF8' },
                  agent_selected: { icon: <Activity size={14} />, color: '#38BDF8' },
                  scope_checked: { icon: <RefreshCw size={14} />, color: '#38BDF8' },
                  hitl: { icon: <StopCircle size={14} />, color: '#F59E0B' },
                  approval_required: { icon: <StopCircle size={14} />, color: '#F59E0B' },
                  tool_call: { icon: <Play size={14} />, color: '#10B981' },
                  tool_started: { icon: <Play size={14} />, color: '#10B981' },
                  tool_completed: { icon: <CheckCircle size={14} />, color: '#10B981' },
                  tool_failed: { icon: <AlertCircle size={14} />, color: '#EF4444' },
                  result_verified: { icon: <CheckCircle size={14} />, color: '#10B981' },
                  evidence_recorded: { icon: <ScanLine size={14} />, color: '#38BDF8' },
                  run_completed: { icon: <CheckCircle size={14} />, color: '#10B981' },
                  run_failed: { icon: <AlertCircle size={14} />, color: '#EF4444' },
                  queue_delivered: { icon: <Rocket size={14} />, color: '#8B5CF6' },
                };
                const info = iconMap[ev.event] || { icon: <RefreshCw size={14} />, color: '#666666' };
                return (
                  <li key={i} className="ark-timeline-item">
                    <span className="ark-timeline-dot" style={{ color: info.color }}>{info.icon}</span>
                    <div className="ark-timeline-content">
                      <div className="ark-timeline-event">{eventLabel(ev)}</div>
                      {eventDetail(ev) && <div className="ark-timeline-detail">{eventDetail(ev)}</div>}
                      <div className="ark-timeline-time">{ev.timestamp ? new Date(ev.timestamp).toLocaleTimeString() : ''}</div>
                    </div>
                  </li>
                );
              })}
            </ol>
          </section>
        )}

        {execution.current_tool && (
          <section className="ark-tool-details">
            <h3 className="ark-section-title">Tool: {execution.current_tool.name}</h3>
            <div className="ark-tool-field">
              <span className="ark-tool-label">ID</span>
              <span className="ark-tool-value ark-mono">{execution.current_tool.id}</span>
            </div>
            <div className="ark-tool-field">
              <span className="ark-tool-label">Status</span>
              <span className={`ark-tool-status ${execution.current_tool.status}`}>{execution.current_tool.status}</span>
            </div>
            <div className="ark-tool-field">
              <span className="ark-tool-label">Inputs (sanitized)</span>
              <pre className="ark-tool-args">{JSON.stringify(execution.current_tool.args, null, 2)}</pre>
            </div>
            {execution.current_tool.result && (
              <div className="ark-tool-field">
                <span className="ark-tool-label">Output</span>
                <pre className="ark-tool-output">{JSON.stringify(execution.current_tool.result, null, 2)}</pre>
              </div>
            )}
            {execution.current_tool.error && (
              <div className="ark-tool-field">
                <span className="ark-tool-label">Error</span>
                <span className="ark-tool-error">{execution.current_tool.error}</span>
              </div>
            )}
            {execution.current_tool.elapsed_ms !== null && (
              <div className="ark-tool-field">
                <span className="ark-tool-label">Elapsed</span>
                <span className="ark-tool-value">{execution.current_tool.elapsed_ms} ms</span>
              </div>
            )}
            <div className="ark-tool-field">
              <span className="ark-tool-label">Verified</span>
              <span className={`ark-tool-status ${execution.current_tool.verified ? 'verified' : 'unverified'}`}>
                {execution.current_tool.verified ? 'Yes — backend-confirmed' : 'No — not verified'}
              </span>
            </div>
          </section>
        )}

        {(execution.lifecycle_status === 'completed' || execution.lifecycle_status === 'failed') && execution.objective_outcome && (
          <section className="ark-findings">
            <h3 className="ark-section-title">Findings</h3>
            <p className="ark-finding-text">
              {execution.objective_outcome === 'succeeded'
                ? `Objective succeeded. ${execution.current_tool ? `Tool "${execution.current_tool.name}" returned ${execution.current_tool.verified ? 'verified' : 'unverified'} output.` : 'No tool executed.'}`
                : `Objective failed. ${execution.current_tool?.error || 'Unknown error'}`}
            </p>
            <p className="ark-finding-text">
              Verification basis: backend-owned tool result status (not model-generated).
              {execution.evidence_ref ? ` Evidence recorded: ${execution.evidence_ref}` : ''}
            </p>
          </section>
        )}

        {execution.evidence_ref && (
          <section className="ark-evidence">
            <h3 className="ark-section-title">Evidence Record</h3>
            <div className="ark-evidence-field">
              <span className="ark-evidence-label">Run ID</span>
              <span className="ark-evidence-value ark-mono">{execution.run_id}</span>
            </div>
            <div className="ark-evidence-field">
              <span className="ark-evidence-label">File</span>
              <span className="ark-evidence-value ark-mono">{execution.evidence_ref}</span>
            </div>
            <div className="ark-evidence-field">
              <span className="ark-evidence-label">Events</span>
              <span className="ark-evidence-value">{execution.events.length}</span>
            </div>
          </section>
        )}

        {queueLoaded && queue.length > 0 && (
          <section className="ark-queue">
            <h3 className="ark-section-title">Message Queue</h3>
            <div className="ark-queue-list">
              {queue.map(q => (
                <div key={q.id} className={`ark-queue-item ${q.status}`}>
                  <div className="ark-queue-info">
                    <span className="ark-queue-id">{q.id}</span>
                    <span className="ark-queue-prompt">{q.prompt}</span>
                    {q.run_id && <span className="ark-queue-run">run: {q.run_id}</span>}
                  </div>
                  <div className="ark-queue-status">
                    <span className={`ark-queue-status-badge ${q.status}`}>{q.status}</span>
                    {q.status === 'pending' && (
                      <button type="button" className="ark-queue-cancel" onClick={() => cancelQueueItem(q.id)} title="Cancel">
                        <X size={12} />
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {execution.lifecycle_status === 'running' && (
          <section className="ark-steering">
            <h3 className="ark-section-title">Steer Active Run</h3>
            <div className="ark-steer-input">
              <textarea
                ref={input}
                value={steeringText}
                rows={2}
                placeholder="Enter steering instruction (e.g., 'focus on port 443', 'pivot to web enumeration')..."
                onChange={e => setSteeringText(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    void sendSteer();
                  }
                }}
              />
              <button type="button" className="ark-steer-send" onClick={sendSteer} disabled={steeringPending || !steeringText.trim() || !execution.run_id}>
                {steeringPending ? 'Sending...' : 'Steer'}
              </button>
            </div>
            {steerings.length > 0 && (
              <div className="ark-steer-list">
                {steerings.slice(-3).map(s => (
                  <div key={s.id} className="ark-steer-item">
                    <span className="ark-steer-msg">{s.message}</span>
                    <span className={`ark-steer-status ${s.status}`}>{s.status}</span>
                  </div>
                ))}
              </div>
            )}
          </section>
        )}

        {execution.lifecycle_status === 'running' && (
          <section className="ark-stop-control">
            <button type="button" className="ark-stop-btn" onClick={stopRun} title="Stop current execution">
              <StopCircle size={16} /> Stop Execution
            </button>
            {queue.some(q => q.status === 'pending') && (
              <button type="button" className="ark-stop-btn ark-stop-cancel" onClick={cancelQueue} title="Cancel queued messages">
                <Trash2 size={16} /> Cancel Queue
              </button>
            )}
          </section>
        )}
      </div>

      {view === 'chat' && <details className="ark-workspace-context">
        <summary>{workspaceTitle}{caseId ? ` · ${caseId}` : ''}</summary>
        <p>{inv.activeEvidence?.filename ?? 'No active evidence'}</p>
        {imageReview && <button type="button" onClick={() => setView('review')} >Open image review</button>}
        {inv.auditTrail.slice(-5).map(event => <p key={event.id}>{event.action} · {event.detail}</p>)}
      </details>}
      <div className="ark-feed" ref={feed} role="log" hidden={view !== 'chat'}>
        {!messages.length && <div className="ark-idle"><MessageSquare size={22} /><strong>Ask ARK-CAI</strong><p>Review evidence, explore a lead, or run a command.</p></div>}
        {messages.map((message, i) => <article key={i} className={message.user ? 'ark-message ark-user' : 'ark-message'}>
          {message.image && <img src={message.image} alt="Attached evidence" />}
          {message.text || (busy && i === messages.length - 1 && !message.approval && !message.tools?.length ? 'Working…' : '')}
          {message.tools?.map(tool => <span key={tool} className="ark-tool-chip">{tool}</span>)}
          {message.approval && <div>Approve {message.approval.tool}? <button disabled={approving} onClick={() => void approve(i, message.approval!, true)}>Approve</button> <button disabled={approving} onClick={() => void approve(i, message.approval!, false)}>Deny</button></div>}
        </article>)}
      </div>
      {imageReview && view === 'review' && <section className="ark-review" aria-label="Image advisory review">
        <div className="ark-review-heading">
          <span>IMAGE ADVISORY REVIEW</span>
          <h2>{imageReview.filename}</h2>
          <p>ARK Core evidence summary · ARK-CAI interpretation</p>
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
      </section>}
      <div className="ark-console" hidden={view !== 'console'}>
        <BottomPanel docked collapsed={view !== 'console'} onToggle={() => setView('chat')} result={inv.result} />
      </div>
      <form hidden={view === 'console'} className="ark-composer" onSubmit={event => { event.preventDefault(); void send(draft, true); }}>
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
        <details className="ark-shortcuts">
          <summary>Quick commands</summary>
          <div className="ark-chips">
            {['@Agents', '/help', '/tools', '/case', '/forensics', '/osint', '/investigate'].map(chip => (
              <button key={chip} type="button" disabled={busy} onClick={() => void send(chip)}>{chip}</button>
            ))}
          </div>
        </details>
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
            rows={3}
            aria-label="Message ARK-CAI"
            placeholder="Ask ARK-CAI or run a command... (/ for commands)"
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
                <button type="button" className="ark-model-pill" onClick={() => setModelMenuOpen(!modelMenuOpen)} title={selectedModel || 'Select model'}>
                  <span className="ark-model-name">{selectedModel ? models.find(m => m.id === selectedModel)?.name || selectedModel : 'Select model'}</span>
                  <ChevronDown size={14} />
                </button>
                {modelsLoaded && modelMenuOpen && (
                  <div className="ark-model-popover">
                    <input type="text" className="ark-model-search" placeholder="Search models…" />
                    {Object.entries(providerGroups).map(([provider, models]) => (
                      <div key={provider} className="ark-model-group">
                        <div className="ark-model-group-label">{provider}</div>
                        {models.map(m => (
                          <button key={m.id} type="button" className={`ark-model-item ${m.id === selectedModel ? 'selected' : ''} ${!m.available ? 'disabled' : ''}`} onClick={() => {
                            setSelectedModel(m.id);
                            setModelMenuOpen(false);
                          }}>
                            <span className="ark-model-item-name">{m.name}</span>
                            <span className={`ark-model-status ${m.available ? 'available' : 'unavailable'}`}>{m.available ? 'Available' : 'Unavailable'}</span>
                          </button>
                        ))}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
            <button className="ark-send" type="submit" aria-label="Send" disabled={busy || Boolean(attachment && analyzing) || (!draft.trim() && !attachment)}>
              <Send size={16} />
            </button>
          </div>
          {notice && <small role="status">{notice}</small>}
        </div>
      </form>
    </aside>
  );
}