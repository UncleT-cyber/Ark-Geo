/**
 * C.1 — Execution event → investigation slice mapping.
 *
 * One pure function that decides which shared investigation slice(s) a live
 * execution event updates, and what it contributes. The manual UI and the AI
 * run both write the SAME slices through the investigation provider, so the
 * case has a single source of truth rather than two parallel state trees.
 *
 * Pure and dependency-free (no React, no I/O) so it is unit-testable and can be
 * applied from any caller. The provider applies the returned mapping.
 */
import type { AuditEvent, Finding } from './entities.ts';
import { deriveShortId } from './entities.ts';

/** The shared slice an event primarily updates. */
export type EventSlice =
  | 'evidence'
  | 'findings'
  | 'audit'
  | 'run'
  | 'approval'
  | 'execution'
  | 'none';

export interface MappingContext {
  runId: string;
  caseId: string;
  evidenceId?: string;
  /** Injectable clock for deterministic tests. */
  nowMs?: number;
}

export interface InvestigationEventMapping {
  slice: EventSlice;
  /** A finding to fold into the case (stable id already derived). */
  finding?: Finding;
  /** Audit events to append to the chain of custody. */
  audit: AuditEvent[];
  /** Evidence path recorded by the run (evidence slice), if any. */
  evidencePath?: string;
  /** Run lifecycle status derived from the event, if any. */
  runStatus?: 'running' | 'completed' | 'failed' | 'stopped' | 'approval_pending';
  /** True when the event requires operator approval before continuing. */
  requiresApproval?: boolean;
}

const _CLAIM_KEYS = ['claim', 'label', 'message', 'summary', 'detail', 'title'] as const;

/** A tool result is a failure when the backend marked it error/denied. */
function _isFailed(result: unknown, verified: boolean | undefined): boolean {
  if (verified === false) return true;
  if (typeof result === 'object' && result !== null) {
    const status = (result as Record<string, unknown>).status;
    return status === 'error' || status === 'denied';
  }
  return false;
}

/** The human-readable claim a tool result carries, if it carries one. */
function _claimFrom(result: unknown): string | null {
  if (result == null) return null;
  if (typeof result === 'string') return result.trim() || null;
  if (typeof result === 'object') {
    const obj = result as Record<string, unknown>;
    for (const key of _CLAIM_KEYS) {
      const v = obj[key];
      if (typeof v === 'string' && v.trim()) return v.trim();
    }
  }
  return null;
}

/**
 * Map one execution event to the slice(s) it updates. Never throws; unknown
 * events map to the execution timeline only (no case mutation).
 */
export function mapExecutionEvent(
  ev: Record<string, any>,
  ctx: MappingContext,
): InvestigationEventMapping {
  const now = ctx.nowMs ?? Date.now();
  const { runId, caseId, evidenceId } = ctx;
  const audit: AuditEvent[] = [];
  const event = String(ev?.event ?? '');

  switch (event) {
    case 'tool': {
      const tool = String(ev.tool ?? 'tool');
      const verified = ev.verified === true;
      const failed = _isFailed(ev.result, ev.verified);
      audit.push({
        id: deriveShortId('AUD', 'TOOL' + runId + tool + String(ev.execution_id ?? '')),
        caseId, evidenceId, runId, timestamp: now,
        action: `ARK AI tool: ${tool} ${failed ? 'failed' : 'completed'}`,
        detail: `${ev.elapsed_ms ?? 0} ms · ${verified ? 'verified' : 'unverified'}`,
        actor: 'ark-ai',
      });
      const claim = _claimFrom(ev.result);
      if (claim && !failed) {
        return {
          slice: 'findings',
          audit,
          finding: {
            id: deriveShortId('FND', 'TOOL' + runId + tool + claim),
            runId, caseId,
            type: tool.toUpperCase(),
            severity: 'LOW',
            status: 'INFO',
            message: claim,
          },
        };
      }
      return { slice: 'audit', audit };
    }

    case 'evidence_recorded': {
      const path = typeof ev.evidence_path === 'string' ? ev.evidence_path : undefined;
      audit.push({
        id: deriveShortId('AUD', 'EVD' + runId + (path ?? '')),
        caseId, evidenceId, runId, timestamp: now,
        action: 'Evidence recorded',
        detail: path ?? 'run evidence bundle',
        actor: 'ark-ai',
      });
      return { slice: 'evidence', audit, evidencePath: path };
    }

    case 'result_verified': {
      audit.push({
        id: deriveShortId('AUD', 'VER' + runId + String(ev.tool ?? '')),
        caseId, evidenceId, runId, timestamp: now,
        action: `Result ${ev.verified ? 'verified' : 'unverified'}`,
        detail: String(ev.basis ?? ''),
        actor: 'system',
      });
      return { slice: 'findings', audit };
    }

    case 'run_created':
      return { slice: 'run', audit, runStatus: 'running' };
    case 'run_completed':
      return { slice: 'run', audit, runStatus: 'completed' };
    case 'run_failed':
      return { slice: 'run', audit, runStatus: 'failed' };
    case 'run_cancelled':
      return { slice: 'run', audit, runStatus: 'stopped' };
    case 'hitl':
    case 'approval_required':
      return { slice: 'approval', audit, requiresApproval: true, runStatus: 'approval_pending' };

    default:
      return { slice: 'execution', audit };
  }
}
