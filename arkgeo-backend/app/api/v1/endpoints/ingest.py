"""Ingest endpoint – image + audio intake pipeline (mobile client).

Follows the strict failover cascade:
  1. Cryptographic hashes (always)
  2. Native EXIF hardware extraction → direct pin + reverse geocode
  3. Cell / Wi-Fi telemetry
  4. AI vision ensemble (if keys configured)
  5. Graceful degradation
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException

from app.brain.metadata_extractor import MetadataExtractor
from app.brain.pipeline import brain
from app.models import AnalyzeResponse, Coordinates, CustodyCertificate, IngestRequest
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

    # Storage (hash computed inside cascade as well, but store_image needs bytes)
    stored = storage.store_image(image_bytes, zero_retention=request.zero_retention)

    # Run the full cascade pipeline
    cascade = await brain.analyze(
        image_bytes,
        device_telemetry=request.device_telemetry,
        user_id=request.user_id,
        run_indoor=True,
        request_id=request_id,
    )

    # Zero-retention cleanup
    if request.zero_retention:
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
