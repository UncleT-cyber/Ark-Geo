/**
 * agentOrchestrator.ts — Level-4 RE-ACT client orchestrator.
 *
 * Thin, typed coordinator between the Security Testing workspace and the
 * backend chain (`app/agent/react_chain.py` → `POST /react/run`). It exists
 * so the UI never talks to the chain ad-hoc: all runs flow through one
 * orchestrator that enforces the client-side authorization contract, builds
 * the target payload from the attested scope, and keeps a session registry
 * for polling.
 *
 * Chain: Plan → Scan → Exploit → Escalate → Mitigate.
 * Authorization: every run REQUIRES `authorized = true` (from the signed
 * engagement attestation) + an operator identity. The backend refuses to
 * start otherwise; this module refuses to even dispatch.
 */
import { api } from '../../api';
import type {
  ReactRequestPayload,
  ReactSession,
  ReactSessionSummary,
  ReactTarget,
} from '../../types';

export type EngagementMode = 'active' | 'dry_run';

/** Client-side enforcement of the authorization gate (mirrors the backend). */
export interface AuthorizationContext {
  operator: string;
  authorized: boolean;
  scope: string;           // attested target scope (free-text, for the record)
  signature: string | null;
}

export interface RunReactOptions {
  target: ReactTarget;
  mode?: EngagementMode;
  notes?: string;
  budget?: Record<string, number>;
}

/** Build a RE-ACT target payload from a host + optional web surface. */
export function targetFromScope(kind: ReactTarget['kind'], scope: string): ReactTarget {
  const host = scope.split(/\s+/)[0] || '';
  const base: ReactTarget = { kind };
  if (kind === 'network') {
    return { ...base, host: host || null, ports: '' };
  }
  if (kind === 'web') {
    const looksLikeUrl = /^https?:\/\//i.test(host);
    return {
      ...base,
      target_url: looksLikeUrl ? host : `https://${host}`,
      host: looksLikeUrl ? new URL(host).hostname : host || null,
    };
  }
  if (kind === 'host') {
    return { ...base, host: host || null };
  }
  return base;
}

const SESSION_KEY = 'ark_react_sessions';

class ReactOrchestrator {
  private sessions: ReactSessionSummary[] = [];

  constructor() {
    this.restore();
  }

  /** The active run can only proceed with a verified attestation. */
  assertAuthorized(ctx: AuthorizationContext): void {
    if (!ctx.authorized || !ctx.operator.trim()) {
      throw new Error(
        'RE-ACT requires an explicit authorized engagement — sign the attestation first.',
      );
    }
  }

  /**
   * Run the full chain against an authorized target.
   * Authorization is checked client-side AND re-checked by the backend.
   */
  async run(ctx: AuthorizationContext, opts: RunReactOptions): Promise<ReactSession> {
    this.assertAuthorized(ctx);
    const payload: ReactRequestPayload = {
      operator: ctx.operator,
      authorized: ctx.authorized,
      target: opts.target,
      mode: opts.mode ?? 'dry_run',
      notes: opts.notes ?? `scope: ${ctx.scope}${ctx.signature ? ` · ${ctx.signature}` : ''}`,
      budget: opts.budget ?? {},
    };
    const session = await api.runReactChain(payload);
    this.remember(session);
    return session;
  }

  /** Poll a session by id. */
  async refresh(sessionId: string): Promise<ReactSession> {
    return api.getReactSession(sessionId);
  }

  /** Recent sessions, newest first. */
  history(): ReactSessionSummary[] {
    return [...this.sessions];
  }

  async reloadHistory(): Promise<ReactSessionSummary[]> {
    try {
      this.sessions = await api.listReactSessions();
      this.persist();
    } catch {
      // Backend unreachable — keep the local registry.
    }
    return this.history();
  }

  /** Derive the operator identity from the attestation record. */
  operatorFromAttestation(record: { user: string; fullName?: string } | null): string {
    return record?.user || record?.fullName || 'analyst';
  }

  // ------------------------------------------------------------------- //
  private remember(session: ReactSession): void {
    this.sessions = [
      {
        session_id: session.session_id,
        case_id: session.case_id,
        status: session.status,
        kind: session.request.target.kind,
        target: this.describeTarget(session.request.target),
        operator: session.request.operator,
        updated_at_ms: session.updated_at_ms,
      },
      ...this.sessions.filter(s => s.session_id !== session.session_id),
    ].slice(0, 50);
    this.persist();
  }

  private describeTarget(t: ReactTarget): string {
    if (t.host) return t.host;
    if (t.target_url) return t.target_url;
    if (t.safety_config_path) return t.safety_config_path;
    if (t.hash_value) return `${t.hash_type || 'hash'} hash`;
    return t.kind;
  }

  private persist(): void {
    try {
      localStorage.setItem(SESSION_KEY, JSON.stringify(this.sessions));
    } catch {
      // Storage unavailable — in-memory registry still works.
    }
  }

  private restore(): void {
    try {
      const raw = localStorage.getItem(SESSION_KEY);
      if (raw) this.sessions = JSON.parse(raw) as ReactSessionSummary[];
    } catch {
      this.sessions = [];
    }
  }
}

export const reactOrchestrator = new ReactOrchestrator();
