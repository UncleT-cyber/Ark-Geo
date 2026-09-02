"""BYOK (Bring Your Own Keys) public endpoints.

``/tools/test-connection`` lets a client validate their OWN key against a
provider without exposing it in logs or sharing it with other tenants.
The key is sent in the request body over HTTPS, used only inside an
outgoing probe header, and discarded.  These endpoints require NO admin
auth — they are part of the client settings surface.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.key_probe import (
    live_probe,
    probe_description,
    PROVIDER_KEY_FIELDS,
)

router = APIRouter(prefix="/tools")

# Provider ids supported by the BYOK key inputs.
BYOK_PROVIDERS = set(PROVIDER_KEY_FIELDS.keys())


class TestConnectionRequest(BaseModel):
    provider: str = Field(..., description="Provider id (openai, gemini, mapbox, ...)")
    key: str = Field("", description="Client-supplied API key to validate (never stored/logged)")
    extra: dict[str, str] = Field(
        default_factory=dict,
        description="Optional paired credentials for multi-key providers (twilio/opencnam/telesign/truid)",
    )


class TestConnectionResponse(BaseModel):
    provider: str
    valid: bool
    detail: str
    latency_ms: int
    method: str


@router.post("/test-connection", response_model=TestConnectionResponse)
async def test_connection(body: TestConnectionRequest):
    provider = (body.provider or "").lower().strip()
    if provider not in BYOK_PROVIDERS:
        raise HTTPException(status_code=422, detail="Unsupported provider")
    key = (body.key or "").strip()
    if not key:
        return TestConnectionResponse(
            provider=provider, valid=False, detail="No key provided",
            latency_ms=0, method=probe_description(provider),
        )
    result = await live_probe(provider, key, body.extra)
    return TestConnectionResponse(
        provider=provider,
        valid=bool(result.get("valid")),
        detail=str(result.get("detail", "")),
        latency_ms=int(result.get("latency_ms", 0)),
        method=probe_description(provider),
    )
