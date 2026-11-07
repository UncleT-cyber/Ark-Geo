"""Operator-declared engagement endpoints — the execution authorization surface.

An authenticated operator declares what ARK may execute against:

* ``POST /engagement``            — declare an engagement (targets, ports, window)
* ``GET  /engagement``            — the active engagement + declaration history
* ``POST /engagement/{id}/revoke``— revoke immediately

The declaration is the source of truth for the target-authorization layer
(:mod:`app.agent.engagement_scope`). Declaring an engagement installs it as
the active scope, so target-bearing tool calls inside it execute without
further approval; calls outside it are refused before dispatch.

Requires the admin bearer token (the operator control plane). Every mutation
writes an append-only audit entry.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.agent import engagement_scope
from app.agent.engagement_store import ALL_PORTS, DEFAULT_WINDOW_HOURS, EngagementStore
from app.api.v1.endpoints.settings import require_admin_token
from app.services.admin_store import admin_store

router = APIRouter(prefix="/engagement")
logger = logging.getLogger(__name__)

_store: Optional[EngagementStore] = None


def _get_store() -> EngagementStore:
    global _store
    if _store is None:
        _store = EngagementStore()
    return _store


class EngagementCreate(BaseModel):
    targets: List[str] = Field(..., min_length=1,
                               description="Addresses/CIDRs ARK may execute against.")
    ports: Optional[List[int]] = Field(
        default=None, description="Declared ports. Omit when all_ports=True.")
    all_ports: bool = Field(
        default=False, description="Authorize every port on the declared targets.")
    start: Optional[str] = Field(default=None, description="ISO-8601 start (default: now).")
    expiry: Optional[str] = Field(
        default=None, description=f"ISO-8601 expiry (default: now + {DEFAULT_WINDOW_HOURS}h).")
    label: str = ""
    notes: str = ""


def _activate(scope: Optional[dict]) -> None:
    """Install an engagement as the active scope (or clear it)."""
    engagement_scope.set_operator_engagement(scope)


def _view(scope: dict) -> dict:
    return {
        "engagement_id": scope.get("engagement_id"),
        "label": scope.get("label") or "",
        "targets": scope.get("approved_addresses", []),
        "ports": scope.get("approved_ports", []),
        "all_ports": bool(scope.get("all_ports")),
        "start": scope.get("start"),
        "expiry": scope.get("expiry"),
        "notes": scope.get("notes") or "",
    }


@router.post("")
async def declare_engagement(body: EngagementCreate, request: Request,
                             actor: str = Depends(require_admin_token)) -> dict:
    """Declare an engagement and make it the active execution scope."""
    try:
        scope = _get_store().create(
            owner_id=actor,
            addresses=body.targets,
            ports=body.ports,
            all_ports=body.all_ports,
            start=body.start,
            expiry=body.expiry,
            label=body.label,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if scope is None:
        raise HTTPException(status_code=422, detail="engagement could not be created")
    _activate(scope)
    admin_store.append_audit(
        actor=actor, action="engagement.declare",
        target=scope.get("engagement_id", ""),
        ip=request.client.host if request.client else "",
        detail=f"targets={','.join(map(str, scope.get('approved_addresses', [])))} "
               f"ports={'all' if scope.get('all_ports') else scope.get('approved_ports')} "
               f"expiry={scope.get('expiry')}",
    )
    return {"status": "active", "engagement": _view(scope)}


@router.get("")
async def get_engagement(actor: str = Depends(require_admin_token)) -> dict:
    """Return the active engagement and the operator's declaration history."""
    active = _get_store().get_active(owner_id=actor)
    history = _get_store().list_active(owner_id=actor)
    return {
        "active": _view(active) if active else None,
        "declared": [_view(s) for s in history],
    }


@router.post("/{engagement_id}/revoke")
async def revoke_engagement(engagement_id: str, request: Request,
                            actor: str = Depends(require_admin_token)) -> dict:
    """Revoke an engagement immediately; it stops authorizing at once."""
    ok = _get_store().revoke(owner_id=actor, engagement_id=engagement_id)
    if not ok:
        raise HTTPException(status_code=404, detail="active engagement not found")
    # If the revoked engagement was the active one, clear the in-force scope.
    current = engagement_scope.get_operator_engagement() or {}
    if current.get("engagement_id") == engagement_id:
        _activate(None)
    admin_store.append_audit(
        actor=actor, action="engagement.revoke", target=engagement_id,
        ip=request.client.host if request.client else "",
    )
    return {"status": "revoked", "engagement_id": engagement_id}
