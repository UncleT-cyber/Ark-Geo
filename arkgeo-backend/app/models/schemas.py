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
    custody_hash: str
    image_sha256: str
    consensus: ConsensusResult
    exif_raw: Optional[dict[str, Any]] = None
    telemetry_resolve: Optional[Coordinates] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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
