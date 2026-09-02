/**
 * BYOK (Bring Your Own Keys) client vault.
 *
 * Persists personal provider keys in encrypted (obfuscated) browser
 * storage.  IMPORTANT honesty note: browser-side "encryption" here is
 * obfuscation against casual reading — it is NOT strong cryptography.
 * The browser is the user's own trust boundary; for true protection the
 * keys should live in a password manager / hardware vault.
 *
 * Key resolution chain (enforced everywhere a key is consumed):
 *   Active Key = User BYOK override (this store)
 *             -> Admin System Key (server-side, encrypted SettingsStore)
 *             -> .env (process.env / VITE_*)
 *
 * BYOK keys are stored under the current client's namespace and are
 * NEVER sent to other tenants, logged, or echoed by the backend.
 */
import type { ByokProviderId, ByokKeySpec, KeySource, ClientModelConfig, ClientNotificationPrefs } from '../../types';

export const BYOK_SPECS: ByokKeySpec[] = [
  { id: 'openai', category: 'Multimodal AI Reasoning', label: 'OpenAI API Key', hint: 'Vision / LLM reasoning ensemble.', placeholder: 'sk-proj-...' },
  { id: 'gemini', category: 'Multimodal AI Reasoning', label: 'Google Gemini API Key', hint: 'Alternative vision provider.', placeholder: 'AIzaSy...' },
  { id: 'anthropic', category: 'Multimodal AI Reasoning', label: 'Anthropic API Key', hint: 'Claude vision / reasoning.', placeholder: 'sk-ant-...' },
  { id: 'openrouter', category: 'Multimodal AI Reasoning', label: 'OpenRouter Key', hint: 'Route custom community models.', placeholder: 'sk-or-...' },
  { id: 'geospy', category: 'Image Intelligence & OSINT', label: 'GeoSpy API Key', hint: 'Street-level image geolocation.', placeholder: 'gs-...' },
  { id: 'geoinfer', category: 'Image Intelligence & OSINT', label: 'Geoinfer API Key', hint: 'Scene-geolocation inference.', placeholder: 'geoinfer-...' },
  { id: 'serper', category: 'Image Intelligence & OSINT', label: 'Serper / Google Lens API Key', hint: 'Reverse source discovery.', placeholder: 'serper-...' },
  { id: 'tineye', category: 'Image Intelligence & OSINT', label: 'TinEye API Key', hint: 'Reverse image search.', placeholder: 'tineye-...' },
  { id: 'hlr', category: 'Telecom Intelligence', label: 'HLR Telecom Lookup Key', hint: 'Phone number / carrier lookup (IPQS).', placeholder: 'hlr-...' },
  { id: 'opencellid', category: 'Telecom Intelligence', label: 'OpenCelliD API Key', hint: 'Cell tower spatial lookup (MCC/MNC/LAC/cell ID → coordinates).', placeholder: 'ocid-...' },
  { id: 'infobip', category: 'Telecom Intelligence', label: 'Infobip API Key', hint: 'Number query / messaging gateway.', placeholder: 'infobip-...' },
  { id: 'mapbox', category: 'Maps & Geocoding', label: 'Mapbox Access Token', hint: 'Client map tiles in the spatial canvas.', placeholder: 'pk.eyJ1...' },
  { id: 'google_maps', category: 'Maps & Geocoding', label: 'Google Maps API Key', hint: 'Street View + Geocoding (address resolution).', placeholder: 'AIzaSy...' },
];

export const DEFAULT_MODEL_CONFIG: ClientModelConfig = {
  provider: 'openai',
  ollamaUrl: 'http://localhost:11434',
  ollamaModel: 'llama3.2-vision:latest',
  privacyMode: false,
};

export const DEFAULT_NOTIFICATION_PREFS: ClientNotificationPrefs = {
  reportLogo: 'THE ARK',
  watermark: 'ARK — CONFIDENTIAL',
  emailAlerts: false,
  pushAlerts: true,
  digestFrequency: 'off',
};

const VAULT_KEY = 'ark.byok.vault.v1';
const VAULT_PEPPER = 'ark-byok-obfuscate-2024';

/** Lightweight XOR + base64 obfuscation (see honesty note above). */
function _obfuscate(plain: string): string {
  const out: string[] = [];
  for (let i = 0; i < plain.length; i++) {
    const code = plain.charCodeAt(i) ^ VAULT_PEPPER.charCodeAt(i % VAULT_PEPPER.length);
    out.push(String.fromCharCode(code));
  }
  return btoa(unescape(encodeURIComponent(out.join(''))));
}

function _deobfuscate(encoded: string): string {
  try {
    const raw = decodeURIComponent(escape(atob(encoded)));
    const out: string[] = [];
    for (let i = 0; i < raw.length; i++) {
      out.push(String.fromCharCode(raw.charCodeAt(i) ^ VAULT_PEPPER.charCodeAt(i % VAULT_PEPPER.length)));
    }
    return out.join('');
  } catch {
    return '';
  }
}

interface VaultData {
  keys: Partial<Record<ByokProviderId, { value: string; override: boolean }>>;
  model: ClientModelConfig;
  notifications: ClientNotificationPrefs;
}

function emptyVault(): VaultData {
  return {
    keys: {},
    model: DEFAULT_MODEL_CONFIG,
    notifications: DEFAULT_NOTIFICATION_PREFS,
  };
}

function readVault(): VaultData {
  try {
    const raw = localStorage.getItem(VAULT_KEY);
    if (!raw) return emptyVault();
    const parsed = JSON.parse(raw) as Partial<VaultData>;
    return {
      keys: parsed.keys ?? {},
      model: { ...DEFAULT_MODEL_CONFIG, ...(parsed.model ?? {}) },
      notifications: { ...DEFAULT_NOTIFICATION_PREFS, ...(parsed.notifications ?? {}) },
    };
  } catch {
    return emptyVault();
  }
}

function writeVault(vault: VaultData): void {
  try {
    localStorage.setItem(VAULT_KEY, JSON.stringify(vault));
  } catch {
    /* storage full / unavailable — non-blocking */
  }
}

const vault = readVault();

export const byokStore = {
  /** The provider's stored BYOK key value, if any. */
  getStoredKey(id: ByokProviderId): string | null {
    const entry = vault.keys[id];
    return entry?.value ? _deobfuscate(entry.value) : null;
  },

  /** Whether the user overrides the system default for this provider. */
  getOverride(id: ByokProviderId): boolean {
    return Boolean(vault.keys[id]?.override);
  },

  setKey(id: ByokProviderId, value: string, override: boolean): void {
    const existing = vault.keys[id];
    if (value.trim()) {
      vault.keys[id] = { value: _obfuscate(value.trim()), override };
    } else if (existing) {
      vault.keys[id] = { value: existing.value, override };
    }
    writeVault(vault);
  },

  clearKey(id: ByokProviderId): void {
    delete vault.keys[id];
    writeVault(vault);
  },

  setOverride(id: ByokProviderId, override: boolean): void {
    const existing = vault.keys[id];
    if (existing) {
      vault.keys[id] = { value: existing.value, override };
    }
    writeVault(vault);
  },

  getModel(): ClientModelConfig {
    return { ...vault.model };
  },

  setModel(model: ClientModelConfig): void {
    vault.model = { ...model };
    writeVault(vault);
  },

  getNotifications(): ClientNotificationPrefs {
    return { ...vault.notifications };
  },

  setNotifications(prefs: ClientNotificationPrefs): void {
    vault.notifications = { ...prefs };
    writeVault(vault);
  },

  /**
   * Resolve the ACTIVE key for a provider through the global chain:
   * user BYOK override → admin system key → env.
   *
   * Returns the key when it is usable client-side (BYOK override / env
   * token) and a source tag.  For admin system keys the key itself is
   * never exposed client-side — source is 'system' and the caller relies
   * on the backend to resolve it.
   */
  resolveKey(id: ByokProviderId): { key: string | null; source: KeySource } {
    const entry = vault.keys[id];
    if (entry?.override && entry.value) {
      return { key: _deobfuscate(entry.value), source: 'byok' };
    }
    if (id === 'mapbox') {
      const envToken = (import.meta as any).env?.VITE_MAPBOX_TOKEN as string | undefined;
      if (envToken) return { key: envToken, source: 'env' };
    }
    return { key: null, source: 'system' };
  },

  /** All providers where the user has set an override key. */
  activeOverrides(): ByokProviderId[] {
    return BYOK_SPECS.map(s => s.id).filter(id => {
      const entry = vault.keys[id];
      return Boolean(entry?.override && entry.value);
    });
  },
};
