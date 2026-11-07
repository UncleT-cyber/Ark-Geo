/** API client for the ArkGeo Investigator Web Portal. */
import axios from 'axios';
import type {
  AnalyzeResponse, AdminConfigResponse, AdminLoginResponse, AdminTokenStatus,
  ThreatAlertResponse, AnalystOverride, InvestigationSession, InvestigationBudget,
  AdminClient, AdminStaff, AdminAuditEntry, AdminToolPolicy, AdminQuotas,
  AdminTooling, AdminSupportSettings, AdminGateway, AdminOverview,
  GatewayModelCatalog,
  ClientStatus, PlanTier, KeyProbeResult,
  HlrLookupResponse, CellLookupResponse, PhonePresenceProbe, NetworkRdapResponse, NetworkBgpResponse,
  NetworkDnsResponse, NetworkCrtResponse, WebProbeResponse,
  SignalingAuditResponse, CellLocalResponse,
  PhoneLocateResponse, CellDbIngestResponse, CaptureObservation, CaptureGeolocateResponse,
  SignalingStatus, PersonnelAuthResponse, PersonnelIdentity, OperatorTokenResponse,
  SignalingResult, SilentSmsResult, ImsiCatcherResult, SignalingAuditEntry,
  PhoneOsintResponse, PhoneAnalysisResponse,
  AgentTaskResponse,
  AgentCapabilities,
  BrowserSessionInfo,
  ReactRequestPayload, ReactSession, ReactSessionSummary,
  GeoCandidate, ReverseSearchResult,
  EngagementState, EngagementView, EngagementCreatePayload,
} from './types';

function getBaseUrl(): string {
  if ((import.meta as any).env?.VITE_ARKGEO_API_URL) {
    return (import.meta as any).env.VITE_ARKGEO_API_URL;
  }
  if (typeof window !== 'undefined' && (window as any).ark?.isElectron) {
    const port = (window as any).ark?.backendPort;
    if (port) {
      return `http://127.0.0.1:${port}/api/v1`;
    }
  }
  return '/api/v1';
}

let BASE_URL = getBaseUrl();

const client = axios.create({
  baseURL: BASE_URL,
  timeout: 120000,
});

/**
 * Operator principal id — a stable, per-browser identifier sent as
 * `X-ARK-Principal`. It scopes the user's model preference, BYOK credentials
 * and entitlements on the server. This is a development stand-in for a real
 * authenticated session (see app/services/principal.py); it is never an admin
 * secret and never touches the admin token store.
 */
const PRINCIPAL_KEY = 'ark_principal_id';
function getPrincipalId(): string {
  try {
    let id = localStorage.getItem(PRINCIPAL_KEY);
    if (!id) {
      id = 'op-' + Math.random().toString(36).slice(2, 10);
      localStorage.setItem(PRINCIPAL_KEY, id);
    }
    return id;
  } catch {
    return 'op-local';
  }
}
client.defaults.headers.common['X-ARK-Principal'] = getPrincipalId();

/**
 * Headers for raw `fetch()` calls (SSE streams), which bypass the axios client
 * and therefore its defaults. The principal MUST be sent on the run stream:
 * the server scopes the caller's saved model preference to it, and a missing
 * header silently demotes the run to the administrator default — which is why
 * a composer model choice appeared to be overridden by the admin dashboard.
 */
function principalHeaders(): Record<string, string> {
  return { 'Content-Type': 'application/json', 'X-ARK-Principal': getPrincipalId() };
}

/**
 * Ensure BASE_URL is resolved for Electron (synchronous preload should have
 * set it, but this is a safety net). Returns the current BASE_URL.
 */
async function ensureBaseUrl(): Promise<string> {
  if (typeof window !== 'undefined' && (window as any).ark?.isElectron) {
    if (!(window as any).ark?.backendPort) {
      try {
        const port = await (window as any).ark?.getBackendPort?.();
        if (port) {
          const electronBaseUrl = `http://127.0.0.1:${port}/api/v1`;
          client.defaults.baseURL = electronBaseUrl;
          BASE_URL = electronBaseUrl;
        }
      } catch { /* ignore */ }
    }
  }
  return BASE_URL;
}

/** Read a File's bytes as a base64 string (data-URI stripped). */
function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || '');
      resolve(result.includes(',') ? result.split(',', 2)[1] : result);
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

/**
 * Admin JWT token storage — held in memory AND mirrored to sessionStorage.
 *
 * sessionStorage survives a page refresh (so a refresh returns you straight
 * to the console instead of a 404 dead-end) but is cleared when the tab
 * closes — keeping the stealth posture of never persisting to disk. The
 * localStorage policy is unchanged: nothing admin-related ever touches it.
 */
const ADMIN_TOKEN_KEY = 'ark_admin_token';

function readStoredToken(): string | null {
  try {
    return sessionStorage.getItem(ADMIN_TOKEN_KEY);
  } catch {
    return null;
  }
}

function writeStoredToken(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(ADMIN_TOKEN_KEY, token);
    else sessionStorage.removeItem(ADMIN_TOKEN_KEY);
  } catch {
    // Storage unavailable (privacy mode etc.) — in-memory token still works.
  }
}

let adminToken: string | null = readStoredToken();

export const adminAuth = {
  /** Store the admin JWT (memory + sessionStorage). */
  setToken(token: string | null) {
    adminToken = token;
    writeStoredToken(token);
  },

  /** Get the current admin JWT (null if not authenticated). */
  getToken(): string | null {
    return adminToken;
  },

  /** Returns true if an admin token is present. */
  isAuthenticated(): boolean {
    return adminToken !== null;
  },

  /** Clear the admin token (logout). */
  logout() {
    adminToken = null;
    writeStoredToken(null);
  },
};

/** AI gateway route status — which provider cascade the backend is on. */
export interface AiStatusResponse {
  status: 'cloud' | 'local_ollama' | 'offline';
  route: {
    status: 'cloud' | 'local_ollama' | 'offline';
    provider: string | null;
    model: string | null;
    detail: string;
  };
  cloud: Record<string, { configured: boolean; probed: boolean; detail: string; latency_ms: number | null }>;
  ollama: { available: boolean; models: string[]; base_url: string };
  vision: boolean;
  vision_enabled: boolean;
  task_models: Record<string, string>;
  latency_ms: number;
}

export const api = {
  /** Upload an image file for forensic analysis (multipart). */
  async analyzeFile(file: File, zeroRetention = false): Promise<AnalyzeResponse> {
    const form = new FormData();
    form.append('file', file);
    const { data } = await client.post<AnalyzeResponse>('/analyze', form, {
      params: { zero_retention: zeroRetention },
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return data;
  },

  /** Health check (public). */
  async health(): Promise<{ status: string; version: string; services: Record<string, string>; uptime_seconds: number }> {
    const { data } = await client.get('/health');
    return data;
  },

  /** AI gateway route status (public — powers the GS/GI/LLM header badges). */
  async transcriptionAvailable(signal: AbortSignal): Promise<boolean> {
    await ensureBaseUrl();
    const { data } = await client.get<{ available: boolean }>('/ai/transcription', { signal });
    return data.available;
  },

  async transcribeAudio(audio: Blob, signal: AbortSignal): Promise<string> {
    await ensureBaseUrl();
    const form = new FormData();
    form.append('file', audio, 'recording');
    const { data } = await client.post<{ text: string }>('/ai/transcription', form, { signal });
    return data.text;
  },

  async aiStatus(): Promise<AiStatusResponse> {
    const { data } = await client.get<AiStatusResponse>('/ai/status');
    return data;
  },

  // ----------------------------------------------------------------------- //
  // Admin Console — all endpoints require JWT bearer auth.
  // The JWT is held in memory only and attached via Authorization header.
  // ----------------------------------------------------------------------- //

  /** Authenticate admin credentials → returns JWT. */
  async adminLogin(username: string, password: string): Promise<AdminLoginResponse> {
    const { data } = await client.post<AdminLoginResponse>('/admin/login', {
      username,
      password,
    });
    adminAuth.setToken(data.access_token);
    return data;
  },

  /** Verify the current admin token is still valid. */
  async adminVerify(): Promise<AdminTokenStatus> {
    const { data } = await client.get<AdminTokenStatus>('/admin/verify', {
      headers: this._adminHeaders(),
    });
    return data;
  },

  /** Get masked config (configured flags + truncated previews, never full keys). */
  async getAdminConfig(): Promise<AdminConfigResponse> {
    const { data } = await client.get<AdminConfigResponse>('/admin/config', {
      headers: this._adminHeaders(),
    });
    return data;
  },

  /** Update API keys and/or thresholds (encrypted server-side). */
  async updateAdminConfig(payload: {
    api_keys?: Record<string, string | null>;
    thresholds?: Record<string, number>;
  }): Promise<AdminConfigResponse> {
    const { data } = await client.post<AdminConfigResponse>('/admin/config', payload, {
      headers: this._adminHeaders(),
    });
    return data;
  },

  /** Test whether a given API key is configured. */
  async adminTestConnection(keyName: string): Promise<{ key_name: string; configured: boolean }> {
    const { data } = await client.post('/admin/config/test-connection', null, {
      params: { key_name: keyName },
      headers: this._adminHeaders(),
    });
    return data;
  },

  /** Dispatch a threat alert (geofence violation / GPS spoofing). */
  async dispatchThreatAlert(payload: {
    alert_type: string;
    user_id?: string;
    coordinates?: { lat: number; lon: number };
    anomaly_score?: number;
    description: string;
    contacts?: { name: string; phone: string }[];
  }): Promise<ThreatAlertResponse> {
    const { data } = await client.post<ThreatAlertResponse>('/threat-alert', payload);
    return data;
  },

  /** Record an analyst override (confirm / reject / needs_review). */
  async recordAnalystOverride(payload: {
    image_sha256: string;
    finding_key: string;
    decision: string;
    note?: string;
    analyst_id?: string;
  }): Promise<{ image_sha256: string; finding_key: string; decision: string; note: string; analyst_id: string; logged_at_ms: number }> {
    const { data } = await client.post('/analyst-override', payload);
    return data;
  },

  /** List analyst overrides for an image (by SHA-256). */
  async listAnalystOverrides(imageSha256: string): Promise<AnalystOverride[]> {
    const { data } = await client.get(`/analyst-overrides/${imageSha256}`);
    return data.overrides ?? [];
  },

  // ----------------------------------------------------------------------- //
  // AI Investigation Mode (Phase C/D/E) — adaptive investigation console
  // ----------------------------------------------------------------------- //

  /**
   * Start an AI investigation: evidence file + objective JSON form field.
   * Returns a PROPOSED session (objective + plan + budget estimate). Nothing
   * has executed until `approveInvestigation` is called.
   */
  async createInvestigation(
    file: File,
    objective: {
      goal?: string;
      subject?: string;
      domain?: string;
      claims_to_verify?: { field: string; value?: string | null }[];
      constraints?: { budget?: Partial<InvestigationBudget> };
    },
  ): Promise<InvestigationSession> {
    const form = new FormData();
    form.append('file', file);
    form.append('objective', JSON.stringify(objective));
    const { data } = await client.post<InvestigationSession>('/investigate', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return data;
  },

  /** Approve the proposed plan (optionally amend) and run the adaptive loop. */
  async approveInvestigation(
    investigationId: string,
    amendSteps?: { tool_id: string; rationale?: string }[],
  ): Promise<InvestigationSession> {
    const { data } = await client.post<InvestigationSession>(
      `/investigate/${investigationId}/approve`,
      { approved_by: 'analyst', amend_steps: amendSteps ?? [] },
    );
    return data;
  },

  /** Resume a paused (pause_to_ask) investigation, optionally with a new budget. */
  async resumeInvestigation(
    investigationId: string,
    budget?: Partial<InvestigationBudget>,
  ): Promise<InvestigationSession> {
    const { data } = await client.post<InvestigationSession>(
      `/investigate/${investigationId}/resume`,
      { approved_by: 'analyst', budget: budget ?? {} },
    );
    return data;
  },

  /** Poll current session state (proposed/running/done/paused). */
  async getInvestigation(investigationId: string): Promise<InvestigationSession> {
    const { data } = await client.get<InvestigationSession>(
      `/investigate/${investigationId}`,
    );
    return data;
  },

  /** Run an agentic tool-calling task (local directory inspection, natural-
   *  language prompts). `targetPath` is resolved against the sandbox root on
   *  the backend; observations fold straight into the active case. */
  async runAgentTask(prompt: string, targetPath?: string): Promise<AgentTaskResponse> {
    const { data } = await client.post<AgentTaskResponse>('/agent/task', {
      prompt,
      target_path: targetPath ?? null,
    });
    return data;
  },

  /** Full ARK capability catalog (tools by domain + platform features). */
  async agentCapabilities(): Promise<AgentCapabilities> {
    const { data } = await client.get<AgentCapabilities>('/agent/capabilities');
    return data;
  },

  /** Internal: build Authorization header for admin requests. */
  _adminHeaders(): Record<string, string> {
    const token = adminAuth.getToken();
    if (!token) {
      throw new Error('Not authenticated — admin login required');
    }
    return { Authorization: `Bearer ${token}` };
  },

  // --------------------------------------------------------------------- //
  // ARK Admin Console — Command Center / Clients / Staff / Gateway / etc.
  // --------------------------------------------------------------------- //

  /** Aggregate Command Center metrics. */
  async adminOverview(): Promise<AdminOverview> {
    const { data } = await client.get<AdminOverview>('/admin/overview', {
      headers: this._adminHeaders(),
    });
    return data;
  },

  /** Client directory with session-handshake telemetry. */
  async listAdminClients(): Promise<AdminClient[]> {
    const { data } = await client.get<{ clients: AdminClient[] }>('/admin/clients', {
      headers: this._adminHeaders(),
    });
    return data.clients;
  },

  async createAdminClient(payload: {
    full_name: string; email: string; plan: PlanTier; status?: ClientStatus;
    telemetry?: Partial<AdminClient['telemetry']>; usage?: Partial<AdminClient['usage']>;
  }): Promise<AdminClient> {
    const { data } = await client.post<AdminClient>('/admin/clients', payload, {
      headers: this._adminHeaders(),
    });
    return data;
  },

  async updateAdminClient(clientId: string, patch: {
    plan?: PlanTier; telemetry?: Partial<AdminClient['telemetry']>; usage?: Partial<AdminClient['usage']>;
  }): Promise<AdminClient> {
    const { data } = await client.patch<AdminClient>(`/admin/clients/${clientId}`, patch, {
      headers: this._adminHeaders(),
    });
    return data;
  },

  /** Suspend / ban / activate a client (invalidates active sessions). */
  async setClientStatus(clientId: string, status: ClientStatus): Promise<AdminClient> {
    const { data } = await client.post<AdminClient>(`/admin/clients/${clientId}/status`, { status }, {
      headers: this._adminHeaders(),
    });
    return data;
  },

  async terminateClientSessions(clientId: string): Promise<{ client_id: string; sessions_terminated: number }> {
    const { data } = await client.post(`/admin/clients/${clientId}/terminate-sessions`, null, {
      headers: this._adminHeaders(),
    });
    return data;
  },

  async deleteAdminClient(clientId: string): Promise<{ deleted: boolean }> {
    const { data } = await client.delete(`/admin/clients/${clientId}`, {
      headers: this._adminHeaders(),
    });
    return data;
  },

  /** Staff directory + RBAC matrix metadata. */
  async listAdminStaff(): Promise<{ staff: AdminStaff[]; roles: string[]; permission_keys: string[] }> {
    const { data } = await client.get('/admin/staff', { headers: this._adminHeaders() });
    return data;
  },

  async createAdminStaff(payload: {
    username: string; full_name: string; role: string; permissions?: Record<string, boolean>;
  }): Promise<AdminStaff> {
    const { data } = await client.post<AdminStaff>('/admin/staff', payload, {
      headers: this._adminHeaders(),
    });
    return data;
  },

  async updateAdminStaff(staffId: string, patch: {
    full_name?: string; role?: string; permissions?: Record<string, boolean>; active?: boolean;
  }): Promise<AdminStaff> {
    const { data } = await client.patch<AdminStaff>(`/admin/staff/${staffId}`, patch, {
      headers: this._adminHeaders(),
    });
    return data;
  },

  async deactivateAdminStaff(staffId: string): Promise<AdminStaff> {
    const { data } = await client.post<AdminStaff>(`/admin/staff/${staffId}/deactivate`, null, {
      headers: this._adminHeaders(),
    });
    return data;
  },

  /** Non-repudiation audit log search (actor / action / target / query). */
  async listAuditLogs(params: {
    actor?: string; action?: string; target?: string; query?: string;
  } = {}): Promise<AdminAuditEntry[]> {
    const { data } = await client.get<{ logs: AdminAuditEntry[] }>('/admin/audit-logs', {
      params,
      headers: this._adminHeaders(),
    });
    return data.logs;
  },

  async getToolPolicy(): Promise<AdminToolPolicy> {
    const { data } = await client.get<{ policy: AdminToolPolicy }>('/admin/tool-policy', {
      headers: this._adminHeaders(),
    });
    return data.policy;
  },

  async toggleTool(tool: string, enabled: boolean): Promise<AdminToolPolicy> {
    const { data } = await client.post<{ policy: AdminToolPolicy }>(`/admin/tool-policy/${tool}/toggle`, { enabled }, {
      headers: this._adminHeaders(),
    });
    return data.policy;
  },

  // --------------------------------------------------------------------- //
  // Operator engagement — the target-authorization scope for execution.
  // --------------------------------------------------------------------- //

  /** Current active engagement + the operator's declaration history. */
  async getEngagement(): Promise<EngagementState> {
    const { data } = await client.get<EngagementState>('/engagement', {
      headers: this._adminHeaders(),
    });
    return data;
  },

  /** Declare an engagement — installs it as the active execution scope. */
  async declareEngagement(payload: EngagementCreatePayload): Promise<EngagementView> {
    const { data } = await client.post<{ status: string; engagement: EngagementView }>(
      '/engagement', payload, { headers: this._adminHeaders() },
    );
    return data.engagement;
  },

  /** Revoke an engagement immediately. */
  async revokeEngagement(engagementId: string): Promise<void> {
    await client.post(`/engagement/${engagementId}/revoke`, {}, {
      headers: this._adminHeaders(),
    });
  },

  /** Stand down the in-force scope — operator declaration and env fixture. */
  async clearEngagement(): Promise<{ status: string; effective_source: string }> {
    const { data } = await client.delete<{ status: string; effective_source: string }>('/engagement', {
      headers: this._adminHeaders(),
    });
    return data;
  },

  async getQuotas(): Promise<AdminQuotas> {
    const { data } = await client.get<{ quotas: AdminQuotas }>('/admin/quotas', {
      headers: this._adminHeaders(),
    });
    return data.quotas;
  },

  async updateQuotaPlan(tier: PlanTier, patch: Partial<AdminQuotas[PlanTier]>): Promise<AdminQuotas> {
    const { data } = await client.patch<{ quotas: AdminQuotas }>(`/admin/quotas/${tier}`, patch, {
      headers: this._adminHeaders(),
    });
    return data.quotas;
  },

  async getTooling(): Promise<AdminTooling> {
    const { data } = await client.get<{ tooling: AdminTooling }>('/admin/tooling', {
      headers: this._adminHeaders(),
    });
    return data.tooling;
  },

  async testTooling(): Promise<AdminTooling> {
    const { data } = await client.post<{ tooling: AdminTooling }>('/admin/tooling/test', null, {
      headers: this._adminHeaders(),
    });
    return data.tooling;
  },

  async getSupportSettings(): Promise<AdminSupportSettings> {
    const { data } = await client.get<{ support: AdminSupportSettings }>('/admin/support', {
      headers: this._adminHeaders(),
    });
    return data.support;
  },

  async updateSupportSettings(patch: Partial<AdminSupportSettings>): Promise<AdminSupportSettings> {
    const { data } = await client.patch<{ support: AdminSupportSettings }>('/admin/support', patch, {
      headers: this._adminHeaders(),
    });
    return data.support;
  },

  async getGateway(): Promise<AdminGateway> {
    const { data } = await client.get<{ gateway: AdminGateway }>('/admin/gateway', {
      headers: this._adminHeaders(),
    });
    return data.gateway;
  },

  async updateGateway(patch: {
    active_llm_provider?: string; ollama_url?: string; ollama_model?: string;
    huggingface_url?: string; huggingface_model?: string;
    openai_model?: string; gemini_model?: string; anthropic_model?: string;
    openrouter_model?: string;
    vision_enabled?: boolean;
    task_models?: Record<string, string>;
  }): Promise<AdminGateway> {
    const { data } = await client.put<{ gateway: AdminGateway }>('/admin/gateway', patch, {
      headers: this._adminHeaders(),
    });
    return data.gateway;
  },

  /** Live (or curated) model catalog for the Active Provider & Model selector. */
  async getGatewayModels(provider: string): Promise<GatewayModelCatalog> {
    const { data } = await client.get<GatewayModelCatalog>('/admin/gateway/models', {
      params: { provider },
      headers: this._adminHeaders(),
    });
    return data;
  },

  /** Live connection test against an admin-configured provider key. */
  async adminTestKey(provider: string): Promise<KeyProbeResult> {
    const { data } = await client.post<KeyProbeResult>('/admin/test-key', { provider }, {
      headers: this._adminHeaders(),
    });
    return data;
  },

  /** Test a user-supplied key against a provider (BYOK, no auth, no logging). */
  async testToolConnection(provider: string, key: string, extra?: Record<string, string>): Promise<KeyProbeResult> {
    const { data } = await client.post<KeyProbeResult>('/tools/test-connection', {
      provider,
      key,
      extra: extra ?? {},
    });
    return data;
  },

  // --------------------------------------------------------------------- //
  // Telecom & Network Intelligence (passive) — Network Workspace
  // --------------------------------------------------------------------- //

  /** HLR lookup — carrier / line type for an E.164 phone number (IPQS). */
  async hlrLookup(phone: string, apiKey?: string): Promise<HlrLookupResponse> {
    const { data } = await client.post<HlrLookupResponse>('/telecom/hlr-lookup', {
      phone,
      api_key: apiKey,
    });
    return data;
  },

  /** Keyless digital-footprint availability probe (wa.me/t.me/signal.me). */
  async presenceProbe(phone: string): Promise<PhonePresenceProbe> {
    const { data } = await client.post<PhonePresenceProbe>('/telecom/presence-probe', {
      phone,
    });
    return data;
  },

  /** Cell tower spatial lookup — MCC/MNC/LAC/cell ID → coordinates. */
  async cellLookup(
    params: {
      mcc: number; mnc: number; lac?: number; cell_id?: number;
      provider?: 'opencellid' | 'beacondb' | 'beacondb-open' | 'local';
    },
    apiKey?: string,
  ): Promise<CellLookupResponse> {
    const { data } = await client.post<CellLookupResponse>('/telecom/cell-lookup', {
      ...params,
      api_key: apiKey,
    });
    return data;
  },

  /** Keyless coarse region estimate from a phone number (no provider licence). */
  async phoneLocate(phone: string): Promise<PhoneLocateResponse> {
    const { data } = await client.post<PhoneLocateResponse>('/telecom/phone-locate', { phone });
    return data;
  },

  /** Ingest an open cell-tower CSV into the local keyless DB. */
  async cellDbIngest(path: string, clear = false): Promise<CellDbIngestResponse> {
    const { data } = await client.post<CellDbIngestResponse>('/telecom/cell-db/ingest', { path, clear });
    return data;
  },

  /** Multilaterate captured CGI observations into a fine position (no licence). */
  async captureGeolocate(
    observations: CaptureObservation[],
    driveSdr = false,
  ): Promise<CaptureGeolocateResponse> {
    const { data } = await client.post<CaptureGeolocateResponse>('/telecom/capture-geolocate', {
      observations,
      drive_sdr: driveSdr,
    });
    return data;
  },

  /** RDAP registration metadata for an IP or domain (rdap.org). */
  async rdap(target: string): Promise<NetworkRdapResponse> {
    const { data } = await client.post<NetworkRdapResponse>('/network/rdap', { target });
    return data;
  },

  /** BGP / ASN intelligence for an IP (bgpview.io). */
  async bgpLookup(ip: string): Promise<NetworkBgpResponse> {
    const { data } = await client.post<NetworkBgpResponse>('/network/bgp-lookup', { ip });
    return data;
  },

  /** DNS resolution via Cloudflare DoH (A / AAAA / MX / NS / TXT / CNAME). */
  async dnsLookup(qname: string, type: string): Promise<NetworkDnsResponse> {
    const { data } = await client.post<NetworkDnsResponse>('/network/dns-lookup', { qname, type });
    return data;
  },

  /** Certificate transparency subdomain enumeration (crt.sh). */
  async crtSearch(domain: string): Promise<NetworkCrtResponse> {
    const { data } = await client.post<NetworkCrtResponse>('/network/crt-search', { domain });
    return data;
  },

  /** Passive single-request HTTP security-header audit. */
  async webProbe(url: string): Promise<WebProbeResponse> {
    const { data } = await client.post<WebProbeResponse>('/network/webprobe', { url });
    return data;
  },

  // --------------------------------------------------------------------- //
  // Telecom & Phone Console (Task 4) — simulated signaling audit
  // --------------------------------------------------------------------- //

  /** Simulated SS7/Diameter signaling-audit workflow (mock, tier-gated). */
  async signalingAudit(
    phone: string,
    tier?: number,
    apiKey?: string,
  ): Promise<SignalingAuditResponse> {
    const { data } = await client.post<SignalingAuditResponse>('/telecom/signaling-audit', {
      phone,
      tier: tier ?? 1,
      api_key: apiKey,
    });
    return data;
  },

  /** Deterministic local cell-DB footprint (mock; no external API). */
  async cellLocal(
    params: {
      mcc: number; mnc: number; lac?: number; cell_id?: number; operator?: string;
    },
  ): Promise<CellLocalResponse> {
    const { data } = await client.post<CellLocalResponse>('/telecom/cell-local', params);
    return data;
  },

  /** AI-assisted assessment of the collected telecom fact sheet. */
  async telecomAnalyze(
    phone: string,
    context: Record<string, unknown>,
  ): Promise<PhoneAnalysisResponse> {
    const { data } = await client.post<PhoneAnalysisResponse>('/telecom/analyze', { phone, context });
    return data;
  },

  // --------------------------------------------------------------------- //
  // Certified live signaling (SS7 / Diameter) — gated boundary
  // --------------------------------------------------------------------- //

  /** Active signaling testbed status (public). */
  async signalingStatus(): Promise<SignalingStatus> {
    const { data } = await client.get<SignalingStatus>('/signaling/status');
    return data;
  },

  /** Personnel login — certified-role JWT. */
  async signalingLogin(username: string, password: string): Promise<PersonnelAuthResponse> {
    const { data } = await client.post<PersonnelAuthResponse>('/signaling/auth/token', { username, password });
    return data;
  },

  /** Current certified identity. */
  async signalingMe(token: string): Promise<PersonnelIdentity> {
    const { data } = await client.get<PersonnelIdentity>('/signaling/auth/me', {
      headers: { Authorization: `Bearer ${token}` },
    });
    return data;
  },

  /** Issue a per-operator authorization token (CERTIFIED_OPERATOR_ADMIN). */
  async signalingOperatorToken(
    token: string,
    payload: { operator: string; mcc: string; scope?: string; valid_hours?: number },
  ): Promise<OperatorTokenResponse> {
    const { data } = await client.post<OperatorTokenResponse>('/signaling/auth/operator-token', payload, {
      headers: { Authorization: `Bearer ${token}` },
    });
    return data;
  },

  /** Run a live or simulated signaling operation on the gated surface. */
  async signalingOp(
    op: 'sri' | 'ulr' | 'ati' | 'plr' | 'imsi' | 'cgi' | 'dry-run',
    personnelToken: string,
    operatorToken: string | null,
    payload: Record<string, unknown>,
  ): Promise<SignalingResult> {
    const headers: Record<string, string> = { Authorization: `Bearer ${personnelToken}` };
    if (operatorToken) headers['X-Operator-Authorization'] = operatorToken;
    const { data } = await client.post<SignalingResult>(`/signaling/${op}`, payload, { headers });
    return data;
  },

  /** Silent SMS injection (certified + operator token). */
  async signalingSilentSms(
    personnelToken: string,
    operatorToken: string,
    target: string,
    text: string,
  ): Promise<SilentSmsResult> {
    const { data } = await client.post<SilentSmsResult>(
      '/signaling/silent-sms',
      { target, text, delivery_report: false },
      {
        headers: {
          Authorization: `Bearer ${personnelToken}`,
          'X-Operator-Authorization': operatorToken,
        },
      },
    );
    return data;
  },

  /** IMSI-catcher sweep (certified + operator token, SDR band only). */
  async signalingImsiCatcher(
    personnelToken: string,
    operatorToken: string,
    payload: { band?: string; radius_m?: number; capture_seconds?: number; mcc_filter?: string },
  ): Promise<ImsiCatcherResult> {
    const { data } = await client.post<ImsiCatcherResult>('/signaling/imsi-catcher', payload, {
      headers: {
        Authorization: `Bearer ${personnelToken}`,
        'X-Operator-Authorization': operatorToken,
      },
    });
    return data;
  },

  /** Signaling audit trail (CERTIFIED_OPERATOR_ADMIN). */
  async signalingAuditTrail(token: string, limit = 100): Promise<SignalingAuditEntry[]> {
    const { data } = await client.get<{ entries: SignalingAuditEntry[] }>('/signaling/audit', {
      headers: { Authorization: `Bearer ${token}` },
      params: { limit },
    });
    return data.entries;
  },

  /**
   * Certified OSINT aggregation — free registry tier plus any configured
   * provider tiers (HLR live state / CNAM / risk) run in parallel.
   * No operator token needed (passive, non-signaling).
   */
  async signalingOsint(
    personnelToken: string,
    phone: string,
    keys?: Record<string, string>,
  ): Promise<PhoneOsintResponse> {
    const { data } = await client.post<PhoneOsintResponse>(
      '/signaling/osint',
      { phone, keys: keys || {} },
      { headers: { Authorization: `Bearer ${personnelToken}` } },
    );
    return data;
  },

  /**
   * City-level geocode via the backend Google Geocoding proxy (cached server-side).
   * Returns {ok, lat, lon} or a non-200 rejection carrying the detail.
   */
  async geocodeCity(q: string): Promise<{ ok: boolean; lat?: number; lon?: number; detail?: string }> {
    try {
      const { data } = await client.get<{ ok: boolean; lat?: number; lon?: number; detail?: string }>(
        '/maps/geocode',
        { params: { q } },
      );
      return data;
    } catch (e: any) {
      return { ok: false, detail: e?.response?.data?.detail || e?.message || 'geocode failed' };
    }
  },

  /**
   * Forward-geocode a batch of OCR text strings into candidate pins
   * (Feature 2 — active OCR → geocoding on upload).
   */
  async geocodeBatch(
    queries: string[],
  ): Promise<{ ok: boolean; candidates: GeoCandidate[]; detail?: string }> {
    try {
      const { data } = await client.post<{ ok: boolean; candidates: GeoCandidate[] }>(
        '/maps/geocode/batch',
        { queries },
      );
      return data;
    } catch (e: any) {
      return { ok: false, candidates: [], detail: e?.response?.data?.detail || e?.message || 'geocode batch failed' };
    }
  },

  /**
   * On-demand reverse source search — the Metadata Panel
   * `[ 🌐 Search Visual Identifiers ]` button.
   */
  async reverseSearch(file: File, searchQuery?: string): Promise<ReverseSearchResult> {
    const b64 = await fileToBase64(file);
    const { data } = await client.post<ReverseSearchResult>(
      '/analyze/reverse-search',
      { image_base64: b64, search_query: searchQuery },
    );
    return data;
  },

  /**
   * Generate a canary link server-side (certified auth) — returns a real
   * reachable URL backed by the canary callback surface.
   */
  async canaryCreate(
    personnelToken: string,
    phone: string,
    pretext: string,
  ): Promise<{ ok: boolean; token?: string; url?: string; ts?: string }> {
    const { data } = await client.post<{ ok: boolean; token?: string; url?: string; ts?: string }>(
      '/signaling/canary',
      { phone, pretext },
      { headers: { Authorization: `Bearer ${personnelToken}` } },
    );
    return data;
  },

  /**
   * Register a canary hit (out-of-band callback) against a generated link.
   */
  async canaryHit(token: string): Promise<{ ok: boolean; id?: string; ts?: string }> {
    const { data } = await client.post<{ ok: boolean; id?: string; ts?: string }>('/signaling/canary/hit', {
      token,
    });
    return data;
  },

  /**
   * Pull the callback ledger for a canary token (certified auth).
   */
  async canaryStatus(
    personnelToken: string,
    token: string,
  ): Promise<{ ok: boolean; hits: { ts: string; ip: string; ua: string }[] }> {
    const { data } = await client.get<{ ok: boolean; hits: { ts: string; ip: string; ua: string }[] }>(
      `/signaling/canary/${token}/hits`,
      { headers: { Authorization: `Bearer ${personnelToken}` } },
    );
    return data;
  },

  // ----------------------------------------------------------------------- //
  // Authorized Security Testing — attestation + telemetry reconciliation.
  // ----------------------------------------------------------------------- //

  /** Echo the server-observed client IP (used to reconcile VPN/proxy drift). */
  async getObservedIp(): Promise<{ ip: string }> {
    const { data } = await client.get<{ ip: string }>('/security/ip');
    return data;
  },

  /** Append a self-asserted authorized-engagement attestation (chain of custody). */
  async logAttestation(payload: {
    full_name: string;
    email?: string;
    position?: string;
    org_name?: string;
    purpose?: string;
    target_scope?: string;
    client_ip?: string;
    real_ip?: string;
    user_agent?: string;
    timestamp?: string;
    telemetry?: Record<string, unknown>;
  }): Promise<{
    log_id: string;
    action: string;
    actor: string;
    target_scope: string;
    ip: string;
    real_ip: string;
    signature: string;
    timestamp: string;
    timestamp_ms: number;
    persisted: boolean;
  }> {
    const { data } = await client.post('/security/attestations', payload);
    return data;
  },

  /** Start a streamed agent task — returns task_id for SSE connection. */
  async runAgentTaskStream(prompt: string, targetPath?: string): Promise<{ task_id: string; stream: boolean; status: string }> {
    const { data } = await client.post('/agent/task', {
      prompt,
      target_path: targetPath ?? null,
      stream: true,
    });
    return data;
  },

  /**
   * Answer a terminal permission prompt for a pending RE-ACT engagement.
   * decision: now | always | deny | dry_run — the chain only executes active
   * tools after the operator answers here.
   */
  async confirmAgentTask(
    sessionId: string,
    decision: string,
    operator = 'terminal',
  ): Promise<AgentTaskResponse> {
    const { data } = await client.post<AgentTaskResponse>('/agent/task/confirm', {
      session_id: sessionId,
      decision,
      operator,
    });
    return data;
  },

  // --------------------------------------------------------------------- //
  // Level-4 RE-ACT chain — Plan → Scan → Exploit → Escalate → Mitigate.
  // The chain runs on the backend (app/agent/react_chain.py) against an
  // EXPLICITLY authorized scope; active capabilities require exec:shell,
  // granted only to this chain surface.
  // --------------------------------------------------------------------- //

  /** Run the five-phase chain. Refuses to start without authorized=true. */
  async runReactChain(payload: ReactRequestPayload): Promise<ReactSession> {
    const { data } = await client.post<ReactSession>('/react/run', payload);
    return data;
  },

  /** Poll a chain session (phases, activity, findings, graph). */
  async getReactSession(sessionId: string): Promise<ReactSession> {
    const { data } = await client.get<ReactSession>(`/react/${sessionId}`);
    return data;
  },

  /** Recent chain sessions (compact summaries). */
  async listReactSessions(): Promise<ReactSessionSummary[]> {
    const { data } = await client.get<ReactSessionSummary[]>('/react');
    return data;
  },

  // ----------------------------------------------------------------------- //
  // ARK unified engine — embedded CAI as THE ARK's AI core.
  // ----------------------------------------------------------------------- //

  /**
   * ARK unified engine — intent classification preview.
   */
  async caiClassify(prompt: string): Promise<{
    mode: string; confidence: number; suggested_role: string; detected_target: string | null; rationale: string;
  }> {
    const { data } = await client.post('/cai/classify', { prompt });
    return data;
  },

  /**
   * ARK unified slash command catalogue (autocomplete source).
   * `prefix` includes the leading slash, e.g. "/a".
   */
  async caiCommands(prefix?: string): Promise<Array<{
    name: string; group: string; description: string; usage: string; arg_mode: string; choices: string[];
  }>> {
    const { data } = await client.get('/cai/commands', { params: prefix ? { prefix } : {} });
    return data;
  },

  /**
   * Dispatch a unified slash command (CAI engine control + ARK workspace).
   */
  async caiCommand(command: string, sessionId?: string): Promise<any> {
    const { data } = await client.post('/cai/command', { command, session_id: sessionId ?? null });
    return data;
  },

  /**
   * Stream an ARK task as Server-Sent Events over a POST body.
   * `onEvent` receives each parsed SSE payload; `onDone` fires on stream end.
   * Falls back gracefully — the caller decides how to render each event.
   */
  async caiStream(
    prompt: string,
    opts: { sessionId?: string; role?: string; model?: string; caseId?: string; advisoryOnly?: boolean },
    onEvent: (ev: any) => void,
    onDone?: () => void,
    signal?: AbortSignal,
  ): Promise<void> {
    const url = await ensureBaseUrl();
    const resp = await fetch(`${url}/cai/${opts.advisoryOnly ? 'review/stream' : 'stream'}`, {
      method: 'POST',
      headers: principalHeaders(),
      body: JSON.stringify({
        prompt,
        session_id: opts.sessionId ?? null,
        role: opts.role ?? null,
        model: opts.model ?? null,
        case_id: opts.caseId ?? null,
      }),
      signal,
    });
    if (!resp.ok) throw new Error(`ARK request failed (HTTP ${resp.status}).`);
    if (!resp.body) { onDone?.(); return; }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    // eslint-disable-next-line no-constant-condition
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop() ?? '';
      for (const part of parts) {
        const line = part.split('\n').find(l => l.startsWith('data:'));
        if (!line) continue;
        const payload = line.slice(5).trim();
        if (!payload) continue;
        try { onEvent(JSON.parse(payload)); } catch { /* ignore non-JSON keepalive */ }
      }
    }
    onDone?.();
  },

  /**
   * ARK TERMINAL — stream a task through THE ARK's real CAI orchestrator
   * (advisory Path A / autonomous Path B with HITL-gated real tool execution).
   * Event contract: status / token / tool / hitl / final / error / done.
   * `onEvent` receives each parsed SSE payload; `onDone` fires on stream end.
   */
  async caiTerminalStream(
    prompt: string,
    opts: { sessionId?: string; model?: string; caseId?: string; workspace?: string; caseContext?: any; executionMode?: 'auto' | 'manual' },
    onEvent: (ev: any) => void,
    onDone?: () => void,
    signal?: AbortSignal,
  ): Promise<void> {
    const url = await ensureBaseUrl();
    const resp = await fetch(`${url}/cai/terminal/stream`, {
      method: 'POST',
      headers: principalHeaders(),
      body: JSON.stringify({
        prompt,
        session_id: opts.sessionId ?? null,
        model: opts.model ?? null,
        case_id: opts.caseId ?? null,
        workspace: opts.workspace ?? null,
        case_context: opts.caseContext ?? null,
        execution_mode: opts.executionMode ?? null,
      }),
      signal,
    });
    if (!resp.ok) throw new Error(`ARK request failed (HTTP ${resp.status}).`);
    if (!resp.body) { onDone?.(); return; }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop() ?? '';
      for (const part of parts) {
        const line = part.split('\n').find(l => l.startsWith('data:'));
        if (!line) continue;
        const payload = line.slice(5).trim();
        if (!payload) continue;
        try { onEvent(JSON.parse(payload)); } catch { /* ignore non-JSON keepalive */ }
      }
    }
    onDone?.();
  },

  /**
   * Operator decision for a HITL-gated tool (the [Y/n] prompt surfaced by the
   * orchestrator during autonomous execution).
   */
  async caiTerminalApprove(sessionId: string, decision: boolean, allowAlways: boolean = false, executionId?: string): Promise<any> {
    const { data } = await client.post('/cai/terminal/approve', { session_id: sessionId, decision, allow_always: allowAlways, execution_id: executionId ?? null });
    return data;
  },

  // ------------------------------------------------------------------------ #
  // Managed browser — operator transport (screenshot-first, CAI-driven)
  // ------------------------------------------------------------------------ #
  /** Managed-browser runtime availability plus live sessions. */
  async browserStatus(): Promise<{ available: boolean; reason: string | null; executable: string | null; engine: string; sessions: BrowserSessionInfo[] }> {
    const { data } = await client.get('/browser/status');
    return data;
  },

  /** Operator-initiated managed session (optional start URL). */
  async browserOpen(url = '', investigationId = '', caseId = ''): Promise<BrowserSessionInfo> {
    const { data } = await client.post('/browser/sessions', { url, investigation_id: investigationId, case_id: caseId });
    return data;
  },

  /** One managed browser session's state. */
  async browserSession(sessionId: string): Promise<BrowserSessionInfo> {
    const { data } = await client.get(`/browser/sessions/${encodeURIComponent(sessionId)}`);
    return data;
  },

  /** Take or return operator control of a managed browser session. */
  async browserControl(sessionId: string, action: 'take' | 'return'): Promise<BrowserSessionInfo> {
    const { data } = await client.post(`/browser/sessions/${encodeURIComponent(sessionId)}/control`, { action });
    return data;
  },

  /** Operator navigation within a managed browser session. */
  async browserNavigate(sessionId: string, url: string): Promise<any> {
    const { data } = await client.post(`/browser/sessions/${encodeURIComponent(sessionId)}/navigate`, { url });
    return data;
  },

  /** Operator history move — back / forward / reload on the active tab. */
  async browserHistory(sessionId: string, action: 'back' | 'forward' | 'reload'): Promise<any> {
    const { data } = await client.post(`/browser/sessions/${encodeURIComponent(sessionId)}/history`, { action });
    return data;
  },

  /** Close a managed browser session. */
  async browserClose(sessionId: string): Promise<any> {
    const { data } = await client.post(`/browser/sessions/${encodeURIComponent(sessionId)}/close`);
    return data;
  },

  /** URL of the most recent captured frame (PNG) for a session. */
  async browserFrameUrl(sessionId: string): Promise<string> {
    const url = await ensureBaseUrl();
    return `${url}/browser/sessions/${encodeURIComponent(sessionId)}/frame`;
  },

  /** Capture a fresh frame and return its URL (cache-busted). */
  async browserCaptureUrl(sessionId: string): Promise<string> {
    const url = await ensureBaseUrl();
    return `${url}/browser/sessions/${encodeURIComponent(sessionId)}/capture?t=${Date.now()}`;
  },

  /** Normalized model catalogue (Phase 4) for the picker. */
  async caiModels(): Promise<{
    providers: Record<string, any[]>;
    active_model: string;
    selected_model: string | null;
    principal: string;
  }> {
    const { data } = await client.get('/cai/models');
    return data;
  },

  /** The model that will actually run for this caller, with routing provenance. */
  async caiActiveModel(): Promise<{
    model: string; provider: string; model_name: string; ok: boolean;
    requested_model: string | null; resolved_model: string | null;
    credential_source: string; routing_reason: string; error: string | null;
  }> {
    const { data } = await client.get('/cai/model');
    return data;
  },

  /** The caller's saved model preference (independent of the admin default). */
  async caiGetPreference(): Promise<{ selected_model: string | null; model_pins: Record<string, string> }> {
    const { data } = await client.get('/user/model/preference');
    return data;
  },

  /** Persist the caller's explicit model selection (Phase 2 rule 2). */
  async caiSetPreference(selectedModel: string | null): Promise<any> {
    const { data } = await client.put('/user/model/preference', { selected_model: selectedModel });
    return data;
  },

  /** Get queue status for a session. */
  async caiQueue(sessionId: string): Promise<{ session_id: string; queue: any[]; pending_count: number; delivered_count: number; cancelled_count: number }> {
    const { data } = await client.get(`/cai/queue/${encodeURIComponent(sessionId)}`);
    return data;
  },

  /** Queue a message for execution after the current run completes. */
  async caiEnqueue(body: { session_id: string; prompt: string; conversation_id?: string; run_id?: string }): Promise<any> {
    const { data } = await client.post('/cai/queue', body);
    return data;
  },

  /** Submit a steering instruction for an active run. */
  async caiSteer(body: { session_id: string; run_id?: string; message: string; instruction_type?: string }): Promise<any> {
    const { data } = await client.post('/cai/steer', body);
    return data;
  },

  /** Set the backend-owned execution mode (auto | manual) for a session/run. */
  async caiMode(body: { session_id: string; run_id?: string; mode: 'auto' | 'manual' }): Promise<any> {
    const { data } = await client.post('/cai/mode', body);
    return data;
  },

  /** Live control state of a run (stop / steer / mode). */
  async caiRun(sessionId: string, runId?: string): Promise<{
    session_id: string; run_id?: string; active: boolean; status: string;
    mode: string | null; stop_requested: boolean; steering: any[];
  }> {
    const { data } = await client.get('/cai/run', { params: { session_id: sessionId, run_id: runId ?? null } });
    return data;
  },

  /** Stop or cancel an active run or queued messages. */
  async caiStop(body: { session_id: string; run_id?: string; stop_type?: string }): Promise<any> {
    const { data } = await client.post('/cai/stop', body);
    return data;
  },

  /** Pin a model for a session. */
  async caiModelSwitch(body: { session_id: string; model: string }): Promise<any> {
    const { data } = await client.post('/cai/model/switch', body);
    return data;
  },

  /** Central config: live active provider + model the whole system is bound to. */
  async configActiveModel(): Promise<{ provider: string; model_name: string; model: string }> {
    const { data } = await client.get('/config/active-model');
    return data;
  },

  /** Free HuggingFace models available on the router (live, curated fallback). */
  async configHuggingfaceModels(): Promise<{ models: string[]; source: string; detail: string }> {
    const { data } = await client.get('/config/huggingface-models');
    return data;
  },

  /** Invoke a CAI sub-agent role directly for a workspace (SSE stream). */
  async caiWorkspaceRun(
    workspace: string,
    prompt: string,
    opts: { sessionId?: string; model?: string; caseId?: string },
    onEvent: (ev: any) => void,
    onDone?: () => void,
    signal?: AbortSignal,
  ): Promise<void> {
    const url = await ensureBaseUrl();
    const resp = await fetch(`${url}/cai/workspace/${encodeURIComponent(workspace)}/run`, {
      method: 'POST',
      headers: principalHeaders(),
      body: JSON.stringify({
        prompt,
        session_id: opts.sessionId ?? null,
        model: opts.model ?? null,
        case_id: opts.caseId ?? null,
      }),
      signal,
    });
    if (!resp.body) { onDone?.(); return; }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop() ?? '';
      for (const part of parts) {
        const line = part.split('\n').find(l => l.startsWith('data:'));
        if (!line) continue;
        const payload = line.slice(5).trim();
        if (payload) { try { onEvent(JSON.parse(payload)); } catch { /* ignore */ } }
      }
    }
    onDone?.();
  },

  /**
   * Open a Server-Sent Events connection to THE ARK global Event Bus. Emits
   * backend CAI agent activity (tool start / output / agent status) so frontend
   * tabs can update their visual state live. `onEvent` fires per payload.
   */
  caiEvents(
    onEvent: (ev: any) => void,
    topic: string = 'ark',
    signal?: AbortSignal,
  ): Promise<void> {
    return ensureBaseUrl().then((url) =>
      fetch(`${url}/cai/events?topic=${encodeURIComponent(topic)}`, { signal }).then(async (r) => {
        if (!r.body) return;
        const reader = r.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split('\n\n');
          buffer = parts.pop() ?? '';
          for (const part of parts) {
            const line = part.split('\n').find(l => l.startsWith('data:'));
            if (!line) continue;
            const payload = line.slice(5).trim();
            if (!payload) continue;
            try { onEvent(JSON.parse(payload)); } catch { /* ignore */ }
          }
        }
      })
    );
  },

  /** THE ARK unified tool & agent registry (all workspaces). */
  async caiRegistry(): Promise<any> {
    const { data } = await client.get('/cai/registry');
    return data;
  },

  /** THE ARK System Overview — principal-scoped operational aggregate. */
  async systemOverview(period: '24h' | '7d' | '30d' = '24h', traces = 25): Promise<{
    generated_at: string;
    period_hours: number;
    kpis: {
      investigations: { total: number; active: number };
      active_agents: { running: number; idle: number };
      tool_executions: { total: number; completed: number; failed: number; success_rate: number | null };
      pending_approvals: { count: number };
    };
    activity: {
      series: Array<{ start: string; count: number; failed: number }>;
      recent: Array<{ at: string | null; kind: string; run_id: string | null; session_id: string | null; status: string | null }>;
    };
    agents: Array<{
      run_id: string; session_id: string; agent: string | null; status: string;
      mode: string | null; stop_requested: boolean; case_id: string | null; model: string | null;
    }>;
    model: {
      available: boolean; model?: string | null; provider?: string | null;
      credential_source?: string | null; routing_reason?: string | null;
      error?: string | null; route_status?: string | null;
    };
    providers: Array<{
      provider: string; configured: boolean; probed: boolean; detail: string | null; latency_ms: number | null;
    }>;
    usage: {
      period_hours: number; requests: number; input_tokens: number | null; output_tokens: number | null;
      cost_usd: number | null; cost_basis: string; local_inference_runs: number | null;
      cloud_inference_runs: number | null; note: string;
    };
    security: {
      scope_active: boolean; scope_lines: string[]; pending_approvals: number;
      scope_denials: number; blocked_operations: number; execution_modes: string[];
    };
    evidence: {
      runs_recorded: number; completed_investigations: number; audit_events: number; latest_verified: string | null;
    };
    traces: Array<{
      run_id: string | null; session_id: string | null; model: string | null; status: string | null;
      agent: string | null; operation: string | null; verified: boolean | null; approval: string | null;
      evidence_ref: string | null; started_at: string | null; ended_at: string | null;
      duration_ms: number | null; error: string | null; event_count: number | null; last_event: string | null;
    }>;
  }> {
    // Resolve the base URL first, like every other call: under the desktop
    // shell `window.ark.backendPort` may not be set at module load, and a
    // relative `/api/v1` then resolves against the app origin and 404s.
    await ensureBaseUrl();
    const { data } = await client.get('/overview', { params: { period, traces } });
    return data;
  },

  /** Durable investigation sessions for this caller (restoration surface). */
  async caiSessions(limit = 50): Promise<{
    sessions: Array<{
      session_id: string; case_id: string | null; workspace: string | null;
      role: string | null; model: string | null; zero_retention: boolean;
      created_at: string; updated_at: string;
      last_run_id: string | null; last_run_status: string | null;
    }>;
  }> {
    const { data } = await client.get('/cai/sessions', { params: { limit } });
    return data;
  },

  /** One durable investigation session: metadata, transcript, runs, evidence refs. */
  async caiSession(sessionId: string): Promise<{
    ok: boolean;
    session?: any;
    messages?: Array<{ role: string; content: string; tool_call_id?: string }>;
    runs?: any[];
    evidence_refs?: string[];
    transcript_available?: boolean;
    error?: string;
  }> {
    const { data } = await client.get(`/cai/sessions/${encodeURIComponent(sessionId)}`);
    return data;
  },

  async caiDeleteSession(sessionId: string): Promise<any> {
    const { data } = await client.delete(`/cai/sessions/${encodeURIComponent(sessionId)}`);
    return data;
  },
};

/**
 * Open a Server-Sent Events connection for a streamed agent task. Returns the
 * native `EventSource` — caller is responsible for closing it once the
 * `"result"` event arrives.
 */
export function openAgentTaskEvents(
  taskId: string,
  onEvent: (event: { event: string; [k: string]: unknown }) => void,
  onError?: (ev: Event) => void,
): EventSource {
  // Ensure base URL is resolved before opening EventSource
  const url = (typeof window !== 'undefined' && (window as any).ark?.backendPort)
    ? `http://127.0.0.1:${(window as any).ark.backendPort}/api/v1`
    : BASE_URL;
  const es = new EventSource(`${url}/agent/task/${taskId}/events`);
  es.onmessage = (ev: MessageEvent) => {
    try { onEvent(JSON.parse(ev.data)); } catch { /* keepalive comment lines have no JSON */ }
  };
  if (onError) es.onerror = onError;
  return es;
}

/** Ensure BASE_URL is resolved for Electron. Returns the current BASE_URL. */
export { ensureBaseUrl };
