/**
 * useInvestigationTabs — the investigation tab surface.
 *
 * Owns the tab list (shared across windows via BroadcastChannel + storage) and
 * this window's active tab (local only, never synchronized). It does NOT own
 * investigation content: opening a tab returns its descriptor so the caller
 * can rehydrate the real transcript/run state from the backend.
 *
 * Conflict safety: writes go through `mergeTabs`, which keeps the higher
 * revision per tab. Two windows editing different tabs never clobber each
 * other; edits to the *same* tab converge deterministically.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  InvestigationTab,
  TabRunStatus,
  WINDOW_ID,
  loadActiveId,
  loadAllTabs,
  loadTabs,
  makeTab,
  mergeTabs,
  newTabId,
  saveActiveId,
  saveTabs,
  touchTab,
} from './tabRegistry';

const CHANNEL = 'ark.investigationTabs';
// Closed tabs are retained as tombstones long enough for the union merge to
// propagate the removal to other windows, then pruned.
const TOMBSTONE_TTL_MS = 24 * 60 * 60 * 1000;

function pruneTombstones(tabs: InvestigationTab[]): InvestigationTab[] {
  const now = Date.now();
  return tabs.filter(t => !t.deleted || now - t.updatedAt < TOMBSTONE_TTL_MS);
}

interface TabsApi {
  tabs: InvestigationTab[];
  activeId: string | null;
  activeTab: InvestigationTab | null;
  /** Create a tab and make it active. Returns the new tab id. */
  createTab: (partial?: Partial<InvestigationTab> & { title?: string }) => string;
  /** Activate an existing tab. */
  selectTab: (id: string) => void;
  /** Close a tab (never cancels the underlying run). */
  closeTab: (id: string) => void;
  /** Rename / re-domain / update status; bumps the revision. */
  updateTab: (id: string, patch: Partial<InvestigationTab>) => void;
  /** Bind a backend session id to the active tab, or create one if none. */
  ensureTab: (sessionId: string, partial?: Partial<InvestigationTab>) => void;
  /** Bind a backend session id to the active investigation without switching
   *  the active tab (used for live run events — never re-keys the store). */
  bindSession: (sessionId: string, partial?: Partial<InvestigationTab>) => void;
  setRunStatus: (sessionId: string, status: TabRunStatus) => void;
}

function broadcast(channel: BroadcastChannel | null, tabs: InvestigationTab[]) {
  if (!channel) return;
  try { channel.postMessage({ type: 'tabs', tabs }); } catch { /* non-blocking */ }
}

export function useInvestigationTabs(): TabsApi {
  const [tabs, setTabs] = useState<InvestigationTab[]>(() => loadTabs());
  const [activeId, setActiveId] = useState<string | null>(() => loadActiveId());
  const channelRef = useRef<BroadcastChannel | null>(null);
  // Guard so our own broadcast does not echo back as a remote change.
  const lastWritten = useRef<InvestigationTab[]>(tabs);

  const commit = useCallback((next: InvestigationTab[]) => {
    const merged = pruneTombstones(mergeTabs(next, lastWritten.current));
    lastWritten.current = merged;
    saveTabs(merged);
    setTabs(merged.filter(t => !t.deleted));
    broadcast(channelRef.current, merged);
  }, []);

  useEffect(() => {
    let channel: BroadcastChannel | null = null;
    try {
      if (typeof BroadcastChannel !== 'undefined') {
        channel = new BroadcastChannel(CHANNEL);
        channelRef.current = channel;
        channel.onmessage = (ev: MessageEvent) => {
          const msg = ev.data;
          if (!msg || msg.type !== 'tabs' || !Array.isArray(msg.tabs)) return;
          // Merge remote metadata in; never touch this window's active tab.
          const merged = pruneTombstones(mergeTabs(msg.tabs, lastWritten.current));
          lastWritten.current = merged;
          saveTabs(merged);
          setTabs(merged.filter(t => !t.deleted));
        };
      }
    } catch { /* BroadcastChannel unavailable — single-window mode */ }

    // Fallback for windows without BroadcastChannel: react to storage writes.
    const onStorage = (e: StorageEvent) => {
      if (e.key !== 'ark.investigationTabs') return;
      const merged = pruneTombstones(mergeTabs(loadAllTabs(), lastWritten.current));
      lastWritten.current = merged;
      setTabs(merged.filter(t => !t.deleted));
    };
    window.addEventListener('storage', onStorage);

    return () => {
      window.removeEventListener('storage', onStorage);
      try { channel?.close(); } catch { /* non-blocking */ }
      channelRef.current = null;
    };
  }, []);

  useEffect(() => { saveActiveId(activeId); }, [activeId]);

  const createTab = useCallback((partial?: Partial<InvestigationTab> & { title?: string }) => {
    const id = partial?.id ?? newTabId();
    const tab = makeTab({ ...partial, id, title: partial?.title ?? 'New investigation' });
    commit([...lastWritten.current, tab]);
    setActiveId(id);
    return id;
  }, [commit]);

  const selectTab = useCallback((id: string) => setActiveId(id), []);

  const closeTab = useCallback((id: string) => {
    const current = lastWritten.current;
    const target = current.find(t => t.id === id);
    // Keep a tombstone (bumped rev) so the union merge propagates the close to
    // other windows instead of resurrecting the tab on the next merge.
    const next = target
      ? current.map(t => (t.id === id ? touchTab(t, { deleted: true }) : t))
      : current;
    commit(next);
    setActiveId(prev => {
      if (prev !== id) return prev;
      const live = next.filter(t => !t.deleted);
      return live.length ? live[live.length - 1].id : null;
    });
  }, [commit]);

  const updateTab = useCallback((id: string, patch: Partial<InvestigationTab>) => {
    commit(lastWritten.current.map(t => (t.id === id ? touchTab(t, patch) : t)));
  }, [commit]);

  const ensureTab = useCallback((sessionId: string, partial?: Partial<InvestigationTab>) => {
    const existing = lastWritten.current.find(t => t.sessionId === sessionId);
    if (existing) {
      // Bind the session + any metadata to the active tab (usually the one
      // that started this run) rather than spawning a duplicate.
      const targetId = activeId && lastWritten.current.some(t => t.id === activeId) ? activeId : existing.id;
      commit(lastWritten.current.map(t => (t.id === targetId ? touchTab(t, { ...partial, sessionId }) : t)));
      return;
    }
    // Bind to the active tab if it has no session yet; otherwise create one.
    const active = activeId ? lastWritten.current.find(t => t.id === activeId) : undefined;
    if (active && !active.sessionId) {
      commit(lastWritten.current.map(t => (t.id === active.id ? touchTab(t, { ...partial, sessionId }) : t)));
      return;
    }
    const tab = makeTab({ ...partial, id: partial?.id ?? newTabId(), sessionId, title: partial?.title ?? 'Investigation' });
    commit([...lastWritten.current, tab]);
    setActiveId(tab.id);
  }, [commit, activeId]);

  /**
   * Bind a backend session id to the active investigation *without* switching
   * the active tab. A run always belongs to the investigation that started it,
   * so a live `session` event must never create or activate a tab: doing so
   * re-keys the investigation store mid-run and orphans the streaming reply
   * (the P0 "send → no response" defect).
   */
  const bindSession = useCallback((sessionId: string, partial?: Partial<InvestigationTab>) => {
    const current = lastWritten.current;
    const owner = current.find(t => t.sessionId === sessionId);
    if (owner) {
      commit(current.map(t => (t.id === owner.id ? touchTab(t, { ...partial, sessionId }) : t)));
      return;
    }
    const active = activeId ? current.find(t => t.id === activeId) : undefined;
    if (active) {
      // Re-home the run's session onto the active investigation, replacing a
      // stale binding (the previous session of this same investigation).
      commit(current.map(t => (t.id === active.id ? touchTab(t, { ...partial, sessionId }) : t)));
      return;
    }
    // No investigation is active: the run is transient and stays keyed to the
    // current (unbound) conversation. Creating a tab here would re-key the
    // store mid-stream and orphan the reply, so we deliberately do not.
  }, [commit, activeId]);

  const setRunStatus = useCallback((sessionId: string, status: TabRunStatus) => {
    const has = lastWritten.current.some(t => t.sessionId === sessionId);
    if (!has) return;
    commit(lastWritten.current.map(t => (t.sessionId === sessionId ? touchTab(t, { runStatus: status }) : t)));
  }, [commit]);

  const activeTab = tabs.find(t => t.id === activeId) ?? null;

  return { tabs, activeId, activeTab, createTab, selectTab, closeTab, updateTab, ensureTab, bindSession, setRunStatus };
}

export { WINDOW_ID };
