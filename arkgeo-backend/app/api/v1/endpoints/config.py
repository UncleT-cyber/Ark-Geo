"""ARK — central AI configuration endpoint.

Single source of truth for the *active* LLM. The terminal banner, every
workspace agent, and the Admin Console all read the active provider/model from
here so the UI never hardcodes or caches a stale model string.

Endpoints
--------
* ``GET /config/active-model``  — the live ``provider`` + ``model_name`` the
  whole system is currently bound to (from central config / Admin Console).
* ``GET /config/huggingface-models`` — the free HuggingFace router models
  available at ``https://router.huggingface.co/v1`` (live, curated fallback).
"""
from __future__ import annotations

from fastapi import APIRouter

from app.services.ai_gateway import get_active_litellm_model
from app.services.model_catalog import fetch_models

router = APIRouter(prefix="/config")


@router.get("/active-model")
async def active_model():
    """Live active model (single source of truth from central config).

    Returns ``provider`` / ``model_name`` so clients (terminal banner, settings
    panel) render exactly what the Admin Console selected — never a hardcoded
    default.
    """
    info = get_active_litellm_model()
    model_string = info.get("model", "unknown")
    if "/" in model_string:
        provider, model_name = model_string.split("/", 1)
    else:
        provider, model_name = model_string, model_string
    return {"provider": provider, "model_name": model_name, "model": model_string}


@router.get("/huggingface-models")
async def huggingface_models():
    """Free HuggingFace models available on the router.

    Fetches the live catalog from ``https://router.huggingface.co/v1`` and
    falls back to the curated ARK ISE whitelist if the router is unreachable.
    """
    from app.services.admin_store import admin_store
    from app.services.settings_store import settings_store

    gw = admin_store.get_gateway()
    api_key = settings_store.get_key("huggingface_api_key") or ""
    base_url = gw.get("huggingface_url") or "https://router.huggingface.co/v1"
    result = await fetch_models(
        "huggingface", api_key=api_key, base_url=base_url
    )
    return result
