/**
 * NeutralWorkspace — the central New Investigation canvas.
 *
 * Three states, driven by the investigation's REAL lifecycle (the same
 * per-investigation `execution` slice the ARK dock conversation writes —
 * no second event stream, no simulated progress):
 *
 *   Empty    — no activity yet: a calm "Ready to investigate" composition
 *              with the existing Attach evidence / Create case actions.
 *   Live     — the activity timeline: one row per event the backend
 *              actually emitted (tools, scope checks, approvals, evidence),
 *              plus genuinely queued objectives.
 *   Done     — the timeline is retained and a compact completion summary is
 *              appended, built from the run's own events (never fabricated).
 *
 * The sidebar remains the navigation surface: this component never offers
 * competing workspace cards.
 */
import React, { useMemo } from 'react';
import {
  Paperclip, FolderPlus, CheckCircle, AlertCircle, Loader2, ShieldAlert,
  Ban, Circle, FileText, FolderSearch,
} from 'lucide-react';
import { useInvestigation } from './useInvestigation';
import { useInvestigationSlice } from '../../core/investigation/InvestigationStoreContext';
import {
  buildActivityTimeline, summarizeRun, timelineStatusLabel,
  initialExecutionState,
  type ExecutionState, type QueueEntry, type TimelineRow, type TimelineStatus,
} from './executionPresentation';

interface NeutralWorkspaceProps {
  /** Investigation title (its identity line). */
  title: string;
  /** Investigation / case identifiers, for the identity line. */
  investigationId: string;
  caseId: string | null;
  /** Tab-level run status (belt-and-braces for "a run is live"). */
  runStatus?: string;
  /** Attach evidence — the existing upload mechanism. */
  onAttachEvidence: () => void;
  /** Create case — the existing Save-to-Case-Vault flow. */
  onCreateCase: () => void;
  /** Open the Case Explorer. */
  onOpenCase: () => void;
  /** Open the existing Case / Report view. */
  onOpenReport: () => void;
}

const STATUS_ICON: Record<TimelineStatus, React.ReactNode> = {
  pending: <Circle size={13} />,
  running: <Loader2 size={13} className="ark-spin" />,
  completed: <CheckCircle size={13} />,
  failed: <AlertCircle size={13} />,
  approval: <ShieldAlert size={13} />,
  cancelled: <Ban size={13} />,
  skipped: <Circle size={13} />,
};

const OUTCOME_LABEL: Record<string, string> = {
  succeeded: 'Completed',
  failed: 'Failed',
  stopped: 'Stopped',
  inconclusive: 'Completed · inconclusive',
  pending: 'In progress',
};

function RowIcon({ status }: { status: TimelineStatus }) {
  return <span className={`inv-timeline-ico inv-ico-${status}`} aria-hidden="true">{STATUS_ICON[status]}</span>;
}

export function NeutralWorkspace({
  title, investigationId, caseId, runStatus = 'idle',
  onAttachEvidence, onCreateCase, onOpenCase, onOpenReport,
}: NeutralWorkspaceProps) {
  const inv = useInvestigation();
  // The SAME per-investigation slices the ARK dock writes — the canvas and
  // the conversation can never disagree about what is happening.
  const [execution] = useInvestigationSlice<ExecutionState>('execution', initialExecutionState);
  const [queue] = useInvestigationSlice<QueueEntry[]>('queue', () => []);

  const lifecycle = execution.lifecycle_status;
  const lifecycleActive = lifecycle === 'running' || lifecycle === 'approval_pending';
  // The execution slice is the authoritative run state. The tab-level run
  // status only fills the gap before `run_created` lands on the slice — a
  // stale tab dot must never keep the canvas out of its completion state.
  const hasRunState = execution.run_id != null || execution.events.length > 0;
  const active = lifecycleActive || (runStatus === 'running' && !hasRunState);
  const started =
    active ||
    hasRunState ||
    lifecycle === 'completed' || lifecycle === 'failed' || lifecycle === 'stopped' ||
    runStatus === 'completed' || runStatus === 'failed' || runStatus === 'interrupted';

  const mode: 'empty' | 'live' | 'done' = active ? 'live' : started ? 'done' : 'empty';

  const rows = useMemo<TimelineRow[]>(
    () => (mode === 'empty' ? [] : buildActivityTimeline(execution, queue)),
    [mode, execution, queue],
  );
  const summary = useMemo(
    () => (mode === 'done' ? summarizeRun(execution) : null),
    [mode, execution],
  );

  const completedOps = rows.filter(r => r.status === 'completed').length;
  const failedOps = rows.filter(r => r.status === 'failed').length;
  const outcomeLabel = summary ? OUTCOME_LABEL[summary.outcome] ?? summary.outcome : '';
  const hasCase = !!inv.activeCase;

  return (
    <div className="neutral-workspace">
      {/* Identity header — unchanged structure, dynamic identifiers. */}
      <header className="neutral-workspace-head">
        <div className="neutral-workspace-identity">
          <span className="neutral-workspace-kicker">Investigation</span>
          <h1 className="neutral-workspace-title">{title}</h1>
          <div className="neutral-workspace-ids mono">
            <span>INV {investigationId.slice(0, 8)}</span>
            {caseId && <span>· CASE {caseId}</span>}
            {!caseId && <span className="neutral-workspace-nocase">· no case yet</span>}
          </div>
        </div>
      </header>

      <div className="neutral-workspace-body">
        {mode === 'empty' ? (
          /* ── State A: minimal investigation canvas ───────────────────── */
          <div className="inv-canvas-empty">
            <strong>Ready to investigate</strong>
            <p>Start with ARK, attach evidence, or open a workspace from the sidebar.</p>
            <div className="inv-canvas-actions">
              <button type="button" className="inv-canvas-btn" onClick={onAttachEvidence}>
                <Paperclip size={14} aria-hidden="true" /> Attach evidence
              </button>
              <button type="button" className="inv-canvas-btn" onClick={onCreateCase}>
                <FolderPlus size={14} aria-hidden="true" /> Create case
              </button>
            </div>
          </div>
        ) : (
          /* ── State B/C: live activity timeline (+ completion summary) ── */
          <div className="inv-canvas-live">
            <div className="inv-canvas-section-head">
              <h2>Investigation activity</h2>
              {active && (
                <span className={`inv-canvas-live-badge inv-badge-${lifecycle === 'approval_pending' ? 'approval' : 'running'}`}>
                  <Loader2 size={11} className="ark-spin" aria-hidden="true" />
                  {lifecycle === 'approval_pending' ? 'Awaiting approval' : 'Running'}
                </span>
              )}
            </div>

            <ol className="inv-timeline">
              {rows.map(row => (
                <li key={row.key} className={`inv-timeline-row inv-row-${row.status}`}>
                  <RowIcon status={row.status} />
                  <div className="inv-timeline-main">
                    <div className="inv-timeline-label">{row.label}</div>
                    {row.detail && <div className="inv-timeline-detail">{row.detail}</div>}
                    {row.error && <div className="inv-timeline-error">{row.error}</div>}
                  </div>
                  <div className="inv-timeline-side">
                    <span className="inv-timeline-status">{timelineStatusLabel(row.status)}</span>
                    {row.timestamp && (
                      <time className="inv-timeline-time">{new Date(row.timestamp).toLocaleTimeString()}</time>
                    )}
                  </div>
                </li>
              ))}
              {!rows.length && (
                <li className="inv-timeline-empty">No execution events were recorded for this investigation.</li>
              )}
            </ol>

            {mode === 'done' && summary && hasRunState && (
              <section className="inv-summary" aria-label="Completion summary">
                <div className="inv-canvas-section-head">
                  <h2>Completion summary</h2>
                  <span className={`inv-summary-outcome inv-outcome-${summary.outcome}`}>{outcomeLabel}</span>
                </div>

                <div className="inv-summary-grid">
                  <div className="inv-summary-cell">
                    <span className="inv-summary-k">Status</span>
                    <span className="inv-summary-v">{outcomeLabel}</span>
                  </div>
                  <div className="inv-summary-cell">
                    <span className="inv-summary-k">Operations</span>
                    <span className="inv-summary-v">
                      {completedOps} completed{failedOps > 0 ? ` · ${failedOps} failed` : ''}
                    </span>
                  </div>
                  <div className="inv-summary-cell">
                    <span className="inv-summary-k">Findings</span>
                    <span className="inv-summary-v">{inv.findings.length}</span>
                  </div>
                  <div className="inv-summary-cell">
                    <span className="inv-summary-k">Evidence</span>
                    <span className="inv-summary-v">{summary.evidenceRefs.length}</span>
                  </div>
                  <div className="inv-summary-cell">
                    <span className="inv-summary-k">Related case</span>
                    <span className="inv-summary-v">{inv.activeCase ? inv.activeCase.title || inv.activeCase.id : 'No case yet'}</span>
                  </div>
                  <div className="inv-summary-cell">
                    <span className="inv-summary-k">Report</span>
                    <span className="inv-summary-v">{hasCase ? 'Available' : 'Not yet generated'}</span>
                  </div>
                </div>

                {summary.failureReason && (
                  <p className="inv-summary-failure">{summary.failureReason}</p>
                )}

                {hasCase ? (
                  <div className="inv-summary-links">
                    <button type="button" className="inv-canvas-btn" onClick={onOpenReport}>
                      <FileText size={14} aria-hidden="true" /> Open case report
                    </button>
                    <button type="button" className="inv-canvas-btn" onClick={onOpenCase}>
                      <FolderSearch size={14} aria-hidden="true" /> Open Case Explorer
                    </button>
                  </div>
                ) : (
                  <p className="inv-summary-note">
                    Save this investigation to a case to unlock the forensic report.
                  </p>
                )}
              </section>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
