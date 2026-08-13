"""Analyze endpoint – direct forensic upload (investigator portal).

Follows the same failover cascade as /ingest but accepts a multipart file
upload and a base64 variant for programmatic access.

Security features:
  * Magic-byte validation — rejects spoofed MIME types with HTTP 415
  * Zero-Retention-Mode header — RAM-only processing, no disk/S3 writes
  * Triple-hash custody (SHA-256 + SHA-1 + MD5) in every response
  * Steganography / EOF anomaly detection flags
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, File, Header, HTTPException, UploadFile, Request

from app.brain.metadata_extractor import MetadataExtractor
from app.brain.pipeline import brain
from app.core.config import settings
from app.core.security import validate_magic_bytes
from app.models import AnalyzeResponse, AnalyzeRequest, CustodyCertificate
from app.services.storage_service import storage

router = APIRouter()
logger = logging.getLogger(__name__)


async def _run_cascade(
    image_bytes: bytes,
    request_id: str,
    zero_retention: bool,
    run_indoor: bool,
    declared_type: str | None = None,
) -> AnalyzeResponse:
    """Shared cascade runner for both upload and base64 endpoints.

    Validates magic bytes, then runs the full brain cascade and maps the
    :class:`CascadeResult` into an :class:`AnalyzeResponse`.
    """
    # ---- Magic-byte validation (anti-spoofing) ---------------------------
    try:
        detected_format = validate_magic_bytes(image_bytes, declared_type)
    except ValueError as exc:
        logger.warning("Magic-byte validation failed [request=%s]: %s", request_id, exc)
        raise HTTPException(status_code=415, detail=str(exc))

    retention = zero_retention or settings.default_zero_retention

    # ---- Storage (skipped entirely in zero-retention RAM-only mode) -------
    stored = storage.store_image(image_bytes, zero_retention=retention)

    # ---- Run the full cascade pipeline ------------------------------------
    cascade = await brain.analyze(
        image_bytes,
        run_indoor=run_indoor,
        request_id=request_id,
    )

    # ---- Zero-retention cleanup -------------------------------------------
    if retention:
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
        gps_spoofing_detected=cascade.gps_spoofing_detected,
        anomaly_score=cascade.anomaly_score,
        sanity_mismatches=cascade.sanity_mismatches,
        gps_climate_zone=cascade.gps_climate_zone,
        visual_climate_zone=cascade.visual_climate_zone,
    )


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    request: Request,
    file: UploadFile = File(...),
    zero_retention: bool = False,
    run_indoor: bool = True,
    x_zero_retention_mode: str | None = Header(default=None, alias="Zero-Retention-Mode"),
):
    """Accept a multipart image upload for forensic analysis.

    Reads the ``Zero-Retention-Mode`` HTTP header (case-insensitive value
    ``"true"``) to enable RAM-only processing — no bytes touch disk or S3.
    """
    request_id = str(uuid.uuid4())
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty image upload")

    # Resolve zero-retention from header or query param
    zr_header = (x_zero_retention_mode or "").strip().lower()
    zero_retention = zero_retention or zr_header in ("true", "1", "yes")

    declared_type = file.content_type
    return await _run_cascade(image_bytes, request_id, zero_retention, run_indoor, declared_type)


@router.post("/analyze/base64", response_model=AnalyzeResponse)
async def analyze_base64(
    request: AnalyzeRequest,
    x_zero_retention_mode: str | None = Header(default=None, alias="Zero-Retention-Mode"),
):
    """JSON/base64 variant for programmatic access."""
    request_id = str(uuid.uuid4())
    try:
        image_bytes = MetadataExtractor.decode_base64_image(request.image_base64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid image_base64: {exc}")

    zr_header = (x_zero_retention_mode or "").strip().lower()
    zero_retention = request.zero_retention or zr_header in ("true", "1", "yes")

    return await _run_cascade(
        image_bytes, request_id, zero_retention, request.run_indoor_prompt,
    )
