/**
 * Shared TypeScript types & SOS payloads for ArkGeo mobile.
 */

export interface Coordinates {
  lat: number;
  lon: number;
}

export interface GpsFix extends Coordinates {
  altitude?: number;
  timestamp?: number;
}

export interface CellTowerInfo {
  mcc: number;
  mnc: number;
  lac: number;
  cell_id: number;
}

export interface DeviceTelemetry {
  last_known_outdoor_gps?: GpsFix | null;
  connected_cell_tower?: CellTowerInfo | null;
  nearby_wifi_bssids?: string[];
}

/** Payload sent to /api/v1/ingest */
export interface ARKGEOIngestPayload {
  image_base64: string;
  exif_extracted_gps?: Coordinates | null;
  device_telemetry: DeviceTelemetry;
  audio_base64?: string | null;
  zero_retention?: boolean;
  user_id?: string;
}

export interface VisualEvidenceTag {
  category: string;
  label: string;
  confidence: number;
}

export interface ConsensusResult {
  estimated_latitude: number;
  estimated_longitude: number;
  search_radius_meters: number;
  confidence_score: number;
  primary_country?: string | null;
  region?: string | null;
  visual_evidence_tags: VisualEvidenceTag[];
  tier_used: string;
  flag_low_context_indoor: boolean;
  sources: string[];
}

export interface AnalyzeResponse {
  request_id: string;
  custody_hash: string;
  image_sha256: string;
  consensus: ConsensusResult;
  exif_raw?: Record<string, unknown> | null;
  telemetry_resolve?: Coordinates | null;
  created_at: string;
}

export interface EmergencyContact {
  name: string;
  phone: string;
  relationship?: string;
}

export interface SosRequest {
  user_id: string;
  user_phone?: string;
  last_capture_image_base64?: string | null;
  last_known_gps?: GpsFix | null;
  consensus?: ConsensusResult | null;
  contacts: EmergencyContact[];
  message?: string;
}

export interface SosResponse {
  sos_id: string;
  dispatched: boolean;
  contacted: string[];
  map_link?: string;
  created_at: string;
}

export interface DeadManConfig {
  user_id: string;
  duration_minutes: number;
  pin_hash: string;
  emergency_contacts: EmergencyContact[];
  last_capture_image_base64?: string | null;
  last_known_gps?: GpsFix | null;
}

export interface DeadManStatus {
  user_id: string;
  armed: boolean;
  expires_at?: string | null;
  grace_remaining_seconds: number;
}

/** Offline queue entry persisted in SQLite */
export interface QueuedPayload {
  id: number;
  payload: ARKGEOIngestPayload;
  created_at: number;
  retry_count: number;
  status: 'pending' | 'syncing' | 'failed';
}

export type NetworkStatus = 'online' | 'offline';

export type SafetyTimerState = 'idle' | 'armed' | 'expired';

export interface SafetyTimerConfig {
  durationMinutes: number;
  pin: string;
  contacts: EmergencyContact[];
}
