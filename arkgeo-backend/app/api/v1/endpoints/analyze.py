"""Analyze endpoint – direct forensic upload (investigator portal)."""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.brain.metadata_extractor import MetadataExtractor
from app.brain.pipeline import brain
from app.core.config import settings
from app.core.security import custody_hash
from app.models import AnalyzeResponse, AnalyzeRequest
from app.services.storage_service import storage

router = APIRouter()
logger = logging.getLogger(__name__)


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

    # Storage + chain-of-custody
    retention = zero_retention or settings.default_zero_retention
    stored = storage.store_image(image_bytes, zero_retention=retention)
    custody = custody_hash(image_bytes, {"request_id": request_id, "filename": file.filename})

    # Run the full Brain pipeline
    consensus, exif_raw = await brain.analyze(image_bytes, run_indoor=run_indoor)

    # Zero-retention cleanup
    if retention:
        storage.delete_image(stored["path"])

    return AnalyzeResponse(
        request_id=request_id,
        custody_hash=custody,
        image_sha256=stored["sha256"],
        consensus=consensus,
        exif_raw=exif_raw,
    )


@router.post("/analyze/base64", response_model=AnalyzeResponse)
async def analyze_base64(request: AnalyzeRequest):
    """JSON/base64 variant for programmatic access."""
    request_id = str(uuid.uuid4())
    try:
        image_bytes = MetadataExtractor.decode_base64_image(request.image_base64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid image_base64: {exc}")

    retention = request.zero_retention or settings.default_zero_retention
    stored = storage.store_image(image_bytes, zero_retention=retention)
    custody = custody_hash(image_bytes, {"request_id": request_id})

    consensus, exif_raw = await brain.analyze(
        image_bytes, run_indoor=request.run_indoor_prompt
    )

    if retention:
        storage.delete_image(stored["path"])

    return AnalyzeResponse(
        request_id=request_id,
        custody_hash=custody,
        image_sha256=stored["sha256"],
        consensus=consensus,
        exif_raw=exif_raw,
    )
