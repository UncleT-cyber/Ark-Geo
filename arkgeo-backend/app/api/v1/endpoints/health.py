"""Health endpoint – system diagnostic telemetry."""
from __future__ import annotations

import time

from fastapi import APIRouter

from app.core.config import settings
from app.models import HealthResponse
from app.services.settings_store import settings_store
from app.services.twilio_service import twilio

router = APIRouter()

_start_time = time.time()


@router.get("/health", response_model=HealthResponse)
async def health():
    def configured(env_attr: str, store_name: str) -> str:
        return "configured" if (settings_store.get_key(store_name) or getattr(settings, env_attr, None)) else "not_configured"

    services = {
        "vision_geospy": configured("geospy_api_key", "geospy_api_key"),
        "vision_geoinfer": configured("geoinfer_api_key", "geoinfer_api_key"),
        "llm": configured("llm_api_key", "llm_api_key"),
        "gemini": configured("gemini_api_key", "gemini_api_key"),
        "anthropic": configured("anthropic_api_key", "anthropic_api_key"),
        "mapbox": configured("mapbox_token", "mapbox_token"),
        "tineye": configured("tineye_api_key", "tineye_api_key"),
        "serper": configured("serper_api_key", "serper_api_key"),
        "tavily": configured("tavily_api_key", "tavily_api_key"),
        "streetview": configured("google_maps_api_key", "google_maps_api_key"),
        "twilio": "configured" if twilio.is_configured else "not_configured",
        "opencellid": configured("opencellid_api_key", "opencellid_api_key"),
        "storage": settings.storage_backend,
    }
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        services=services,
        uptime_seconds=round(time.time() - _start_time, 2),
    )
