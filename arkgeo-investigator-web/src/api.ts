/** API client for the ArkGeo Investigator Web Portal. */
import axios from 'axios';
import type { AnalyzeResponse, AdminConfigResponse, AdminLoginResponse, AdminTokenStatus, ThreatAlertResponse, AnalystOverride } from './types';

const BASE_URL = (import.meta as any).env?.VITE_ARKGEO_API_URL || '/api/v1';

const client = axios.create({
  baseURL: BASE_URL,
  timeout: 120000,
});

/** Admin JWT token storage — in-memory only, never persisted to localStorage. */
let adminToken: string | null = null;

export const adminAuth = {
  /** Store the admin JWT in memory (cleared on page refresh). */
  setToken(token: string | null) {
    adminToken = token;
  },

  /** Get the current admin JWT (null if not authenticated). */
  getToken(): string | null {
    return adminToken;
  },

  /** Returns true if an admin token is present in memory. */
  isAuthenticated(): boolean {
    return adminToken !== null;
  },

  /** Clear the admin token (logout). */
  logout() {
    adminToken = null;
  },
};

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
  async health(): Promise<{ status: string; version: string }> {
    const { data } = await client.get('/health');
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

  /** Internal: build Authorization header for admin requests. */
  _adminHeaders(): Record<string, string> {
    const token = adminAuth.getToken();
    if (!token) {
      throw new Error('Not authenticated — admin login required');
    }
    return { Authorization: `Bearer ${token}` };
  },
};
