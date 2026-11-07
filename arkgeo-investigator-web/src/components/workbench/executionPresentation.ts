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
