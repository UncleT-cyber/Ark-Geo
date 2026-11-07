/**
 * Investigation store — the investigation-keyed state multiplexer.
 *
 * This is the fix for the P0 defect: the workbench used to hold one global
 * conversation, one execution timeline, one case context and one workspace
 * selection, so switching tabs only moved the highlight. Here, every piece of
 * per-investigation state is addressed by `investigationId`, and the active
 * investigation selects which slice is rendered.
 *
 * Two maps, deliberately separate:
 *
 *   slicesRef — in-memory, investigation-keyed UI state (conversation, execution
 *               timeline, case context, terminal feed, …). Never persisted:
 *               the backend session store is the durable transcript, and it
 *               honours Zero-Retention mode.
 *   metas     — durable, content-free investigation metadata (ids, workspace
 *               selection, run-status hint). Safe to persist locally.
 *
 * Switching tabs does not unmount anything and does not touch the backend, so a
 * run in Investigation A keeps executing while Investigation B is displayed.
 */
import React, {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from 'react';
import {
  InvestigationMeta,
  InvestigationRunStatus,
  InvestigationWorkspaceSelection,
  loadInvestigations,
  makeInvestigation,
  saveInvestigations,
} from './investigationStore';
import type { DomainId } from '../../components/workbench/entities';

type Setter<T> = T | ((prev: T) => T);

interface StoreApi {
  /** Active investigation id (== active tab id). */
  activeId: string | null;
  /** Durable metadata for an investigation, if known. */
  metaFor: (id: string) => InvestigationMeta | undefined;
  /** Create metadata for an investigation if absent (idempotent). */
  ensure: (id: string, partial?: Partial<InvestigationMeta>) => void;
  /** Patch durable metadata (bumps updatedAt). */
  patchMeta: (id: string, patch: Partial<InvestigationMeta>) => void;
  /** Patch the investigation's workspace selection. */
  patchWorkspace: (id: string, patch: Partial<InvestigationWorkspaceSelection>) => void;
  /** Record the active run status hint. */
  setRunStatus: (id: string, status: InvestigationRunStatus, runId?: string | null) => void;
  /**
   * Release an investigation's live UI state (on tab close). Durable,
   * content-free metadata is retained: closing a tab must never cancel a
   * running backend execution, so the session id has to survive to re-bind the
   * now-orphaned run. Metadata is capped, so this cannot grow without bound.
   */
  drop: (id: string) => void;
  /** Read an investigation-keyed UI slice, initializing it on first access. */
  getSlice: <T>(id: string, key: string, init: () => T) => T;
  /** Write an investigation-keyed UI slice (functional updater supported). */
  setSlice: <T>(id: string, key: string, value: Setter<T>) => void;
}

const Ctx = createContext<StoreApi | null>(null);

/** Investigations are addressed by tab id today; a tab points to exactly one
 *  investigation, and its identity is that id. */
export function investigationIdForTab(tabId: string): string {
  return tabId;
}

export function InvestigationStoreProvider({ activeId, children }: {
  activeId: string | null;
  children: React.ReactNode;
}) {
  const slicesRef = useRef<Map<string, Map<string, unknown>>>(new Map());
  const [metas, setMetas] = useState<InvestigationMeta[]>(() => loadInvestigations());
  // Version counter: slice writes are not React state, so we bump this and
  // include it in the context value to re-render consumers reading slices.
  const [version, setVersion] = useState(0);
  const bump = useCallback(() => setVersion(v => v + 1), []);

  // Persist durable metadata whenever it changes.
  useEffect(() => { saveInvestigations(metas); }, [metas]);

  const metaFor = useCallback(
    (id: string) => metas.find(m => m.id === id),
    [metas],
  );

  const ensure = useCallback((id: string, partial?: Partial<InvestigationMeta>) => {
    setMetas(prev => {
      const existing = prev.find(m => m.id === id);
      if (existing) {
        if (!partial) return prev;
        return prev.map(m => (m.id === id ? { ...m, ...partial, updatedAt: Date.now() } : m));
      }
      return [...prev, makeInvestigation({ id, ...partial })];
    });
  }, []);

  const patchMeta = useCallback((id: string, patch: Partial<InvestigationMeta>) => {
    setMetas(prev => {
      const existing = prev.find(m => m.id === id);
      if (!existing) return [...prev, makeInvestigation({ id, ...patch })];
      return prev.map(m => (m.id === id ? { ...m, ...patch, updatedAt: Date.now() } : m));
    });
  }, []);

  const patchWorkspace = useCallback((id: string, patch: Partial<InvestigationWorkspaceSelection>) => {
    setMetas(prev => {
      const existing = prev.find(m => m.id === id);
      if (!existing) {
        const fresh = makeInvestigation({ id });
        return [...prev, { ...fresh, workspace: { ...fresh.workspace, ...patch }, updatedAt: Date.now() }];
      }
      return prev.map(m => (
        m.id === id
          ? { ...m, workspace: { ...m.workspace, ...patch }, updatedAt: Date.now() }
          : m
      ));
    });
  }, []);

  const setRunStatus = useCallback((id: string, status: InvestigationRunStatus, runId?: string | null) => {
    setMetas(prev => prev.map(m => (
      m.id === id
        ? { ...m, runStatus: status, lastRunId: runId !== undefined ? runId : m.lastRunId, updatedAt: Date.now() }
        : m
    )));
  }, []);

  const drop = useCallback((id: string) => {
    // Release only the live UI state; keep durable metadata so a closed tab's
    // still-running backend session can be re-bound (closing a tab is not a stop).
    slicesRef.current.delete(id);
  }, []);

  const getSlice = useCallback(<T,>(id: string, key: string, init: () => T): T => {
    let inv = slicesRef.current.get(id);
    if (!inv) { inv = new Map(); slicesRef.current.set(id, inv); }
    if (!inv.has(key)) inv.set(key, init());
    return inv.get(key) as T;
  }, []);

  const setSlice = useCallback(<T,>(id: string, key: string, value: Setter<T>) => {
    let inv = slicesRef.current.get(id);
    if (!inv) { inv = new Map(); slicesRef.current.set(id, inv); }
    const prev = inv.get(key) as T;
    const next = typeof value === 'function' ? (value as (p: T) => T)(prev) : value;
    inv.set(key, next);
    bump();
  }, [bump]);

  const api = useMemo<StoreApi>(() => ({
    activeId, metaFor, ensure, patchMeta, patchWorkspace, setRunStatus, drop, getSlice, setSlice,
  // `version` is a dependency on purpose: slice writes are not React state, so
  // the context value must change for consumers to observe them.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [activeId, version, metaFor, ensure, patchMeta, patchWorkspace, setRunStatus, drop, getSlice, setSlice]);

  return <Ctx.Provider value={api}>{children}</Ctx.Provider>;
}

export function useInvestigationStore(): StoreApi {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useInvestigationStore must be used within <InvestigationStoreProvider>');
  return ctx;
}

/**
 * Investigation-keyed UI state, the React-facing primitive.
 *
 * `useState`-compatible, but the value is stored per active investigation and
 * swaps when the active investigation changes — without unmounting the caller.
 * A write always lands on the investigation that was active when the setter was
 * created, so a run started in A keeps writing to A after the operator switches
 * to B.
 */
export function useInvestigationSlice<T>(
  key: string,
  initial: () => T,
): [T, (value: Setter<T>) => void] {
  const store = useInvestigationStore();
  const invId = store.activeId ?? '__none__';
  const value = store.getSlice<T>(invId, key, initial);
  const set = useCallback((next: Setter<T>) => {
    store.setSlice<T>(invId, key, next);
  }, [store, invId, key]);
  return [value, set];
}

export type { StoreApi };
export type { DomainId };
