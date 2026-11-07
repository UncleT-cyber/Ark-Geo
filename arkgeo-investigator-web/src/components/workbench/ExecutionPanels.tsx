/**
 * Execution presentation components for the ARK conversation canvas.
 *
 * Both render only what the backend reported:
 *   * `ExecutionActivity` is the compact, collapsible inline card that replaces
 *     the old permanent upper execution region — the conversation is the
 *     primary surface, and execution detail expands in place.
 *   * `InvestigationReport` is the structured final report appended to the
 *     conversation when a run reaches a terminal state.
 *
 * The card carries no Stop control: per the interface directive the composer's
 * send button becomes the single Stop affordance while a run is active.
 */
import { useState } from 'react';
import {
  ChevronDown, ChevronUp, CheckCircle, AlertCircle, Loader2,
  ShieldCheck, ShieldAlert, FileCheck2, Copy, Ban, Target,
} from 'lucide-react';
import {
  eventLabel, eventDetail, rawDetail, formatRole,
  deriveExecutionPhase, groupExecutionByObjective,
  type ExecutionEvent, type RunSummary, type ExecutionPhase,
} from './executionPresentation';

const PHASE_TONE: Record<ExecutionPhase, string> = {
  PLANNING: 'idle',
  RUNNING: 'live',
  VERIFYING: 'live',
  REPORTING: 'live',
  COMPLETED: 'ok',
  AWAITING_APPROVAL: 'warn',
  PAUSED: 'warn',
  FAILED: 'bad',
  CANCELLED: 'bad',
  PARTIAL: 'warn',
};

export type ExecutionView = {
  run_id: string | null;
  objective: string | null;
  objective_outcome: 'pending' | 'succeeded' | 'failed' | null;
  lifecycle_status: string;
  mode: 'auto' | 'manual';
  events: ExecutionEvent[];
  active_agent?: string | null;
  target?: string | null;
  current_tool: { id: string; name: string; status: 'running' | 'completed' | 'failed'; elapsed_ms: number | null; verified: boolean; error: string | null } | null;
  evidence_ref: string | null;
};

const STATUS_COPY: Record<string, { label: string; tone: string }> = {
  idle: { label: 'Ready', tone: 'idle' },
  running: { label: 'Running', tone: 'live' },
  approval_pending: { label: 'Awaiting approval', tone: 'warn' },
  completed: { label: 'Completed', tone: 'ok' },
  failed: { label: 'Failed', tone: 'bad' },
  stopped: { label: 'Stopped', tone: 'bad' },
};

function statusMeta(status: string) {
  return STATUS_COPY[status] ?? STATUS_COPY.idle;
}

/**
 * Compact inline execution activity card. Collapsed by default; expands to the
 * authorization facts and full event timeline without leaving the conversation.
 */
export function ExecutionActivity({
  execution, defaultOpen = false,
}: {
  execution: ExecutionView;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const meta = statusMeta(execution.lifecycle_status);
  const phase = deriveExecutionPhase(execution);
  const groups = groupExecutionByObjective(execution);
  const running = execution.lifecycle_status === 'running' || execution.lifecycle_status === 'approval_pending';
  const toolCount = execution.events.filter(e => e.event === 'tool' || e.event === 'tool_completed' || e.event === 'tool_failed').length;
  const lastScope = [...execution.events].reverse().find(e => e.event === 'scope_checked');
  const scopeDenied = lastScope?.allowed === false;
  const scopeApproved = lastScope?.allowed === true;

  return (
    <section className={`ark-exec ${open ? 'ark-exec-open' : ''}`} aria-label="Execution activity">
      <button
        type="button"
        className="ark-exec-bar"
        aria-expanded={open}
        onClick={() => setOpen(v => !v)}
      >
        <span className={`ark-exec-dot ark-exec-dot-${meta.tone}`} aria-hidden="true" />
        <span className="ark-exec-label">{meta.label}</span>
        <span className={`ark-exec-phase ark-exec-phase-${PHASE_TONE[phase]}`}>{phase}</span>
        {running && execution.current_tool && (
          <span className="ark-exec-current">
            {execution.current_tool.status === 'running' && <Loader2 size={12} className="ark-spin" />}
            {execution.current_tool.name}
            {execution.current_tool.elapsed_ms != null && <em>{execution.current_tool.elapsed_ms} ms</em>}
          </span>
        )}
        {execution.active_agent && (
          <span className="ark-exec-specialist">{formatRole(execution.active_agent)}</span>
        )}
        {execution.target && <span className="ark-exec-target">{execution.target}</span>}
        <span className="ark-exec-meta">
          {toolCount > 0 && <span>{toolCount} tool{toolCount === 1 ? '' : 's'}</span>}
          <span className="ark-exec-mode">{execution.mode === 'manual' ? 'Manual' : 'Automatic'}</span>
        </span>
        {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>

      {open && (
        <div className="ark-exec-body">
          <dl className="ark-exec-facts">
            <div>
              <dt>Objective</dt>
              <dd>{execution.objective || '—'}</dd>
            </div>
            <div>
              <dt>Specialist</dt>
              <dd>{execution.active_agent ? formatRole(execution.active_agent) : 'Not yet selected'}</dd>
            </div>
            <div>
              <dt>Authorization</dt>
              <dd className={scopeDenied ? 'ark-exec-bad' : scopeApproved ? 'ark-exec-ok' : undefined}>
                {scopeDenied ? 'Scope denied' : scopeApproved ? 'Scope approved' : 'Not yet validated'}
                {execution.target ? ` · ${execution.target}` : ''}
              </dd>
            </div>
            <div>
              <dt>Objective outcome</dt>
              <dd>{execution.objective_outcome ?? 'pending'}</dd>
            </div>
          </dl>
          {groups.some(g => g.stages.length > 0) && (
            <div className="ark-exec-objectives">
              {groups.map((g, gi) => (
                <div className="ark-exec-objective" key={gi}>
                  <div className="ark-exec-objective-head">
                    <Target size={13} />
                    <span className="ark-exec-objective-title">{g.objective}</span>
                    <span className={`ark-exec-phase ark-exec-phase-${PHASE_TONE[g.phase]}`}>{g.phase}</span>
                    {g.durationMs > 0 && <span className="ark-exec-objective-dur">{g.durationMs} ms</span>}
                  </div>
                  <ul className="ark-exec-stages">
                    {g.stages.map((s, si) => (
                      <li key={si} className={`ark-exec-stage ark-exec-stage-${s.status}`}>
                        <span className="ark-exec-stage-dot" aria-hidden="true" />
                        <span className="ark-exec-stage-name">{s.name}</span>
                        <span className="ark-exec-stage-meta">
                          {s.status === 'running' && <Loader2 size={11} className="ark-spin" />}
                          {s.elapsedMs != null && <em>{s.elapsedMs} ms</em>}
                          {s.status !== 'running' && (
                            <span className={s.verified ? 'ark-exec-ok' : 'ark-exec-bad'}>
                              {s.verified ? 'verified' : s.status === 'failed' ? 'failed' : 'unverified'}
                            </span>
                          )}
                        </span>
                        {s.error && <div className="ark-exec-stage-error">{s.error}</div>}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
          <ol className="ark-exec-timeline">
            {execution.events.slice(-80).map((ev, i) => {
              const raw = rawDetail(ev);
              return (
                <li key={i} className={`ark-exec-event ark-exec-event-${eventTone(ev)}`}>
                  <span className="ark-exec-event-dot" aria-hidden="true" />
                  <div className="ark-exec-event-content">
                    <div className="ark-exec-event-label">{eventLabel(ev)}</div>
                    {eventDetail(ev) && <div className="ark-exec-event-detail">{eventDetail(ev)}</div>}
                    {raw && (
                      <details className="ark-exec-raw">
                        <summary>Raw output</summary>
                        <pre>{raw}</pre>
                      </details>
                    )}
                  </div>
                  {ev.timestamp && <time className="ark-exec-event-time">{new Date(ev.timestamp).toLocaleTimeString()}</time>}
                </li>
              );
            })}
            {!execution.events.length && <li className="ark-exec-empty">No execution events yet.</li>}
          </ol>
        </div>
      )}
    </section>
  );
}

function eventTone(ev: ExecutionEvent): string {
  if (ev.event === 'run_failed' || ev.event === 'tool_failed' || (ev.event === 'scope_checked' && ev.allowed === false)) return 'bad';
  if (ev.event === 'run_cancelled' || ev.event === 'hitl' || ev.event === 'approval_required') return 'warn';
  if (ev.event === 'run_completed' || ev.event === 'tool' || ev.event === 'result_verified') return 'ok';
  return 'neutral';
}

/**
 * Structured final report appended to the conversation when a run ends. Built
 * from the run's own events — never a fabricated narrative.
 */
export function InvestigationReport({ summary, onCopyRunId }: { summary: RunSummary; onCopyRunId?: () => void }) {
  const { outcome } = summary;
  const badge = outcome === 'succeeded' ? { cls: 'ok', icon: <CheckCircle size={14} />, text: 'Objective succeeded' }
    : outcome === 'stopped' ? { cls: 'bad', icon: <Ban size={14} />, text: 'Stopped by operator' }
    : outcome === 'failed' ? { cls: 'bad', icon: <AlertCircle size={14} />, text: 'Objective failed' }
    : outcome === 'inconclusive' ? { cls: 'warn', icon: <AlertCircle size={14} />, text: 'Inconclusive' }
    : { cls: 'warn', icon: <Loader2 size={14} />, text: 'In progress' };

  return (
    <section className="ark-report" aria-label="Investigation report">
      <header className="ark-report-head">
        <span className={`ark-report-badge ark-report-badge-${badge.cls}`}>{badge.icon}{badge.text}</span>
        {summary.runId && (
          <button type="button" className="ark-report-runid" onClick={onCopyRunId} title="Copy run ID">
            <span className="ark-mono">{summary.runId}</span><Copy size={11} />
          </button>
        )}
      </header>

      <div className="ark-report-objective">
        <span className="ark-report-k">Objective</span>
        <span className="ark-report-v">{summary.objective}</span>
      </div>

      {summary.engagement && (
        <div className="ark-report-objective">
          <span className="ark-report-k"><Target size={12} /> Engagement</span>
          <span className="ark-report-v">{summary.engagement}</span>
        </div>
      )}

      <div className="ark-report-section">
        <span className="ark-report-k">Execution summary</span>
        <p className="ark-report-summary">{summary.executionSummary}</p>
      </div>

      <div className="ark-report-section">
        <span className="ark-report-k">Tools executed ({summary.tools.length})</span>
        {summary.tools.length === 0 && <p className="ark-report-empty">No tools were dispatched for this run.</p>}
        {summary.tools.length > 0 && (
          <ul className="ark-report-tools">
            {summary.tools.map((t, i) => (
              <li key={i} className="ark-report-tool">
                <span className={`ark-report-tool-ico ${t.verified ? 'ok' : 'bad'}`}>
                  {t.verified ? <CheckCircle size={13} /> : <AlertCircle size={13} />}
                </span>
                <span className="ark-report-tool-name">{t.name}</span>
                <span className="ark-report-tool-id ark-mono">{t.tool}</span>
                {t.elapsed_ms != null && <span className="ark-report-tool-ms">{t.elapsed_ms} ms</span>}
                <span className={`ark-report-tool-status ${t.verified ? 'ok' : 'bad'}`}>
                  {t.verified ? 'verified' : t.error ? 'failed' : 'unverified'}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="ark-report-grid">
        <div className="ark-report-cell">
          <ShieldCheck size={14} />
          <span className="ark-report-k">Approvals</span>
          <span className="ark-report-v">{summary.approvals}</span>
        </div>
        <div className="ark-report-cell">
          <ShieldAlert size={14} className={summary.scopeDenials ? 'ark-report-warn' : undefined} />
          <span className="ark-report-k">Scope denials</span>
          <span className="ark-report-v">{summary.scopeDenials}</span>
        </div>
        <div className="ark-report-cell">
          <Ban size={14} />
          <span className="ark-report-k">Events</span>
          <span className="ark-report-v">{summary.events}</span>
        </div>
      </div>

      <div className="ark-report-section">
        <span className="ark-report-k"><FileCheck2 size={12} /> Evidence recorded</span>
        {summary.evidenceRefs.length === 0 && <p className="ark-report-empty">No evidence references recorded.</p>}
        <ul className="ark-report-evidence">
          {summary.evidenceRefs.map((ref, i) => <li key={i} className="ark-mono">{ref}</li>)}
        </ul>
      </div>

      {summary.outcome === 'failed' && summary.failureReason && (
        <div className="ark-report-section">
          <span className="ark-report-k">Failure</span>
          <p className="ark-report-failure">{summary.failureReason}</p>
        </div>
      )}

      {summary.recommendations.length > 0 && (
        <div className="ark-report-section">
          <span className="ark-report-k">Recommended next actions</span>
          <ul className="ark-report-reco">
            {summary.recommendations.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      )}

      {summary.verificationBasis && (
        <p className="ark-report-basis">
          Verification basis: {summary.verificationBasis}. Tool results are backend-owned; ARK never
          reports a tool as verified on model output alone.
        </p>
      )}
    </section>
  );
}
