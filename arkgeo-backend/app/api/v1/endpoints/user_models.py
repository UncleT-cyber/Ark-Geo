"""User-facing model preferences, BYOK credentials and entitlements.

Phase 2 (persistence) + Phase 3 (credential separation) + Phase 6 (entitlements
surface) for the operator/user surface.  Administrator configuration of
platform providers and policy stays in the admin console; these routes only
ever act on the caller's own principal namespace.
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.services.entitlements import evaluate, resolve_entitlement
from app.services.principal import principal_from_request
from app.services.user_credentials import USER_KEY_PROVIDERS, user_credentials
from app.services.user_preferences import user_preferences

router = APIRouter(prefix="/user/model")


# --------------------------------------------------------------------------- #
# Preferences (Phase 2)
# --------------------------------------------------------------------------- #
class PreferenceRequest(BaseModel):
    selected_model: Optional[str] = Field(None, description="Canonical '<provider>/<model>' or null to clear")


@router.get("/preference")
async def get_preference(request: Request):
    """The caller's saved model preference (independent of admin default)."""
    principal = principal_from_request(request)
    prefs = user_preferences.get(principal.namespace())
    return {"principal": principal.subject, "selected_model": prefs.get("selected_model"),
            "model_pins": prefs.get("model_pins") or {}}


@router.put("/preference")
async def set_preference(body: PreferenceRequest, request: Request):
    """Persist the caller's explicit model selection (Phase 2 rule 2)."""
    from app.services.model_router import resolve

    principal = principal_from_request(request)
    if body.selected_model:
        resolution = resolve(principal, body.selected_model)
        if not resolution.ok:
            return {"ok": False, "error": resolution.error, "code": resolution.error_code}
    prefs = user_preferences.set_selected_model(principal.namespace(), body.selected_model)
    return {"ok": True, "selected_model": prefs.get("selected_model")}


@router.delete("/preference")
async def clear_preference(request: Request):
    """Clear the saved preference — the admin default then applies again."""
    principal = principal_from_request(request)
    prefs = user_preferences.set_selected_model(principal.namespace(), None)
    return {"ok": True, "selected_model": prefs.get("selected_model")}


# --------------------------------------------------------------------------- #
# BYOK credentials (Phase 3)
# --------------------------------------------------------------------------- #
class CredentialRequest(BaseModel):
    provider: str
    key: str = Field("", description="Provider API key (never echoed back)")
    test: bool = Field(True, description="Run a live connection test before storing")


def _validate_provider_endpoint(provider: str, endpoint: Optional[str]) -> Optional[str]:
    """SSRF guard for user-supplied endpoints (Phase 3).

    Rejects non-HTTPS, loopback/private/link-local/reserved addresses and
    ``.internal`` names so a user cannot point a provider at internal services.
    Returns an error string, or ``None`` when the endpoint is acceptable.
    """
    if not endpoint:
        return None
    parsed = urlparse(endpoint)
    if parsed.scheme != "https":
        return "Endpoint must use https://"
    host = parsed.hostname or ""
    if not host:
        return "Endpoint has no host"
    if host.endswith(".internal") or host.endswith(".local"):
        return "Endpoint host is not permitted"
    try:
        addrs = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except OSError:
        addrs = set()
    for addr in addrs:
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return "Endpoint resolves to a private/internal address"
    return None


@router.get("/credentials")
async def list_credentials(request: Request):
    """Which BYOK providers the caller has configured (masked, never raw)."""
    principal = principal_from_request(request)
    return {"principal": principal.subject, "providers": user_credentials.status(principal.namespace()),
            "supported": list(USER_KEY_PROVIDERS)}


@router.post("/credentials")
async def set_credential(body: CredentialRequest, request: Request):
    """Store a user API key (encrypted) after an optional live connection test."""
    principal = principal_from_request(request)
    provider = (body.provider or "").strip().lower()
    if provider not in USER_KEY_PROVIDERS:
        return {"ok": False, "error": f"Unsupported provider '{provider}'"}

    key = (body.key or "").strip()
    if not key:
        user_credentials.set_key(principal.namespace(), provider, None)
        return {"ok": True, "provider": provider, "configured": False, "revoked": True}

    if body.test:
        from app.services.key_probe import live_probe

        probe = await live_probe(provider, key, {})
        if not probe.get("valid"):
            return {"ok": False, "provider": provider, "error": probe.get("detail", "connection test failed"),
                    "code": "credential_invalid"}

    user_credentials.set_key(principal.namespace(), provider, key)
    return {"ok": True, "provider": provider, "configured": True, "stored": "encrypted"}


@router.delete("/credentials/{provider}")
async def revoke_credential(provider: str, request: Request):
    """Revoke a stored user credential."""
    principal = principal_from_request(request)
    provider = (provider or "").strip().lower()
    if provider not in USER_KEY_PROVIDERS:
        return {"ok": False, "error": f"Unsupported provider '{provider}'"}
    user_credentials.set_key(principal.namespace(), provider, None)
    return {"ok": True, "provider": provider, "revoked": True}


# --------------------------------------------------------------------------- #
# Entitlements (Phase 6 — read-only view for the caller)
# --------------------------------------------------------------------------- #
@router.get("/entitlements")
async def my_entitlements(request: Request):
    """The effective entitlement for the caller (no secrets, no admin internals)."""
    principal = principal_from_request(request)
    eff, source = resolve_entitlement(principal)
    return {
        "principal": principal.subject,
        "source": source,
        "plan": eff.get("plan"),
        "allow_platform": eff.get("allow_platform"),
        "allow_byok": eff.get("allow_byok"),
        "allow_local": eff.get("allow_local"),
        "allowed_providers": eff.get("allowed_providers"),
        "subscription_models": eff.get("subscription_models"),
        "usage_limits": eff.get("usage_limits"),
    }
