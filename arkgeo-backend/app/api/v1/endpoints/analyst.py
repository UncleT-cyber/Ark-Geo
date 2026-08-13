"""Analyst override endpoints — record and retrieve human assessment.

Separates machine findings from analyst conclusions.  Every override is
logged to the audit trail so the chain of custody remains complete.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.models import (
    AnalystOverrideListResponse,
    AnalystOverrideRequest,
    AnalystOverrideResponse,
)
from app.services.analyst_overrides import analyst_override_store

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/analyst-override", response_model=AnalystOverrideResponse)
async def record_override(request: AnalystOverrideRequest):
    """Record an analyst decision (confirm / reject / needs_review) + note."""
    try:
        result = analyst_override_store.record(
            image_sha256=request.image_sha256,
            finding_key=request.finding_key,
            decision=request.decision,
            note=request.note,
            analyst_id=request.analyst_id,
        )
        logger.info(
            "Analyst override recorded: %s=%s for %s",
            request.finding_key, request.decision, request.image_sha256[:12],
        )
        return AnalystOverrideResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/analyst-overrides/{image_sha256}", response_model=AnalystOverrideListResponse)
async def list_overrides(image_sha256: str):
    """List all analyst overrides for a given image (by SHA-256)."""
    overrides = analyst_override_store.list_for_image(image_sha256)
    return AnalystOverrideListResponse(overrides=overrides)
