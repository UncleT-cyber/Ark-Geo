"""ARK-CAI unified engine endpoint (REAL execution back-end).

Exposes THE ARK's CAI orchestrator over HTTP:
* ``POST /cai/stream``     — SSE stream of advisory / autonomous execution.
* ``POST /cai/classify``   — intent classification preview.
* ``GET  /cai/commands``   — unified slash command catalogue.
* ``GET  /cai/tools``      — registered ARK tool catalogue (REAL tools).
* ``POST /cai/command``    — dispatch a slash command.
* ``POST /terminal/stream``— CAI-TUI terminal session stream (PATH A/B + HITL).
* ``POST /terminal/approve``— operator approve/deny of a HITL-gated tool.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.engine import slash
from app.engine.orchestrator import get_session, approve, run as orchestrate
from app.engine.router import IntentMode, SpecialistRole, classify_intent
from app.services.ai_gateway import get_active_litellm_model, get_active_model_string
from app.services.bus import bus

router = APIRouter(prefix="/cai")
logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Request / response models
# --------------------------------------------------------------------------- #
class StreamRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=8000)
    session_id: Optional[str] = None
    role: Optional[str] = None
    model: Optional[str] = None
    case_id: Optional[str] = None
    workspace: Optional[str] = None
    case_context: Optional[dict] = None


class ClassifyRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=8000)


class CommandRequest(BaseModel):
    command: str = Field(..., min_length=1, max_length=8000)
    session_id: Optional[str] = None


class TerminalRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=8000)
    session_id: Optional[str] = None
    model: Optional[str] = None
    case_id: Optional[str] = None
    workspace: Optional[str] = None
    case_context: Optional[dict] = None


class ApproveRequest(BaseModel):
    session_id: str
    decision: bool
    allow_always: bool = False
    execution_id: Optional[str] = None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _resolve_session(session_id: Optional[str], model: Optional[str], case_id: Optional[str], role: Optional[str], workspace: Optional[str] = None):
    sid = session_id or str(uuid.uuid4())
    s = get_session(sid, model=model or None, case_id=case_id or None, workspace=workspace or None)
    if model:
        s.model = model
    if case_id:
        s.case_id = case_id
    if role:
        s.role = role
    if workspace:
        s.workspace = workspace
    return s, sid


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@router.post("/classify")
async def classify(body: ClassifyRequest):
    decision = classify_intent(body.prompt)
    return decision.to_dict()


@router.get("/commands")
async def commands(prefix: Optional[str] = None):
    if prefix:
        return slash.complete(prefix)
    return slash.all_commands()


@router.get("/tools")
async def tools(domain: Optional[str] = None):
    from app.engine.tool_adapter import get_tool_specs

    data = get_tool_specs()
    if domain:
        data = [t for t in data if t["domain"] == domain]
    return {"count": len(data), "tools": data}


@router.get("/model")
async def active_model():
    """Live active model (single source of truth from central config).

    Surfaces the provider/model string the CAI engine and every workspace are
    currently bound to, so clients (terminal banner, settings panel) can show
    exactly what the Admin Console selected — no hardcoded defaults.
    """
    info = get_active_litellm_model()
    model_string = info.get("model", "unknown")
    provider = model_string.split("/", 1)[0] if "/" in model_string else model_string
    return {
        "model": model_string,
        "provider": provider,
        "model_name": model_string.split("/", 1)[1] if "/" in model_string else model_string,
    }


@router.post("/command")
async def run_command(body: CommandRequest):
    name, args = slash.parse(body.command)
    if name is None:
        return {"ok": False, "error": "Not a slash command", "command": body.command}
    spec = slash.get_command(name)
    if spec is None:
        return {"ok": False, "error": f"Unknown command: /{name}"}

    session, sid = _resolve_session(body.session_id, None, None, None)

    if name == "clear":
        session.messages.clear()
        return {"ok": True, "action": "clear", "session_id": sid}
    if name == "sessions":
        return {"ok": True, "action": "sessions", "session_id": sid, "history": session.messages[-20:]}
    if name == "agent":
        session.role = (args.strip() or "generalist")
        return {"ok": True, "action": "agent", "role": session.role, "session_id": sid}
    if name == "model":
        session.model = args.strip() or None
        return {"ok": True, "action": "model", "model": session.model, "session_id": sid}
    if name == "case":
        session.case_id = args.strip() or None
        return {"ok": True, "action": "case", "case_id": session.case_id, "session_id": sid}
    if name == "env":
        return {"ok": True, "action": "env", "model": session.model, "role": session.role, "cai_available": True}
    if name == "tools":
        from app.engine.tool_adapter import get_tool_specs

        data = get_tool_specs()
        if args.strip():
            data = [t for t in data if t["domain"] == args.strip()]
        return {"ok": True, "action": "tools", "tools": data}
    if name == "evidence":
        from app.engine.tool_adapter import call_tool

        res = call_tool("case.evidence", evidence_id=args.strip())
        return {"ok": True, "action": "evidence", "result": res}
    if name == "help":
        return {"ok": True, "action": "help", "commands": slash.all_commands()}
    return {"ok": True, "action": name, "note": "Command accepted."}


@router.post("/stream")
async def stream(body: StreamRequest):
    session, sid = _resolve_session(body.session_id, body.model, body.case_id, body.role, body.workspace)
    if body.case_context:
        session.case_context = body.case_context

    async def event_gen():
        yield _sse({"event": "session", "session_id": sid})
        try:
            async for ev in orchestrate(session, body.prompt, workspace=body.workspace):
                yield _sse({"event": ev.get("type", "event"), **ev})
        except Exception as exc:
            logger.exception("CAI stream error")
            yield _sse({"event": "error", "message": str(exc)})
        yield _sse({"event": "done"})

    return StreamingResponse(event_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


# --------------------------------------------------------------------------- #
# CAI-TUI terminal endpoints
# --------------------------------------------------------------------------- #
@router.post("/terminal/stream")
async def terminal_stream(body: TerminalRequest):
    session, sid = _resolve_session(body.session_id, body.model, body.case_id, None, body.workspace)
    if body.case_context:
        session.case_context = body.case_context

    async def event_gen():
        yield _sse({"event": "session", "session_id": sid})
        try:
            async for ev in orchestrate(session, body.prompt, workspace=body.workspace):
                yield _sse({"event": ev.get("type", "event"), **ev})
        except Exception as exc:
            logger.exception("terminal stream error")
            yield _sse({"event": "error", "message": str(exc)})
        yield _sse({"event": "done"})

    return StreamingResponse(event_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


@router.post("/terminal/approve")
async def terminal_approve(body: ApproveRequest):
    ok = approve(body.session_id, body.decision, allow_always=body.allow_always, execution_id=body.execution_id)
    return {"ok": ok, "session_id": body.session_id, "decision": body.decision, "allow_always": body.allow_always, "execution_id": body.execution_id}


# --------------------------------------------------------------------------- #
# Central registry + global Event Bus
# --------------------------------------------------------------------------- #
@router.get("/registry")
async def registry():
    """Return THE ARK unified tool & agent registry (all workspaces)."""
    from app.engine.cai.registry import get_unified_registry

    return get_unified_registry()


@router.get("/events")
async def events(topic: str = "ark"):
    """Server-Sent Events stream of the global backend Event Bus.

    Frontend tabs (Map UI, Network Graph, Evidence Table) subscribe here to
    receive live tool start / output / agent-status events and update their
    visual state automatically.
    """

    async def event_gen():
        try:
            async for chunk in bus.stream(topic):
                yield chunk
        except asyncio.CancelledError:
            return

    return StreamingResponse(event_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


# --------------------------------------------------------------------------- #
# Workspace → CAI agent triggers
#   IMINT drag-and-drop  → cai.agents.IMINTAgent
#   Network scan buttons → cai.agents.ReconAgent
#   SIEM log analysis    → cai.agents.BlueTeamAgent
# --------------------------------------------------------------------------- #
_WORKSPACES = {"imint", "recon", "network", "siem", "blueteam", "case"}


@router.post("/workspace/{workspace}/run")
async def workspace_run(workspace: str, body: TerminalRequest):
    if workspace.lower() not in _WORKSPACES:
        return {"ok": False, "error": f"Unknown workspace: {workspace}"}
    session, sid = _resolve_session(body.session_id, body.model, body.case_id, None, workspace)
    if body.case_context:
        session.case_context = body.case_context

    async def event_gen():
        yield _sse({"event": "session", "session_id": sid, "workspace": workspace})
        try:
            async for ev in orchestrate(session, body.prompt, workspace=workspace):
                yield _sse({"event": ev.get("type", "event"), **ev})
        except Exception as exc:
            logger.exception("workspace stream error")
            yield _sse({"event": "error", "message": str(exc)})
        yield _sse({"event": "done"})

    return StreamingResponse(event_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


__all__ = ["router"]
