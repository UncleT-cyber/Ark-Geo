"""Level-4 RE-ACT chain endpoints — authorized engagements.

``POST /react/run``     — run the five-phase chain (Plan → Scan → Exploit →
                         Escalate → Mitigate) against an explicitly authorized
                         scope. Refuses to run without ``authorized=True`` and
                         a resolvable target.
``GET /react/{id}``     — poll a chain session (phases, activity, findings,
                         mitigation posture, evidence graph).
``GET /react``          — list recent chain sessions.

The chain is the dedicated surface for active capabilities (``exec:shell``);
the standard investigator loop keeps them denied. Authorization is recorded
on the case graph before anything executes.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.agent.react_chain import ReactRequest, react_chain

router = APIRouter()
logger = logging.getLogger(__name__)


class ReactRunRequest(BaseModel):
    operator: str
    authorized: bool = False
    target: dict
    mode: str = "active"           # active | dry_run
    notes: str = ""
    budget: dict = {}


@router.post("/react/run")
async def run_react_chain(body: ReactRunRequest):
    """Run the full RE-ACT chain against an authorized scope."""
    try:
        request = ReactRequest(**body.model_dump())
    except Exception as exc:  # noqa: BLE001 — bad payload → 400
        raise HTTPException(status_code=400, detail=f"Invalid RE-ACT request: {exc}")
    session = await react_chain.run(request)
    logger.info(
        "RE-ACT %s finished (status=%s, operator=%s, target=%s)",
        session.session_id, session.status, request.operator,
        request.target.summary(),
    )
    return session.to_dict()


@router.get("/react/{session_id}")
async def get_react_session(session_id: str):
    session = react_chain.store.get(session_id)
    if not session:
        raise HTTPException(status_code=404,
                            detail=f"Unknown RE-ACT session {session_id}")
    return session.to_dict()


@router.get("/react")
async def list_react_sessions():
    """Recent chain sessions (compact)."""
    return [
        {
            "session_id": s.session_id,
            "case_id": s.case_id,
            "status": s.status,
            "kind": s.request.target.kind.value,
            "target": s.request.target.summary(),
            "operator": s.request.operator,
            "updated_at_ms": s.updated_at_ms,
        }
        for s in sorted(react_chain.store.list(),
                        key=lambda s: s.updated_at_ms, reverse=True)
    ]
