/**
 * Investigation tab registry — ONE store for investigation tabs.
 *
 * A tab is a *descriptor* for an investigation: its stable id (the backend
 * session id), a title, the owning domain, a run-status hint and a revision.
 * It deliberately holds NO forensic content — no transcript, no evidence, no
 * audit records. Those remain the backend's (see `/cai/sessions`). This keeps
 * a single source of truth: the registry is navigation metadata, the backend
 * is the investigation.
 *
 * Cross-window synchronization is *merge-based*, not last-writer-wins: each
 * tab carries a monotonically increasing `rev` and the id of the window that
 * last wrote it. A merge keeps the higher revision and breaks ties by origin
 * id, so two windows editing the same tab converge instead of clobbering each
 * other. Only metadata travels — never credentials or evidence.
 */
import { tabStorage, storageLabel } from '../storage';

export const TABS_KEY = 'ark.investigationTabs';
export const ACTIVE_KEY = 'ark.activeInvestigationTab';

export type TabRunStatus = 'idle' | 'running' | 'completed' | 'failed' | 'interrupted';

export interface InvestigationTab {
  /** Stable client tab id (unique per tab in this registry). */
  id: string;
  /** Backend durable session id once the investigation has started. */
  sessionId: string | null;
  title: string;
  domain: 'system' | 'image' | 'network' | 'secops' | 'cases' | 'telecom' | 'settings';
  caseId: string | null;
  runStatus: TabRunStatus;
  /** Monotonic revision, bumped on every write. */
  rev: number;
  /** Id of the window that last wrote this tab (conflict tie-break). */
  origin: string;
  createdAt: number;
  updatedAt: number;
  /** Tombstone. A closed tab is kept in the store marked deleted (with a
   *  bumped rev) so the merge — which is a union — can propagate the removal
   *  to other windows instead of resurrecting the tab. Deleted records are
   *  filtered out of the UI list. */
  deleted?: boolean;
}

export interface TabRegistrySnapshot {
  tabs: InvestigationTab[];
  /** Per-window active tab — never synchronized across windows. */
  activeId: string | null;
}

/** Stable per-window id. Kept in sessionStorage so each window is distinct. */
function resolveWindowId(): string {
  const KEY = 'ark.windowId';
  try {
    const existing = sessionStorage.getItem(KEY);
    if (existing) return existing;
    const id = `win-${Math.random().toString(36).slice(2, 10)}`;
    sessionStorage.setItem(KEY, id);
    return id;
  } catch {
    return `win-${Math.random().toString(36).slice(2, 10)}`;
  }
}

export const WINDOW_ID = resolveWindowId();

export function newTabId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return `sess-${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
}

function isTab(value: unknown): value is InvestigationTab {
  if (!value || typeof value !== 'object') return false;
  const t = value as Record<string, unknown>;
  return typeof t.id === 'string' && typeof t.title === 'string' && typeof t.rev === 'number';
}

/** Read the shared tab list (live tabs only). Active selection is per-window. */
export function loadTabs(): InvestigationTab[] {
  return loadAllTabs().filter(t => !t.deleted);
}

/** Read every record including tombstones — used by the merge. */
export function loadAllTabs(): InvestigationTab[] {
  try {
    const raw = tabStorage.get(TABS_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    // Normalize legacy records written before `sessionId` existed.
    return Array.isArray(arr) ? arr.filter(isTab).map(t => ({ ...t, sessionId: t.sessionId ?? null })) : [];
  } catch {
    return [];
  }
}

export function saveTabs(tabs: InvestigationTab[]): void {
  tabStorage.set(TABS_KEY, JSON.stringify(tabs));
}

export function loadActiveId(): string | null {
  try { return sessionStorage.getItem(ACTIVE_KEY); } catch { return null; }
}

export function saveActiveId(id: string | null): void {
  try {
    if (id) sessionStorage.setItem(ACTIVE_KEY, id);
    else sessionStorage.removeItem(ACTIVE_KEY);
  } catch { /* non-blocking */ }
}

/**
 * Merge two tab lists conflict-safely. For a tab present in both, the higher
 * `rev` wins; equal revisions break by `origin` (lexicographic) so the result
 * is deterministic and identical in every window.
 */
export function mergeTabs(a: InvestigationTab[], b: InvestigationTab[]): InvestigationTab[] {
  const byId = new Map<string, InvestigationTab>();
  for (const tab of [...a, ...b]) {
    const existing = byId.get(tab.id);
    if (!existing) { byId.set(tab.id, tab); continue; }
    if (tab.rev > existing.rev) byId.set(tab.id, tab);
    else if (tab.rev === existing.rev && tab.origin > existing.origin) byId.set(tab.id, tab);
  }
  return [...byId.values()].sort((x, y) => x.createdAt - y.createdAt);
}

export function makeTab(
  partial: Partial<InvestigationTab> & { id: string; title: string },
): InvestigationTab {
  const now = Date.now();
  return {
    id: partial.id,
    sessionId: partial.sessionId ?? null,
    title: partial.title,
    domain: partial.domain ?? 'image',
    caseId: partial.caseId ?? null,
    runStatus: partial.runStatus ?? 'idle',
    rev: partial.rev ?? 1,
    origin: partial.origin ?? WINDOW_ID,
    createdAt: partial.createdAt ?? now,
    updatedAt: now,
    deleted: partial.deleted ?? false,
  };
}

/** Bump a tab's revision and stamp this window as the writer. */
export function touchTab(tab: InvestigationTab, patch: Partial<InvestigationTab>): InvestigationTab {
  return { ...tab, ...patch, rev: tab.rev + 1, origin: WINDOW_ID, updatedAt: Date.now() };
}

export { storageLabel };
