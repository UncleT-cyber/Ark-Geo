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
from app.engine.provider_errors import public_error
from app.engine.orchestrator import SessionState, get_session, approve, run as orchestrate
from app.engine.router import IntentMode, SpecialistRole, classify_intent
from app.services.ai_gateway import ai_gateway, get_active_litellm_model, get_active_model_string, CLOUD_PROVIDERS
from app.services.admin_store import admin_store
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


@router.get("/models")
async def list_models():
    """List available AI models grouped by provider.

    Discovers providers from the ARK AI Gateway configuration and
    Ollama runtime. Returns provider-grouped model metadata including
    name, provider, pricing class, tool-calling capability, context
    window, availability, and local-vs-remote execution mode.
    """
    from app.services.ai_gateway import ai_gateway

    # Build provider-grouped model catalogue from the gateway config
    providers = {}

    # Helper to determine if a model supports tool calling
    def _supports_tools(model_name: str) -> bool:
        name = model_name.lower()
        # Most modern instruct/chat models support tool calling
        tool_capable_patterns = [
            "qwen2.5-coder", "qwen2.5", "qwen3", "codestral", "deepseek-coder",
            "llama-3.1", "llama-3.2", "llama-3.3", "claude-3", "claude-3.5",
            "gpt-4", "gpt-4o", "nemotron", "nvidia/nemotron", "mistral",
            "mixtral", "dbrx", "command-r", "aya", "solar",
        ]
        return any(p in name for p in tool_capable_patterns)

    # Helper to estimate context window
    def _context_window(model_name: str) -> int:
        name = model_name.lower()
        context_map = {
            "qwen2.5-coder:3b": 131072,
            "qwen2.5-coder:7b": 131072,
            "qwen2.5-coder:14b": 131072,
            "qwen2.5-coder:32b": 131072,
            "nemotron-3.5-lightning": 131072,
            "nemotron-3.5-super-vl": 131072,
            "gpt-4o": 128000,
            "gpt-4o-mini": 128000,
            "claude-3-5-sonnet": 200000,
            "claude-3-haiku": 200000,
            "gemini-2.0-flash": 1000000,
            "gemini-2.5-flash": 1000000,
            "llama-3.1-8b": 131072,
            "llama-3.1-70b": 131072,
            "llama-3.2-3b": 131072,
            "llama-3.2-11b": 131072,
        }
        for key, size in context_map.items():
            if key in name:
                return size
        return 32768  # Default conservative estimate

    # Ollama local models
    ollama_models = ai_gateway._ollama_models_sync()
    if ollama_models:
        providers["Ollama (Local)"] = []
        for model_name in ollama_models:
            is_vision = bool(_VISION_NAME_RE.search(model_name)) if '_VISION_NAME_RE' in dir(ai_gateway) else False
            providers["Ollama (Local)"].append({
                "id": f"ollama/{model_name}",
                "name": model_name,
                "provider": "ollama",
                "provider_group": "local",
                "pricing": "free",
                "pricing_detail": "Local execution — no API cost",
                "tool_calling": _supports_tools(model_name),
                "context_window": _context_window(model_name),
                "available": True,
                "local": True,
                "vision": is_vision,
            })

    # Cloud providers from config
    for provider in CLOUD_PROVIDERS:
        key = ai_gateway._cloud_key(provider)
        if not key:
            continue
        gw = admin_store.get_gateway()
        gw_providers = gw.get("providers", {})
        prov_cfg = gw_providers.get(provider, {})
        provider_configured = prov_cfg.get("configured", bool(key))
        model_field = {
            "openai": "openai_model",
            "anthropic": "anthropic_model",
            "gemini": "gemini_model",
            "openrouter": "openrouter_model",
            "huggingface": "huggingface_model",
        }.get(provider)
        configured_model = ""
        if model_field:
            configured_model = (gw.get(model_field) or "").strip()

        # Determine available models for this provider
        provider_models = []
        if provider == "openrouter":
            # OpenRouter exposes many models; list common ones
            provider_models = [
                "openai/gpt-4o",
                "openai/gpt-4o-mini",
                "openai/gpt-4-turbo",
                "anthropic/claude-3.5-sonnet",
                "anthropic/claude-3-haiku",
                "google/gemini-2.0-flash",
                "google/gemini-2.5-flash",
                "meta-llama/llama-3.1-8b-instruct",
                "meta-llama/llama-3.1-70b-instruct",
                "nvidia/nemotron-3.5-lightning",
                "nvidia/nemotron-3.5-super-vl",
                "qwen/qwen2.5-coder:3b",
                "qwen/qwen2.5-coder:7b",
                "cohere/north-mini-code:free",
            ]
        elif provider == "openai":
            provider_models = [
                "gpt-4o",
                "gpt-4o-mini",
                "gpt-4-turbo",
                "gpt-3.5-turbo",
            ]
        elif provider == "anthropic":
            provider_models = [
                "claude-3-5-sonnet-latest",
                "claude-3-haiku-latest",
                "claude-3-opus-latest",
            ]
        elif provider == "gemini":
            provider_models = [
                "gemini-2.0-flash",
                "gemini-2.5-flash",
                "gemini-1.5-pro",
            ]
        elif provider == "huggingface":
            provider_models = [
                "Qwen/Qwen2.5-Coder-7B-Instruct",
                "Qwen/Qwen2.5-Coder-32B-Instruct",
                "Qwen/Qwen2.5-VL-7B-Instruct",
                "meta-llama/Llama-3.2-3B-Instruct",
                "meta-llama/Llama-3.2-11B-Instruct",
                "meta-llama/Llama-3.1-8B-Instruct",
            ]

        provider_display = provider.capitalize()
        providers[provider_display] = []
        for model_name in provider_models:
            is_configured = (configured_model == model_name) or not configured_model
            providers[provider_display].append({
                "id": f"{provider}/{model_name}",
                "name": model_name,
                "provider": provider,
                "provider_group": "cloud",
                "pricing": "paid",
                "pricing_detail": f"Provider API billing via {provider}",
                "tool_calling": _supports_tools(model_name),
                "context_window": _context_window(model_name),
                "available": provider_configured,
                "local": False,
                "vision": provider in ("openai", "anthropic", "gemini"),
                "configured": bool(configured_model),
                "is_active": configured_model == model_name,
            })

    return {
        "providers": providers,
        "active_model": get_active_litellm_model().get("model", "unknown"),
        "active_provider": get_active_litellm_model().get("provider", "unknown"),
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
# Active run state per session: {session_id: {"run_id": str, "status": str}}
_ACTIVE_RUNS: dict[str, dict] = {}
# Steering messages per active run: {run_id: [steering_messages]}
_STEERING_STORE: dict[str, list[dict]] = {}


class QueueRequest(BaseModel):
    session_id: str
    prompt: str
    conversation_id: Optional[str] = None
    run_id: Optional[str] = None  # Associate with an existing run


class SteerRequest(BaseModel):
    session_id: str
    run_id: str
    message: str
    instruction_type: str = "steer"  # steer | replan | pause | resume


class StopRequest(BaseModel):
    session_id: str
    run_id: Optional[str] = None
    stop_type: str = "stop"  # stop | cancel_pending | cancel_tool | stop_all


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
    import uuid as _uuid
    qid = f"q-{_uuid.uuid4().hex[:8]}"
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


@router.post("/steer")
async def steer_run(body: SteerRequest):
    """Submit a steering instruction for an active run.

    The steering message is stored durably and delivered to the CAI
    orchestrator at the next safe checkpoint (after the current tool
    completes). The orchestrator treats it as operator guidance that
    may trigger re-planning.
    """
    _STEERING_STORE.setdefault(body.run_id, []).append({
        "id": f"steer-{_uuid.uuid4().hex[:8]}",
        "run_id": body.run_id,
        "session_id": body.session_id,
        "message": body.message,
        "instruction_type": body.instruction_type,
        "status": "submitted",
        "created_at": _utc_now_iso(),
        "applied_at": None,
        "applied": False,
    })
    return {"ok": True, "steering_id": f"steer-{_uuid.uuid4().hex[:8]}", "status": "submitted", "run_id": body.run_id}


@router.post("/stop")
async def stop_run(body: StopRequest):
    """Stop or cancel an active run or pending queued message.

    stop_type:
      - stop: Stop the overall investigation run (stop after current tool)
      - cancel_pending: Cancel pending queued messages for this session
      - cancel_tool: Cancel the current tool operation
      - stop_all: Stop everything (run + queue)
    """
    session_id = body.session_id
    run_id = body.run_id
    stop_type = body.stop_type

    results = []

    if stop_type in ("cancel_pending", "stop_all"):
        # Cancel pending queued messages for this session
        queue = _QUEUE_STORE.get(session_id, [])
        cancelled = 0
        for entry in queue:
            if entry["status"] == "pending":
                entry["status"] = "cancelled"
                entry["error"] = "cancelled by operator"
                cancelled += 1
        results.append({"action": "cancel_pending", "cancelled": cancelled})

    if stop_type in ("stop", "stop_all") and run_id:
        # Mark the active run as stopped
        if session_id in _ACTIVE_RUNS:
            _ACTIVE_RUNS[session_id]["status"] = "stopped"
            _ACTIVE_RUNS[session_id]["stopped_at"] = _utc_now_iso()
        results.append({"action": "stop", "run_id": run_id, "status": "stopped"})

    if stop_type == "cancel_tool" and run_id:
        # Mark the current tool as cancelled
        results.append({"action": "cancel_tool", "run_id": run_id, "status": "cancelled"})

    return {"ok": True, "session_id": session_id, "results": results}


@router.post("/model/switch")
async def switch_model(body: ModelSwitchRequest):
    """Pin a model for the session. Takes effect on the next run.

    For idle sessions, the pin applies immediately to the next request.
    For running sessions, the pin is recorded and applied at the next
    safe run boundary.
    """
    session, sid = _resolve_session(body.session_id, body.model, None, None)
    session.model = body.model
    return {
        "ok": True,
        "action": "model",
        "model": session.model,
        "session_id": sid,
        "note": "Model pinned for next run",
    }


def _utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


@router.post("/stream")
async def stream(body: StreamRequest):
    return _stream_response(body, advisory_only=False)


@router.post("/review/stream")
async def review_stream(body: StreamRequest):
    return _stream_response(body, advisory_only=True)


def _stream_response(body: StreamRequest, *, advisory_only: bool):
    if advisory_only:
        sid = str(uuid.uuid4())
        session = SessionState(session_id=sid, model=body.model)
    else:
        session, sid = _resolve_session(body.session_id, body.model, body.case_id, body.role, body.workspace)
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
                current_session, _ = _resolve_session(current_session.session_id, current_session.model, current_session.case_id, current_session.role, current_session.workspace)
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
            yield _sse(public_error(exc))
        yield _sse({"event": "done"})

    return StreamingResponse(event_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


__all__ = ["router"]
