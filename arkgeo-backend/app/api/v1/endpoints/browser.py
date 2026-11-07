"""Operator browser transport — the human side of the managed browser runtime.

CAI drives browsing through the ``browser.*`` tools (agent plane). The operator
observes and can take over through these endpoints (operator plane). Transport is
**screenshot-first**: frames are delivered as PNG bytes and the live DOM is never
proxied into an arbitrary cross-origin iframe — which keeps the operator view
outside the untrusted page's origin.

Endpoints:
* ``GET  /browser/status``                     — runtime availability + sessions
* ``GET  /browser/sessions``                   — list live sessions
* ``GET  /browser/sessions/{sid}``             — one session's state
* ``GET  /browser/sessions/{sid}/frame``       — latest screenshot (PNG bytes)
* ``GET  /browser/sessions/{sid}/capture``     — take a fresh screenshot (PNG)
* ``POST /browser/sessions/{sid}/control``     — take / return operator control
* ``POST /browser/sessions/{sid}/navigate``    — operator navigation
* ``POST /browser/sessions/{sid}/history``     — operator back / forward / reload
* ``POST /browser/sessions/{sid}/close``       — close the session
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.tools.web_intel import browser as rt
from app.tools.web_intel import tools as W

router = APIRouter(prefix="/browser")


class ControlRequest(BaseModel):
    action: str = "take"     # take | return


class NavigateRequest(BaseModel):
    url: str


class HistoryRequest(BaseModel):
    action: str = "reload"   # back | forward | reload


class OpenRequest(BaseModel):
    url: str = ""
    investigation_id: str = ""
    case_id: str = ""


def _session_or_404(sid: str) -> rt.BrowserSession:
    try:
        return rt.browser_manager.get(sid)
    except rt.SessionNotFound:
        raise HTTPException(status_code=404, detail=f"no such browser session: {sid}")


def _latest_screenshot(session: rt.BrowserSession) -> Optional[rt.Artifact]:
    shots = [a for a in session.artifacts if a.kind == "screenshot"]
    return shots[-1] if shots else None


@router.get("/status")
async def browser_status() -> dict:
    """Runtime availability plus the live session list."""
    return W.browser_status()


@router.get("/sessions")
async def list_sessions() -> dict:
    return {"sessions": rt.browser_manager.list_sessions()}


@router.post("/sessions")
async def open_session(body: OpenRequest) -> dict:
    """Open a managed session from the operator plane (optional start URL)."""
    result = await W.browser_operator_open(body.url, body.investigation_id, body.case_id)
    if result.get("state") != "AVAILABLE":
        raise HTTPException(status_code=409, detail=result.get("detail", "open failed"))
    return result


@router.get("/sessions/{sid}")
async def get_session(sid: str) -> dict:
    session = _session_or_404(sid)
    out = session.to_dict()
    shot = _latest_screenshot(session)
    out["latest_screenshot"] = shot.to_dict() if shot else None
    return out


@router.get("/sessions/{sid}/frame")
async def get_frame(sid: str):
    """Return the most recent screenshot as PNG bytes (404 if none yet)."""
    session = _session_or_404(sid)
    shot = _latest_screenshot(session)
    if shot is None or not os.path.exists(shot.path):
        raise HTTPException(status_code=404, detail="no screenshot captured yet")
    return FileResponse(shot.path, media_type="image/png")


@router.get("/sessions/{sid}/capture")
async def capture_frame(sid: str):
    """Capture a fresh screenshot and return it as PNG bytes."""
    result = await W.browser_operator_capture(sid, label="operator-capture")
    if result.get("state") != "AVAILABLE":
        raise HTTPException(status_code=409, detail=result.get("detail", "capture failed"))
    path = (result.get("artifact") or {}).get("path")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=500, detail="screenshot artifact missing")
    return FileResponse(path, media_type="image/png")


@router.post("/sessions/{sid}/control")
async def control(sid: str, body: ControlRequest) -> dict:
    _session_or_404(sid)
    if body.action == "take":
        return rt.browser_manager.take_control(sid)
    if body.action == "return":
        return rt.browser_manager.return_control(sid)
    raise HTTPException(status_code=400, detail="action must be 'take' or 'return'")


@router.post("/sessions/{sid}/navigate")
async def navigate(sid: str, body: NavigateRequest) -> dict:
    """Operator-initiated navigation (works regardless of control state)."""
    _session_or_404(sid)
    result = await W.browser_operator_navigate(sid, body.url)
    if result.get("state") not in {"AVAILABLE"}:
        raise HTTPException(status_code=409, detail=result.get("detail", "navigation failed"))
    return result


@router.post("/sessions/{sid}/history")
async def history(sid: str, body: HistoryRequest) -> dict:
    """Operator history move — back / forward / reload on the active tab."""
    _session_or_404(sid)
    if body.action not in {"back", "forward", "reload"}:
        raise HTTPException(status_code=400, detail="action must be 'back', 'forward' or 'reload'")
    result = await W.browser_operator_history(sid, body.action)
    if result.get("state") not in {"AVAILABLE"}:
        raise HTTPException(status_code=409, detail=result.get("detail", "history action failed"))
    return result


@router.post("/sessions/{sid}/close")
async def close(sid: str) -> dict:
    _session_or_404(sid)
    return await W.browser_close(sid)
