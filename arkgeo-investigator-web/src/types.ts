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
  // Workbench forensic extensions
  deep_metadata?: DeepMetadata | null;
  consistency_findings?: ConsistencyFinding[];
  provenance?: ProvenanceResult | null;
  geolocation_fusion?: GeoFusionResult | null;
  source_discovery?: SourceDiscoveryResult | null;
  contradictions?: Contradiction[];
  evidence_summary?: EvidenceSummary | null;
  analysis_log?: string[];
}

/** ExifTool deep metadata tree. */
export interface DeepMetadata {
  available: boolean;
  groups: Record<string, MetadataGroupEntry[]>;
  raw: Record<string, unknown>[];
  file_info: Record<string, unknown>;
  error?: string | null;
}

export interface MetadataGroupEntry {
  tag: string;
  value: string;
}

/** Structured metadata consistency finding. */
export interface ConsistencyFinding {
  status: 'OK' | 'WARNING' | 'ERROR';
  type: string;
  severity: 'LOW' | 'MEDIUM' | 'HIGH';
  message: string;
  evidence: string[];
}

/** C2PA / Content Credentials provenance result. */
export interface ProvenanceResult {
  state: 'VERIFIED' | 'UNAVAILABLE' | 'INVALID' | 'INCOMPLETE';
  manifest_found: boolean;
  issuer?: string | null;
  signature_valid?: boolean | null;
  claims: unknown[];
  actions: string[];
  modifications: string[];
  warnings: string[];
  detail: string;
}

/** Multi-layer geolocation fusion result with explainability. */
export interface GeoFusionResult {
  hypothesis: { lat: number; lon: number } | null;
  primary_location: string;
  confidence: number;
  supporting: FusionEvidence[];
  contradicting: FusionEvidence[];
  independent_evidence_classes: number;
  detail: {
    question: string;
    supporting: string[];
    against: string[];
    independent_evidence_classes: number;
    confidence_pct: number;
    note: string;
  };
}

export interface FusionEvidence {
  layer: string;
  label: string;
  direction: 'supporting' | 'contradicting' | 'neutral';
  confidence: number;
  evidence_class: string;
  value?: string;
}

/** Source discovery result (provider-agnostic). */
export interface SourceDiscoveryResult {
  state: 'AVAILABLE' | 'UNAVAILABLE';
  phash: string;
  embedded_urls: string[];
  exact_matches: unknown[];
  similar_matches: unknown[];
  timeline: unknown[];
  provider: string;
  detail: string;
}

/** Structured contradiction across evidence layers. */
export interface Contradiction {
  what_conflicts: string;
  evidence_sources: string[];
  reliability: string;
  severity: 'LOW' | 'MEDIUM' | 'HIGH';
  affects_assessment: boolean;
  type: string;
}

/** Investigation overview — what we know / don't know / suspicious. */
export interface EvidenceSummary {
  location: string;
  confidence: number;
  integrity: string;
  provenance: string;
  contradictions: number;
  evidence_count: number;
  sources_discovered: number;
  analysis_status: string;
  known: string[];
  unknown: string[];
  suspicious: string[];
  next_steps: string[];
}

/** Analyst override. */
export interface AnalystOverride {
  finding_key: string;
  decision: 'confirm' | 'reject' | 'needs_review';
  note: string;
  analyst_id: string;
  created_at_ms: number;
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
