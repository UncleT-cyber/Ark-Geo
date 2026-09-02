"""Admin Console endpoints — authenticated API key management.

All endpoints under /admin/* require a valid admin JWT bearer token.
API keys are stored encrypted (AES-256-GCM) in the settings store and
are NEVER returned in plain text to the frontend.  GET responses return
only masked previews (truncated first/last characters).
"""
from __future__ import annotations

import logging
from typing import Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel

from app.core.config import settings, get_admin_password_hash
from app.core.security import create_access_token, decode_access_token, verify_password
from app.models import (
    AdminConfigResponse,
    AdminConfigUpdate,
    AdminLoginRequest,
    AdminLoginResponse,
)
from app.services.settings_store import settings_store

router = APIRouter(prefix="/admin")
logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# JWT dependency
# --------------------------------------------------------------------------- #
async def require_admin_token(
    authorization: Optional[str] = Header(default=None),
) -> str:
    """FastAPI dependency that validates the admin JWT bearer token.

    Returns the subject (username) on success, raises 401 otherwise.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1]
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired admin token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Verify the token has the admin role claim
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Insufficient privileges")
    return payload.get("sub", "admin")


# --------------------------------------------------------------------------- #
# Login
# --------------------------------------------------------------------------- #
@router.post("/login", response_model=AdminLoginResponse)
async def admin_login(request: AdminLoginRequest):
    """Authenticate admin credentials and return a JWT access token."""
    if request.username != settings.admin_username:
        logger.warning("Admin login failed: bad username '%s'", request.username)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    password_hash = get_admin_password_hash()
    if not verify_password(request.password, password_hash):
        logger.warning("Admin login failed: bad password for '%s'", request.username)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(
        subject=request.username,
        extra_claims={"role": "admin"},
        expires_minutes=settings.admin_jwt_expiry_minutes,
    )
    logger.info("Admin login successful for '%s'", request.username)
    return AdminLoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.admin_jwt_expiry_minutes * 60,
    )


# --------------------------------------------------------------------------- #
# Config — protected by JWT
# --------------------------------------------------------------------------- #
@router.get("/config", response_model=AdminConfigResponse)
async def get_admin_config(admin: str = Depends(require_admin_token)):
    """Return masked API key status + thresholds.

    CRITICAL: Never returns plain-text API keys.  Only returns
    ``configured`` boolean and a truncated ``key_preview``.
    """
    masked = settings_store.get_keys_masked()
    api_keys = {
        name: {"configured": v["configured"], "key_preview": v["key_preview"]}
        for name, v in masked.items()
    }
    return AdminConfigResponse(
        api_keys=api_keys,
        thresholds=settings_store.get_thresholds(),
    )


@router.post("/config", response_model=AdminConfigResponse)
async def update_admin_config(
    update: AdminConfigUpdate,
    admin: str = Depends(require_admin_token),
):
    """Update API keys and/or thresholds.  Keys are encrypted server-side.

    Submitted key values are AES-256-GCM encrypted and stored in SQLite.
    They are pulled directly from the encrypted store by the vision
    pipeline — never exposed to the user's browser.
    """
    if update.api_keys:
        keys_dict = {
            name: value
            for name, value in update.api_keys.model_dump().items()
            if value is not None
        }
        if keys_dict:
            settings_store.update_api_keys(keys_dict)
            logger.info("Admin '%s' updated API keys", admin)

    if update.thresholds:
        t = {}
        if update.thresholds.min_confidence_threshold is not None:
            t["min_confidence_threshold"] = update.thresholds.min_confidence_threshold
        if update.thresholds.default_uncertainty_radius is not None:
            t["default_uncertainty_radius"] = update.thresholds.default_uncertainty_radius
        settings_store.update_thresholds(t)
        logger.info("Admin '%s' updated thresholds", admin)

    masked = settings_store.get_keys_masked()
    api_keys = {
        name: {"configured": v["configured"], "key_preview": v["key_preview"]}
        for name, v in masked.items()
    }
    return AdminConfigResponse(
        api_keys=api_keys,
        thresholds=settings_store.get_thresholds(),
    )


# --------------------------------------------------------------------------- #
# Test connection — protected by JWT
# --------------------------------------------------------------------------- #
class TestConnectionResponse(BaseModel):
    key_name: str
    configured: bool
    valid: bool = False
    detail: str = ""


@router.post("/config/test-connection", response_model=TestConnectionResponse)
async def test_api_connection(
    key_name: str,
    admin: str = Depends(require_admin_token),
):
    """Probe whether the stored admin key actually connects to its provider."""
    from app.services.key_probe import KEY_TO_PROVIDER, live_probe

    provider = KEY_TO_PROVIDER.get(key_name)
    if not provider:
        return TestConnectionResponse(
            key_name=key_name,
            configured=bool(settings_store.get_key(key_name)),
            valid=False,
            detail="No probe mapped for this key field",
        )
    key = settings_store.get_key(key_name)
    if not key:
        return TestConnectionResponse(key_name=key_name, configured=False, detail="No key configured")
    result = await live_probe(provider, key)
    return TestConnectionResponse(
        key_name=key_name,
        configured=True,
        valid=bool(result.get("valid")),
        detail=str(result.get("detail", "")),
    )


# --------------------------------------------------------------------------- #
# Token verification — for frontend to check if session is still valid
# --------------------------------------------------------------------------- #
class TokenStatus(BaseModel):
    valid: bool
    username: Optional[str] = None


@router.get("/verify", response_model=TokenStatus)
async def verify_token(admin: str = Depends(require_admin_token)):
    """Verify that the current admin JWT is still valid."""
    return TokenStatus(valid=True, username=admin)
