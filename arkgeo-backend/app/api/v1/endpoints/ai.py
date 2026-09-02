"""AI gateway status endpoint — the runtime route every AI consumer is on.

Reports the unified provider cascade state (``cloud`` / ``local_ollama`` /
``offline``) that powers the GS / GI / LLM badges in the web header and the
Admin Console model-gateway panel.  Reads are cheap (server-side cache) and
never expose key material — only configured flags and route state.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.services.ai_gateway import ai_gateway

router = APIRouter()


@router.get("/ai/status")
async def ai_status() -> dict[str, Any]:
    return await ai_gateway.status()
