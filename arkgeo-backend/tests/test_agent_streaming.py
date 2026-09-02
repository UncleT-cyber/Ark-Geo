"""Tests for the streaming Terminal SSE surface (agent task event stream).

Covers:
  * ``POST /agent/task`` with ``stream: true`` returns the task id immediately
    and the background ReAct loop streams ``tool_started`` / ``tool_done``
    events live, followed by a final ``result`` event.
  * Unknown task ids 404 on the events endpoint.
"""
import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))

from app.agent import agent_loop as al  # noqa: E402
from app.agent import local_inspector as li  # noqa: E402
from main import app  # noqa: E402


class _StreamingGateway:
    """Native tool-calling fake: one inspect call, then a final answer."""

    default_model = "stream-test"

    async def available(self):
        return True

    async def chat_tool_round(self, messages, *, tools=None, **kwargs):
        if any(m.get("role") == "tool" for m in messages):
            return {"content": "Inspected live.", "tool_calls": []}
        return {
            "content": "",
            "tool_calls": [{
                "id": "call_1",
                "name": "inspect_local_path",
                "arguments": {"target_path": "case-001"},
            }],
        }


def _make_sandbox(root, case="case-001"):
    sub = os.path.join(root, case, "evidence")
    os.makedirs(sub)
    with open(os.path.join(sub, "notes.txt"), "w") as fh:
        fh.write("plaintext notes " * 20)
    with open(os.path.join(sub, "payload.bin"), "wb") as fh:
        fh.write(os.urandom(1024 * 1024 + 1024))
    return root


def _patch_sandbox(monkeypatch, tmp_path):
    root = tmp_path / "sandbox"
    monkeypatch.setattr(li, "sandbox_root", lambda: root)
    return root


def test_agent_task_stream_emits_events(monkeypatch, tmp_path):
    _make_sandbox(_patch_sandbox(monkeypatch, tmp_path))
    monkeypatch.setattr(al, "gateway", _StreamingGateway())

    client = TestClient(app)
    resp = client.post(
        "/api/v1/agent/task",
        json={
            "prompt": "inspect case-001",
            "target_path": "case-001",
            "stream": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["stream"] is True
    assert body["status"] == "running"
    task_id = body["task_id"]
    assert task_id.startswith("ARK-TASK-")

    with client.stream(
        "GET", f"/api/v1/agent/task/{task_id}/events",
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        text = "".join(r.iter_text())

    assert '"event": "tool_started"' in text
    assert '"event": "tool_done"' in text
    assert '"status": "ran"' in text
    assert '"event": "result"' in text
    assert "Inspected live." in text


def test_agent_task_stream_result_has_agent_shape(monkeypatch, tmp_path):
    _make_sandbox(_patch_sandbox(monkeypatch, tmp_path))
    monkeypatch.setattr(al, "gateway", _StreamingGateway())

    client = TestClient(app)
    task_id = client.post(
        "/api/v1/agent/task",
        json={
            "prompt": "inspect case-001",
            "target_path": "case-001",
            "stream": True,
        },
    ).json()["task_id"]

    with client.stream(
        "GET", f"/api/v1/agent/task/{task_id}/events",
    ) as r:
        text = "".join(r.iter_text())

    result_block = text.split('"event": "result"', 1)[1]
    assert "tool_calls" in result_block
    assert "observations" in result_block
    assert '"status": "done"' in result_block
    assert "payload.bin" in result_block


def test_agent_task_events_unknown_task_404():
    client = TestClient(app)
    resp = client.get("/api/v1/agent/task/ARK-TASK-NOPE/events")
    assert resp.status_code == 404


def test_agent_task_events_after_finish_404(monkeypatch, tmp_path):
    _make_sandbox(_patch_sandbox(monkeypatch, tmp_path))
    monkeypatch.setattr(al, "gateway", _StreamingGateway())

    client = TestClient(app)
    task_id = client.post(
        "/api/v1/agent/task",
        json={
            "prompt": "inspect case-001",
            "target_path": "case-001",
            "stream": True,
        },
    ).json()["task_id"]
    with client.stream("GET", f"/api/v1/agent/task/{task_id}/events") as r:
        "".join(r.iter_text())

    from app.services.agent.stream import task_streams
    task_streams.close(task_id)
    assert client.get(
        f"/api/v1/agent/task/{task_id}/events").status_code == 404
