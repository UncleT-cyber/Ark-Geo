"""Terminal task event streams — SSE plumbing for the live agent loop.

`POST /agent/task?stream=true` registers a :class:`TaskEventStream`, runs the
ReAct loop in a background asyncio task, and returns the ``task_id``
immediately. The frontend then opens ``GET /agent/task/{id}/events`` and
renders events as they arrive: ``tool_started`` / ``tool_done`` lines appear in
the terminal in real time, and a final ``result`` event carries the complete
AgentTaskResponse.

Streams are in-process and bounded: closed streams are pruned after a short
TTL so memory never leaks. No cross-worker support — single-process dev
runtime, matching the rest of the backend.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, AsyncGenerator, Optional

logger = logging.getLogger(__name__)

_TTL_S = 120  # prune closed streams after this long
_HEARTBEAT_S = 15.0


class TaskEventStream:
    """Buffers agent events for one task; consumed by the SSE endpoint."""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self._queue: asyncio.Queue[dict] = asyncio.Queue()
        self._closed = False
        self._created = time.monotonic()

    # ------------------------------------------------------------------ #
    async def emit(self, event: dict) -> None:
        """Queue one agent event (tool_started / tool_done / result)."""
        if self._closed:
            return
        await self._queue.put(event)

    def finish(self) -> None:
        self._closed = True

    # ------------------------------------------------------------------ #
    async def events(self) -> AsyncGenerator[str, None]:
        """SSE body: ``data: <json>\n\n`` per event, heartbeats while idle."""
        while True:
            if self._closed and self._queue.empty():
                yield f"data: {json.dumps({'event': 'done', 'task_id': self.task_id})}\n\n"
                return
            try:
                event = await asyncio.wait_for(self._queue.get(),
                                               timeout=_HEARTBEAT_S)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"  # comment line keeps the proxy alive
                continue
            yield f"data: {json.dumps(event, default=str)}\n\n"
            if event.get("event") == "result":
                return


class TaskStreamRegistry:
    """In-process registry of active task event streams."""

    def __init__(self) -> None:
        self._streams: dict[str, TaskEventStream] = {}
        self._janitor: Optional[asyncio.Task] = None

    def create(self) -> TaskEventStream:
        self._prune()
        stream = TaskEventStream(task_id=f"ARK-TASK-{uuid.uuid4().hex[:8].upper()}")
        self._streams[stream.task_id] = stream
        return stream

    def get(self, task_id: str) -> Optional[TaskEventStream]:
        self._prune()
        return self._streams.get(task_id)

    def close(self, task_id: str) -> None:
        stream = self._streams.pop(task_id, None)
        if stream is not None:
            stream.finish()

    def _prune(self) -> None:
        now = time.monotonic()
        stale = [
            tid for tid, s in self._streams.items()
            if s._closed and now - s._created > _TTL_S
        ]
        for tid in stale:
            self._streams.pop(tid, None)


task_streams = TaskStreamRegistry()
