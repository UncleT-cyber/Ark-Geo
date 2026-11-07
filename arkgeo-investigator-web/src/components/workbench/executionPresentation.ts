/**
 * Execution presentation — one source of truth for how a run's raw backend
 * events are labelled and summarised in the UI.
 *
 * Everything here is derived from the events the backend actually emitted
 * (tool_started / tool / result_verified / scope_checked / evidence_recorded /
 * run_completed / run_cancelled …). Nothing is invented: the structured final
 * report reads the same event list the conversation streamed, so it can never
 * claim a tool ran when the backend did not report it.
 */

export type ExecutionEvent = {
  event: string;
  run_id?: string;
  timestamp?: string;
  source?: string;
  tool?: string;
  args?: Record<string, any>;
  allowed?: boolean;
  reason?: string;
  risk?: string;
  mode?: string;
  execution_id?: string;
  session_id?: string;
  result?: any;
  elapsed_ms?: number;
  verified?: boolean;
  verification_basis?: string;
  path?: string;
  role?: string;
  prompt?: string;
  steering_id?: string;
  status?: string;
  [key: string]: any;
};

const TOOL_DISPLAY_NAMES: Record<string, string> = {
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

export function toolDisplayName(toolId: string | undefined | null): string {
  if (!toolId) return 'Tool';
  return TOOL_DISPLAY_NAMES[toolId]
    || toolId.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

export function formatRole(role: string | null | undefined): string {
  if (!role) return '—';
  const stripped = role.replace(/^SpecialistRole\./, '');
  return stripped.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join(' ');
}

/** Short human label for one execution event (conversation timeline). */
export function eventLabel(ev: ExecutionEvent): string {
  switch (ev.event) {
    case 'run_created': return 'Run created';
    case 'execution_mode': return ev.mode === 'manual' ? 'Manual execution' : 'Automatic execution';
    case 'agent_selected': return 'Specialist selected';
    case 'scope_checked': return ev.allowed === false ? 'Scope denied' : 'Scope approved';
    case 'hitl':
    case 'approval_required': return 'Approval required';
    case 'tool_call': return 'Tool invoked';
    case 'tool_started': return 'Tool started';
    case 'tool_completed': return 'Tool completed';
    case 'tool_failed': return 'Tool failed';
    case 'tool': return ev.verified === false ? 'Tool returned (unverified)' : 'Tool returned';
    case 'result_verified': return 'Result verified';
    case 'evidence_recorded': return 'Evidence recorded';
    case 'steer_ack': return ev.status === 'accepted' ? 'Steering accepted'
      : ev.status === 'deferred' ? 'Steering deferred' : 'Steering rejected';
    case 'run_completed': return 'Run completed';
    case 'run_failed': return 'Run failed';
    case 'run_cancelled': return 'Run stopped by operator';
    case 'queue_delivered': return 'Queued message delivered';
    default: return ev.event;
  }
}

/** Secondary detail line for one execution event. */
export function eventDetail(ev: ExecutionEvent): string {
  if (ev.event === 'agent_selected') return `Specialist: ${formatRole(ev.role)} · Path: ${ev.path ?? '—'}`;
  if (ev.event === 'scope_checked') return `${ev.allowed ? 'Approved' : 'Denied'} · ${ev.reason ?? ''}`;
  if (ev.event === 'tool_call' || ev.event === 'tool_started') return toolDisplayName(ev.tool);
  if (ev.event === 'tool' || ev.event === 'tool_completed' || ev.event === 'tool_failed') {
    return `${toolDisplayName(ev.tool)} · ${ev.elapsed_ms ?? 0} ms · ${ev.verified ? 'verified' : 'unverified'}`;
  }
  if (ev.event === 'hitl' || ev.event === 'approval_required') return `Approval required: ${toolDisplayName(ev.tool)}`;
  if (ev.event === 'steer_ack') return ev.reason ?? '';
  if (ev.event === 'run_failed') return ev.reason ?? '';
  if (ev.event === 'run_cancelled') return ev.reason ?? 'Operator stop honoured at a safe checkpoint';
  return '';
}

/** Expandable raw output for one event, or null when there is nothing to show. */
export function rawDetail(ev: ExecutionEvent): string | null {
  if (ev.event === 'tool' || ev.event === 'tool_completed' || ev.event === 'tool_failed') {
    if (ev.result == null) return null;
    try {
      const text = typeof ev.result === 'string' ? ev.result : JSON.stringify(ev.result, null, 2);
      return text.length > 4000 ? `${text.slice(0, 4000)}\n… (${text.length - 4000} more characters)` : text;
    } catch {
      return String(ev.result);
    }
  }
  if ((ev.event === 'scope_checked' || ev.event === 'approval_required' || ev.event === 'hitl') && ev.args) {
    try { return JSON.stringify(ev.args, null, 2); } catch { return null; }
  }
  return null;
}

export type ExecutionStatus = 'idle' | 'running' | 'completed' | 'failed' | 'approval_pending' | 'stopped';

/**
 * B.5 — the directive's richer execution vocabulary, DERIVED from the events
 * the backend already emits. This is presentation state only: it never
 * replaces the persisted run status enum (`session_store.py`), so persistence
 * stays stable while the UI gains the required states.
 */
export type ExecutionPhase =
  | 'PLANNING' | 'RUNNING' | 'VERIFYING' | 'REPORTING' | 'COMPLETED'
  | 'AWAITING_APPROVAL' | 'PAUSED' | 'FAILED' | 'CANCELLED' | 'PARTIAL';

const _PLANNING_EVENTS = new Set([
  'run_created', 'execution_mode', 'agent_selected', 'scope_checked', 'session',
]);

/** Derive the lifecycle phase from the run's own events. Pure, total. */
export function deriveExecutionPhase(execution: {
  lifecycle_status: string;
  objective_outcome?: 'pending' | 'succeeded' | 'failed' | null;
  events: ExecutionEvent[];
}): ExecutionPhase {
  const status = execution.lifecycle_status;
  const events = execution.events;
  const last = events.length ? events[events.length - 1] : null;
  const toolEvents = events.filter(e => e.event === 'tool' || e.event === 'tool_completed' || e.event === 'tool_failed');
  const anyFailedTool = toolEvents.some(e =>
    e.event === 'tool_failed'
    || (typeof e.result === 'object' && e.result !== null
        && ((e.result as any).status === 'error' || (e.result as any).status === 'denied')));

  if (status === 'idle') return 'PLANNING';
  if (status === 'approval_pending') return 'AWAITING_APPROVAL';
  if (status === 'stopped') return 'CANCELLED';
  if (status === 'failed') return 'FAILED';

  if (status === 'running') {
    if (!last || _PLANNING_EVENTS.has(last.event)) return 'PLANNING';
    return 'RUNNING';
  }

  // status === 'completed'
  if (last?.event === 'run_completed' && (execution.objective_outcome ?? 'pending') === 'pending') {
    return 'REPORTING';
  }
  if (toolEvents.length === 0) return 'COMPLETED';
  if (anyFailedTool || execution.objective_outcome === 'failed') return 'PARTIAL';
  return 'COMPLETED';
}

/** One inspectable tool stage inside an objective group (C.2). */
export interface ExecutionStage {
  tool: string;
  name: string;
  status: 'running' | 'completed' | 'failed' | 'skipped';
  elapsedMs: number | null;
  verified: boolean;
  error: string | null;
}

/** The run's timeline grouped under its objective, with per-stage detail. */
export interface ObjectiveGroup {
  objective: string;
  phase: ExecutionPhase;
  stages: ExecutionStage[];
  durationMs: number;
}

/**
 * C.2 — group the execution timeline under the current objective with
 * per-stage status, duration and inspectable result. Collapsed by default in
 * the UI; this function only shapes the data (no chain-of-thought, no
 * invented stages — a stage exists only if the backend reported the tool).
 */
export function groupExecutionByObjective(execution: {
  objective: string | null;
  lifecycle_status: string;
  objective_outcome?: 'pending' | 'succeeded' | 'failed' | null;
  events: ExecutionEvent[];
}): ObjectiveGroup[] {
  const stages: ExecutionStage[] = [];
  const byTool = new Map<string, ExecutionStage>();

  const ensure = (tool: string): ExecutionStage => {
    let stage = byTool.get(tool);
    if (!stage) {
      stage = { tool, name: toolDisplayName(tool), status: 'running', elapsedMs: null, verified: false, error: null };
      byTool.set(tool, stage);
      stages.push(stage);
    }
    return stage;
  };

  for (const ev of execution.events) {
    const tool = ev.tool;
    if (!tool) continue;
    if (ev.event === 'tool_call' || ev.event === 'tool_started') {
      const s = ensure(tool);
      s.status = 'running';
    } else if (ev.event === 'tool' || ev.event === 'tool_completed' || ev.event === 'tool_failed') {
      const s = ensure(tool);
      const failed = ev.event === 'tool_failed'
        || (typeof ev.result === 'object' && ev.result !== null
            && ((ev.result as any).status === 'error' || (ev.result as any).status === 'denied'));
      s.status = failed ? 'failed' : 'completed';
      s.elapsedMs = typeof ev.elapsed_ms === 'number' ? ev.elapsed_ms : s.elapsedMs;
      s.verified = ev.verified === true;
      s.error = failed ? String((ev.result as any)?.error ?? 'failed') : null;
    }
  }

  const durationMs = stages.reduce((sum, s) => sum + (s.elapsedMs ?? 0), 0);
  return [{
    objective: execution.objective || 'Untitled objective',
    phase: deriveExecutionPhase(execution),
    stages,
    durationMs,
  }];
}

export type RunSummary = {
  objective: string;
  engagement: string | null;
  executionSummary: string;
  outcome: 'succeeded' | 'failed' | 'stopped' | 'inconclusive' | 'pending';
  tools: Array<{ tool: string; name: string; verified: boolean; elapsed_ms: number | null; error: string | null }>;
  evidenceRefs: string[];
  scopeDenials: number;
  approvals: number;
  events: number;
  runId: string | null;
  verificationBasis: string | null;
  failureReason: string | null;
  recommendations: string[];
};

/**
 * Build the structured final report from the events the backend emitted.
 * Pure and honest: a tool only appears if a `tool` event carried its result.
 */
export function summarizeRun(execution: {
  run_id: string | null;
  objective: string | null;
  objective_outcome: 'pending' | 'succeeded' | 'failed' | null;
  lifecycle_status: string;
  events: ExecutionEvent[];
  evidence_ref: string | null;
}): RunSummary {
  const tools: RunSummary['tools'] = [];
  const evidenceRefs: string[] = [];
  let scopeDenials = 0;
  let approvals = 0;

  for (const ev of execution.events) {
    if (ev.event === 'tool') {
      const isError = typeof ev.result === 'object' && ev.result !== null
        && (ev.result.status === 'error' || ev.result.status === 'denied');
      tools.push({
        tool: ev.tool ?? 'unknown',
        name: toolDisplayName(ev.tool),
        verified: ev.verified === true,
        elapsed_ms: typeof ev.elapsed_ms === 'number' ? ev.elapsed_ms : null,
        error: isError ? String((ev.result as any)?.error ?? 'failed') : null,
      });
    }
    if (ev.event === 'scope_checked' && ev.allowed === false) scopeDenials += 1;
    if (ev.event === 'hitl' || ev.event === 'approval_required') approvals += 1;
    if (ev.event === 'evidence_recorded' && ev.evidence_path) {
      if (!evidenceRefs.includes(ev.evidence_path)) evidenceRefs.push(ev.evidence_path);
    }
  }
  if (execution.evidence_ref && !evidenceRefs.includes(execution.evidence_ref)) {
    evidenceRefs.push(execution.evidence_ref);
  }

  const stopped = execution.lifecycle_status === 'stopped';

  const lastVerified = [...execution.events].reverse().find(e => e.event === 'result_verified');
  const runFailed = [...execution.events].reverse().find(e => e.event === 'run_failed');

  const objective = execution.objective ?? '—';
  const engagement = targetOf(execution.events);
  const failedTools = tools.filter(t => !t.verified && t.error);

  const executionSummary = tools.length === 0
    ? 'No tools were dispatched for this run.'
    : `${tools.length} tool${tools.length === 1 ? '' : 's'} executed`
      + (engagement ? ` against ${engagement}` : '')
      + `; ${tools.filter(t => t.verified).length} verified, ${failedTools.length} failed.`;

  const outcome: RunSummary['outcome'] = stopped ? 'stopped'
    : execution.objective_outcome === 'succeeded' ? 'succeeded'
    : execution.objective_outcome === 'failed' ? 'failed'
    : execution.lifecycle_status === 'failed' ? 'failed'
    : execution.lifecycle_status === 'completed' && tools.some(t => t.verified) ? 'succeeded'
    : execution.lifecycle_status === 'completed' ? 'inconclusive'
    : 'pending';

  const recommendations: string[] = [];
  if (outcome === 'failed' && failedTools.length) {
    recommendations.push(`Review the ${failedTools.length} failed tool invocation${failedTools.length === 1 ? '' : 's'} in the execution details before retrying.`);
  }
  if (scopeDenials > 0) {
    recommendations.push('A dispatch was denied by engagement scope — confirm the target is within the authorized scope before retrying.');
  }
  if (outcome === 'succeeded' && evidenceRefs.length > 0) {
    recommendations.push('Evidence was recorded; open the case record to review the chain of custody.');
  }
  if (tools.length > 0 && tools.every(t => !t.verified)) {
    recommendations.push('No tool result was independently verified — treat these observations as unconfirmed.');
  }

  return {
    objective,
    engagement,
    executionSummary,
    outcome,
    tools,
    evidenceRefs,
    scopeDenials,
    approvals,
    events: execution.events.length,
    runId: execution.run_id,
    verificationBasis: lastVerified?.basis ?? lastVerified?.verification_basis ?? null,
    failureReason: outcome === 'failed' || outcome === 'stopped'
      ? (runFailed?.reason ?? (stopped ? 'Stopped by operator.' : null))
      : null,
    recommendations,
  };
}

/** First target the run's own scope/engagement events referenced, if any. */
function targetOf(events: ExecutionEvent[]): string | null {
  for (const ev of events) {
    const candidate = ev.target ?? ev.engagement ?? (ev.args && (ev.args.target ?? ev.args.host ?? ev.args.url ?? ev.args.domain));
    if (typeof candidate === 'string' && candidate.trim()) return candidate.trim();
  }
  return null;
}

/* ==========================================================================
 * Investigation canvas — shared execution state + activity timeline
 *
 * The `execution` slice is ONE per-investigation state object: the ARK dock
 * conversation writes it (ArkControl) and the central New Investigation
 * canvas reads it. Both surfaces therefore show the same events — there is
 * no second event stream and no duplicate state.
 * ========================================================================== */

export type ExecutionState = {
  run_id: string | null;
  objective: string | null;
  objective_outcome: 'pending' | 'succeeded' | 'failed' | null;
  engagement: string | null;
  target: string | null;
  active_agent: string | null;
  lifecycle_status: 'idle' | 'running' | 'completed' | 'failed' | 'approval_pending' | 'stopped';
  mode: 'auto' | 'manual';
  events: ExecutionEvent[];
  current_tool: {
    id: string;
    name: string;
    status: 'running' | 'completed' | 'failed';
    args: Record<string, any>;
    result: any;
    elapsed_ms: number | null;
    verified: boolean;
    error: string | null;
  } | null;
  evidence_ref: string | null;
  objective_expanded: boolean;
  /** Set once the backend confirms the run stopped at a safe checkpoint. */
  stop_requested?: boolean;
};

/** First-access seed for the `execution` slice. Every reader must use this
 *  exact factory: `getSlice` stores whatever runs first, so divergent seeds
 *  would give the dock and the canvas different shapes. */
export function initialExecutionState(): ExecutionState {
  return {
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
  };
}

/** One queued objective from the conversation queue (backend contract). */
export type QueueEntry = {
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

/** Activity-timeline row statuses (the investigation-canvas vocabulary). */
export type TimelineStatus =
  | 'pending' | 'running' | 'completed' | 'failed' | 'approval' | 'cancelled' | 'skipped';

export type TimelineRow = {
  key: string;
  label: string;
  detail: string;
  status: TimelineStatus;
  timestamp?: string;
  error?: string | null;
};

const TIMELINE_STATUS_LABEL: Record<TimelineStatus, string> = {
  pending: 'Pending',
  running: 'Running',
  completed: 'Completed',
  failed: 'Failed',
  approval: 'Awaiting approval',
  cancelled: 'Cancelled',
  skipped: 'Skipped',
};

export function timelineStatusLabel(status: TimelineStatus): string {
  return TIMELINE_STATUS_LABEL[status];
}

/**
 * Fold a run's own events into an activity timeline for the central canvas.
 *
 * Pure and honest: every row corresponds to an event the backend actually
 * emitted (or to live slice state such as a currently-running tool or a
 * queued objective). Nothing is synthesised — a tool that never ran never
 * appears here. Tool-family events are folded per execution so a
 * `tool_call`/`tool_started` row is closed by its matching `tool` result.
 */
export function buildActivityTimeline(
  execution: {
    events: ExecutionEvent[];
    current_tool: ExecutionState['current_tool'];
    lifecycle_status: ExecutionState['lifecycle_status'];
  },
  queue: QueueEntry[] = [],
): TimelineRow[] {
  const rows: TimelineRow[] = [];
  const openTools = new Map<string, number>();
  const toolKey = (ev: ExecutionEvent) => String(ev.execution_id ?? ev.tool ?? 'tool');
  const isToolError = (ev: ExecutionEvent) =>
    typeof ev.result === 'object' && ev.result !== null
    && (ev.result.status === 'error' || ev.result.status === 'denied');

  for (const ev of execution.events) {
    const stamp = ev.timestamp;
    switch (ev.event) {
      case 'tool_call':
      case 'tool_started': {
        const k = toolKey(ev);
        if (openTools.has(k)) break; // already tracking this execution
        openTools.set(k, rows.length);
        rows.push({ key: `tool:${k}:${rows.length}`, label: eventLabel(ev), detail: eventDetail(ev), status: 'running', timestamp: stamp });
        break;
      }
      case 'tool':
      case 'tool_completed':
      case 'tool_failed': {
        const k = toolKey(ev);
        const failed = ev.event === 'tool_failed' || isToolError(ev);
        const row: TimelineRow = {
          key: `tool:${k}:${rows.length}`,
          label: toolDisplayName(ev.tool),
          detail: eventDetail(ev),
          status: failed ? 'failed' : 'completed',
          timestamp: stamp,
          error: failed ? String((ev.result as any)?.error ?? 'failed') : null,
        };
        const openIdx = openTools.get(k);
        if (openIdx != null) {
          rows[openIdx] = { ...row, key: rows[openIdx].key };
          openTools.delete(k);
        } else {
          rows.push(row);
        }
        break;
      }
      case 'scope_checked':
        rows.push({ key: `scope:${rows.length}`, label: eventLabel(ev), detail: eventDetail(ev), status: ev.allowed === false ? 'failed' : 'completed', timestamp: stamp });
        break;
      case 'hitl':
      case 'approval_required':
        rows.push({ key: `hitl:${rows.length}`, label: eventLabel(ev), detail: eventDetail(ev), status: 'approval', timestamp: stamp });
        break;
      case 'run_cancelled':
        rows.push({ key: `cancel:${rows.length}`, label: eventLabel(ev), detail: eventDetail(ev), status: 'cancelled', timestamp: stamp });
        break;
      case 'run_failed':
        rows.push({ key: `failed:${rows.length}`, label: eventLabel(ev), detail: eventDetail(ev), status: 'failed', timestamp: stamp, error: ev.reason ?? null });
        break;
      default:
        rows.push({ key: `${ev.event}:${rows.length}`, label: eventLabel(ev), detail: eventDetail(ev), status: 'completed', timestamp: stamp });
    }
  }

  // A tool executing right now, when no open row exists (live state, not
  // speculation — the slice only carries it while the backend is running it).
  if (execution.current_tool?.status === 'running' && !rows.some(r => r.status === 'running')) {
    rows.push({
      key: 'live-tool',
      label: execution.current_tool.name,
      detail: 'Running',
      status: 'running',
    });
  }

  // Run active but no events persisted yet: one honest "in progress" row.
  if (
    rows.length === 0
    && (execution.lifecycle_status === 'running' || execution.lifecycle_status === 'approval_pending')
  ) {
    rows.push({
      key: 'live-run',
      label: 'Run in progress',
      detail: 'Awaiting the first execution events.',
      status: execution.lifecycle_status === 'approval_pending' ? 'approval' : 'running',
    });
  }

  // Objectives the operator queued — genuinely pending work.
  for (const q of queue) {
    if (q.status !== 'pending') continue;
    rows.push({
      key: `queue:${q.id}`,
      label: 'Queued objective',
      detail: q.prompt.length > 160 ? `${q.prompt.slice(0, 160)}…` : q.prompt,
      status: 'pending',
      timestamp: q.created_at,
    });
  }

  return rows;
}
