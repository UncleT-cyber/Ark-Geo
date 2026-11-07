"""ARK unified engine endpoint (REAL execution back-end).

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

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.engine import run_control
from app.engine import slash
from app.engine.provider_errors import public_error
from app.engine.orchestrator import SessionState, get_session, approve, run as orchestrate
from app.engine.router import IntentMode, SpecialistRole, classify_intent
from app.services.ai_gateway import ai_gateway, get_active_litellm_model, get_active_model_string, CLOUD_PROVIDERS
from app.services.admin_store import admin_store
from app.services.entitlements import ANONYMOUS
from app.services.principal import principal_from_request
from app.models.model_registry import lookup as _lookup
from app.services.bus import bus
from app.services.session_store import session_store

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
    # Backend-owned execution mode for this run: "auto" | "manual".
    execution_mode: Optional[str] = None


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
    # Backend-owned execution mode for this run: "auto" | "manual".
    execution_mode: Optional[str] = None


class ApproveRequest(BaseModel):
    session_id: str
    decision: bool
    allow_always: bool = False
    execution_id: Optional[str] = None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _resolve_session(session_id: Optional[str], model: Optional[str], case_id: Optional[str], role: Optional[str], workspace: Optional[str] = None, principal=None):
    sid = session_id or str(uuid.uuid4())
    s = get_session(sid, model=model or None, case_id=case_id or None, workspace=workspace or None, principal=principal)
    if model:
        s.model = model
    if case_id:
        s.case_id = case_id
    if role:
        s.role = role
    if workspace:
        s.workspace = workspace
    if principal is not None:
        s.principal = principal
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
async def active_model(request: Request):
    """The model that will actually run for THIS caller.

    Resolved through the model-selection authority: an explicit/saved user
    selection wins over the administrator default, and the response discloses
    the requested vs. resolved model plus the routing reason.
    """
    from app.services.model_router import resolve

    principal = principal_from_request(request)
    resolution = resolve(principal)
    meta = resolution.metadata()
    model_string = resolution.resolved_model or resolution.requested_model or "unknown"
    provider = resolution.provider or (model_string.split("/", 1)[0] if "/" in model_string else model_string)
    return {
        "model": model_string,
        "provider": provider,
        "model_name": resolution.model_name or model_string,
        "ok": resolution.ok,
        "requested_model": meta["requested_model"],
        "resolved_model": meta["resolved_model"],
        "credential_source": meta["credential_source"],
        "routing_reason": meta["routing_reason"],
        "error": resolution.error,
        "principal": principal.subject,
    }


@router.get("/models")
async def list_models(request: Request):
    """Normalized model catalogue for the picker (Phase 4).

    Every entry is a normalized record: stable id, provider, display name, logo,
    availability (+reason), pricing, context/token limits and the modality/tool
    capabilities we can actually justify.  A capability we have not verified is
    reported as ``"unknown"`` — never invented.  ``availability`` reflects both
    provider configuration and the caller's entitlement, so a model the user may
    not run is marked unavailable with a reason.
    """
    from app.models.model_registry import PROVIDER_MODELS, PROVIDER_IDENTITY
    from app.services.model_router import _availability
    from app.services.user_preferences import user_preferences

    principal = principal_from_request(request)

    # Administrator policy gates which providers appear at all.
    gw = admin_store.get_gateway()
    allowed_providers = (gw.get("entitlements", {}) or {}).get("default", {}).get(
        "allowed_providers", ["*"]) if isinstance(gw.get("entitlements"), dict) else ["*"]
    import fnmatch

    def _provider_permitted(pid: str) -> bool:
        return any(fnmatch.fnmatch(pid, pat) for pat in (allowed_providers or ["*"]))

    prefs = user_preferences.get(principal.namespace())
    selected = prefs.get("selected_model")

    providers: dict[str, list] = {}
    order = ["openrouter", "openai", "anthropic", "gemini", "huggingface", "ollama"]

    # Ollama local runtime (live discovery — no invented models).
    try:
        ollama_tags = ai_gateway._ollama_models_sync()
    except Exception:
        ollama_tags = []
    local_records = []
    for name in ollama_tags:
        rec = _lookup("ollama", name)
        avail, reason, _src = _availability(principal, "ollama", name)
        rec.availability = "available" if avail else "unavailable"
        rec.availability_reason = reason
        local_records.append(rec)
    if local_records:
        providers["Ollama (Local)"] = local_records

    for provider in order:
        if provider == "ollama" or provider not in PROVIDER_MODELS:
            continue
        if not _provider_permitted(provider):
            continue
        configured = bool(ai_gateway._cloud_key(provider))
        records = []
        for model in PROVIDER_MODELS[provider]:
            rec = _lookup(provider, model)
            avail, reason, _src = _availability(principal, provider, model)
            if not configured:
                avail, reason = False, f"{PROVIDER_IDENTITY.get(provider, {}).get('name', provider)} is not configured."
            rec.availability = "available" if avail else "unavailable"
            rec.availability_reason = reason
            records.append(rec)
        display = PROVIDER_IDENTITY.get(provider, {}).get("name", provider.capitalize())
        providers[display] = records

    # ARK-managed (subscription) models — declared, denied until granted.
    from app.models.model_registry import subscription_records
    from app.services.entitlements import resolve_entitlement
    eff, _src = resolve_entitlement(principal)
    granted = set(eff.get("subscription_models") or [])
    ark_records = []
    for rec in subscription_records():
        ok = rec.id in granted or rec.model in granted
        rec.availability = "available" if ok else "unavailable"
        rec.availability_reason = "" if ok else "Requires an ARK subscription plan."
        ark_records.append(rec)
    if ark_records:
        providers["ARK Managed"] = ark_records

    def _ser(rec):
        d = rec.to_dict()
        d["is_active"] = (d["id"] == selected)
        # Convenience aliases for the picker (normalized fields remain present).
        d["available"] = d["availability"] == "available"
        d["name"] = d["display_name"]
        d["configured"] = d["availability"] == "available"
        return d

    return {
        "providers": {name: [_ser(r) for r in recs] for name, recs in providers.items()},
        "active_model": get_active_litellm_model().get("model", "unknown"),
        "selected_model": selected,
        "principal": principal.subject,
    }


@router.post("/command")
async def run_command(body: CommandRequest):

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


# --------------------------------------------------------------------------- #
# Queue / Steer / Stop / Model Switch endpoints (Milestone B)
# --------------------------------------------------------------------------- #

# In-memory queue store keyed by session_id. Each queue entry is a dict with:
#   id, session_id, conversation_id, run_id, prompt, status,
#   created_at, delivered_at, error
_QUEUE_STORE: dict[str, list[dict]] = {}


class QueueRequest(BaseModel):
    session_id: str
    prompt: str
    conversation_id: Optional[str] = None
    run_id: Optional[str] = None  # Associate with an existing run


class SteerRequest(BaseModel):
    session_id: str
    run_id: Optional[str] = None
    message: str
    instruction_type: str = "steer"  # steer | replan | pause | resume


class StopRequest(BaseModel):
    session_id: str
    run_id: Optional[str] = None
    stop_type: str = "stop"  # stop | cancel_pending | cancel_tool | stop_all


class ModeRequest(BaseModel):
    session_id: str
    run_id: Optional[str] = None
    mode: str  # auto | manual


class ModelSwitchRequest(BaseModel):
    session_id: str
    model: str


@router.post("/queue")
async def queue_message(body: QueueRequest):
    """Queue a message for execution after the current run completes.

    The message is stored durably (in-memory) and associated with the
    session. When the active run finishes, the next queued message is
    delivered automatically. Returns a queue entry ID that can be used
    to cancel or inspect the queued message.
    """
    qid = f"q-{uuid.uuid4().hex[:8]}"
    entry = {
        "id": qid,
        "session_id": body.session_id,
        "conversation_id": body.conversation_id or body.session_id,
        "run_id": body.run_id,
        "prompt": body.prompt,
        "status": "pending",
        "created_at": _utc_now_iso(),
        "delivered_at": None,
        "error": None,
    }
    _QUEUE_STORE.setdefault(body.session_id, []).append(entry)
    return {"ok": True, "queue_id": qid, "status": "pending", "queue_position": len(_QUEUE_STORE[body.session_id])}


@router.get("/queue/{session_id}")
async def get_queue(session_id: str):
    """Return the current queue state for a session."""
    queue = _QUEUE_STORE.get(session_id, [])
    pending = [e for e in queue if e["status"] == "pending"]
    delivered = [e for e in queue if e["status"] == "delivered"]
    cancelled = [e for e in queue if e["status"] == "cancelled"]
    return {
        "session_id": session_id,
        "queue": queue,
        "pending_count": len(pending),
        "delivered_count": len(delivered),
        "cancelled_count": len(cancelled),
    }


@router.get("/run")
async def run_status(session_id: str, run_id: Optional[str] = None):
    """Return the live control state of a run (stop / steer / mode).

    ``status`` is one of ``running`` | ``stopping`` | ``cancelled`` |
    ``completed`` | ``failed``. A stop is *requested* here and honoured by the
    orchestrator at its next safe checkpoint, so the UI can distinguish
    "requested" from "stopped" instead of claiming execution has halted.
    """
    control = run_control.resolve(session_id, run_id)
    if control is None:
        return {"session_id": session_id, "run_id": run_id, "active": False, "status": "idle",
                "mode": None, "stop_requested": False, "steering": []}
    return {
        "session_id": control.session_id,
        "run_id": control.run_id,
        "active": control.status in ("running", "stopping"),
        "status": control.status,
        "mode": control.mode,
        "stop_requested": control.stop_requested,
        "stop_type": control.stop_type,
        "stop_reason": control.stop_reason,
        "steering": control.steering_snapshot(),
    }


@router.post("/steer")
async def steer_run(body: SteerRequest):
    """Submit a steering instruction for an active run.

    The instruction is queued and delivered to the orchestrator at its next
    safe checkpoint, which acknowledges it as ``accepted``, ``deferred`` or
    ``rejected`` (streamed as a ``steer_ack`` event). Steering never silently
    widens authority — an instruction that would change the requested
    permissions is deferred for explicit operator confirmation, and any new
    target it names is still revalidated against the engagement scope.
    """
    control = run_control.resolve(body.session_id, body.run_id)
    if control is None:
        return {"ok": False, "error": "no active run for this session", "status": "rejected"}
    msg = control.submit_steer(body.message, body.instruction_type)
    return {
        "ok": True,
        "steering_id": msg.id,
        "status": "submitted",
        "run_id": control.run_id,
        "note": "Delivered to the orchestrator at its next safe checkpoint.",
    }


@router.post("/mode")
async def set_execution_mode(body: ModeRequest):
    """Set the backend-owned execution mode for a session (and its active run).

    ``auto`` lets the agent sequence permitted tools inside the active scope;
    ``manual`` requires operator confirmation at every target-directed
    security-sensitive dispatch. Mode is enforced by the orchestrator, never
    inferred from the prompt, and can be changed mid-run — it takes effect at
    the next dispatch.
    """
    mode = (body.mode or "").lower()
    if mode not in run_control.MODES:
        return {"ok": False, "error": f"mode must be one of {sorted(run_control.MODES)}"}
    session, sid = _resolve_session(body.session_id, None, None, None)
    session.execution_mode = mode
    control = run_control.resolve(sid, body.run_id)
    applied_live = False
    if control is not None:
        control.mode = mode
        applied_live = control.status in ("running", "stopping")
    return {
        "ok": True,
        "mode": mode,
        "session_id": sid,
        "run_id": control.run_id if control else None,
        "applied_live": applied_live,
        "note": "Applies to the next dispatch." if applied_live else "Applies to the next run.",
    }


@router.post("/stop")
async def stop_run(body: StopRequest):
    """Request a stop of an active run, or cancel pending queued messages.

    stop_type:
      - stop: stop the overall run at its next safe checkpoint
      - cancel_pending: cancel pending queued messages for this session
      - cancel_tool: cancel the current tool operation
      - stop_all: stop everything (run + queue)

    A running tool cannot be safely interrupted mid-syscall, so the stop is
    *requested* and honoured by the orchestrator at the next safe checkpoint.
    The response reports ``stop_requested`` — never a fabricated ``stopped``.
    """
    session_id = body.session_id
    run_id = body.run_id
    stop_type = body.stop_type
    results = []

    if stop_type in ("cancel_pending", "stop_all"):
        queue = _QUEUE_STORE.get(session_id, [])
        cancelled = 0
        for entry in queue:
            if entry["status"] == "pending":
                entry["status"] = "cancelled"
                entry["error"] = "cancelled by operator"
                cancelled += 1
        results.append({"action": "cancel_pending", "cancelled": cancelled})

    control = None
    if stop_type in ("stop", "stop_all", "cancel_tool"):
        control = run_control.request_stop(session_id, run_id, stop_type=stop_type,
                                           reason="operator requested stop")
        if control is not None:
            results.append({
                "action": stop_type,
                "run_id": control.run_id,
                "status": "stopping",
                "stop_requested": True,
            })

    return {
        "ok": True,
        "session_id": session_id,
        "run_id": control.run_id if control else run_id,
        "stop_requested": bool(control and control.stop_requested),
        "results": results,
        "note": "Stop honoured at the next safe checkpoint; completed tool output is preserved.",
    }


@router.post("/model/switch")
async def switch_model(body: ModelSwitchRequest, request: Request):
    """Select the model for this session AND persist it as the user's preference.

    Phase 2 rules: an explicit selection takes precedence over the admin default,
    persists in user settings, and is shared by Chat and Console (both resolve
    through the same session + preference).  For running sessions the pin is
    recorded and applied at the next safe run boundary.
    """
    from app.services.model_router import resolve
    from app.services.user_preferences import user_preferences

    principal = principal_from_request(request)
    session, sid = _resolve_session(body.session_id, body.model, None, None, principal=principal)

    # Validate up front — a denied/unavailable model returns a clear error and
    # is NOT silently substituted.
    resolution = resolve(principal, body.model)
    if not resolution.ok:
        return {
            "ok": False,
            "action": "model",
            "requested_model": body.model,
            "error": resolution.error,
            "code": resolution.error_code,
            "session_id": sid,
        }

    session.model = body.model
    user_preferences.set_selected_model(principal.namespace(), body.model)
    return {
        "ok": True,
        "action": "model",
        "model": session.model,
        "resolved_model": resolution.resolved_model,
        "credential_source": resolution.credential_source,
        "routing_reason": resolution.routing_reason,
        "persisted": True,
        "session_id": sid,
        "note": "Model pinned for next run and saved as your preference",
    }


def _utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


@router.post("/stream")
async def stream(body: StreamRequest, request: Request):
    return _stream_response(body, advisory_only=False, principal=principal_from_request(request))


@router.post("/review/stream")
async def review_stream(body: StreamRequest, request: Request):
    return _stream_response(body, advisory_only=True, principal=principal_from_request(request))


def _apply_mode(session, execution_mode: Optional[str]) -> None:
    """Set the backend-owned execution mode on the session (validated)."""
    mode = (execution_mode or "").lower()
    if mode in run_control.MODES:
        session.execution_mode = mode


def _stream_response(body: StreamRequest, *, advisory_only: bool, principal=None):
    if advisory_only:
        sid = str(uuid.uuid4())
        session = SessionState(session_id=sid, model=body.model, principal=principal or ANONYMOUS)
    else:
        session, sid = _resolve_session(body.session_id, body.model, body.case_id, body.role, body.workspace, principal=principal)
    _apply_mode(session, body.execution_mode)
    if body.case_context:
        session.case_context = body.case_context

    async def event_gen():
        yield _sse({"event": "session", "session_id": sid})
        try:
            # Process the initial prompt and any queued follow-ups
            current_prompt = body.prompt
            current_session = session
            while True:
                async for ev in orchestrate(current_session, current_prompt, workspace=body.workspace, advisory_only=advisory_only):
                    yield _sse({"event": ev.get("type", "event"), **ev})
                # After run completes, check for queued messages
                queue = _QUEUE_STORE.get(current_session.session_id, [])
                next_msg = None
                for entry in queue:
                    if entry["status"] == "pending":
                        entry["status"] = "delivered"
                        entry["delivered_at"] = _utc_now_iso()
                        next_msg = entry
                        break
                if next_msg is None:
                    break  # No more queued messages
                # Yield a queue-delivered event so the frontend knows
                yield _sse({
                    "event": "queue_delivered",
                    "queue_id": next_msg["id"],
                    "run_id": sid,
                    "session_id": sid,
                })
                current_prompt = next_msg["prompt"]
                # Re-resolve session with the same session_id to preserve state
                current_session, _ = _resolve_session(
                    current_session.session_id, current_session.model,
                    current_session.case_id, current_session.role,
                    current_session.workspace, principal=principal)
                _apply_mode(current_session, body.execution_mode)
        except Exception as exc:
            logger.exception("CAI stream error")
            yield _sse(public_error(exc))
        yield _sse({"event": "done"})

    return StreamingResponse(event_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


# --------------------------------------------------------------------------- #
# CAI-TUI terminal endpoints
# --------------------------------------------------------------------------- #
@router.post("/terminal/stream")
async def terminal_stream(body: TerminalRequest, request: Request):
    session, sid = _resolve_session(body.session_id, body.model, body.case_id, None, body.workspace, principal=principal_from_request(request))
    _apply_mode(session, body.execution_mode)
    if body.case_context:
        session.case_context = body.case_context

    async def event_gen():
        yield _sse({"event": "session", "session_id": sid})
        try:
            async for ev in orchestrate(session, body.prompt, workspace=body.workspace):
                yield _sse({"event": ev.get("type", "event"), **ev})
        except Exception as exc:
            logger.exception("terminal stream error")
            yield _sse(public_error(exc))
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
async def workspace_run(workspace: str, body: TerminalRequest, request: Request):
    if workspace.lower() not in _WORKSPACES:
        return {"ok": False, "error": f"Unknown workspace: {workspace}"}
    session, sid = _resolve_session(body.session_id, body.model, body.case_id, None, workspace, principal=principal_from_request(request))
    _apply_mode(session, body.execution_mode)
    if body.case_context:
        session.case_context = body.case_context

    async def event_gen():
        yield _sse({"event": "session", "session_id": sid, "workspace": workspace})
        try:
            async for ev in orchestrate(session, body.prompt, workspace=workspace):
                yield _sse({"event": ev.get("type", "event"), **ev})
        except Exception as exc:
            logger.exception("workspace stream error")
            yield _sse(public_error(exc))
        yield _sse({"event": "done"})

    return StreamingResponse(event_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


# --------------------------------------------------------------------------- #
# Durable investigation sessions (restoration surface)
#
# These expose the persisted session metadata, transcript, run history and
# evidence *references* so a reopened tab can rehydrate. The backend remains
# the authoritative source; the transcript here is the durable mirror of the
# CAI conversation (metadata only for zero-retention sessions).
# --------------------------------------------------------------------------- #
@router.get("/sessions")
async def list_sessions(request: Request, limit: int = 50):
    """List durable investigation sessions for the caller's principal.

    A run left ``running`` by a previous process is reported as ``interrupted``
    — never as live.
    """
    principal = principal_from_request(request)
    if principal is ANONYMOUS:
        # The anonymous principal owns rows recorded without a subject (legacy
        # rows) *and* rows the orchestrator stamped with the literal
        # ``ANONYMOUS.subject`` ("anonymous"). Both are its own; nothing else is.
        subject = ANONYMOUS.subject
        sessions = session_store.list_sessions(
            principal_subject=subject, limit=limit, include_unowned=True
        )
    else:
        sessions = session_store.list_sessions(
            principal_subject=getattr(principal, "subject", None), limit=limit
        )
    return {"sessions": sessions}


def _session_visible_to(meta: dict, principal) -> bool:
    """Owner check for a durable session.

    A caller may only reach its own sessions. The stored owner is the resolved
    principal's subject (``ANONYMOUS.subject`` for anonymous runs); a legacy row
    with no recorded owner is treated as anonymous. One principal's transcript,
    evidence references and run history can therefore never be read or deleted
    by another. A cross-principal request is reported exactly like an unknown
    session, so the endpoint is not an existence oracle.
    """
    owner = meta.get("principal_subject") or ANONYMOUS.subject
    return owner == getattr(principal, "subject", ANONYMOUS.subject)


@router.get("/sessions/{session_id}")
async def get_session_detail(request: Request, session_id: str):
    """Return persisted metadata, transcript, runs and evidence references.

    ``zero_retention`` sessions return an empty transcript by design — the
    protected content was never written and cannot be reconstructed.
    """
    principal = principal_from_request(request)
    meta = session_store.get_session_meta(session_id)
    if meta is None or not _session_visible_to(meta, principal):
        return {"ok": False, "error": "unknown session", "session_id": session_id}
    messages = session_store.load_messages(session_id) if not meta["zero_retention"] else []
    return {
        "ok": True,
        "session": meta,
        "messages": messages,
        "runs": session_store.list_runs(session_id),
        "evidence_refs": [
            ref for run in session_store.list_runs(session_id) for ref in run.get("evidence_refs", [])
        ],
        "transcript_available": not meta["zero_retention"],
    }


@router.delete("/sessions/{session_id}")
async def delete_session(request: Request, session_id: str):
    principal = principal_from_request(request)
    meta = session_store.get_session_meta(session_id)
    if meta is None or not _session_visible_to(meta, principal):
        return {"ok": False, "error": "unknown session", "session_id": session_id}
    session_store.delete_session(session_id)
    return {"ok": True, "session_id": session_id}


__all__ = ["router"]
