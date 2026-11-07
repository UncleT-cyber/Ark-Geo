/**
 * Storage abstraction for the investigation tab registry.
 *
 * Web builds use localStorage; the Electron desktop shell (which runs the same
 * renderer) keeps the same interface so there is exactly one tab registry and
 * no second store. Sensitive investigation data is NEVER written here — the
 * registry holds identifiers, titles and a status hint only. Authoritative
 * transcript/run/evidence data lives behind the backend session API.
 */
import { isDesktop } from './desktop';

export interface KeyValueStorage {
  get(key: string): string | null;
  set(key: string, value: string): void;
  remove(key: string): void;
}

const memory = new Map<string, string>();

const memoryStorage: KeyValueStorage = {
  get: (k) => (memory.has(k) ? (memory.get(k) as string) : null),
  set: (k, v) => { memory.set(k, v); },
  remove: (k) => { memory.delete(k); },
};

function localStore(): KeyValueStorage {
  return {
    get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* quota / private mode */ } },
    remove: (k) => { try { localStorage.removeItem(k); } catch { /* non-blocking */ } },
  };
}

/**
 * The active storage backend. Desktop and web share localStorage in the
 * renderer; a memory fallback covers non-browser contexts (SSR/tests).
 */
export const tabStorage: KeyValueStorage =
  typeof window !== 'undefined' && typeof window.localStorage !== 'undefined'
    ? localStore()
    : memoryStorage;

export function storageLabel(): string {
  if (isDesktop()) return 'desktop-local';
  return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined' ? 'browser-local' : 'memory';
}
