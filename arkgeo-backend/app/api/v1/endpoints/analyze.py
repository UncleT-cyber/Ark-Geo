"""Analyze endpoint – direct forensic upload (investigator portal).

Follows the same failover cascade as /ingest but accepts a multipart file
upload and a base64 variant for programmatic access.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.brain.metadata_extractor import MetadataExtractor
from app.brain.pipeline import brain
from app.core.config import settings
from app.models import AnalyzeResponse, AnalyzeRequest, CustodyCertificate
from app.services.storage_service import storage

router = APIRouter()
logger = logging.getLogger(__name__)


async def _run_cascade(
    image_bytes: bytes,
    request_id: str,
    zero_retention: bool,
    run_indoor: bool,
) -> AnalyzeResponse:
    """Shared cascade runner for both upload and base64 endpoints."""
    retention = zero_retention or settings.default_zero_retention
    stored = storage.store_image(image_bytes, zero_retention=retention)

    cascade = await brain.analyze(
        image_bytes,
        run_indoor=run_indoor,
        request_id=request_id,
    )

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
    )


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    file: UploadFile = File(...),
    zero_retention: bool = False,
    run_indoor: bool = True,
):
    """Accept a multipart image upload for forensic analysis."""
    request_id = str(uuid.uuid4())
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty image upload")
    return await _run_cascade(image_bytes, request_id, zero_retention, run_indoor)


@router.post("/analyze/base64", response_model=AnalyzeResponse)
async def analyze_base64(request: AnalyzeRequest):
    """JSON/base64 variant for programmatic access."""
    request_id = str(uuid.uuid4())
    try:
        image_bytes = MetadataExtractor.decode_base64_image(request.image_base64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid image_base64: {exc}")
    return await _run_cascade(
        image_bytes, request_id, request.zero_retention, request.run_indoor_prompt
    )
