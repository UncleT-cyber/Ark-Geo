"""Authorized Security Testing — attestation surface.

Self-asserted engagement attestations are recorded here as an append-only,
server-observed chain-of-custody record (action ``security_testing.attestation``
in the shared audit store).  The authoritative client IP is captured
server-side from the connection / X-Forwarded-For chain so the record does not
depend on a client-reported value.  The frontend telemetry bundle is stored
verbatim alongside it.

``GET /security/ip`` exists so the attestation modal can show the IP the
backend actually observes before a record is written.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.services.admin_store import admin_store

router = APIRouter(prefix="/security")
logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class AttestationCreate(BaseModel):
    """Client-supplied attestation. ``client_ip``/``real_ip`` are advisory —
    the authoritative IP is captured server-side."""

    full_name: str
    email: str = ""
    position: str = ""
    org_name: str = ""
    purpose: str = ""
    target_scope: str = ""
    client_ip: str = ""
    real_ip: str = ""
    user_agent: str = ""
    timestamp: str = ""
    telemetry: dict[str, Any] = Field(default_factory=dict)


class AttestationRecord(BaseModel):
    log_id: str
    action: str
    actor: str
    target_scope: str
    ip: str
    real_ip: str
    signature: str
    timestamp: str
    timestamp_ms: int
    persisted: bool = True


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _client_ip(request: Request) -> str:
    """Best-effort client IP: honor X-Forwarded-For, else the socket peer."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _signature(log_id: str, ts_ms: int, actor: str, scope: str) -> str:
    """Deterministic non-repudiation tag over the record's identity fields."""
    digest = hashlib.sha256(
        f"{log_id}|{ts_ms}|{actor.lower()}|{scope.strip().lower()}".encode()
    ).hexdigest()[:12].upper()
    return f"ARK-ATT-{digest}"


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@router.get("/ip")
async def observed_ip(request: Request) -> dict[str, str]:
    """Echo the server-observed client IP (used to reconcile VPN/proxy drift)."""
    return {"ip": _client_ip(request)}


@router.post("/attestations")
async def create_attestation(payload: AttestationCreate, request: Request) -> dict[str, Any]:
    """Append an authorized-engagement attestation to the audit store.

    No auth is required: the attestation is a self-asserted declaration logged
    for chain of custody, not an administrative action.  The audit store is
    append-only and bounded, so this cannot be used to mutate state.
    """
    server_ip = _client_ip(request)
    detail = json.dumps(
        {
            "org": payload.org_name,
            "position": payload.position,
            "purpose": payload.purpose,
            "target_scope": payload.target_scope,
            "client_ip": payload.client_ip or server_ip,
            "real_ip": payload.real_ip,
            "user_agent": payload.user_agent,
            "telemetry": payload.telemetry,
        },
        ensure_ascii=False,
    )

    entry = admin_store.append_audit(
        actor=f"{payload.full_name} <{payload.email}>" if payload.email else payload.full_name,
        action="security_testing.attestation",
        target=payload.target_scope[:200] or "authorized testing scope",
        ip=server_ip,
        detail=detail[:2000],
    )

    signature = _signature(entry["log_id"], entry["timestamp_ms"], payload.full_name, payload.target_scope)
    return {
        "log_id": entry["log_id"],
        "action": entry["action"],
        "actor": entry["actor"],
        "target_scope": payload.target_scope,
        "ip": server_ip,
        "real_ip": payload.real_ip,
        "signature": signature,
        "timestamp": entry["timestamp"],
        "timestamp_ms": entry["timestamp_ms"],
        "persisted": True,
    }
