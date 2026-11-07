/**
 * Application notifications — derived from real backend events.
 *
 * Nothing here is fabricated. Notifications are produced from the same global
 * Event Bus stream (`/cai/events`) the rest of the workbench consumes, plus
 * the run lifecycle the orchestrator publishes. Each notification carries the
 * investigation (session) and run it belongs to so a click can navigate to the
 * associated tab or execution record.
 *
 * Only identifiers and short summaries are held — never evidence contents,
 * coordinates or credentials.
 */

export type NotificationKind =
  | 'agent_completed'
  | 'run_failed'
  | 'approval_request'
  | 'security_alert';

export interface AppNotification {
  id: string;
  kind: NotificationKind;
  title: string;
  detail: string;
  /** Backend investigation/session id this belongs to (navigation target). */
  sessionId: string | null;
  runId: string | null;
  ts: number;
  read: boolean;
}

const CAP = 100;

export const NOTIFICATION_META: Record<NotificationKind, { label: string; tone: 'ok' | 'error' | 'warn' }> = {
  agent_completed: { label: 'Completed', tone: 'ok' },
  run_failed: { label: 'Failed', tone: 'error' },
  approval_request: { label: 'Approval', tone: 'warn' },
  security_alert: { label: 'Security', tone: 'error' },
};

function uid(): string {
  return `ntf-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

/**
 * Derive a notification from a single backend event, or return null when the
 * event is not notification-worthy. Kept pure so it is unit-testable.
 */
export function notificationFromEvent(ev: Record<string, any>): AppNotification | null {
  const category = String(ev.category ?? ev.event ?? '');
  const sessionId = ev.session_id ?? null;
  const runId = ev.run_id ?? null;
  const tool = ev.tool ?? ev.detail?.tool ?? '';

  // Human-in-the-loop approval requested by the orchestrator.
  if (category === 'hitl' || category === 'approval_required') {
    return {
      id: uid(), kind: 'approval_request', ts: Date.now(), read: false,
      sessionId, runId,
      title: 'Approval required',
      detail: tool ? `Tool "${tool}" is waiting for operator approval.` : 'A tool is waiting for operator approval.',
    };
  }

  // Engagement-scope denial or blocked tool — a security-relevant alert.
  if (category === 'scope_checked' && ev.allowed === false) {
    return {
      id: uid(), kind: 'security_alert', ts: Date.now(), read: false,
      sessionId, runId,
      title: 'Engagement scope blocked a call',
      detail: String(ev.reason ?? ev.message ?? 'A target outside the authorized engagement was denied.'),
    };
  }
  if (category === 'tool_denied' || category === 'tool.denied') {
    return {
      id: uid(), kind: 'security_alert', ts: Date.now(), read: false,
      sessionId, runId,
      title: 'Tool denied by policy',
      detail: tool ? `Tool "${tool}" was denied by execution policy.` : 'A tool was denied by execution policy.',
    };
  }

  // Run lifecycle outcomes.
  if (category === 'run_failed' || (category === 'error' && ev.code)) {
    return {
      id: uid(), kind: 'run_failed', ts: Date.now(), read: false,
      sessionId, runId,
      title: 'Run failed',
      detail: String(ev.message ?? ev.error ?? 'The investigation run failed.'),
    };
  }
  if (category === 'run_completed' || (category === 'agent.status' && ev.stage === 'completed')) {
    return {
      id: uid(), kind: 'agent_completed', ts: Date.now(), read: false,
      sessionId, runId,
      title: 'Investigation completed',
      detail: 'The ARK agent finished this investigation run.',
    };
  }

  return null;
}

export function pushNotification(
  list: AppNotification[],
  n: AppNotification,
): AppNotification[] {
  const next = [n, ...list];
  return next.length > CAP ? next.slice(0, CAP) : next;
}

/** Build a notification from an explicit kind/detail (used by live UI events). */
export function makeNotification(
  kind: NotificationKind,
  title: string,
  detail: string,
  sessionId: string | null = null,
  runId: string | null = null,
): AppNotification {
  return { id: uid(), kind, title, detail, sessionId, runId, ts: Date.now(), read: false };
}

export function unreadCount(list: AppNotification[]): number {
  return list.reduce((n, item) => n + (item.read ? 0 : 1), 0);
}
