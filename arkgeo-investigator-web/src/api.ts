/** API client for the ArkGeo Investigator Web Portal. */
import axios from 'axios';
import type { AnalyzeResponse, SettingsResponse, ThreatAlertResponse } from './types';

const BASE_URL = (import.meta as any).env?.VITE_ARKGEO_API_URL || '/api/v1';

const client = axios.create({
  baseURL: BASE_URL,
  timeout: 120000,
});

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

  /** Health check */
  async health(): Promise<{ status: string; version: string }> {
    const { data } = await client.get('/health');
    return data;
  },

  /** Get admin settings (API key configured flags + thresholds). */
  async getSettings(): Promise<SettingsResponse> {
    const { data } = await client.get<SettingsResponse>('/settings');
    return data;
  },

  /** Update admin settings (API keys and/or thresholds). */
  async updateSettings(payload: {
    api_keys?: Record<string, string | null>;
    thresholds?: Record<string, number>;
  }): Promise<SettingsResponse> {
    const { data } = await client.put<SettingsResponse>('/settings', payload);
    return data;
  },

  /** Test whether a given API key is configured. */
  async testConnection(keyName: string): Promise<{ key_name: string; configured: boolean }> {
    const { data } = await client.post('/settings/test-connection', null, {
      params: { key_name: keyName },
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
};
