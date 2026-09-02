"""THE ARK — Real CAI Orchestrator.

A **genuine** execution back-end built on CAI's model substrate (``litellm``)
with THE ARK's real tool registry dispatched on every tool call. It replaces the
old simulated ``agent_bridge`` and the previous hard ``max_iterations`` abort
with an **adaptive** ReAct loop:

  * PATH A — Advisory: single streaming model completion, no tools.
  * PATH B — Autonomous: a ReAct tool-calling loop executing REAL ARK tools,
    with HITL [Y/n] approvals for risky tools and live progress streaming.

Adaptive behaviour (per directive):
  * No hard abort. Operational tasks may run up to ``ITER_BUDGET`` (50) steps.
  * At every ``CHECKPOINT`` (15) steps without a final answer, a clean HITL
    continuation prompt is streamed; the operator may pause (clean stop, never
    an "aborted" error) or continue.
  * Long-running loops are protected by context compaction so the LLM context
    window is never exceeded.
  * Every tool start / output is published to the global Event Bus so frontend
    tabs (Map, Network Graph, Evidence) update live.

The orchestrator never fabricates; every tool result is the real output of the
underlying binary or THE ARK service.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

import litellm

from app.engine.router import classify_intent, IntentMode
from app.engine.cai.registry import get_workspace_system
from app.services.ai_gateway import get_active_litellm_model
from app.services.bus import bus, publish_tool_start, publish_tool_output, publish_agent_status


# The active model is the single source of truth from the Admin Console /
# Settings panel (central config). We no longer hardcode a default provider
# here — CAI resolves it dynamically via ``get_active_litellm_model`` so every
# workspace uses the same AI. ``ARKGEO_CAI_MODEL`` remains only as an explicit
# escape hatch that overrides the admin selection when set.
_DEFAULT_MODEL_ENV = os.environ.get("ARKGEO_CAI_MODEL")

# Persona is bound dynamically from the central prompts module — never hardcoded
# inside individual tool functions.
from app.engine.prompts import advisory_system, autonomous_system  # noqa: E402

ADVISORY_SYSTEM = advisory_system()

# Adaptive loop budgets (no hard abort — operator can always pause).
ITER_BUDGET = 50          # operational tasks may run up to 50 seamless steps
CHECKPOINT = 15           # HITL continuation prompt every 15 steps
COMPACT_KEEP = 14         # keep only the last N messages (context compaction)
HITL_TIMEOUT = 30         # seconds to wait for operator approval


@dataclass
class SessionState:
    session_id: str
    role: str = "operator"
    case_id: Optional[str] = None
    model: Optional[str] = None
    workspace: Optional[str] = None
    messages: list[dict] = field(default_factory=list)
    approval_event: asyncio.Event = field(default_factory=asyncio.Event)
    approval_decision: Optional[bool] = None
    pending_tool: Optional[str] = None
    pre_approval: Optional[bool] = None
    auto_approve: bool = False
    auto_approve_announced: bool = False
    last_execution_id: Optional[str] = None
    case_context: Optional[dict] = None


_SESSIONS: dict[str, SessionState] = {}


def get_session(session_id: str, **kw) -> SessionState:
    # A model passed in is an explicit per-session pin (e.g. /model command);
    # otherwise the session inherits the admin-active model at call time.
    if kw.get("model"):
        kw["model"] = kw["model"]
    if session_id not in _SESSIONS:
        _SESSIONS[session_id] = SessionState(session_id=session_id, **kw)
    else:
        s = _SESSIONS[session_id]
        if kw.get("model"):
            s.model = kw["model"]
        if kw.get("case_id"):
            s.case_id = kw["case_id"]
        if kw.get("role"):
            s.role = kw["role"]
        if kw.get("workspace"):
            s.workspace = kw["workspace"]
        if kw.get("case_context"):
            s.case_context = kw["case_context"]
    return _SESSIONS[session_id]


def approve(session_id: str, decision: bool, allow_always: bool = False, execution_id: Optional[str] = None) -> bool:
    s = _SESSIONS.setdefault(session_id, SessionState(session_id=session_id))
    if allow_always:
        s.auto_approve = True
    if execution_id:
        s.last_execution_id = execution_id
    if s.pending_tool:
        s.approval_decision = True if allow_always else decision
        s.approval_event.set()
    else:
        s.pre_approval = True if allow_always else decision  # operator responded before the gate armed
    return True


def _domain_for_workspace(workspace: Optional[str]) -> Optional[str]:
    """Return the tool domain filter for a workspace (None = all tools)."""
    if not workspace:
        return None
    from app.engine.cai.registry import WORKSPACE_AGENTS
    meta = WORKSPACE_AGENTS.get(workspace.lower(), WORKSPACE_AGENTS["general"])
    domains = meta["domains"]
    # A workspace spanning multiple domains → no single-domain filter (use all).
    if not domains or len(domains) != 1:
        return None
    return domains[0]


def _compact(session: SessionState) -> None:
    """Context compaction: keep only the most recent messages to bound the
    LLM context window during long-running ReAct loops."""
    if len(session.messages) > COMPACT_KEEP:
        session.messages = session.messages[-COMPACT_KEEP:]


async def _litellm_kwargs(session: SessionState, system: str, with_tools: bool, stream: bool, tools_domain: Optional[str] = None, workspace: Optional[str] = None) -> dict:
    msgs = [{"role": "system", "content": system}] + session.messages
    # Single source of truth: resolve the active model from central config
    # (Admin Console / Settings). An explicit per-session pin in session.model
    # (e.g. /model) still wins; otherwise we inherit the admin selection.
    if _DEFAULT_MODEL_ENV:
        resolved = get_active_litellm_model(model_override=_DEFAULT_MODEL_ENV)
    elif session.model:
        if "/" in session.model:
            prov, mdl = session.model.split("/", 1)
        else:
            prov, mdl = None, session.model
        resolved = get_active_litellm_model(provider_override=prov, model_override=mdl)
    else:
        resolved = get_active_litellm_model()
    kw = {
        "model": resolved["model"],
        "messages": msgs,
        "api_base": resolved.get("api_base", "http://localhost:11434"),
        "api_key": resolved.get("api_key", "ollama"),
        "stream": stream,
        "temperature": 0.2,
    }
    if with_tools:
        # UNIFIED REGISTRY — single source of truth for ALL tools.
        # No more three-way merge, no more runtime deduplication.
        from app.agent.unified_registry import unified_registry
        if not unified_registry._populated:
            unified_registry.populate()
        kw["tools"] = unified_registry.openai_tools(tools_domain)
        kw["tool_choice"] = "auto"
    return kw


async def _stream_completion(kw: dict):
    """Yield ('token', text) for an advisory (no-tool) streaming completion."""
    response = await litellm.acompletion(**kw)
    async for chunk in response:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if getattr(delta, "content", None):
            yield ("token", delta.content)
    return


async def _complete(kw: dict):
    """Non-streaming completion — reliable structured tool calls (Ollama)."""
    resp = await litellm.acompletion(**kw)
    msg = resp.choices[0].message
    calls = []
    for tc in (msg.tool_calls or []):
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {"_raw": tc.function.arguments}
        calls.append({"name": tc.function.name, "arguments": args})
    return (msg.content or "", calls)


def _parse_tool_call_obj(obj: object):
    """Extract (name, arguments) from an OpenAI-style or definition-style dict.

    Handles ``{"type":"function","function":{"name":...,"arguments":...}}`` and
    the bare ``{"name":...,"arguments":...}`` shapes. A tool *definition* (which
    carries ``description``/``parameters`` but no call ``arguments``) yields an
    empty argument dict so the call can still be rendered cleanly.
    """
    if not isinstance(obj, dict):
        return None, None
    fn = obj.get("function")
    if isinstance(fn, dict):
        name = fn.get("name")
        raw = fn.get("arguments")
        if raw is None and "parameters" in fn:
            raw = "{}"
    else:
        name = obj.get("name")
        raw = obj.get("arguments")
    if not name:
        return None, None
    args: dict = {}
    if isinstance(raw, str):
        try:
            args = json.loads(raw or "{}")
        except json.JSONDecodeError:
            args = {}
    elif isinstance(raw, dict):
        args = raw
    return name, args


def _extract_tool_calls_from_text(content: str):
    """Recover tool calls the model emitted as inline JSON (CAI-equivalent).

    Mirrors CAI's malformed-tool-call recovery: when the model returns the call
    as text instead of structured ``tool_calls``, parse it out and strip the raw
    JSON so it is never streamed verbatim to the terminal.

    Returns ``(cleaned_content, list_of_calls)`` where each call is
    ``{"name": str, "arguments": dict}``.
    """
    if not content or ("function" not in content and '"name"' not in content):
        return content, []
    calls: list = []
    cleaned = content
    depth = 0
    start = -1
    for i, ch in enumerate(content):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    frag = content[start:i + 1]
                    try:
                        obj = json.loads(frag)
                    except json.JSONDecodeError:
                        obj = None
                    if obj is not None:
                        name, args = _parse_tool_call_obj(obj)
                        if name:
                            calls.append({"name": name, "arguments": args})
                            cleaned = cleaned.replace(frag, "", 1)
                    start = -1
    return cleaned, calls


async def _stream_words(text: str):
    for tok in text.split(" "):
        yield ("token", tok + " ")
        await asyncio.sleep(0.01)


async def _await_approval(session: SessionState, tool_id: str) -> bool:
    session.pending_tool = tool_id
    session.approval_decision = None
    session.approval_event.clear()
    if session.pre_approval is not None:
        decision = session.pre_approval
        session.pre_approval = None
        session.pending_tool = None
        return decision
    try:
        await asyncio.wait_for(session.approval_event.wait(), timeout=HITL_TIMEOUT)
    except asyncio.TimeoutError:
        decision = False
    else:
        decision = bool(session.approval_decision)
    session.pending_tool = None
    return decision


# _run_cai_tool removed — CAI tools are now in the unified registry.


async def _dispatch_tool(tool_id: str, args: dict, domain: Optional[str]) -> dict:
    """Unified tool dispatch via the Unified Registry.

    Single entry point. No more three-tier fallback. The unified registry
    knows about every tool — ARK substrate, ARK catalogue, and CAI native.
    Returns an ARK-style ``{status, tool, result}`` dict.
    """
    from app.agent.unified_registry import unified_registry
    if not unified_registry._populated:
        unified_registry.populate()
    try:
        raw = await unified_registry.acall(tool_id, **args)
        return {"status": "ok", "tool": tool_id, "result": raw}
    except Exception as exc:
        return {"status": "error", "tool": tool_id, "error": str(exc)}


# _agent_registry() removed — all dispatch goes through unified_registry.


# Risk tiers that require HITL / step confirmation (normalized across the
# agent RiskLevel enum and the ARK string constants).
_RISK_GATED = {"medium", "elevated", "high", "critical"}


def _resolve_risk(tool_id: str, domain: Optional[str]) -> str:
    """Return the gating risk tier for a tool id, normalized to a lowercase str."""
    from app.agent.unified_registry import unified_registry
    if not unified_registry._populated:
        unified_registry.populate()
    tool = unified_registry.get(tool_id)
    if tool:
        return tool.risk
    return "high"  # unknown tools get highest gate


def _build_case_context_block(ctx: dict) -> str:
    """Build a system-prompt block from the frontend's case analysis context.

    This injects the current image analysis results (coordinates, confidence,
    EXIF, contradictions, observations) into the AI's context so it can reason
    about the active investigation without re-running the full pipeline.
    """
    lines = ["===== ACTIVE CASE ANALYSIS CONTEXT =====",
             "The following is the current image analysis state from the "
             "BrainPipeline. Use this to reason about the image without "
             "re-running deterministic tools unless you need deeper analysis.\n"]

    if ctx.get("image_sha256"):
        lines.append(f"Image SHA-256: {ctx['image_sha256']}")
    if ctx.get("source"):
        lines.append(f"Analysis Source: {ctx['source']}")
    if ctx.get("filename"):
        lines.append(f"Filename: {ctx['filename']}")

    # Coordinates
    coords = ctx.get("coordinates")
    if coords:
        lines.append(f"\nGPS Coordinates: {coords.get('lat')}, {coords.get('lon')}")
    if ctx.get("address"):
        addr = ctx["address"]
        if isinstance(addr, dict):
            lines.append(f"Address: {addr.get('formatted', addr.get('display_name', ''))}")
    if ctx.get("altitude"):
        lines.append(f"Altitude: {ctx['altitude']}m")
    if ctx.get("datetime_original"):
        lines.append(f"DateTime Original: {ctx['datetime_original']}")

    # Camera
    cam = ctx.get("camera")
    if cam:
        if isinstance(cam, dict):
            lines.append(f"Camera: {cam.get('make', '')} {cam.get('model', '')}")

    # Consensus
    consensus = ctx.get("consensus", {})
    if consensus:
        conf = consensus.get("confidence_score", 0)
        lines.append(f"\nConsensus Confidence: {round(conf * 100, 1)}%")
        if consensus.get("tier"):
            lines.append(f"Confidence Tier: {consensus['tier']}")
        tags = consensus.get("visual_evidence_tags", [])
        if tags:
            lines.append(f"Visual Evidence Tags: {', '.join(tags[:10])}")

    # Consistency findings
    cf = ctx.get("consistency_findings", [])
    if cf:
        issues = [f for f in cf if isinstance(f, dict) and f.get("status") != "OK"]
        if issues:
            lines.append(f"\nConsistency Issues ({len(issues)}):")
            for f in issues[:5]:
                lines.append(f"  - [{f.get('severity', '?')}] {f.get('field', '?')}: {f.get('message', '')}")

    # Contradictions
    contradictions = ctx.get("contradictions", [])
    if contradictions:
        lines.append(f"\nContradictions ({len(contradictions)}):")
        for c in contradictions[:5]:
            if isinstance(c, dict):
                lines.append(f"  - {c.get('description', c.get('type', ''))}")

    # GPS spoofing
    if ctx.get("gps_spoofing_detected"):
        lines.append("\n⚠ GPS SPOOFING DETECTED — metadata GPS may be fabricated")
    if ctx.get("steganography_detected"):
        lines.append("⚠ STEGANOGRAPHY DETECTED — hidden data may be present")

    # Source discovery
    sd = ctx.get("source_discovery", {})
    if sd and isinstance(sd, dict):
        lines.append(f"\nSource Discovery: {sd.get('state', 'unknown')}")
        exact = sd.get("exact_matches", [])
        similar = sd.get("similar_matches", [])
        if exact:
            lines.append(f"  Exact matches: {len(exact)}")
        if similar:
            lines.append(f"  Similar matches: {len(similar)}")
        if sd.get("phash"):
            lines.append(f"  Perceptual hash: {sd['phash'][:16]}...")

    # Evidence summary
    es = ctx.get("evidence_summary", {})
    if es and isinstance(es, dict):
        ladder = es.get("ladder", {})
        if ladder:
            lines.append(f"\nEvidence Ladder:")
            for tier, count in ladder.items():
                if count:
                    lines.append(f"  {tier}: {count} item(s)")

    # Telemetry
    telem = ctx.get("telemetry_resolve")
    if telem and isinstance(telem, dict):
        lines.append(f"\nTelemetry Resolution: {telem.get('method', 'none')}")
        if telem.get("confidence"):
            lines.append(f"  Confidence: {telem['confidence']}")

    lines.append("\nYou can run brain_analyze for a fresh analysis, or use "
                 "specific tools (search_reverse_source, extract_exif_deep, etc.) "
                 "for deeper investigation on specific aspects.")
    return "\n".join(lines)


async def run(session: SessionState, prompt: str, workspace: Optional[str] = None) -> AsyncIterator[dict]:
    """Execute a prompt through ARK-CAI and stream SSE-style event dicts."""
    if workspace:
        session.workspace = workspace
    session.messages.append({"role": "user", "content": prompt})
    decision = classify_intent(prompt)
    is_advisory = decision.mode == IntentMode.ADVISORY
    path = "advisory" if is_advisory else "autonomous"
    system = ADVISORY_SYSTEM if is_advisory else autonomous_system(get_workspace_system(session.workspace))

    # Inject case context for IMINT workspace — the AI needs to know the
    # current image analysis state to reason about it.
    if session.case_context and session.workspace in ("imint", "image", None):
        ctx = session.case_context
        context_block = _build_case_context_block(ctx)
        if context_block:
            system = f"{system}\n\n{context_block}"

    yield {
        "type": "status", "stage": "planning", "path": path,
        "workspace": session.workspace, "reason": decision.rationale,
    }
    publish_agent_status("planning", {"path": path, "workspace": session.workspace}, session.workspace, session.session_id)

    if is_advisory:
        yield {"type": "status", "stage": "thinking"}
        kw = await _litellm_kwargs(session, system, with_tools=False, stream=True)
        full = []
        async for kind, payload in _stream_completion(kw):
            if kind == "token":
                yield {"type": "token", "text": payload}
                full.append(payload)
        session.messages.append({"role": "assistant", "content": "".join(full)})
        yield {"type": "final", "text": "".join(full)}
        return

    # AUTONOMOUS adaptive ReAct loop
    tools_domain = _domain_for_workspace(session.workspace)
    iteration = 0
    while iteration < ITER_BUDGET:
        iteration += 1
        yield {"type": "status", "stage": "calling_model", "turn": iteration}
        publish_agent_status("calling_model", {"turn": iteration}, session.workspace, session.session_id)
        kw = await _litellm_kwargs(session, system, with_tools=True, stream=False, tools_domain=tools_domain, workspace=session.workspace)
        content, tool_calls = await _complete(kw)

        # CAI-style recovery: the model (esp. local Ollama) may emit the tool
        # call as inline JSON text rather than structured tool_calls. Recover it
        # so we render a clean call badge instead of dumping raw JSON into the
        # terminal.
        recovered = False
        if not tool_calls:
            content, recovered_calls = _extract_tool_calls_from_text(content)
            if recovered_calls:
                tool_calls = recovered_calls
                recovered = True

        if not tool_calls:
            session.messages.append({"role": "assistant", "content": content})
            async for kind, payload in _stream_words(content):
                if kind == "token":
                    yield {"type": "token", "text": payload}
            yield {"type": "final", "text": content}
            return

        if recovered:
            session.messages.append({"role": "assistant", "content": content})

        # Adaptive checkpoint: ask the operator to continue past 15 steps.
        if iteration % CHECKPOINT == 0:
            if not session.auto_approve:
                yield {
                    "type": "hitl", "tool": "__continue__", "args": {},
                    "continue": True, "session_id": session.session_id,
                    "prompt": "ARK: Completed 15 investigation steps. Continue deep assessment? [Y/n]",
                }
                decision = await _await_approval(session, "__continue__")
                if not decision:
                    yield {"type": "final", "text": "Investigation paused at operator request after "
                                                    f"{iteration} steps. Findings gathered so far are above."}
                    return

        for tc in tool_calls:
            tool_id = tc["name"]
            args = tc.get("arguments", {})
            eid = uuid.uuid4().hex
            risk = _resolve_risk(tool_id, tools_domain)
            if risk in _RISK_GATED:
                # "Allow Always" — operator granted continuous auto-approval for
                # this investigation turn; skip the prompt and run without asking.
                if session.auto_approve:
                    if not session.auto_approve_announced:
                        yield {
                            "type": "status", "stage": "auto_approve",
                            "text": "ARK-CAI: Auto-approval session grant enabled by operator.",
                            "session_id": session.session_id,
                        }
                        session.auto_approve_announced = True
                    allowed = True
                else:
                    yield {
                        "type": "hitl", "tool": tool_id, "args": args,
                        "function": {"name": tool_id, "arguments": args},
                        "execution_id": eid, "risk": risk,
                        "session_id": session.session_id,
                        "prompt": f"ARK: wants to run {tool_id}({args}). Approve? [Y/n/A]",
                    }
                    allowed = await _await_approval(session, tool_id)
                if not allowed:
                    yield {"type": "status", "stage": "tool_denied", "tool": tool_id}
                    session.messages.append({
                        "role": "tool", "tool_call_id": None, "name": tool_id,
                        "content": json.dumps({"status": "denied", "tool": tool_id,
                                               "error": "operator denied execution"}),
                    })
                    continue
            # Dynamic, frontend-parseable tool-call event (OpenAI-style
            # `function` envelope). The SSE listener renders the RUNNING badge
            # from this structure without any hardcoded target/regex matching.
            yield {
                "type": "tool_call", "tool": tool_id, "args": args,
                "function": {"name": tool_id, "arguments": args},
                "execution_id": eid, "session_id": session.session_id,
            }
            yield {"type": "status", "stage": "tool_running", "tool": tool_id, "args": args}
            publish_tool_start(tool_id, args, session.workspace, session.session_id)
            t0 = time.time()
            result = await _dispatch_tool(tool_id, args, tools_domain)
            elapsed_ms = int((time.time() - t0) * 1000)
            publish_tool_output(tool_id, result, session.workspace, session.session_id)
            yield {
                "type": "tool", "tool": tool_id, "args": args,
                "elapsed_ms": elapsed_ms, "result": result,
                "execution_id": eid,
            }
            session.messages.append({
                "role": "tool", "name": tool_id,
                "content": json.dumps(result, default=str)[:8000],
            })

        _compact(session)

    # Reached the operational budget without a final answer — soft stop, NOT an
    # "aborted" error (the operator may resume in a fresh session).
    yield {
        "type": "final",
        "text": f"Assessment reached the {ITER_BUDGET}-step operational budget; "
                "partial findings are above. Resume or refine the objective to continue.",
    }


__all__ = ["SessionState", "get_session", "approve", "run"]
