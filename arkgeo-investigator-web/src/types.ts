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

// ----------------------------------------------------------------------- //
// IMINT — 4-pillar unified Image Data Extraction payload
// ----------------------------------------------------------------------- //

/** Pillar 1 — Geospatial Intelligence (Where). */
export interface ImintGeospatial {
  latitude?: string | null;
  latitude_ref?: string | null;
  latitude_decimal?: number | null;
  longitude?: string | null;
  longitude_ref?: string | null;
  longitude_decimal?: number | null;
  gps_altitude?: number | null;
  altitude_meters?: number | null;
  altitude_ref?: string | null;
  gps_img_direction?: number | null;
  gps_img_direction_ref?: string | null;
  gps_speed?: number | null;
  gps_speed_ref?: string | null;
  gps_processing_method?: string | null;
  gps_dest_latitude?: string | null;
  gps_dest_latitude_ref?: string | null;
  dest_latitude_decimal?: number | null;
  gps_dest_longitude?: string | null;
  gps_dest_longitude_ref?: string | null;
  dest_longitude_decimal?: number | null;
  gps_dop?: number | null;
  dop_quality?: string | null;
  gps_satellites?: string | null;
  gps_status?: string | null;
  gps_measure_mode?: string | null;
  has_coordinates: boolean;
  coords_plausible: boolean;
}

/** Pillar 2 — Chronological & Temporal Integrity (When). */
export interface ImintTemporal {
  datetime_original?: string | null;
  datetime_digitized?: string | null;
  offset_time?: string | null;
  offset_time_original?: string | null;
  offset_time_digitized?: string | null;
  subsec_time_original?: string | null;
  subsec_time_digitized?: string | null;
  gps_date_stamp?: string | null;
  gps_time_stamp?: string | null;
  device_clock_utc?: string | null;
  satellite_clock_utc?: string | null;
  clock_delta_seconds?: number | null;
  clock_drift_detected: boolean;
  has_timestamps: boolean;
}

/** Pillar 3 — Hardware Provenance & Digital Fingerprinting. */
export interface ImintDevice {
  make?: string | null;
  model?: string | null;
  lens_make?: string | null;
  lens_model?: string | null;
  body_serial_number?: string | null;
  lens_serial_number?: string | null;
  software?: string | null;
  image_unique_id?: string | null;
  owner_name?: string | null;
  artist?: string | null;
  copyright?: string | null;
  profile_strings?: Record<string, string | null> | null;
  has_provenance: boolean;
}

/** Pillar 4 — Photographic Capture Diagnostics (How). */
export interface ImintCapture {
  exposure_time?: number | null;
  exposure_time_str?: string | null;
  f_number?: number | null;
  aperture_value?: number | null;
  shutter_speed_value?: number | null;
  iso?: number | null;
  flash?: number | null;
  flash_fired?: boolean | null;
  focal_length?: number | null;
  focal_length_35mm?: number | null;
  metering_mode?: number | null;
  light_source?: number | null;
  sensing_method?: number | null;
  exposure_program?: number | null;
  has_capture: boolean;
}

/** Derived intelligence computed over the four pillars. */
export interface ImintAnalysis {
  pillars_present: Record<string, boolean>;
  clock_drift_detected: boolean;
  dop_quality?: string | null;
  subsec_anomaly_detected: boolean;
  subsec_anomaly_reasons: string[];
  geospatial_conflicts: string[];
  unique_fingerprint?: string | null;
  is_screenshot_likely?: boolean;
  screenshot_aspect_ratio?: number | null;
  screenshot_reasons?: string[];
}

/** Unified IMINT extraction payload — one key per pillar, always present. */
export interface ImintPayload {
  geospatial: ImintGeospatial;
  temporal: ImintTemporal;
  device: ImintDevice;
  capture: ImintCapture;
  analysis: ImintAnalysis;
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
  /** 95% credible-interval radius (metres) from Monte-Carlo sampling. */
  credible_interval_radius?: number | null;
  /** Coarse probability surface for map heatmap visualisation. */
  probability_surface?: Record<string, unknown> | null;
  monte_carlo_samples?: number;
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
  image_intelligence?: ImintPayload | null;
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
  // Universal Image Intelligence suite
  streetview?: Record<string, unknown> | null;
  ai_evidence?: Record<string, unknown> | null;
  evidence_graph?: Record<string, unknown> | null;
  search_radius_meters?: number | null;
  /** Stripped-metadata fallback routing (Feature 1). */
  metadata_status?: string | null;
  /** OCR → geocoding candidate pins (Feature 2). */
  geo_candidates?: GeoCandidate[] | null;
  /** Terrain IMINT ranked candidate regions (Feature 4). */
  candidate_regions?: CandidateRegion[] | null;
  /** Canonical structured observations (OBS-*) from every forensic layer. */
  observations?: Observation[];
  /** Likely Screenshot | Likely Camera Photograph | Likely Exported Image | Unknown. */
  image_classification?: string | null;
  // ---- Step 1 / Step 3: rehydration + Monte-Carlo / satellite ----
  /** GPS/metadata recovered by rehydrating the original (pre-compression) copy. */
  recovered_original?: {
    recovered_gps?: { lat: number; lon: number };
    recovered_metadata?: Record<string, unknown>;
    recovered_source_url?: string;
    [k: string]: unknown;
  } | null;
  /** Probability surface mirror of consensus.probability_surface. */
  probability_surface?: Record<string, unknown> | null;
  /** 95% credible-interval radius (metres) from Monte-Carlo sampling. */
  credible_interval_radius?: number | null;
  /** Satellite/aerial cross-reference of the predicted location. */
  satellite_crossref?: {
    state?: string;
    provider?: string;
    tile_url?: string;
    zoom?: number;
    detail?: string;
    [k: string]: unknown;
  } | null;
  /** AI intelligence assessment from the global ARK-CAI model. */
  ai_intelligence?: {
    ai_assessment?: string;
    key_observations?: string[];
    contradictions_analysis?: string;
    confidence_adjustment?: string;
    recommended_actions?: string[];
    risk_flags?: string[];
    [k: string]: unknown;
  } | null;
}

/** A forward-geocoded OCR text candidate plotted on the spatial canvas. */
export interface GeoCandidate {
  query: string;
  lat: number;
  lon: number;
  source: string;
  cached: boolean;
  matched: boolean;
}

/** One ranked Terrain IMINT candidate region. */
export interface CandidateRegion {
  region: string;
  confidence: number;
  rationale?: string | null;
}

/** Result of an on-demand reverse source search (Visual Identifiers button). */
export interface ReverseSearchResult {
  state: string;
  phash: string;
  embedded_urls: string[];
  exact_matches: ReverseSearchMatch[];
  similar_matches: ReverseSearchMatch[];
  timeline: { source?: string; url?: string }[];
  provider: string;
  detail: string;
}

export interface ReverseSearchMatch {
  title?: string;
  filepath?: string;
  score?: number | null;
  url?: string;
  image_url?: string;
  source_url?: string;
  backlinks?: unknown[];
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
  /** GPS recovered from the original (pre-compression) web copy. */
  recovered_gps?: { lat: number; lon: number } | null;
  recovered_metadata?: Record<string, unknown> | null;
  recovered_source_url?: string | null;
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
  next_steps: NextStep[];
  /** Canonical structured observations (OBS-*) from every forensic layer. */
  observations?: Observation[];
  /** Likely Screenshot | Likely Camera Photograph | Likely Exported Image | Unknown. */
  image_classification?: string;
  /** Fallback investigation ladder state. */
  ladder?: InvestigationLadder;
  /** Location hypothesis for GPS-off / location-stripped images. */
  location_hypothesis?: LocationHypothesis | null;
}

/** One structured evidence observation in the Investigation workspace. */
export interface Observation {
  id: string;
  type: string;
  status: 'OBSERVED' | 'NOT_OBSERVED' | 'UNAVAILABLE' | 'ANOMALY' | 'HYPOTHESIS';
  layer: string;
  label: string;
  detail: string;
  source: 'cryptographic' | 'tool_inference' | 'ai_hypothesis';
  confidence?: number | null;
}

/** A context-aware recommendation that can launch a real ARK AI investigation. */
export interface NextStep {
  id: string;
  action: string;
  reason: string;
  goal: string;
  priority: string;
  claim?: string | null;
}

/** Fallback investigation ladder state. */
export interface InvestigationLadder {
  steps: {
    id: string;
    label: string;
    tool_id: string;
    requires_key: boolean;
    resolves: string;
    fallback: string | null;
    status: 'ran' | 'reachable' | 'blocked' | 'skipped';
  }[];
  ran: number;
  total: number;
  blocked: number;
  reachable_next: string | null;
  complete: boolean;
}

/** Location hypothesis for GPS-off / location-stripped images. */
export interface LocationHypothesis {
  hypothesis: { lat: number; lon: number } | null;
  confidence: number;
  supporting: { layer: string; label: string }[];
  contradicting: { layer: string; label: string }[];
  clues: string[];
  alternatives: { claim: string; confidence: number }[];
  note: string;
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

// ----------------------------------------------------------------------- //
// AI Investigation Mode (Phase C/D/E) — the adaptive investigation console
// ----------------------------------------------------------------------- //

export interface InvestigationClaim { field: string; value: string | null; }

export interface InvestigationBudget {
  max_steps: number;
  max_tokens: number;
  max_ms: number;
  max_api_calls: number;
}

export interface InvestigationConstraints {
  skip_external_sources?: boolean;
  prioritize?: string[];
  exclude?: string[];
  budget?: InvestigationBudget | null;
  zero_retention?: boolean;
}

export interface InvestigationObjective {
  objective_id: string;
  goal: string;
  subject: string;
  domain: string;
  claims_to_verify: InvestigationClaim[];
  constraints: InvestigationConstraints;
  natural_language?: string | null;
}

export interface PlanStep {
  step_id: string;
  tool_id: string;
  arguments?: Record<string, unknown>;
  rationale?: string;
  status: string;
  result_node_id?: string | null;
}

export interface BudgetEstimate {
  budget: InvestigationBudget | null;
  estimated_steps: number;
  estimated_tokens: number;
  estimated_ms: number;
  estimated_api_calls: number;
}

export interface PlanRevision {
  revision_id: string;
  parent_revision_id: string | null;
  objective_id: string;
  steps: PlanStep[];
  delta_reason?: string | null;
  approved_at_ms?: number | null;
  approved_by?: string | null;
  budget_estimate?: BudgetEstimate | null;
  hash: string;
}

/**
 * One entry in the merged plan — the whole investigation lineage flattened to
 * a single ordered step list (initial proposal + amendments + adaptive deltas)
 * with each step tagged by the revision that (re)introduced it.
 */
export interface MergedPlanStep {
  step_id: string;
  tool_id: string;
  rationale: string;
  status: string;
  result_node_id?: string | null;
  revision_id: string;
  delta_reason?: string | null;
}

export interface ActivityLogEntry {
  step_id: string;
  tool_id: string;
  status: string;          // ran | skipped | failed | memoized
  message: string;
  node_id?: string | null;
  elapsed_ms: number;
}

export interface GraphGap {
  gap_id: string;
  gap_type: string;        // unverified_claim | open_contradiction | ...
  severity: string;        // low | medium | high | critical
  rationale: string;
  addressable_by: string[];
  related_node_ids: string[];
  resolved: boolean;
}

export interface Hypothesis {
  hypothesis_id: string;
  case_id: string;
  domain: string;
  claim: string;
  confidence: number;
  supporting_node_ids: string[];
  contradicting_node_ids: string[];
  unresolved_questions: string[];
  model_id?: string | null;
  alternatives: { claim: string; confidence: number }[];
}

export interface Critique {
  critique_id: string;
  case_id: string;
  target_id: string;
  questions: string[];
  risks: string[];
  alternative_explanations: string[];
  challenges_conclusion: boolean;
  model_id?: string | null;
}

export interface EvidenceNode {
  node_id: string;
  case_id: string;
  tool_id: string;
  provenance_type: string;
  claim: string;
  claim_type: string;
  value: Record<string, unknown>;
  confidence: number;
  model_id?: string | null;
  produced_at_ms: number;
  hash: string;
}

export interface EvidenceEdge {
  edge_id: string;
  case_id: string;
  src: string;
  dst: string;
  relation: string;
  weight: number;
  note?: string | null;
}

export interface InvestigationFinding {
  finding_id: string;
  case_id: string;
  claim_type: string;
  claim: string;
  value: Record<string, unknown>;
  confidence: number;
  supporting_node_ids: string[];
  contradicting_node_ids: string[];
  finding_type: string;
  severity: string;
  status: string;
  domain?: string | null;
}

export interface EvidenceGraphPayload {
  case_id: string;
  nodes: Record<string, EvidenceNode>;
  edges: EvidenceEdge[];
  findings: InvestigationFinding[];
  plan_id?: string | null;
}

export interface BudgetUsage {
  budget: InvestigationBudget;
  steps: number;
  tokens: number;
  ms: number;
  api_calls: number;
}

/** Full AI investigation session as returned by create/approve/get/resume. */
export interface InvestigationSession {
  investigation_id: string;
  case_id: string;
  objective: InvestigationObjective;
  plan: PlanRevision;
  planner_source: string;
  model_id?: string | null;
  status: string;           // proposed | running | done | paused | ...
  pause_reason?: string | null;
  created_at_ms: number;
  approved_at_ms?: number | null;
  updated_at_ms: number;
  activity_log: ActivityLogEntry[];
  iterations: number;
  hypotheses: Hypothesis[];
  critiques: Critique[];
  gaps: GraphGap[];
  acted_gap_ids: string[];
  budget_usage: BudgetUsage;
  graph: EvidenceGraphPayload;
  findings: InvestigationFinding[];
  revisions: PlanRevision[];
  merged_plan: { steps: MergedPlanStep[]; count: number };
}

// ----------------------------------------------------------------------- //
// Agent Tool-Calling (terminal) — the autonomous `ark inspect` / natural-
// language agent surface (POST /agent/task).
// ----------------------------------------------------------------------- //

export interface AgentToolCall {
  step_id: string;
  tool_id: string;
  arguments: Record<string, unknown>;
  status: string;          // ran | failed | denied | invalid
  message: string;
  node_id?: string | null;
  elapsed_ms: number;
}

/** One folded observation — matches the CaseObservation input contract. */
export interface AgentObservation {
  type: string;
  status: 'OBSERVED' | 'NOT_OBSERVED' | 'UNAVAILABLE' | 'ANOMALY' | 'HYPOTHESIS';
  layer: string;
  label: string;
  detail: string;
  confidence?: number | null;
}

export interface AgentTaskResponse {
  task_id: string;
  case_id: string;
  status: string;          // done | partial | failed | needs_approval
  answer: string;
  model_id: string | null;
  model_calls: number;
  target_path?: string | null;
  sandbox_root?: string | null;
  tool_calls: AgentToolCall[];
  observations: AgentObservation[];
  findings: InvestigationFinding[];
  budget_usage: BudgetUsage;
  iterations: number;
  /** Pentest engagements (RE-ACT chain) carry these extras. */
  kind?: 'pentest';
  session_id?: string;
  target?: string;
  tools?: string[];
  phases?: ReactPhase[];
  ask?: string;
  session?: ReactSession;
  pentestFindings?: ReactFinding[];
  mitigation?: ReactMitigation[];
}

/** ARK capability catalog — tools by domain + platform features. */
export interface AgentCapabilities {
  domains: { id: string; label: string }[];
  tools: {
    domain: string;
    label: string;
    tools: { tool_id: string; name: string; description: string; deterministic: boolean }[];
  }[];
  platform: { feature: string; label: string; detail: string }[];
}

// ----------------------------------------------------------------------- //
// Level-4 RE-ACT chain — Plan → Scan → Exploit → Escalate → Mitigate
// ----------------------------------------------------------------------- //

/** Engagement scope for a RE-ACT chain run (backend `ReactTarget`). */
export interface ReactTarget {
  kind: 'network' | 'web' | 'host' | 'ot' | 'offline';
  host?: string | null;
  ports?: string;
  target_url?: string | null;
  web_root?: string | null;
  ros2?: boolean;
  safety_config_path?: string | null;
  reference_config_path?: string | null;
  hash_value?: string | null;
  hash_type?: string;
  wordlist?: string | null;
}

/** One RE-ACT run request (backend `ReactRequest`). */
export interface ReactRequestPayload {
  operator: string;
  authorized: boolean;
  target: ReactTarget;
  mode: 'active' | 'dry_run' | 'pending';
  notes?: string;
  budget?: Record<string, number>;
}

/** A single line in the chain activity log. */
export interface ReactActivityEntry {
  phase: string;
  tool_id?: string | null;
  status: string;          // ran | skipped | failed | done
  message: string;
  node_id?: string | null;
  elapsed_ms?: number;
}

/** Phase plan entry — one of the five RE-ACT phases. */
export interface ReactPhase {
  phase: string;
  tool_ids: string[];
  rationale: string;
  skippable: boolean;
}

/** Structured finding produced during the mitigate phase. */
export interface ReactFinding {
  finding_id: string;
  tool_id: string;
  severity: string;
  title: string;
  detail: string;
  node_id?: string;
  value?: unknown;
}

/** Remediation row mapped from a finding. */
export interface ReactMitigation {
  tool_id: string;
  severity: string;
  remediation: string;
}

/** A completed (or in-progress) RE-ACT chain session. */
export interface ReactSession {
  session_id: string;
  case_id: string;
  request: ReactRequestPayload;
  status: string;          // proposed | pending_approval | running | done | rejected | paused | failed
  rejection_reason?: string | null;
  phases: ReactPhase[];
  activity: ReactActivityEntry[];
  findings: ReactFinding[];
  mitigation: ReactMitigation[];
  budget_usage: BudgetUsage;
  graph: EvidenceGraphPayload;
  created_at_ms: number;
  updated_at_ms: number;
}

/** Compact listing row for the chain-session history. */
export interface ReactSessionSummary {
  session_id: string;
  case_id: string;
  status: string;
  kind: string;
  target: string;
  operator: string;
  updated_at_ms: number;
}

// ----------------------------------------------------------------------- //
// ARK Admin Console & Client Telemetry (Task 1)
// ----------------------------------------------------------------------- //

export type ClientStatus = 'active' | 'suspended' | 'banned';
export type PlanTier = 'free' | 'pro' | 'enterprise';

export interface AdminClientTelemetry {
  last_login_ip: string;
  country: string;
  city: string;
  asn: string;
  proxy: boolean;
  vpn: boolean;
  tor_exit: boolean;
  user_agent: string;
  os: string;
  browser: string;
  tls_fingerprint: string;
}

export interface AdminClientUsage {
  active_cases: number;
  storage_bytes: number;
  api_spend_usd: number;
  tokens_consumed: number;
}

export interface AdminClient {
  client_id: string;
  full_name: string;
  email: string;
  plan: PlanTier;
  status: ClientStatus;
  created_at: string;
  seed?: boolean;
  previous_status?: string;
  sessions_invalidated?: number;
  status_changed_at?: string;
  telemetry: AdminClientTelemetry;
  usage: AdminClientUsage;
}

export type StaffRole =
  | 'SUPER_ADMIN'
  | 'LEAD_ANALYST'
  | 'SECURITY_OPERATOR'
  | 'AUDITOR';

export interface StaffPermissions {
  canManageApiKeys: boolean;
  canManageBilling: boolean;
  canManageClients: boolean;
  canExecuteHighRiskTools: boolean;
  canManageStaff: boolean;
}

export interface AdminStaff {
  staff_id: string;
  username: string;
  full_name: string;
  role: StaffRole;
  active: boolean;
  seed?: boolean;
  permissions: StaffPermissions;
  created_at: string;
}

export interface AdminAuditEntry {
  log_id: string;
  actor: string;
  action: string;
  target: string;
  ip: string;
  detail: string;
  timestamp: string;
  timestamp_ms: number;
}

export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

export interface AdminToolPolicyEntry {
  risk_level: RiskLevel;
  enabled: boolean;
}

export interface AdminToolPolicy {
  [tool: string]: AdminToolPolicyEntry;
}

export interface AdminQuotaPlan {
  storage_bytes: number;
  max_active_cases: number;
  monthly_token_budget: number;
  rate_limit_rpm: number;
  api_spend_cap_usd: number;
  display: string;
}

export interface AdminQuotas {
  free: AdminQuotaPlan;
  pro: AdminQuotaPlan;
  enterprise: AdminQuotaPlan;
}

export interface AdminTooling {
  exiftool: { available: boolean; path: string; version: string; detail: string };
  tesseract: { available: boolean; path: string; version: string; detail: string };
  ollama: { available: boolean; url: string; model: string; detail: string };
  local_nodes: { id: string; name: string; url: string; ok: boolean }[];
}

export interface AdminSupportSettings {
  show_banner: boolean;
  bmc_url: string;
  github_url: string;
  discord_url: string;
  build_version: string;
}

export interface AdminGatewayProvider {
  configured: boolean;
  preview: string | null;
}

/** Model catalog response from GET /admin/gateway/models. */
export interface GatewayModelCatalog {
  provider: string;
  models: string[];
  source: 'live' | 'curated' | 'error';
  detail: string;
  latency_ms: number;
}

export interface AdminGateway {
  active_llm_provider: string;
  ollama_url: string;
  ollama_model: string;
  huggingface_url: string;
  huggingface_model: string;
  openai_model: string;
  gemini_model: string;
  anthropic_model: string;
  openrouter_model: string;
  vision_enabled: boolean;
  task_models: Record<string, string>;
  providers: Record<string, AdminGatewayProvider>;
}

export interface AdminOverview {
  clients: { total: number; active: number; suspended: number; banned: number };
  staff: { total: number; active: number };
  cases: { total: number };
  usage: { storage_bytes: number; api_spend_usd: number; tokens_consumed: number };
  tools: { enabled: number; total: number; enabled_high_risk: string[] };
  audit_count: number;
  support: { show_banner: boolean };
  quotas: AdminQuotas;
  generated_at_ms: number;
}

/** Live key probe result (admin gateway + BYOK share this shape). */
export interface KeyProbeResult {
  provider: string;
  valid: boolean;
  detail: string;
  latency_ms: number;
  configured?: boolean;
  method?: string;
}

// ----------------------------------------------------------------------- //
// Client Settings & BYOK (Task 2)
// ----------------------------------------------------------------------- //

/** Client BYOK provider ids supported by /tools/test-connection. */
export type ByokProviderId =
  | 'openai'
  | 'gemini'
  | 'anthropic'
  | 'openrouter'
  | 'geospy'
  | 'geoinfer'
  | 'serper'
  | 'tineye'
  | 'hlr'
  | 'opencellid'
  | 'mapbox'
  | 'google_maps'
  | 'infobip';

export interface ByokKeySpec {
  id: ByokProviderId;
  label: string;
  hint: string;
  category: 'Multimodal AI Reasoning' | 'Image Intelligence & OSINT' | 'Telecom Intelligence' | 'Maps & Geocoding';
  placeholder: string;
}

/** Active-key resolution source: user override → admin system key → env. */
export type KeySource = 'byok' | 'system' | 'env' | 'none';

export interface ClientModelConfig {
  provider: 'openai' | 'gemini' | 'openrouter' | 'ollama';
  openRouterModel?: string;
  ollamaUrl: string;
  ollamaModel: string;
  privacyMode: boolean;
}

export interface ClientNotificationPrefs {
  reportLogo: string;
  watermark: string;
  emailAlerts: boolean;
  pushAlerts: boolean;
  digestFrequency: 'daily' | 'weekly' | 'off';
}

// ----------------------------------------------------------------------- //
// Network Intelligence Workspace (Task 3) — telecom & passive network
// ----------------------------------------------------------------------- //

export interface HlrLookupResponse {
  looked_up: boolean;
  requires_key: boolean;
  live_state_available?: boolean;
  phone_e164?: string | null;
  country_code?: string | null;
  iso2?: string | null;
  line_type?: string | null;
  carrier?: string | null;
  carrier_ported?: string | null;
  active?: boolean | null;
  mcc?: string | null;
  mnc?: string | null;
  location?: string | Record<string, unknown> | null;
  is_voip?: boolean | null;
  is_prepaid?: boolean | null;
  caller_name?: string | null;
  region?: string | null;
  zip_code?: string | null;
  fraud_score?: number | null;
  valid?: boolean;
  possible?: boolean;
  number_type?: string | null;
  national_number?: string | null;
  ndc?: string | null;
  subscriber_number?: string | null;
  national_format?: string;
  international_format?: string;
  geo_city?: string | null;
  routing_location?: string | null;
  timezone?: string[];
  detail: string;
}

export interface PhoneFinding {
  code: string;
  title: string;
  detail: string;
  severity: 'info' | 'observation' | 'risk' | 'critical';
}

/** AI-assisted assessment of the collected telecom fact sheet (/telecom/analyze). */
export interface PhoneAnalysisResponse {
  analyzed: boolean;
  ai_used: boolean;
  engine: string; // openai-compatible | ollama | heuristic
  model: string;
  phone_e164: string;
  title: string;
  summary: string;
  risk_profile: string;
  geospatial_analysis: string;
  audit_next_steps: string;
  findings: PhoneFinding[];
  confidence: string; // high | medium | low
  risks: string[];
  next_actions: string[];
  caveats: string[];
  detail: string;
}

export interface CellLookupResponse {
  looked_up: boolean;
  requires_key: boolean;
  provider: string;
  mcc?: number | null;
  mnc?: number | null;
  lac?: number | null;
  cell_id?: number | null;
  lat?: number | null;
  lon?: number | null;
  range_meters?: number | null;
  radio?: string | null;
  samples?: number | null;
  method?: string | null;
  confidence?: number | null;
  towers_used?: number | null;
  detail: string;
}

export interface PhoneLocateResponse {
  looked_up: boolean;
  phone_e164: string;
  iso2?: string | null;
  mcc?: string | null;
  operator?: string | null;
  lat?: number | null;
  lon?: number | null;
  radius_m?: number | null;
  confidence: number;
  method: string;
  towers_used: number;
  detail: string;
}

export interface CellDbIngestResponse {
  ok: boolean;
  ingested: number;
  store_size: number;
  detail: string;
}

export interface CaptureObservation {
  mcc: number;
  mnc: number;
  lac?: number | null;
  cell_id: number;
  rssi?: number | null;
  imei?: string | null;
  imsi?: string | null;
}

export interface CaptureGeolocateResponse {
  looked_up: boolean;
  lat?: number | null;
  lon?: number | null;
  radius_m?: number | null;
  confidence: number;
  method: string;
  towers_used: number;
  captured: Record<string, unknown>[];
  detail: string;
}

export interface NetworkRdapResponse {
  target: string;
  kind: 'ip' | 'domain';
  handle?: string | null;
  name?: string | null;
  registered_org?: string | null;
  status: string[];
  events: { eventAction?: string; eventDate?: string }[];
  start_address?: string | null;
  end_address?: string | null;
  cidr?: string | null;
  detail: string;
}

export interface NetworkBgpResponse {
  ip: string;
  ptr_record?: string | null;
  asn?: number | null;
  asn_name?: string | null;
  asn_description?: string | null;
  asn_country?: string | null;
  prefixes: { prefix: string; asn?: number; name?: string; description?: string; country_code?: string }[];
  detail: string;
}

export interface NetworkDnsResponse {
  qname: string;
  type: string;
  answers: { name?: string; type?: number; ttl?: number; data?: string }[];
  detail: string;
}

export interface NetworkCrtResponse {
  domain: string;
  certificates: {
    common_name?: string;
    name_value?: string;
    issuer_name?: string;
    not_before?: string;
    not_after?: string;
  }[];
  detail: string;
}

export interface WebProbeResponse {
  url: string;
  final_url: string;
  status_code?: number | null;
  security_headers: Record<string, { present: boolean; ok: boolean | null; detail: string }>;
  tech_hints: Record<string, string>;
  grade: string;
  detail: string;
}

// ----------------------------------------------------------------------- //
// Telecom & Phone Console (Task 4) — simulated signaling-audit workflow
// ----------------------------------------------------------------------- //

/** One line of the streaming signaling terminal log. */
export interface SignalingStep {
  ts: string;
  kind: string; // in | db | chk | loc | out
  event: string;
  detail: string;
  warn?: string | null;
}

/** Sequential field-reveal output extracted by the (simulated) workflow. */
export interface SignalingExtracted {
  mcc?: string | null;
  mnc?: string | null;
  lac?: string | null;
  cell_id?: string | null;
  imsi?: string | null;
  cgi?: string | null;
  operator?: string | null;
  country?: string | null;
}

/** Synthetic coverage footprint that drives map fly-to + pulse animation. */
export interface SignalingSpatial {
  lat?: number | null;
  lon?: number | null;
  radius_meters?: number | null;
}

export interface SignalingAuditResponse {
  simulated: boolean;
  tier: number;
  thread: string;
  steps: SignalingStep[];
  extracted: SignalingExtracted;
  spatial: SignalingSpatial;
  detail: string;
}

export interface CellLocalResponse {
  looked_up: boolean;
  provider: string;
  mcc?: number | null;
  mnc?: number | null;
  lac?: number | null;
  cell_id?: number | null;
  lat?: number | null;
  lon?: number | null;
  range_meters?: number | null;
  detail: string;
}

// ----------------------------------------------------------------------- //
// Certified live signaling (SS7 / Diameter) — gated backend surface
// ----------------------------------------------------------------------- //

export interface SignalingStatus {
  backend: string;
  live: boolean;
  testbed: string;
}

export interface PersonnelAuthResponse {
  access_token: string;
  token_type: string;
  role: string;
  full_name: string;
  operator_scopes: string[];
  expires_in: number;
}

export interface PersonnelIdentity {
  username: string;
  full_name: string;
  role: string;
  operator_scopes: string[];
}

export interface OperatorTokenResponse {
  token: string;
  operator: string;
  mcc: string;
  scope: string;
  valid_until: number;
  trace_id: string;
}

export interface SignalingTarget {
  msisdn: string;
  mcc?: string | null;
  mnc?: string | null;
  lac?: number | null;
  cell_id?: number | null;
}

export interface SignalingSubscriber {
  msisdn: string;
  imsi?: string | null;
  mcc?: string | null;
  mnc?: string | null;
  operator?: string | null;
  country?: string | null;
  vlr?: string | null;
  lac?: number | null;
  cell_id?: number | null;
  roaming?: boolean | null;
}

export interface SignalingCell {
  cgi?: string | null;
  mcc?: string | null;
  mnc?: string | null;
  lac?: number | null;
  cell_id?: number | null;
  operator?: string | null;
  country?: string | null;
  lat?: number | null;
  lon?: number | null;
  radius_meters?: number | null;
}

export interface SignalingResult {
  op: string;
  backend: string;
  live: boolean;
  simulated: boolean;
  target: SignalingTarget;
  subscriber?: SignalingSubscriber | null;
  cell?: SignalingCell | null;
  steps: Array<{ ts: string; kind: string; event: string; detail: string; warn?: string | null }>;
  raw: Record<string, unknown>;
  trace_id: string;
  detail: string;
}

export interface SilentSmsResult {
  message_id: string;
  target: string;
  sent: boolean;
  submitted_at_ms: number;
  detail: string;
}

export interface ImsiCatcherResult {
  band: string;
  captures: unknown[];
  count: number;
  started_ms: number;
  duration_ms: number;
}

export interface SignalingAuditEntry {
  ts_iso: string;
  ts_ms: number;
  actor: string;
  role: string;
  op: string;
  target: string;
  operator: string;
  mcc: string;
  trace_id: string;
  outcome: string;
  detail: string;
}

export interface OsintWorkerResult {
  status: 'ok' | 'requires_key' | 'error' | 'skipped';
  note?: string;
  data: Record<string, unknown>;
}

export interface PhoneFootprint {
  presence: Record<string, boolean>;
  avatar_url?: string | null;
  profile_status?: string | null;
  probes?: { platform: string; status_code: number; reachable: boolean }[];
  probed: boolean;
  simulated: boolean;
  note: string;
}

export interface PhonePresenceProbe {
  ok: boolean;
  phone_e164?: string;
  probed: boolean;
  simulated: boolean;
  enabled: boolean;
  presence: Record<string, boolean>;
  probes: { platform: string; status_code: number; reachable: boolean }[];
  presence_links: { platform: string; kind: string; url: string }[];
  note: string;
}

export interface PhoneReputation {
  spam_score?: number | null;
  spam?: boolean | null;
  risky?: boolean | null;
  leaktory?: boolean | null;
  fraud_score?: number | null;
  is_voip?: boolean | null;
  is_prepaid?: boolean | null;
  cnam_registered?: boolean | null;
  threat_intel_flags: string[];
  simulated: boolean;
  note: string;
}

export interface PhoneOsintResponse {
  ok: boolean;
  phone_e164: string;
  country_code: string;
  iso2: string;
  carrier?: string | null;
  mcc?: string | null;
  mnc?: string | null;
  line_type?: string | null;
  valid?: boolean;
  possible?: boolean;
  number_type?: string | null;
  national_number?: string | null;
  ndc?: string | null;
  subscriber_number?: string | null;
  national_format?: string;
  international_format?: string;
  geo_city?: string | null;
  routing_location?: string | null;
  timezone?: string[];
  geo_zone?: string | null;
  active?: boolean | null;
  ported?: boolean | null;
  roaming_country?: string | null;
  live_state?: string | null;
  line_state?: string | null;
  sim_last_changed?: string | null;
  sim_swap_risk?: number | null;
  same_device_score?: number | null;
  caller_name?: string | null;
  risk: Record<string, unknown>;
  reputation: PhoneReputation;
  footprint: PhoneFootprint;
  requires_key: string[];
  location_hint?: string | null;
  provider_note: string;
  free_source: string;
  trace_id: string;
  workers: Record<string, OsintWorkerResult>;
  detail: string;
}
