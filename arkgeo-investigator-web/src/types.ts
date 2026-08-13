/** Shared types for the ArkGeo Investigator Web Portal. */

export interface Coordinates { lat: number; lon: number; }

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
