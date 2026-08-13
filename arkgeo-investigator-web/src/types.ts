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
  created_at: string;
}
