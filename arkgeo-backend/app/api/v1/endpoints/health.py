"""Health endpoint – system diagnostic telemetry."""
from __future__ import annotations

import time

from fastapi import APIRouter

from app.core.config import settings
from app.models import HealthResponse
from app.services.twilio_service import twilio

router = APIRouter()

_start_time = time.time()


@router.get("/health", response_model=HealthResponse)
async def health():
    services = {
        "vision_geospy": "configured" if settings.geospy_api_key else "not_configured",
        "vision_geoinfer": "configured" if settings.geoinfer_api_key else "not_configured",
        "llm": "configured" if settings.llm_api_key else "not_configured",
        "twilio": "configured" if twilio.is_configured else "not_configured",
        "opencellid": "configured" if settings.opencellid_api_key else "not_configured",
        "storage": settings.storage_backend,
    }
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        services=services,
        uptime_seconds=round(time.time() - _start_time, 2),
    )
