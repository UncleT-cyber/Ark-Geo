/**
 * Axios HTTP client to ArkGeo Core Backend.
 */
import axios, { AxiosInstance } from 'axios';
import { AnalyzeResponse, SosRequest, SosResponse, ARKGEOIngestPayload, DeadManConfig, DeadManStatus } from '../../types';

// In dev, point this at your local backend or tunnel.
const BASE_URL = process.env.EXPO_PUBLIC_ARKGEO_API_URL || 'http://localhost:8000';

const client: AxiosInstance = axios.create({
  baseURL: `${BASE_URL}/api/v1`,
  timeout: 60000,
  headers: { 'Content-Type': 'application/json' },
});

export const api = {
  /** Ingest a safety snapshot + telemetry */
  async ingest(payload: ARKGEOIngestPayload): Promise<AnalyzeResponse> {
    const { data } = await client.post<AnalyzeResponse>('/ingest', payload);
    return data;
  },

  /** Direct forensic analysis (base64) */
  async analyze(imageBase64: string, zeroRetention = false): Promise<AnalyzeResponse> {
    const { data } = await client.post<AnalyzeResponse>('/analyze/base64', {
      image_base64: imageBase64,
      zero_retention: zeroRetention,
    });
    return data;
  },

  /** Trigger SOS */
  async sos(request: SosRequest): Promise<SosResponse> {
    const { data } = await client.post<SosResponse>('/sos', request);
    return data;
  },

  /** Health check */
  async health(): Promise<{ status: string; version: string }> {
    const { data } = await client.get('/health');
    return data;
  },

  /** Dead-Man's switch — arm */
  async armDeadMan(config: DeadManConfig): Promise<DeadManStatus> {
    const { data } = await client.post<DeadManStatus>('/deadman/arm', config);
    return data;
  },

  /** Dead-Man's switch — check in */
  async checkInDeadMan(userId: string, pinHash: string): Promise<DeadManStatus> {
    const { data } = await client.post<DeadManStatus>('/deadman/checkin', null, {
      params: { user_id: userId, pin_hash: pinHash },
    });
    return data;
  },

  /** Dead-Man's switch — disarm */
  async disarmDeadMan(userId: string): Promise<DeadManStatus> {
    const { data } = await client.post<DeadManStatus>('/deadman/disarm', null, {
      params: { user_id: userId },
    });
    return data;
  },

  /** Dead-Man's switch — status */
  async deadManStatus(userId: string): Promise<DeadManStatus> {
    const { data } = await client.get<DeadManStatus>(`/deadman/status/${userId}`);
    return data;
  },
};
