"""THE ARK — Global Backend Event Bus.

A lightweight in-process publish/subscribe bus that lets CAI agents running
inside ANY workspace broadcast their activity (tool start, progress, output)
to the rest of the backend — and, via the SSE endpoint in
``app/api/v1/endpoints/cai.py``, to the frontend tabs (Map UI, Network Graph,
Evidence Table) so they can update their visual state live.

Design:
  * Topics are free-form strings. A publish to topic ``T`` is delivered to
    subscribers of ``T`` AND to subscribers of the ``global`` topic.
  * Subscribers receive an ``asyncio.Queue``; the SSE helper drains it.
  * No external broker required — the bus is process-local, which matches the
    single-backend, zero-retention forensic model.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Optional


class EventBus:
    def __init__(self) -> None:
        # topic -> set of asyncio.Queue
        self._subs: dict[str, set[asyncio.Queue]] = {}
        self._seq = 0

    def subscribe(self, topic: str = "global") -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subs.setdefault(topic, set()).add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue, topic: str = "global") -> None:
        self._subs.get(topic, set()).discard(q)

    def publish(self, category: str, payload: dict, workspace: Optional[str] = None) -> dict:
        """Publish an event to the ``ark`` channel and the workspace channel."""
        self._seq += 1
        event = {
            "id": f"evt-{self._seq}",
            "ts": time.time(),
            "category": category,
            "workspace": workspace,
            **payload,
        }
        targets = {"ark"}
        if workspace:
            targets.add(f"ws.{workspace}")
        for topic in targets:
            for q in list(self._subs.get(topic, set())):
                try:
                    q.put_nowait(event)
                except Exception:
                    # Drop if the subscriber queue is somehow closed/broken.
                    self._subs.get(topic, set()).discard(q)
        return event

    async def stream(self, topic: str = "ark"):
        """Async generator yielding SSE-formatted strings for a topic."""
        q = self.subscribe(topic)
        try:
            while True:
                event = await q.get()
                yield f"data: {json.dumps(event, default=str)}\n\n"
        finally:
            self.unsubscribe(q, topic)


# Process-wide singleton used by the orchestrator and workspace triggers.
bus = EventBus()


def publish_tool_start(tool: str, args: dict, workspace: Optional[str] = None, session_id: Optional[str] = None) -> None:
    bus.publish("tool.start", {"tool": tool, "args": args, "session_id": session_id}, workspace)


def publish_tool_output(tool: str, result: dict, workspace: Optional[str] = None, session_id: Optional[str] = None) -> None:
    bus.publish("tool.output", {"tool": tool, "result": result, "session_id": session_id}, workspace)


def publish_agent_status(stage: str, detail: dict, workspace: Optional[str] = None, session_id: Optional[str] = None) -> None:
    bus.publish("agent.status", {"stage": stage, "detail": detail, "session_id": session_id}, workspace)


__all__ = ["EventBus", "bus", "publish_tool_start", "publish_tool_output", "publish_agent_status"]
