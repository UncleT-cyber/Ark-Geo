/**
 * Core Image Intelligence pipeline types.
 *
 * The continuous image intelligence cascade runs CLIENT-SIDE over every
 * uploaded asset regardless of metadata presence. Each step emits structured
 * observations that are fused and folded into the shared investigation case
 * store. Honesty is a hard requirement: when a provider or capability is
 * unavailable, steps emit explicit UNAVAILABLE / NOT_OBSERVED observations
 * instead of failing silently.
 */
import type { Observation } from '../types';
import type { GeoCandidate } from '../types';

export type { Observation };

export type ObservationStatus = Observation['status'];
export type ObservationSource = Observation['source'];

/** One structured evidence observation produced by a pipeline step. */
export interface PipelineObservation extends Observation {
  /** 1-indexed cascade step that produced this observation. */
  step: number;
}

/** Step 1 — asset classification & screenshot attribution. */
export interface AssetClassification {
  classification:
    | 'Likely Camera Photograph'
    | 'Likely Screenshot'
    | 'Likely Exported/Messenger Asset'
    | 'Unknown';
  platformProfile:
    | 'WhatsApp Compression'
    | 'Telegram Re-encode'
    | 'iOS Native'
    | 'Android Native'
    | 'Unknown';
  confidence: number;
  reasons: string[];
  dimensions: { width: number; height: number };
  format: string;
  hasExif: boolean;
  /** Longest image side in pixels. */
  maxSide: number;
  /** width / height. */
  aspect: number;
  /** Average JPEG quantization AC coefficient (higher = heavier re-encode). */
  quantizationHint: number | null;
}

/** Local perceptual hashes (64-bit hex). */
export interface PerceptualHashes {
  phash: string;
  dhash: string;
  ahash: string;
}

export interface SourceMatch {
  kind: 'exact' | 'similar' | 'crop' | 'resized';
  url: string;
  similarity: number | null;
  firstSeen: string | null;
  source: string | null;
}

/** Step 2 — perceptual hashing & reverse source discovery. */
export interface SourceDiscoveryResult {
  hashes: PerceptualHashes;
  providersConfigured: boolean;
  provider: string;
  matches: SourceMatch[];
  timeline: { date: string | null; note: string; sourceUrl?: string | null }[];
  detail: string;
}

export interface OcrTelemetryMatch {
  kind: 'url' | 'phone' | 'social_handle' | 'currency' | 'street' | 'license_plate' | 'carrier';
  value: string;
}

/** Step 3 — OCR & text telemetry extraction. */
export interface OcrTelemetry {
  text: string;
  confidence: number;
  language: string;
  regions: number;
  engine: 'server_ai' | 'tesseract' | 'none';
  matches: OcrTelemetryMatch[];
  /** Forward-geocoded candidate pins for location-relevant OCR text. */
  geo_candidates?: GeoCandidate[];
}

export interface VisualFeature {
  kind: 'lighting' | 'palette' | 'horizon' | 'sky' | 'scene';
  label: string;
  value: string;
  confidence: number;
}

/** Step 4 — multi-modal visual geolocation & landmark analysis. */
export interface VisualGeoResult {
  providersConfigured: boolean;
  coordinates: { lat: number; lon: number; confidence: number } | null;
  features: VisualFeature[];
  geohypothesis: { lat: number; lon: number; confidence: number } | null;
  note: string;
}

export interface FusionItem {
  layer: string;
  label: string;
  detail: string;
  confidence: number | null;
}

export interface LocationAssessment {
  candidate: string | null;
  confidence: number;
  supporting: FusionItem[];
  contradicting: FusionItem[];
  status: 'CORROBORATED' | 'REQUIRES_REVIEW' | 'NOT_ESTABLISHED';
  note: string;
}

export interface EvidenceVerdict {
  dimension:
    | 'origin'
    | 'location'
    | 'camera'
    | 'source'
    | 'timeline'
    | 'screenshot'
    | 'metadata';
  conclusion: string;
  confidence: number;
  status: 'ESTABLISHED' | 'PARTIAL' | 'UNRESOLVED' | 'CONTRADICTED';
}

/** Step 5 — evidence fusion engine output. */
export interface EvidenceFusionResult {
  corroborations: FusionItem[];
  contradictions: FusionItem[];
  timeline: { date: string | null; note: string; sourceUrl?: string | null }[];
  location: LocationAssessment;
  verdicts: EvidenceVerdict[];
  note: string;
}

/** The result of one cascade step (wraps typed data + its observations). */
export interface PipelineStepResult<T = unknown> {
  step: number;
  name: string;
  ok: boolean;
  elapsedMs: number;
  data: T;
  observations: PipelineObservation[];
}

/** Full output of the continuous image intelligence pipeline. */
export interface ImagePipelineResult {
  file: { name: string; size: number; type: string };
  sha256: string | null;
  startedAt: number;
  completedAt: number;
  classification: AssetClassification;
  sourceDiscovery: SourceDiscoveryResult;
  ocr: OcrTelemetry;
  visualGeo: VisualGeoResult;
  fusion: EvidenceFusionResult;
  steps: PipelineStepResult[];
  observations: PipelineObservation[];
  /** Forward-geocoded OCR candidate pins (Feature 2). */
  geo_candidates: GeoCandidate[];
}

/** Progress callback fired as each cascade step completes. */
export interface PipelineProgress {
  currentStep: number;
  totalSteps: number;
  name: string;
}
