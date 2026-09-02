/**
 * telemetry.ts — client telemetry + Authorized Security Testing attestation.
 *
 * Collects a browser fingerprint bundle, reconciles the server-observed IP
 * against a WebRTC STUN/ICE-derived IP (to surface VPN/proxy drift), and
 * maintains the client-side chain-of-custody store (adminAuditStore) that the
 * security-testing gatekeeper reads before unlocking the workspace.
 */
import { api } from '../../api';

// --------------------------------------------------------------------------- //
// Browser telemetry bundle
// --------------------------------------------------------------------------- //
export interface TelemetryBundle {
  userAgent: string;
  platform: string;
  language: string;
  timezone: string;
  screen: string;
  cores: number | null;
  memoryGB: number | null;
  timestamp: string;
  timestampMs: number;
}

/** Synchronous, best-effort browser fingerprint — never throws. */
export function collectBrowserTelemetry(): TelemetryBundle {
  const nav = typeof navigator !== 'undefined' ? navigator : null;
  const scr = typeof screen !== 'undefined' ? screen : null;
  return {
    userAgent: nav?.userAgent ?? 'unknown',
    platform: nav?.platform ?? '',
    language: nav?.language ?? '',
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone ?? '',
    screen: scr ? `${scr.width}x${scr.height}x${scr.colorDepth}` : '',
    cores: nav?.hardwareConcurrency ?? null,
    memoryGB: (nav as unknown as { deviceMemory?: number })?.deviceMemory ?? null,
    timestamp: new Date().toISOString(),
    timestampMs: Date.now(),
  };
}

// --------------------------------------------------------------------------- //
// IP reconciliation — server-observed vs WebRTC STUN/ICE
// --------------------------------------------------------------------------- //
const ICE_SERVERS: RTCIceServer[] = [
  { urls: ['stun:stun.l.google.com:19302', 'stun:stun1.l.google.com:19302'] },
];

const LOCAL_IP_RE =
  /^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|169\.254\.|0\.|fe8|fec|fd|fc)/;

function gatherIceCandidates(timeoutMs = 3000): Promise<string[]> {
  return new Promise((resolve) => {
    if (typeof RTCPeerConnection === 'undefined') { resolve([]); return; }
    let pc: RTCPeerConnection | null = null;
    try { pc = new RTCPeerConnection({ iceServers: ICE_SERVERS }); } catch { resolve([]); return; }
    const ips = new Set<string>();
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      try { pc?.close(); } catch { /* noop */ }
      resolve([...ips]);
    };
    const timer = window.setTimeout(finish, timeoutMs);
    pc.onicecandidate = (e) => {
      if (!e.candidate) { window.clearTimeout(timer); finish(); return; }
      const m = /(\d{1,3}(\.\d{1,3}){3})/.exec(e.candidate.candidate || '');
      if (m) ips.add(m[1]);
    };
    pc.createDataChannel('ip-probe');
    pc.createOffer()
      .then((o) => pc?.setLocalDescription(o))
      .catch(() => { window.clearTimeout(timer); finish(); });
  });
}

/** Resolve the WebRTC-derived IP, preferring a public candidate. */
async function resolveWebRtcIp(): Promise<string | null> {
  try {
    const ips = await gatherIceCandidates();
    if (!ips.length) return null;
    const publicIp = ips.find((ip) => !LOCAL_IP_RE.test(ip));
    return publicIp ?? ips[0];
  } catch {
    return null;
  }
}

export interface IpTelemetry {
  clientIp: string;   // server-observed
  realIp: string | null; // WebRTC STUN/ICE-derived (may equal clientIp)
  drift: boolean;     // true when the two disagree (VPN/proxy visible)
}

/** Reconcile server-observed vs WebRTC IPs with a hard timeout. */
export async function resolveIpTelemetry(): Promise<IpTelemetry> {
  const result: IpTelemetry = { clientIp: '', realIp: null, drift: false };
  const timeout = (ms: number) =>
    new Promise<never>((_, rej) => window.setTimeout(() => rej(new Error('timeout')), ms));
  try {
    const { ip } = await Promise.race([api.getObservedIp(), timeout(5000)]);
    result.clientIp = ip;
  } catch { /* backend unreachable — leave empty */ }
  try {
    result.realIp = await Promise.race([resolveWebRtcIp(), timeout(3000)]);
  } catch { /* WebRTC unavailable */ }
  result.drift = Boolean(result.clientIp && result.realIp && result.clientIp !== result.realIp);
  return result;
}

// --------------------------------------------------------------------------- //
// adminAuditStore — client-side chain of custody for security-testing attestation
// --------------------------------------------------------------------------- //
export interface AttestationPayload {
  user: string;          // full name
  email: string;
  position: string;
  orgName: string;
  purpose: string;
  targetScope: string;
  clientIP: string;
  realIP: string;
  timestamp: string;     // ISO-8601
  userAgent: string;
}

export interface AttestationRecord extends AttestationPayload {
  logId: string;
  signature: string;
  timestampMs: number;
  persisted: boolean;    // true when mirrored to the backend audit store
}

const RECORDS_KEY = 'ark.secTesting.attestations';
const UNLOCK_KEY = 'ark.secTesting.unlocked';
const IDENTITY_KEY = 'ark.secTesting.identity';

/** FNV-1a 32-bit → 8-hex (cheap, deterministic client signature seed). */
function fnvHex(input: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = (h * 0x01000193) >>> 0;
  }
  return h.toString(16).padStart(8, '0').toUpperCase();
}

function readRecords(): AttestationRecord[] {
  try {
    const raw = localStorage.getItem(RECORDS_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr : [];
  } catch { return []; }
}

function saveRecords(list: AttestationRecord[]) {
  try { localStorage.setItem(RECORDS_KEY, JSON.stringify(list.slice(0, 200))); } catch { /* non-blocking */ }
}

function rememberIdentity(payload: AttestationPayload) {
  try {
    localStorage.setItem(IDENTITY_KEY, JSON.stringify({
      user: payload.user, email: payload.email, position: payload.position, orgName: payload.orgName,
    }));
  } catch { /* non-blocking */ }
}

export const adminAuditStore = {
  /** True when a session attestation unlock is present. */
  isUnlocked(): boolean {
    try { return sessionStorage.getItem(UNLOCK_KEY) !== null; } catch { return false; }
  },

  /** The current session attestation record (or null when locked). */
  getCurrent(): AttestationRecord | null {
    try {
      const raw = sessionStorage.getItem(UNLOCK_KEY);
      return raw ? (JSON.parse(raw) as AttestationRecord) : null;
    } catch { return null; }
  },

  /** Last attested identity, used to pre-fill the modal on repeat engagement. */
  getLastIdentity(): { user: string; email: string; position: string; orgName: string } | null {
    try {
      const raw = localStorage.getItem(IDENTITY_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch { return null; }
  },

  /** Local attestation trail (for the compliance ledger view). */
  list(): AttestationRecord[] {
    return readRecords();
  },

  /**
   * Record an authorized-engagement attestation: persist locally for chain of
   * custody, mirror to the backend audit store when reachable, then unlock the
   * session.  Resolves with the authoritative record.
   */
  async logAttestation(payload: AttestationPayload): Promise<AttestationRecord> {
    const telemetry = collectBrowserTelemetry();
    const now = Date.now();
    const stamp = payload.timestamp || new Date(now).toISOString();

    const clientSig = fnvHex(
      `${payload.user}|${payload.email}|${payload.targetScope}|${now}`,
    );
    const record: AttestationRecord = {
      ...payload,
      timestamp: stamp,
      timestampMs: now,
      logId: `ATT-${fnvHex(payload.email || payload.user)}`,
      signature: `ARK-ATT-${clientSig}`,
      persisted: false,
    };

    try {
      const server = await api.logAttestation({
        full_name: payload.user,
        email: payload.email,
        position: payload.position,
        org_name: payload.orgName,
        purpose: payload.purpose,
        target_scope: payload.targetScope,
        client_ip: payload.clientIP,
        real_ip: payload.realIP,
        user_agent: payload.userAgent,
        timestamp: stamp,
        telemetry: { ...telemetry } as unknown as Record<string, unknown>,
      });
      record.logId = server.log_id;
      record.signature = server.signature;
      record.timestampMs = server.timestamp_ms;
      record.timestamp = server.timestamp;
      record.persisted = true;
    } catch { /* backend offline — local record still stands (persisted=false) */ }

    rememberIdentity(payload);
    const list = readRecords().filter((r) => r.logId !== record.logId);
    saveRecords([record, ...list]);
    try { sessionStorage.setItem(UNLOCK_KEY, JSON.stringify(record)); } catch { /* non-blocking */ }
    return record;
  },

  /** Revoke the session unlock — the workspace returns to the gatekeeper. */
  revoke() {
    try { sessionStorage.removeItem(UNLOCK_KEY); } catch { /* non-blocking */ }
  },
};
