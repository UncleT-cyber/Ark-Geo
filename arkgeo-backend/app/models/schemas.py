"""Pydantic models for ArkGeo requests, responses and persistence."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Shared building blocks
# --------------------------------------------------------------------------- #
class Coordinates(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


class GpsFix(Coordinates):
    altitude: Optional[float] = None
    timestamp: Optional[int] = None


class AddressInfo(BaseModel):
    country: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    road: Optional[str] = None
    postcode: Optional[str] = None
    display_name: Optional[str] = None


class CustodyCertificate(BaseModel):
    """Cryptographic chain-of-custody block computed at ingestion time."""
    sha256: str
    sha1: str
    md5: str
    ingested_at_ms: int = Field(..., description="UTC epoch milliseconds")


# --------------------------------------------------------------------------- #
# Ingest payload (mobile client → /ingest)
# --------------------------------------------------------------------------- #
class CellTowerInfo(BaseModel):
    mcc: int
    mnc: int
    lac: int
    cell_id: int


class DeviceTelemetry(BaseModel):
    last_known_outdoor_gps: Optional[GpsFix] = None
    connected_cell_tower: Optional[CellTowerInfo] = None
    nearby_wifi_bssids: Optional[List[str]] = None


class IngestRequest(BaseModel):
    image_base64: str
    exif_extracted_gps: Optional[Coordinates] = None
    device_telemetry: DeviceTelemetry = Field(default_factory=DeviceTelemetry)
    audio_base64: Optional[str] = None
    zero_retention: bool = False
    user_id: Optional[str] = None


# --------------------------------------------------------------------------- #
# Forensic upload (/analyze)
# --------------------------------------------------------------------------- #
class AnalyzeRequest(BaseModel):
    image_base64: str
    zero_retention: bool = False
    run_indoor_prompt: bool = True


class ReverseSearchRequest(BaseModel):
    """On-demand reverse source search for a single image (Visual Identifiers)."""
    image_base64: str
    search_query: Optional[str] = None


class BatchGeocodeRequest(BaseModel):
    """Forward-geocode a list of OCR text strings (street/place candidates)."""
    queries: List[str]


# --------------------------------------------------------------------------- #
# Brain output (vision + consensus)
# --------------------------------------------------------------------------- #
class VisualEvidenceTag(BaseModel):
    category: str = Field(..., description="architecture|botanical|ocr|infrastructure")
    label: str
    confidence: float = Field(0.0, ge=0.0, le=1.0)


class VisionResult(BaseModel):
    source: str
    estimated_latitude: Optional[float] = None
    estimated_longitude: Optional[float] = None
    search_radius_meters: Optional[float] = None
    confidence_score: float = 0.0
    primary_country: Optional[str] = None
    region: Optional[str] = None
    evidence_tags: List[VisualEvidenceTag] = Field(default_factory=list)
    raw: Optional[dict[str, Any]] = None
    # Terrain IMINT — ranked candidate regions from the vision-LLM reasoning pass.
    candidate_regions: List[dict[str, Any]] = Field(
        default_factory=list,
        description="Ranked top-3 candidate regions with confidence + rationale.",
    )


class CandidateRegion(BaseModel):
    """One ranked IMINT candidate region (terrain / vegetation / language)."""
    region: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: Optional[str] = None


class GeoCandidate(BaseModel):
    """A forward-geocoded OCR text candidate plotted on the spatial canvas."""
    query: str
    lat: float
    lon: float
    source: str = Field(
        default="nominatim",
        description="google | nominatim",
    )
    cached: bool = False
    matched: bool = True


class ConsensusResult(BaseModel):
    estimated_latitude: float
    estimated_longitude: float
    search_radius_meters: float
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    primary_country: Optional[str] = None
    region: Optional[str] = None
    visual_evidence_tags: List[VisualEvidenceTag] = Field(default_factory=list)
    tier_used: str = Field(..., description="metadata|telemetry|vision|consensus")
    flag_low_context_indoor: bool = False
    sources: List[str] = Field(default_factory=list)
    # ------------------------------------------------------------------ #
    # Monte-Carlo uncertainty quantification (probabilistic surface)
    # ------------------------------------------------------------------ #
    credible_interval_radius: Optional[float] = Field(
        None,
        description="95% credible-interval radius (metres) from Monte-Carlo sampling.",
    )
    probability_surface: Optional[dict] = Field(
        None,
        description="Coarse probability surface for map heatmap visualisation "
        "(center, sigma_m, grid).",
    )
    monte_carlo_samples: int = Field(
        0, description="Number of Monte-Carlo samples drawn.",
    )


# --------------------------------------------------------------------------- #
# IMINT — 4-pillar unified Image Data Extraction payload
# --------------------------------------------------------------------------- #
class GeospatialInfo(BaseModel):
    """Pillar 1 — Geospatial Intelligence (Where)."""
    latitude: Optional[str] = None
    latitude_ref: Optional[str] = None
    latitude_decimal: Optional[float] = None
    longitude: Optional[str] = None
    longitude_ref: Optional[str] = None
    longitude_decimal: Optional[float] = None
    gps_altitude: Optional[float] = None
    altitude_meters: Optional[float] = None
    altitude_ref: Optional[str] = None
    gps_img_direction: Optional[float] = None
    gps_img_direction_ref: Optional[str] = None
    gps_speed: Optional[float] = None
    gps_speed_ref: Optional[str] = None
    gps_processing_method: Optional[str] = None
    gps_dest_latitude: Optional[str] = None
    gps_dest_latitude_ref: Optional[str] = None
    dest_latitude_decimal: Optional[float] = None
    gps_dest_longitude: Optional[str] = None
    gps_dest_longitude_ref: Optional[str] = None
    dest_longitude_decimal: Optional[float] = None
    gps_dop: Optional[float] = None
    dop_quality: Optional[str] = None
    gps_satellites: Optional[str] = None
    gps_status: Optional[str] = None
    gps_measure_mode: Optional[str] = None
    has_coordinates: bool = False
    coords_plausible: bool = False


class TemporalInfo(BaseModel):
    """Pillar 2 — Chronological & Temporal Integrity (When)."""
    datetime_original: Optional[str] = None
    datetime_digitized: Optional[str] = None
    offset_time: Optional[str] = None
    offset_time_original: Optional[str] = None
    offset_time_digitized: Optional[str] = None
    subsec_time_original: Optional[str] = None
    subsec_time_digitized: Optional[str] = None
    gps_date_stamp: Optional[str] = None
    gps_time_stamp: Optional[str] = None
    device_clock_utc: Optional[str] = None
    satellite_clock_utc: Optional[str] = None
    clock_delta_seconds: Optional[int] = None
    clock_drift_detected: bool = False
    has_timestamps: bool = False


class DeviceInfo(BaseModel):
    """Pillar 3 — Hardware Provenance & Digital Fingerprinting."""
    make: Optional[str] = None
    model: Optional[str] = None
    lens_make: Optional[str] = None
    lens_model: Optional[str] = None
    body_serial_number: Optional[str] = None
    lens_serial_number: Optional[str] = None
    software: Optional[str] = None
    image_unique_id: Optional[str] = None
    owner_name: Optional[str] = None
    artist: Optional[str] = None
    copyright: Optional[str] = None
    profile_strings: Optional[dict[str, Optional[str]]] = None
    has_provenance: bool = False


class CaptureInfo(BaseModel):
    """Pillar 4 — Photographic Capture Diagnostics (How)."""
    exposure_time: Optional[float] = None
    exposure_time_str: Optional[str] = None
    f_number: Optional[float] = None
    aperture_value: Optional[float] = None
    shutter_speed_value: Optional[float] = None
    iso: Optional[int] = None
    flash: Optional[int] = None
    flash_fired: Optional[bool] = None
    focal_length: Optional[float] = None
    focal_length_35mm: Optional[int] = None
    metering_mode: Optional[int] = None
    light_source: Optional[int] = None
    sensing_method: Optional[int] = None
    exposure_program: Optional[int] = None
    has_capture: bool = False


class ImintAnalysis(BaseModel):
    """Derived intelligence computed over the four pillars."""
    pillars_present: dict[str, bool] = Field(default_factory=dict)
    clock_drift_detected: bool = False
    dop_quality: Optional[str] = None
    subsec_anomaly_detected: bool = False
    subsec_anomaly_reasons: List[str] = Field(default_factory=list)
    geospatial_conflicts: List[str] = Field(default_factory=list)
    unique_fingerprint: Optional[str] = None
    is_screenshot_likely: bool = False
    screenshot_aspect_ratio: Optional[float] = None
    screenshot_reasons: List[str] = Field(default_factory=list)


class ImintPayload(BaseModel):
    """Unified IMINT extraction payload — one key per pillar, always present."""
    geospatial: GeospatialInfo = Field(default_factory=GeospatialInfo)
    temporal: TemporalInfo = Field(default_factory=TemporalInfo)
    device: DeviceInfo = Field(default_factory=DeviceInfo)
    capture: CaptureInfo = Field(default_factory=CaptureInfo)
    analysis: ImintAnalysis = Field(default_factory=ImintAnalysis)


# --------------------------------------------------------------------------- #
# Full ingest / analyze response
# --------------------------------------------------------------------------- #
class AnalyzeResponse(BaseModel):
    request_id: str
    status: str = Field("SUCCESS", description="SUCCESS | PARTIAL_SUCCESS")
    source: str = Field(
        "NATIVE_EXIF_HARDWARE",
        description="NATIVE_EXIF_HARDWARE | TELEMETRY | AI_VISION | NO_METADATA_NO_AI_KEY",
    )
    custody_certificate: Optional[CustodyCertificate] = None
    custody_hash: str
    image_sha256: str
    consensus: ConsensusResult
    coordinates: Optional[Coordinates] = None
    address: Optional[AddressInfo] = None
    camera: dict[str, Any] = Field(default_factory=dict)
    altitude: Optional[float] = None
    datetime_original: Optional[str] = None
    exif_raw: Optional[dict[str, Any]] = None
    telemetry_resolve: Optional[Coordinates] = None
    message: Optional[str] = None
    steganography_detected: bool = False
    trailing_bytes_count: int = 0
    exif_missing: bool = False
    file_format: Optional[str] = None
    ela_heatmap: Optional[str] = None
    gps_spoofing_detected: bool = False
    anomaly_score: float = Field(0.0, ge=0.0, le=1.0)
    sanity_mismatches: List[str] = Field(default_factory=list)
    gps_climate_zone: Optional[str] = None
    visual_climate_zone: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # ------------------------------------------------------------------ #
    # Stripped-metadata fallback routing (Feature 1)
    # ------------------------------------------------------------------ #
    metadata_status: Optional[str] = Field(
        None,
        description="EXIF_PRESENT | STRIPPED_BY_INTERMEDIARY",
    )
    # ------------------------------------------------------------------ #
    # OCR → geocoding candidates (Feature 2)
    # ------------------------------------------------------------------ #
    geo_candidates: List["GeoCandidate"] = Field(
        default_factory=list,
        description="Forward-geocoded OCR text candidates (street/place).",
    )
    # ------------------------------------------------------------------ #
    # Terrain IMINT — ranked candidate regions (Feature 4)
    # ------------------------------------------------------------------ #
    candidate_regions: List["CandidateRegion"] = Field(
        default_factory=list,
        description="Ranked top-3 candidate regions from vision-LLM terrain reasoning.",
    )

    # ------------------------------------------------------------------ #
    # IMINT — 4-pillar unified Image Data Extraction payload (Image
    # Intelligence Core). Every field is Optional: a missing/stripped tag
    # is serialised as null, never dropped, never crashes.
    # ------------------------------------------------------------------ #
    image_intelligence: Optional["ImintPayload"] = None

    # ------------------------------------------------------------------ #
    # Workbench forensic extensions (deep analysis layer)
    # ------------------------------------------------------------------ #
    deep_metadata: Optional[dict[str, Any]] = Field(
        None,
        description="ExifTool deep metadata tree (groups + file_info).",
    )
    consistency_findings: List[dict[str, Any]] = Field(
        default_factory=list,
        description="Structured metadata consistency findings.",
    )
    provenance: Optional[dict[str, Any]] = Field(
        None,
        description="C2PA / Content Credentials provenance result.",
    )
    geolocation_fusion: Optional[dict[str, Any]] = Field(
        None,
        description="Multi-layer geolocation evidence model with explainability.",
    )
    source_discovery: Optional[dict[str, Any]] = Field(
        None,
        description="Reverse image search / source footprint result.",
    )
    contradictions: List[dict[str, Any]] = Field(
        default_factory=list,
        description="Structured contradictions detected across evidence layers.",
    )
    evidence_summary: Optional[dict[str, Any]] = Field(
        None,
        description="Investigation overview (what we know / don't know / suspicious).",
    )
    analysis_log: List[str] = Field(
        default_factory=list,
        description="Live analysis stream of forensic processing events.",
    )

    # ------------------------------------------------------------------ #
    # Universal Image Intelligence suite
    # ------------------------------------------------------------------ #
    streetview: Optional[dict[str, Any]] = Field(
        None,
        description="Google Street View panorama (metadata + static image URL).",
    )
    ai_evidence: Optional[dict[str, Any]] = Field(
        None,
        description="Discrete AI provider results (geospy / scene / reverse source).",
    )
    evidence_graph: Optional[dict[str, Any]] = Field(
        None,
        description="Provenance-tagged evidence graph (ai_hypothesis vs tool_inference).",
    )
    search_radius_meters: Optional[float] = Field(
        None,
        description="Probabilistic bounding-circle radius for the resolved pin.",
    )
    observations: List[dict[str, Any]] = Field(
        default_factory=list,
        description="Canonical structured observations (OBS-*) from every forensic layer.",
    )
    image_classification: Optional[str] = Field(
        None,
        description="Likely Screenshot | Likely Camera Photograph | Likely Exported Image | Unknown",
    )
    # ------------------------------------------------------------------ #
    # Step 1 — Original rehydration (recover GPS from a stripped share's
    # earliest known web copy via reverse-source + EXIF re-extraction)
    # ------------------------------------------------------------------ #
    recovered_original: Optional[dict[str, Any]] = Field(
        None,
        description="GPS/metadata recovered by rehydrating the original (pre-"
        "compression) copy discovered through reverse source search.",
    )
    # ------------------------------------------------------------------ #
    # Step 3 — Monte-Carlo + satellite cross-reference surfaced for the report
    # ------------------------------------------------------------------ #
    probability_surface: Optional[dict] = Field(
        None,
        description="Probability surface mirror of consensus.probability_surface "
        "for top-level report access.",
    )
    credible_interval_radius: Optional[float] = Field(
        None, description="Mirror of consensus.credible_interval_radius.",
    )
    satellite_crossref: Optional[dict] = Field(
        None,
        description="Satellite/aerial cross-reference of the predicted location.",
    )
    # ------------------------------------------------------------------ #
    # AI Intelligence Layer — structured assessment from the global model
    # ------------------------------------------------------------------ #
    ai_intelligence: Optional[dict[str, Any]] = Field(
        None,
        description="AI intelligence assessment (observations, contradictions, "
        "recommendations) from the global ARK-CAI model.",
    )


# --------------------------------------------------------------------------- #
# SOS
# --------------------------------------------------------------------------- #
class EmergencyContact(BaseModel):
    name: str
    phone: str
    relationship: Optional[str] = None

class SosRequest(BaseModel):
    user_id: str
    user_phone: Optional[str] = None
    last_capture_image_base64: Optional[str] = None
    last_known_gps: Optional[GpsFix] = None
    consensus: Optional[ConsensusResult] = None
    contacts: List[EmergencyContact]
    message: Optional[str] = None


class SosResponse(BaseModel):
    sos_id: str
    dispatched: bool
    contacted: List[str] = Field(default_factory=list)
    map_link: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --------------------------------------------------------------------------- #
# Dead-man's switch
# --------------------------------------------------------------------------- #
class DeadManConfig(BaseModel):
    user_id: str
    duration_minutes: int = Field(30, ge=1, le=1440)
    pin_hash: str
    emergency_contacts: List[EmergencyContact]
    last_capture_image_base64: Optional[str] = None
    last_known_gps: Optional[GpsFix] = None


class DeadManStatus(BaseModel):
    user_id: str
    armed: bool
    expires_at: Optional[datetime] = None
    grace_remaining_seconds: int = 0


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #
class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    services: dict[str, str] = Field(default_factory=dict)
    uptime_seconds: float


# --------------------------------------------------------------------------- #
# Admin Console auth & config
# --------------------------------------------------------------------------- #
class ApiKeysUpdate(BaseModel):
    geospy_api_key: Optional[str] = None
    geoinfer_api_key: Optional[str] = None
    llm_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    huggingface_api_key: Optional[str] = None
    mapbox_token: Optional[str] = None
    tineye_api_key: Optional[str] = None
    serper_api_key: Optional[str] = None
    google_maps_api_key: Optional[str] = None
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_from_number: Optional[str] = None
    hlr_api_key: Optional[str] = None
    opencellid_api_key: Optional[str] = None
    infobip_api_key: Optional[str] = None
    opencnam_account_sid: Optional[str] = None
    opencnam_auth_token: Optional[str] = None
    telesign_customer_id: Optional[str] = None
    telesign_rest_key: Optional[str] = None
    truid_client_id: Optional[str] = None
    truid_client_secret: Optional[str] = None
    reverse_search_api_key: Optional[str] = None
    ocr_api_key: Optional[str] = None
    c2pa_api_key: Optional[str] = None
    satellite_api_key: Optional[str] = None


class ThresholdsUpdate(BaseModel):
    min_confidence_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)
    default_uncertainty_radius: Optional[float] = Field(None, ge=100.0, le=50000.0)


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class AdminLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class AdminConfigKeyStatus(BaseModel):
    configured: bool
    key_preview: Optional[str] = None  # truncated, e.g. "sk-proj-...3f8a"


class AdminConfigResponse(BaseModel):
    api_keys: dict[str, AdminConfigKeyStatus] = Field(default_factory=dict)
    thresholds: dict[str, float] = Field(default_factory=dict)


class AdminConfigUpdate(BaseModel):
    api_keys: Optional[ApiKeysUpdate] = None
    thresholds: Optional[ThresholdsUpdate] = None


# --------------------------------------------------------------------------- #
# Threat / Geofence Alert
# --------------------------------------------------------------------------- #
class ThreatAlertRequest(BaseModel):
    alert_type: str = Field(..., description="geofence_violation | gps_spoofing")
    user_id: Optional[str] = None
    coordinates: Optional[Coordinates] = None
    anomaly_score: Optional[float] = None
    description: str = ""
    contacts: List[EmergencyContact] = Field(default_factory=list)


class ThreatAlertResponse(BaseModel):
    alert_id: str
    dispatched: bool
    contacted: List[str] = Field(default_factory=list)
    alert_type: str
    message: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --------------------------------------------------------------------------- #
# Analyst overrides
# --------------------------------------------------------------------------- #
class AnalystOverrideRequest(BaseModel):
    image_sha256: str
    finding_key: str = Field(..., description="e.g. 'location', 'integrity', 'provenance'")
    decision: str = Field(..., description="confirm | reject | needs_review")
    note: str = ""
    analyst_id: str = "analyst"


class AnalystOverrideResponse(BaseModel):
    image_sha256: str
    finding_key: str
    decision: str
    note: str = ""
    analyst_id: str
    logged_at_ms: int


class AnalystOverrideListResponse(BaseModel):
    overrides: List[dict[str, Any]] = Field(default_factory=list)
