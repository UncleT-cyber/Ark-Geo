"""Native tool-calling ReAct loop — autonomous LLM tool invocation.

The model is presented the full JSON Function Schema surface (derived from the
registry by :mod:`app.services.agent.tools`). Each turn either:

  * emits ``tool_calls`` — the loop executes them through the registry (after
    policy authorization) and re-appends the results as ``role: "tool"``
    messages, then asks the model again; or
  * returns plain text — the loop terminates with that text as the final
    answer. This is what makes chit-chat / capability questions terminate
    immediately: no tools, just a conversational reply, driven by the system
    prompt rather than a rigid classifier.

Tool invocations are emitted to an optional async ``sink`` (the Terminal SSE
stream) as they happen. The loop is best-effort by design: an unreachable
model, a model that never picks a tool, or a capped step budget all terminate
with the model's text or a short guard message — the terminal is never left
blocked. AI proposes; the policy guard authorizes; ARK executes; nothing is
fabricated.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Awaitable, Callable, Optional

from app.agent.model_gateway import gateway as default_gateway
from app.services.agent.tools import execute_tool, function_schemas

logger = logging.getLogger(__name__)

# The only canned strings in the loop are edge-guards for "cannot make
# progress" — they are not steering templates and do not enumerate tools.
_MAX_STEPS_MSG = (
    "I reached the maximum number of tool steps before a final answer. "
    "Here is what ran and where things stand."
)
_NO_RESPONSE_MSG = (
    "The model gateway did not return a usable response. Nothing fabricated."
)

# Async callable receiving agent events: {event: "tool_started"|"tool_done", ...}
EventSink = Callable[[dict], Awaitable[None]]


async def _noop_sink(_event: dict) -> None:  # pragma: no cover — trivial
    return None


class ToolCallingLoop:
    """Iterative ReAct loop: model proposes tool_calls → ARK executes → repeat.

    Provider-neutral: the loop only ever speaks the neutral message shape (see
    ``app.agent.model_gateway`` helpers). Gateway, schema surface and policy
    are injectable so unit tests can drive the loop without a live model.
    """

    def __init__(
        self,
        gateway: Optional[Any] = None,
        max_steps: int = 6,
        sink: Optional[EventSink] = None,
    ) -> None:
        self.gateway = gateway or default_gateway
        self.max_steps = max_steps
        self.sink = sink or _noop_sink

    @property
    def model_id(self) -> str:
        return str(getattr(self.gateway, "default_model", "unknown"))

    # ------------------------------------------------------------------ #
    async def run(
        self,
        messages: list[dict],
        *,
        tools: Optional[list[dict]] = None,
        max_steps: Optional[int] = None,
        sink: Optional[EventSink] = None,
        authorize: Optional[Callable[[str], Optional[Any]]] = None,
        temperature: float = 0.2,
    ) -> dict:
        """Run the loop to completion. Returns the AgentTask-shaped trace.

        ``authorize(tool_id)`` returns a policy decision (any object with an
        ``allowed`` flag and ``reason``) or None. A denied call is recorded as
        ``status="denied"`` in the trace and the loop continues — the model may
        pick a different tool.
        """
        tools = tools if tools is not None else function_schemas()
        max_steps = max_steps or self.max_steps
        emit = sink or self.sink
        trace: list[dict] = []
        model_calls = 0
        final: Optional[str] = None

        for step in range(1, max_steps + 1):
            response = await self.gateway.chat_tool_round(
                messages, tools=tools, temperature=temperature,
            )
            model_calls += 1
            if response is None:
                logger.warning("Tool-calling round produced no usable response")
                break
            content = (response.get("content") or "").strip()
            calls = response.get("tool_calls") or []
            if not calls:
                final = content or (
                    _MAX_STEPS_MSG if trace else _NO_RESPONSE_MSG
                )
                break

            messages.append({
                "role": "assistant",
                "content": content or None,
                "tool_calls": calls,
            })

            for call in calls:
                tool_id = str(call.get("name") or "").strip()
                call_id = call.get("id") or f"call_{tool_id}_{uuid.uuid4().hex[:6]}"
                arguments = call.get("arguments") or {}
                step_id = f"STEP-{step:02d}"

                # Policy gate — never execute without authorization.
                denied: Optional[str] = None
                if authorize is not None:
                    try:
                        decision = authorize(tool_id)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Policy check failed for %s: %s",
                                       tool_id, exc)
                        decision = None
                    if decision is None or not getattr(decision, "allowed", False):
                        denied = getattr(decision, "reason", None) or \
                            (f"tool {tool_id} is not authorized for this surface"
                             if decision is None else "policy decision denied")

                await self._emit(emit, {
                    "event": "tool_started",
                    "step_id": step_id,
                    "tool_id": tool_id,
                    "arguments": arguments,
                })

                if denied:
                    entry, tool_msg = self._denied_entry(
                        step_id, tool_id, arguments, call_id, denied)
                else:
                    entry, tool_msg = await self._run_tool(
                        step_id, tool_id, arguments, call_id)

                trace.append(entry)
                messages.append(tool_msg)
                await self._emit(emit, {
                    "event": "tool_done",
                    "step_id": entry["step_id"],
                    "tool_id": entry["tool_id"],
                    "status": entry["status"],
                    "message": entry["message"],
                    "elapsed_ms": entry["elapsed_ms"],
                })

        if final is None:
            final = _MAX_STEPS_MSG if trace else _NO_RESPONSE_MSG
        return {
            "answer": final,
            "model_calls": model_calls,
            "tool_calls": trace,
            "status": "done" if trace else (
                "done" if model_calls else "failed"
            ),
        }

    # ------------------------------------------------------------------ #
    async def _run_tool(
        self,
        step_id: str,
        tool_id: str,
        arguments: dict,
        call_id: str,
    ) -> tuple[dict, dict]:
        """Execute one authorized tool call; returns (trace_entry, tool_msg)."""
        started = time.perf_counter()
        result = await execute_tool(tool_id, arguments)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        ok = bool(result.get("ok"))
        content = json.dumps(result, default=str)
        entry = {
            "step_id": step_id,
            "tool_id": tool_id,
            "arguments": arguments,
            "status": "ran" if ok else "failed",
            "message": "complete" if ok else str(result.get("error") or "failed"),
            "elapsed_ms": elapsed_ms,
            "result": result.get("result") if ok else None,
        }
        tool_msg = {
            "role": "tool",
            "tool_call_id": call_id,
            "content": content,
        }
        return entry, tool_msg

    @staticmethod
    def _denied_entry(
        step_id: str,
        tool_id: str,
        arguments: dict,
        call_id: str,
        reason: str,
    ) -> tuple[dict, dict]:
        """Build a denied-call entry without executing anything."""
        entry = {
            "step_id": step_id,
            "tool_id": tool_id,
            "arguments": arguments,
            "status": "denied",
            "message": reason,
            "elapsed_ms": 0,
            "result": None,
        }
        tool_msg = {
            "role": "tool",
            "tool_call_id": call_id,
            "content": json.dumps({"ok": False, "error": reason,
                                   "denied": True}),
        }
        return entry, tool_msg

    @staticmethod
    async def _emit(sink: EventSink, event: dict) -> None:
        try:
            await sink(event)
        except Exception as exc:  # noqa: BLE001 — the stream must never break
            logger.warning("Agent stream sink failed: %s", exc)


tool_loop = ToolCallingLoop()
