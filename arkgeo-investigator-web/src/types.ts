/** Shared types for the ArkGeo Investigator Web Portal. */

export interface Coordinates { lat: number; lon: number; }

export interface VisualEvidenceTag {
  category: string;
  label: string;
  confidence: number;
}

export interface AddressInfo {
  country?: string | null;
  state?: string | null;
  city?: string | null;
  road?: string | null;
  postcode?: string | null;
  display_name?: string | null;
}

export interface CustodyCertificate {
  sha256: string;
  sha1: string;
  md5: string;
  ingested_at_ms: number;
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
  status: string;
  source: string;
  custody_certificate?: CustodyCertificate | null;
  custody_hash: string;
  image_sha256: string;
  consensus: ConsensusResult;
  coordinates?: Coordinates | null;
  address?: AddressInfo | null;
  camera?: Record<string, unknown>;
  altitude?: number | null;
  datetime_original?: string | null;
  exif_raw?: Record<string, unknown> | null;
  telemetry_resolve?: Coordinates | null;
  message?: string | null;
  steganography_detected?: boolean;
  trailing_bytes_count?: number;
  exif_missing?: boolean;
  file_format?: string | null;
  ela_heatmap?: string | null;
  gps_spoofing_detected?: boolean;
  anomaly_score?: number;
  sanity_mismatches?: string[];
  gps_climate_zone?: string | null;
  visual_climate_zone?: string | null;
  created_at: string;
}

/** Admin config key status — masked, never returns full key value. */
export interface AdminConfigKeyStatus {
  configured: boolean;
  key_preview: string | null; // truncated, e.g. "sk-proj-...3f8a"
}

/** Admin config response from GET /admin/config (JWT-protected). */
export interface AdminConfigResponse {
  api_keys: Record<string, AdminConfigKeyStatus>;
  thresholds: Record<string, number>;
}

/** Admin login response from POST /admin/login. */
export interface AdminLoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

/** Token verification response from GET /admin/verify. */
export interface AdminTokenStatus {
  valid: boolean;
  username: string | null;
}

/** Threat alert response from /threat-alert endpoint. */
export interface ThreatAlertResponse {
  alert_id: string;
  dispatched: boolean;
  contacted: string[];
  alert_type: string;
  message: string;
  created_at: string;
}
