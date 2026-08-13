"""Ingest endpoint – image + audio intake pipeline (mobile client)."""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException

from app.brain.metadata_extractor import MetadataExtractor
from app.brain.pipeline import brain
from app.core.security import custody_hash
from app.models import AnalyzeResponse, Coordinates, IngestRequest
from app.services.storage_service import storage

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/ingest", response_model=AnalyzeResponse)
async def ingest(request: IngestRequest):
    request_id = str(uuid.uuid4())

    try:
        image_bytes = MetadataExtractor.decode_base64_image(request.image_base64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid image_base64: {exc}")

    # Storage + chain-of-custody
    stored = storage.store_image(image_bytes, zero_retention=request.zero_retention)
    custody = custody_hash(image_bytes, {"request_id": request_id})

    # Run the full Brain pipeline
    consensus, exif_raw = await brain.analyze(
        image_bytes,
        device_telemetry=request.device_telemetry,
        user_id=request.user_id,
    )

    # Telemetry resolve for the response (may differ from consensus tier)
    telemetry_resolve = None
    if consensus.tier_used == "telemetry":
        telemetry_resolve = Coordinates(
            lat=consensus.estimated_latitude,
            lon=consensus.estimated_longitude,
        )

    # Zero-retention cleanup
    if request.zero_retention:
        storage.delete_image(stored["path"])

    return AnalyzeResponse(
        request_id=request_id,
        custody_hash=custody,
        image_sha256=stored["sha256"],
        consensus=consensus,
        exif_raw=exif_raw,
        telemetry_resolve=telemetry_resolve,
    )
