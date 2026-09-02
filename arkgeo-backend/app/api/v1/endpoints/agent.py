"""Agent tool-calling endpoint — drives the terminal's agentic surface.

``POST /agent/task`` runs an analyst prompt (from the bottom-panel terminal)
through the :class:`AgentLoop`: model-proposed tool calls, policy-guarded,
recorded on an evidence graph, with a deterministic fallback when the model is
offline. The response carries the final answer, the tool activity log, and
CaseObservation-shaped observations the frontend folds straight into the
active case.

This is the generic agent endpoint — the ``/investigate`` flow stays the
plan→approve→execute review loop; this one is the autonomous terminal path.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.agent_loop import agent_loop
from app.agent.capabilities import capability_catalog
from app.agent.react_chain import chain_task_result, react_chain
from app.services.agent.stream import task_streams

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/agent/capabilities")
async def get_capabilities():
    """Return the ARK capability catalog (tools by domain + platform features).

    Rendered by the terminal ``ark capabilities`` command so the analyst and
    the agent share a single source of truth about what ARK can do.
    """
    return capability_catalog()


class AgentTaskRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=4000)
    target_path: Optional[str] = None
    budget: Optional[dict] = None
    stream: bool = False


async def _run_streamed(body: AgentTaskRequest, task_id: str) -> None:
    """Run the loop in the background, streaming events as they happen."""
    stream = task_streams.get(task_id)
    if stream is None:
        return
    try:
        result = await agent_loop.run(
            prompt=body.prompt,
            target_path=body.target_path,
            budget=body.budget,
            task_id=task_id,
            emit=stream.emit,
        )
        await stream.emit({"event": "result", "result": result})
        logger.info(
            "Agent task %s streamed (status=%s, tool_calls=%s)",
            task_id, result["status"], len(result["tool_calls"]),
        )
    except Exception as exc:  # noqa: BLE001 — the stream must always terminate
        logger.exception("Agent task %s failed: %s", task_id, exc)
        await stream.emit({
            "event": "result",
            "result": {
                "task_id": task_id,
                "status": "failed",
                "answer": "The agent task failed unexpectedly. Nothing fabricated.",
                "tool_calls": [],
            },
        })
    finally:
        stream.finish()


@router.post("/agent/task")
async def run_agent_task(body: AgentTaskRequest):
    """Resolve a terminal prompt into policy-guarded tool calls + findings.

    Offensive-security prompts ("perform a penetration test on <ip>") are
    classified as a pentest intent and return a ``needs_approval`` task: the
    chain planned the engagement and the analyst must answer the permission
    prompt via :func:`confirm_agent_task` before anything executes.

    With ``stream: true`` the task runs in the background and this returns the
    ``task_id`` immediately; tool invocations are then broadcast live over
    ``GET /agent/task/{task_id}/events`` (Server-Sent Events) with a final
    ``result`` event carrying the complete AgentTaskResponse.
    """
    if body.stream:
        stream = task_streams.create()
        asyncio.create_task(_run_streamed(body, stream.task_id))
        return {"task_id": stream.task_id, "stream": True, "status": "running"}
    result = await agent_loop.run(
        prompt=body.prompt,
        target_path=body.target_path,
        budget=body.budget,
    )
    logger.info(
        "Agent task %s done (status=%s, tool_calls=%s)",
        result["task_id"], result["status"], len(result["tool_calls"]),
    )
    return result


@router.get("/agent/task/{task_id}/events")
async def agent_task_events(task_id: str):
    """Server-Sent Events stream for a running terminal agent task.

    Emits ``tool_started`` / ``tool_done`` events live as the ReAct loop runs,
    a final ``result`` event with the complete AgentTaskResponse, and
    keep-alive comments while the model is thinking. Unknown or fully pruned
    task ids return 404.
    """
    stream = task_streams.get(task_id)
    if stream is None:
        raise HTTPException(status_code=404,
                            detail=f"Unknown or expired agent task {task_id}")
    return StreamingResponse(
        stream.events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class AgentConfirmRequest(BaseModel):
    """Answer to a terminal permission prompt for a pending RE-ACT plan.

    ``decision`` is one of:
      * ``now``  — approve and run the planned engagement (active mode).
      * ``always`` — approve and remember the tools (no prompt on future runs).
      * ``deny`` — refuse; nothing executes and the session is closed.
      * ``dry_run`` — approve but simulate (no traffic / subprocesses).
    """
    session_id: str = Field(..., min_length=1)
    decision: str = Field(..., min_length=1)
    operator: str = "terminal"


@router.post("/agent/task/confirm")
async def confirm_agent_task(body: AgentConfirmRequest):
    """Execute (or refuse) a pending RE-ACT engagement after the permission prompt."""
    decision = body.decision.strip().lower()
    session = react_chain.store.get(body.session_id)
    if not session:
        raise HTTPException(status_code=404,
                            detail=f"Unknown RE-ACT session {body.session_id}")

    if decision in ("deny", "no", "n", "reject", "refuse"):
        session.status = "rejected"
        session.rejection_reason = (
            "denied by the operator at the terminal permission prompt")
        session.updated_at_ms = int(time.time() * 1000)
        react_chain.store.put(session)
        logger.info("RE-ACT %s denied by operator", body.session_id)
        return chain_task_result(session)

    always = decision in ("always", "always use", "yes always", "aa", "ay")
    mode = ("dry_run" if decision in ("dry", "dry_run", "simulate", "simulation")
            else "active")
    try:
        session = await react_chain.approve(
            body.session_id, operator=body.operator, mode=mode, always=always)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    logger.info(
        "RE-ACT %s approved (operator=%s, mode=%s, always=%s) → %s",
        body.session_id, body.operator, mode, always, session.status,
    )
    return chain_task_result(session)
