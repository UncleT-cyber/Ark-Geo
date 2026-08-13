"""Settings endpoint — admin API key management + engine thresholds.

All API keys are stored encrypted in the settings store.  GET responses
never return key values — only a boolean ``configured`` flag.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter

from app.models import (
    ApiKeysUpdate,
    SettingsResponse,
    SettingsUpdate,
    ThresholdsUpdate,
)
from app.services.settings_store import settings_store

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/settings", response_model=SettingsResponse)
async def get_settings():
    """Return current settings: key configured flags + thresholds."""
    return SettingsResponse(
        api_keys=settings_store.get_keys_configured(),
        thresholds=settings_store.get_thresholds(),
    )


@router.put("/settings", response_model=SettingsResponse)
async def update_settings(update: SettingsUpdate):
    """Update API keys and/or thresholds.  Persists encrypted to SQLite."""
    if update.api_keys:
        keys_dict = {
            "geospy_api_key": update.api_keys.geospy_api_key,
            "geoinfer_api_key": update.api_keys.geoinfer_api_key,
            "llm_api_key": update.api_keys.llm_api_key,
            "twilio_account_sid": update.api_keys.twilio_account_sid,
            "twilio_auth_token": update.api_keys.twilio_auth_token,
            "twilio_from_number": update.api_keys.twilio_from_number,
        }
        settings_store.update_api_keys(keys_dict)
        logger.info("Admin settings: API keys updated")

    if update.thresholds:
        t = {}
        if update.thresholds.min_confidence_threshold is not None:
            t["min_confidence_threshold"] = update.thresholds.min_confidence_threshold
        if update.thresholds.default_uncertainty_radius is not None:
            t["default_uncertainty_radius"] = update.thresholds.default_uncertainty_radius
        settings_store.update_thresholds(t)
        logger.info("Admin settings: thresholds updated")

    return SettingsResponse(
        api_keys=settings_store.get_keys_configured(),
        thresholds=settings_store.get_thresholds(),
    )


@router.post("/settings/test-connection")
async def test_api_connection(key_name: str):
    """Test whether a given API key is configured (does not make external calls).

    Returns a simple boolean indicating whether the key is set.
    """
    configured = bool(settings_store.get_key(key_name))
    return {"key_name": key_name, "configured": configured}
