"""Certified-personnel access boundary for the signaling subsystem.

Two independent layers:

1. Personnel JWT — issued on login with a certified role claim
   (``CERTIFIED_OPERATOR``, ``CERTIFIED_OPERATOR_ADMIN``, ``AUDITOR``).
   Only certified roles may reach any ``/signaling/*`` endpoint.

2. Per-operator authorization token — a short-lived token bound to one
   operator (MCC), issued only by a ``CERTIFIED_OPERATOR_ADMIN``.  Every
   live signaling operation must present a valid operator token whose MCC
   matches the target before the driver is invoked.

Personnel records come from ``settings.signaling_personnel_file`` (JSON) or a
development seed when the file is absent.  Passwords are bcrypt-hashed; the
token boundary never stores plaintext credentials.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Optional

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.security import create_access_token, decode_access_token
from app.signaling.schema import (
    CERTIFIED_ROLES,
    CertifiedRole,
    OperatorAuthorization,
    PersonnelRecord,
)

logger = logging.getLogger(__name__)


class PersonnelAuthRequest(BaseModel):
    username: str
    password: str


class PersonnelAuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    full_name: str
    operator_scopes: list[str] = Field(default_factory=list)
    expires_in: int = 0


class OperatorTokenRequest(BaseModel):
    operator: str = Field(..., min_length=1, max_length=64)
    mcc: str = Field(..., min_length=3, max_length=3)
    scope: str = "sri,ulr,ati,plr,imsi,cgi,silent_sms,imsi_catcher"
    valid_hours: int = Field(default=24, ge=1, le=168)


class OperatorTokenResponse(BaseModel):
    token: str
    operator: str
    mcc: str
    scope: str
    valid_until: int
    trace_id: str


class PersonnelIdentity(BaseModel):
    username: str
    full_name: str
    role: str
    operator_scopes: list[str] = Field(default_factory=list)


def _default_personnel() -> list[dict[str, Any]]:
    """Development seed. Override via ARKGEO_SIGNALING_PERSONNEL_FILE."""
    from app.core.security import hash_password

    return [
        {
            "username": "sigops",
            "full_name": "Certified Signaling Operator (dev)",
            "role": "CERTIFIED_OPERATOR",
            "password_hash": hash_password("sigops-cert"),
            "active": True,
            "operator_scopes": ["621"],
        },
        {
            "username": "sigadmin",
            "full_name": "Certified Signaling Admin (dev)",
            "role": "CERTIFIED_OPERATOR_ADMIN",
            "password_hash": hash_password("sigadmin-cert"),
            "active": True,
            "operator_scopes": ["621"],
        },
        {
            "username": "sigaudit",
            "full_name": "Signaling Auditor (dev)",
            "role": "AUDITOR",
            "password_hash": hash_password("sigaudit-cert"),
            "active": True,
            "operator_scopes": [],
        },
    ]


class PersonnelRegistry:
    def __init__(self) -> None:
        self._records: dict[str, PersonnelRecord] = {}
        self._load()

    def _load(self) -> None:
        path = settings.signaling_personnel_file
        raw: list[dict[str, Any]]
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        else:
            raw = _default_personnel()
        for entry in raw:
            rec = PersonnelRecord(**entry)
            if rec.role not in CERTIFIED_ROLES:
                logger.warning("Ignoring non-certified personnel role '%s'", rec.role)
                continue
            self._records[rec.username] = rec

    def get(self, username: str) -> Optional[PersonnelRecord]:
        return self._records.get(username)

    def verify(self, username: str, password: str) -> Optional[PersonnelRecord]:
        rec = self.get(username)
        if not rec or not rec.active:
            return None
        if not rec.password_hash:
            return None
        try:
            ok = bcrypt.checkpw(password.encode("utf-8"), rec.password_hash.encode("utf-8"))
        except ValueError:
            return None
        return rec if ok else None


personnel_registry = PersonnelRegistry()


def issue_personnel_token(username: str, password: str) -> PersonnelAuthResponse | None:
    rec = personnel_registry.verify(username, password)
    if not rec:
        return None
    token = create_access_token(
        subject=rec.username,
        extra_claims={
            "token_type": "personnel",
            "sig_role": rec.role,
            "full_name": rec.full_name,
            "scopes": rec.operator_scopes,
        },
    )
    return PersonnelAuthResponse(
        access_token=token,
        role=rec.role,
        full_name=rec.full_name,
        operator_scopes=list(rec.operator_scopes),
        expires_in=settings.jwt_expiry_minutes * 60,
    )


def _identity_from_payload(payload: dict[str, Any]) -> PersonnelIdentity:
    return PersonnelIdentity(
        username=str(payload.get("sub", "")),
        full_name=str(payload.get("full_name", payload.get("sub", ""))),
        role=str(payload.get("sig_role", "")),
        operator_scopes=[str(s) for s in payload.get("scopes", [])],
    )


async def require_certified(
    authorization: Optional[str] = Header(default=None),
) -> PersonnelIdentity:
    """FastAPI dependency — bearer JWT with a certified signaling role."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.split(" ", 1)[1]
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if payload.get("token_type") != "personnel" or payload.get("sig_role") not in CERTIFIED_ROLES:
        raise HTTPException(status_code=403, detail="Not a certified signaling principal")
    return _identity_from_payload(payload)


async def require_operator_admin(
    identity: PersonnelIdentity = Depends(require_certified),
) -> PersonnelIdentity:
    if identity.role != CertifiedRole.CERTIFIED_OPERATOR_ADMIN.value:
        raise HTTPException(status_code=403, detail="Requires CERTIFIED_OPERATOR_ADMIN role")
    return identity


def issue_operator_token(request: OperatorTokenRequest) -> OperatorTokenResponse:
    """Issue a short-lived operator-authorization token (admin-only callers)."""
    valid_until = int(time.time()) + request.valid_hours * 3600
    trace = f"opa-{os.urandom(6).hex()}"
    token = create_access_token(
        subject=request.operator,
        extra_claims={
            "token_type": "operator_auth",
            "op": request.operator,
            "mcc": request.mcc,
            "scope": request.scope,
            "valid_until": valid_until,
            "trace": trace,
        },
        expires_minutes=request.valid_hours * 60,
    )
    return OperatorTokenResponse(
        token=token,
        operator=request.operator,
        mcc=request.mcc,
        scope=request.scope,
        valid_until=valid_until,
        trace_id=trace,
    )


def validate_operator_token(
    token: str,
    required_mcc: str | None = None,
    required_op: str = "",
) -> OperatorAuthorization:
    """Validate a per-operator token; raise HTTPException on any failure."""
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        raise HTTPException(status_code=403, detail="Invalid operator-authorization token")
    if payload.get("token_type") != "operator_auth":
        raise HTTPException(status_code=403, detail="Not an operator-authorization token")
    valid_until = int(payload.get("valid_until", 0))
    if valid_until < int(time.time()):
        raise HTTPException(status_code=403, detail="Operator authorization expired")
    if required_mcc and payload.get("mcc") != required_mcc:
        raise HTTPException(
            status_code=403,
            detail=f"Operator token authorized for MCC {payload.get('mcc')}, "
            f"not {required_mcc}",
        )
    return OperatorAuthorization(
        operator=str(payload.get("op", "")),
        mcc=str(payload.get("mcc", "")),
        scope=str(payload.get("scope", "")),
        valid_until=valid_until,
        trace_id=str(payload.get("trace", "")),
    )


def operator_token_authorizes(auth: OperatorAuthorization, op: str) -> bool:
    """Does the operator token's scope cover the requested operation?"""
    allowed = {s.strip() for s in auth.scope.split(",") if s.strip()}
    return op in allowed
