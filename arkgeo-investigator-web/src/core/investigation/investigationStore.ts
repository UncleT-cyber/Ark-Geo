/**
 * Investigation-keyed state model.
 *
 * THE ARK distinguishes, and never conflates:
 *
 *   tabId            — the visual tab (registry descriptor; merge-safe, durable)
 *   investigationId  — the investigation's identity (== its tab id today)
 *   conversationId   — the identity of the investigation's conversation
 *   sessionId        — the backend durable session, assigned when a run starts
 *   caseId           — the associated case/evidence record, when one exists
 *   runId            — one particular backend execution
 *   workspaceId      — the active workspace selection for that investigation
 *
 * A tab *points to* an investigation; the investigation owns its conversation,
 * execution history, workspace selection and case data. Two tabs representing
 * different investigations never share mutable investigation state.
 *
 * This module holds the investigation-keyed model and the durable *metadata*
 * store. It deliberately persists NO conversation content and NO evidence: the
 * transcript and run/evidence records are the backend's, behind the encrypted
 * session API (`/cai/sessions`), and honour Zero-Retention mode. Only
 * identifiers, the workspace selection and a status hint are written locally —
 * exactly the same discipline as the tab registry.
 */
import type { DomainId } from '../../components/workbench/entities';
import { tabStorage } from '../storage';

export const INVESTIGATIONS_KEY = 'ark.investigations';

/** Stable id for a new investigation. */
export function newInvestigationId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return `inv-${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
}

export function newConversationId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return `conv-${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
}

/** The workspace an investigation is currently showing. */
export interface InvestigationWorkspaceSelection {
  /**
   * True until the operator picks a workspace. A new investigation starts
   * neutral: the central area shows the clean investigation workspace (ARK's
   * conversation + workspace selection), never Image Intelligence's System
   * Overview. Selecting any workspace clears this flag.
   */
  neutral: boolean;
  domain: DomainId;
  /** IMAGE sub-view id (see IMAGE_SUBVIEWS) — a plain string here so core has
   *  no dependency on the workbench component layer. */
  imageSubview: string;
  /** NETWORK tab id — plain string, same rationale. */
  networkTab: string;
  /** A workspace tool taking over the central area (e.g. 'browser'), or null. */
  workspaceTool: string | null;
}

export type InvestigationRunStatus =
  | 'idle' | 'running' | 'completed' | 'failed' | 'interrupted';

/** Durable, content-free metadata for one investigation. */
export interface InvestigationMeta {
  id: string;
  conversationId: string;
  title: string;
  /** Backend durable session id once a run has started. */
  sessionId: string | null;
  caseId: string | null;
  lastRunId: string | null;
  runStatus: InvestigationRunStatus;
  workspace: InvestigationWorkspaceSelection;
  zeroRetention: boolean;
  createdAt: number;
  updatedAt: number;
}

export function defaultWorkspaceSelection(): InvestigationWorkspaceSelection {
  return { neutral: true, domain: 'image', imageSubview: 'overview', networkTab: 'discovery', workspaceTool: null };
}

/**
 * Create a fresh investigation. It starts on the neutral investigation
 * workspace; a new investigation never creates a case record.
 */
export function makeInvestigation(
  partial: Partial<InvestigationMeta> & { id?: string; title?: string } = {},
): InvestigationMeta {
  const now = Date.now();
  return {
    id: partial.id ?? newInvestigationId(),
    conversationId: partial.conversationId ?? newConversationId(),
    title: partial.title ?? 'New investigation',
    sessionId: partial.sessionId ?? null,
    caseId: partial.caseId ?? null,
    lastRunId: partial.lastRunId ?? null,
    runStatus: partial.runStatus ?? 'idle',
    workspace: partial.workspace ?? defaultWorkspaceSelection(),
    zeroRetention: partial.zeroRetention ?? false,
    createdAt: partial.createdAt ?? now,
    updatedAt: partial.updatedAt ?? now,
  };
}

function isMeta(value: unknown): value is InvestigationMeta {
  if (!value || typeof value !== 'object') return false;
  const m = value as Record<string, unknown>;
  return typeof m.id === 'string' && typeof m.conversationId === 'string';
}

/** Read every persisted investigation metadata record. */
export function loadInvestigations(): InvestigationMeta[] {
  try {
    const raw = tabStorage.get(INVESTIGATIONS_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    if (!Array.isArray(arr)) return [];
    return arr.filter(isMeta).map(m => ({
      ...m,
      workspace: { ...defaultWorkspaceSelection(), ...(m.workspace || {}) },
    }));
  } catch {
    return [];
  }
}

export function saveInvestigations(list: InvestigationMeta[]): void {
  // Cap the durable set so a long-lived vault cannot grow without bound. The
  // most recently touched records win; content is never stored here.
  const capped = [...list]
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .slice(0, 200);
  try { tabStorage.set(INVESTIGATIONS_KEY, JSON.stringify(capped)); } catch { /* quota / private mode */ }
}
