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
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_from_number: Optional[str] = None


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
