import React, { createContext, useCallback, useContext, useRef, useState } from 'react';

/**
 * Bridges CAI agent browser activity to the operator Browser view.
 *
 * CAI decides *when* to browse (via the ``browser.*`` tools). Those tool calls
 * stream through ARK as ``tool_call`` / ``tool`` events. ArkControl reports
 * the browser-related ones here; the operator view reacts — opening itself when a
 * session first appears, and following the active session as CAI navigates.
 *
 * This is a notification bus, not a data store: the authoritative session state
 * always comes from the backend (``/browser/sessions``).
 */
interface CaiBrowserState {
  /** Session ids seen from live CAI browser tool activity, most recent first. */
  sessionIds: string[];
  /** The session CAI is currently driving (focus target for the view). */
  activeSessionId: string | null;
  /** Monotonic counter bumped on every browser tool event (drives refreshes). */
  revision: number;
  /** Last browser tool id observed (e.g. ``browser.navigate``). */
  lastTool: string | null;
  /** Record a browser tool call observed in the CAI stream. */
  noteToolCall: (toolId: string, args?: Record<string, any>, result?: any) => void;
  /** Operator focus override — pin the view to a specific session. */
  focusSession: (sessionId: string | null) => void;
}

const Ctx = createContext<CaiBrowserState | null>(null);

const SESSION_ARG_KEYS = ['session_id', 'sessionId'];

function extractSessionId(args?: Record<string, any>, result?: any): string | null {
  for (const source of [result, args]) {
    if (!source || typeof source !== 'object') continue;
    for (const key of SESSION_ARG_KEYS) {
      const value = (source as Record<string, any>)[key];
      if (typeof value === 'string' && value.startsWith('bws_')) return value;
    }
  }
  return null;
}

export function CaiBrowserProvider({ children }: { children: React.ReactNode }) {
  const [sessionIds, setSessionIds] = useState<string[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [lastTool, setLastTool] = useState<string | null>(null);
  const focusRef = useRef<string | null>(null);

  const noteToolCall = useCallback((toolId: string, args?: Record<string, any>, result?: any) => {
    if (!toolId?.startsWith('browser.')) return;
    setLastTool(toolId);
    setRevision(value => value + 1);
    if (toolId === 'browser.close') {
      const closed = extractSessionId(args, result);
      if (closed) setSessionIds(prev => prev.filter(id => id !== closed));
      return;
    }
    const sid = extractSessionId(args, result);
    if (sid) {
      setSessionIds(prev => [sid, ...prev.filter(id => id !== sid)]);
      // Only auto-follow when the operator has not pinned a different session.
      if (!focusRef.current) setActiveSessionId(sid);
    }
  }, []);

  const focusSession = useCallback((sessionId: string | null) => {
    focusRef.current = sessionId;
    setActiveSessionId(sessionId);
  }, []);

  const value: CaiBrowserState = {
    sessionIds, activeSessionId, revision, lastTool, noteToolCall, focusSession,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useCaiBrowser(): CaiBrowserState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useCaiBrowser must be used within <CaiBrowserProvider>');
  return ctx;
}
