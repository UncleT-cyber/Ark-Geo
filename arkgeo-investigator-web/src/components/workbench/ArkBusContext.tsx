import React, { createContext, useContext, useEffect, useRef, useState } from 'react';
import { api } from '../../api';

type BusListener = (ev: any) => void;

interface ArkBusState {
  /** Subscribe to backend Event Bus events; returns an unsubscribe fn. */
  subscribe: (cb: BusListener) => () => void;
  /** Most recent events (ring buffer, max 200). */
  events: any[];
  connected: boolean;
}

const ArkBusContext = createContext<ArkBusState | null>(null);

/**
 * Connects to THE ARK global backend Event Bus (`/cai/events`) and exposes a
 * pub/sub surface so any frontend tab (Map UI, Network Graph, Evidence Table,
 * BottomPanel) can react to live CAI agent activity.
 */
export function ArkBusProvider({ children }: { children: React.ReactNode }) {
  const [events, setEvents] = useState<any[]>([]);
  const [connected, setConnected] = useState(false);
  const listeners = useRef<Set<BusListener>>(new Set());
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    controllerRef.current = controller;
    api
      .caiEvents((ev) => {
        setEvents((prev) => {
          const next = prev.concat(ev);
          return next.length > 200 ? next.slice(next.length - 200) : next;
        });
        listeners.current.forEach((cb) => cb(ev));
      }, 'ark', controller.signal)
      .then(() => setConnected(true))
      .catch(() => setConnected(false));
    return () => controller.abort();
  }, []);

  const value: ArkBusState = {
    subscribe: (cb: BusListener) => {
      listeners.current.add(cb);
      return () => listeners.current.delete(cb);
    },
    events,
    connected,
  };

  return <ArkBusContext.Provider value={value}>{children}</ArkBusContext.Provider>;
}

export function useArkBus(): ArkBusState {
  const ctx = useContext(ArkBusContext);
  if (!ctx) {
    throw new Error('useArkBus must be used within <ArkBusProvider>');
  }
  return ctx;
}
