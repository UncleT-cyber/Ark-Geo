/** API client for the ArkGeo Investigator Web Portal. */
import axios from 'axios';
import type { AnalyzeResponse } from './types';

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
};
