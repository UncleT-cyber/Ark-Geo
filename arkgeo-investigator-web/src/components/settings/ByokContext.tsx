/**
 * BYOK context — reactive client-side key vault + model config.
 *
 * Wraps the byokStore so the Settings panels and the workspace react to
 * changes.  Keys are resolved through the global chain:
 *   User BYOK override -> Admin System Key -> .env
 */
import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';
import { api } from '../../api';
import { byokStore, BYOK_SPECS } from '../../core/byok/byokStore';
import type {
  ByokProviderId, ByokKeySpec, ClientModelConfig, ClientNotificationPrefs,
  KeyProbeResult, KeySource,
} from '../../types';

export interface ByokKeyState {
  spec: ByokKeySpec;
  stored: string | null;
  override: boolean;
  resolved: KeySource;
  tested: KeyProbeResult | null;
  testing: boolean;
}

interface ByokContextValue {
  keys: Record<ByokProviderId, ByokKeyState>;
  model: ClientModelConfig;
  notifications: ClientNotificationPrefs;
  setKey: (id: ByokProviderId, value: string) => void;
  clearKey: (id: ByokProviderId) => void;
  setOverride: (id: ByokProviderId, override: boolean) => void;
  testKey: (id: ByokProviderId) => Promise<void>;
  setModel: (model: ClientModelConfig) => void;
  setNotifications: (prefs: ClientNotificationPrefs) => void;
  resolveKey: (id: ByokProviderId) => { key: string | null; source: KeySource };
  /** Number of active BYOK overrides (drives the workspace status badge). */
  overrideCount: number;
}

const ByokContext = createContext<ByokContextValue | null>(null);

/** Broadcast to modules (TopBar API dots, etc.) that the key chain changed. */
function notifyByokChange() {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event('ark:byok-changed'));
  }
}

export function ByokProvider({ children }: { children: React.ReactNode }) {
  const [keys, setKeys] = useState<Record<ByokProviderId, ByokKeyState>>(() =>
    buildInitial(),
  );
  const [model, setModelState] = useState<ClientModelConfig>(() => byokStore.getModel());
  const [notifications, setNotificationsState] = useState<ClientNotificationPrefs>(
    () => byokStore.getNotifications(),
  );
  const [overrideCount, setOverrideCount] = useState(() => byokStore.activeOverrides().length);

  function buildInitial(): Record<ByokProviderId, ByokKeyState> {
    const out = {} as Record<ByokProviderId, ByokKeyState>;
    for (const spec of BYOK_SPECS) {
      out[spec.id] = {
        spec,
        stored: byokStore.getStoredKey(spec.id),
        override: byokStore.getOverride(spec.id),
        resolved: byokStore.resolveKey(spec.id).source,
        tested: null,
        testing: false,
      };
    }
    return out;
  }

  const refresh = useCallback(() => {
    const next = {} as Record<ByokProviderId, ByokKeyState>;
    for (const spec of BYOK_SPECS) {
      const prev = keys[spec.id];
      next[spec.id] = {
        spec,
        stored: byokStore.getStoredKey(spec.id),
        override: byokStore.getOverride(spec.id),
        resolved: byokStore.resolveKey(spec.id).source,
        tested: prev?.tested ?? null,
        testing: prev?.testing ?? false,
      };
    }
    setKeys(next);
    setOverrideCount(byokStore.activeOverrides().length);
  }, [keys]);

  useEffect(() => { refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  const setKey = useCallback((id: ByokProviderId, value: string) => {
    byokStore.setKey(id, value, true);
    refresh();
    notifyByokChange();
  }, [refresh]);

  const clearKey = useCallback((id: ByokProviderId) => {
    byokStore.clearKey(id);
    refresh();
    notifyByokChange();
  }, [refresh]);

  const setOverride = useCallback((id: ByokProviderId, override: boolean) => {
    byokStore.setOverride(id, override);
    refresh();
    notifyByokChange();
  }, [refresh]);

  const testKey = useCallback(async (id: ByokProviderId) => {
    const value = byokStore.getStoredKey(id) ?? '';
    setKeys(prev => ({ ...prev, [id]: { ...prev[id], testing: true } }));
    try {
      const result = await api.testToolConnection(id, value);
      setKeys(prev => ({ ...prev, [id]: { ...prev[id], tested: result, testing: false } }));
    } catch (err) {
      setKeys(prev => ({
        ...prev,
        [id]: {
          ...prev[id],
          testing: false,
          tested: {
            provider: id, valid: false,
            detail: err instanceof Error ? err.message : 'Test failed',
            latency_ms: 0,
          },
        },
      }));
    }
  }, []);

  const setModel = useCallback((next: ClientModelConfig) => {
    byokStore.setModel(next);
    setModelState(byokStore.getModel());
  }, []);

  const setNotifications = useCallback((next: ClientNotificationPrefs) => {
    byokStore.setNotifications(next);
    setNotificationsState(byokStore.getNotifications());
  }, []);

  const resolveKey = useCallback((id: ByokProviderId) => byokStore.resolveKey(id), []);

  const value: ByokContextValue = {
    keys, model, notifications,
    setKey, clearKey, setOverride, testKey, setModel, setNotifications,
    resolveKey, overrideCount,
  };

  return <ByokContext.Provider value={value}>{children}</ByokContext.Provider>;
}

export function useByok(): ByokContextValue {
  const ctx = useContext(ByokContext);
  if (!ctx) {
    throw new Error('useByok must be used within a ByokProvider');
  }
  return ctx;
}
