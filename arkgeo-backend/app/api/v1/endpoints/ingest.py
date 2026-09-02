"""Ingest endpoint – image + audio intake pipeline (mobile client).

Follows the strict failover cascade:
  1. Cryptographic triple-hash (SHA-256 + SHA-1 + MD5) — always
  2. Magic-byte validation — rejects spoofed MIME types with HTTP 415
  3. Native EXIF hardware extraction → direct pin + reverse geocode
  4. Cell / Wi-Fi telemetry
  5. AI vision ensemble (if keys configured)
  6. Graceful degradation

Security features:
  * Magic-byte validation — anti-spoofing on declared image format
  * Zero-Retention-Mode header — RAM-only processing, no disk/S3 writes
  * Steganography / EOF anomaly detection flags
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Header, HTTPException

from app.brain.metadata_extractor import MetadataExtractor, detect_format
from app.brain.pipeline import brain
from app.core.security import validate_magic_bytes
from app.models import AnalyzeResponse, Coordinates, CustodyCertificate, IngestRequest
from app.services.storage_service import storage

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/ingest", response_model=AnalyzeResponse)
async def ingest(
    request: IngestRequest,
    x_zero_retention_mode: str | None = Header(default=None, alias="Zero-Retention-Mode"),
):
    request_id = str(uuid.uuid4())

    try:
        image_bytes = MetadataExtractor.decode_base64_image(request.image_base64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid image_base64: {exc}")

    # ---- Magic-byte validation (anti-spoofing) ---------------------------
    try:
        detected_format = validate_magic_bytes(image_bytes)
    except ValueError as exc:
        logger.warning("Magic-byte validation failed [request=%s]: %s", request_id, exc)
        raise HTTPException(status_code=415, detail=str(exc))

    # ---- Resolve zero-retention from header or body ----------------------
    zr_header = (x_zero_retention_mode or "").strip().lower()
    zero_retention = request.zero_retention or zr_header in ("true", "1", "yes")

    # ---- Storage (skipped entirely in zero-retention RAM-only mode) -------
    # In zero-retention mode the bytes never touch disk or S3 — they are
    # passed straight through to the cascade as an in-memory buffer.
    stored = storage.store_image(image_bytes, zero_retention=zero_retention)

    # ---- Run the full cascade pipeline ------------------------------------
    cascade = await brain.analyze(
        image_bytes,
        device_telemetry=request.device_telemetry,
        user_id=request.user_id,
        run_indoor=True,
        request_id=request_id,
    )

    # ---- Zero-retention cleanup -------------------------------------------
    if zero_retention:
        storage.delete_image(stored["path"])

    return AnalyzeResponse(
        request_id=request_id,
        status=cascade.status,
        source=cascade.source,
        custody_certificate=CustodyCertificate(**cascade.custody_certificate),
        custody_hash=cascade.custody_hash,
        image_sha256=cascade.image_sha256,
        consensus=cascade.consensus,
        coordinates=cascade.coordinates,
        address=cascade.address,
        camera=cascade.camera,
        altitude=cascade.altitude,
        datetime_original=cascade.datetime_original,
        exif_raw=cascade.exif_raw or None,
        telemetry_resolve=cascade.telemetry_resolve,
        message=cascade.message,
        steganography_detected=cascade.steganography_detected,
        trailing_bytes_count=cascade.trailing_bytes_count,
        exif_missing=cascade.exif_missing,
        file_format=cascade.file_format or detected_format,
        ela_heatmap=cascade.ela_heatmap,
        image_intelligence=cascade.image_intelligence,
        gps_spoofing_detected=cascade.gps_spoofing_detected,
        anomaly_score=cascade.anomaly_score,
        sanity_mismatches=cascade.sanity_mismatches,
        gps_climate_zone=cascade.gps_climate_zone,
        visual_climate_zone=cascade.visual_climate_zone,
    )
