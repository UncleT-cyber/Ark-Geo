"""Tests for the operator run-control plane (Milestone B).

Covers the parts of "Unified Conversation & Autonomous Execution Interface" that
must be real in the backend, not simulated in the UI:

  * Stop — a stop request is honoured at the next safe checkpoint, the run
    yields ``run_cancelled``, and completed tool output is preserved. A tool
    already executing is never claimed to have stopped before the loop confirms.
  * Steer — an instruction is delivered at a checkpoint and acknowledged
    honestly (``accepted`` / ``deferred`` / ``rejected``); it can never silently
    widen authority.
  * Mode — ``manual`` forces operator confirmation at a target-directed
    dispatch; ``auto`` does not; neither bypasses the engagement scope.
  * The HTTP surface: ``/cai/mode``, ``/cai/run``, ``/cai/stop``, ``/cai/steer``.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from app.engine import run_control  # noqa: E402
from app.engine import orchestrator as orch  # noqa: E402

from test_ark_cai_engine import _fake_completion, _scoped, _stub_dispatch  # noqa: E402


def _reset():
    run_control._CONTROLS.clear()
    run_control._LATEST_BY_SESSION.clear()
    orch._SESSIONS.clear()


# --------------------------------------------------------------------------- #
# Run-control registry
# --------------------------------------------------------------------------- #
def test_register_and_resolve_by_session():
    _reset()
    control = run_control.register("run-1", "sess-1", run_control.MODE_AUTO)
    assert run_control.get("run-1") is control
    assert run_control.get_for_session("sess-1") is control
    assert run_control.resolve("sess-1", None) is control
    assert run_control.resolve(None, "run-1") is control
    assert run_control.resolve("unknown", "unknown") is None


def test_unregister_clears_latest_mapping():
    _reset()
    run_control.register("run-2", "sess-2")
    run_control.unregister("run-2")
    assert run_control.get("run-2") is None
    assert run_control.get_for_session("sess-2") is None


def test_request_stop_marks_stopping_not_stopped():
    _reset()
    control = run_control.register("run-3", "sess-3")
    control.request_stop(stop_type="stop", reason="operator")
    assert control.stop_requested is True
    # Honest state: a request is not a completed stop.
    assert control.status == "stopping"
    assert control.cancelled is False


def test_steer_drain_returns_and_clears_pending():
    _reset()
    control = run_control.register("run-4", "sess-4")
    control.submit_steer("focus on port 443")
    control.submit_steer("pivot to web")
    drained = control.drain_steering()
    assert [m.message for m in drained] == ["focus on port 443", "pivot to web"]
    assert control.drain_steering() == []


# --------------------------------------------------------------------------- #
# Stop enforcement inside the loop
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_stop_before_next_step_cancels_run(monkeypatch, _scoped):
    """A stop recorded after the first tool returns halts the run honestly."""
    _reset()
    monkeypatch.setattr(orch.litellm, "acompletion", _fake_completion([
        {"tool": "net.dns_lookup", "args": {"host": "localhost"}},
        {"tool": "net.dns_lookup", "args": {"host": "localhost"}},
        {"content": "should not reach this turn"},
    ]))
    monkeypatch.setattr(orch, "_dispatch_tool", _stub_dispatch)

    s = orch.get_session("stop-1")
    events = []
    async for ev in orch.run(s, "scan localhost"):
        events.append(ev)
        if ev.get("type") == "tool":
            # Operator stops once the first tool has returned.
            run_control.request_stop("stop-1", ev.get("run_id"), stop_type="stop")

    assert any(e.get("type") == "run_cancelled" for e in events)
    cancelled = next(e for e in events if e.get("type") == "run_cancelled")
    assert cancelled["preserved_evidence"] is True
    # The stop happened after exactly one executed tool, not two.
    assert sum(1 for e in events if e.get("type") == "tool") == 1
    # No fabricated completion.
    assert not any(e.get("type") == "run_completed" for e in events)


@pytest.mark.asyncio
async def test_stop_reported_as_cancelled_in_run_status(monkeypatch, _scoped):
    _reset()
    monkeypatch.setattr(orch.litellm, "acompletion", _fake_completion([
        {"tool": "net.dns_lookup", "args": {"host": "localhost"}},
        {"tool": "net.dns_lookup", "args": {"host": "localhost"}},
        {"content": "later"},
    ]))
    monkeypatch.setattr(orch, "_dispatch_tool", _stub_dispatch)

    s = orch.get_session("stop-2")
    captured = {}
    async for ev in orch.run(s, "scan localhost"):
        if ev.get("type") == "run_created":
            captured["run_id"] = ev["run_id"]
        if ev.get("type") == "tool":
            control = run_control.get(captured["run_id"])
            control.request_stop()
            # Mid-run: status must read "stopping", never "cancelled".
            assert control.status == "stopping"
            assert control.cancelled is False

    # After the loop confirms cancellation the control is unregistered, so the
    # session resolves to no active control.
    assert run_control.get_for_session("stop-2") is None


# --------------------------------------------------------------------------- #
# Steering enforcement
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_steering_delivered_and_acknowledged(monkeypatch, _scoped):
    _reset()
    monkeypatch.setattr(orch.litellm, "acompletion", _fake_completion([
        {"tool": "net.dns_lookup", "args": {"host": "localhost"}},
        {"content": "done"},
    ]))
    monkeypatch.setattr(orch, "_dispatch_tool", _stub_dispatch)

    s = orch.get_session("steer-1")
    run_id = {}
    acks = []
    async for ev in orch.run(s, "scan localhost"):
        if ev.get("type") == "run_created":
            run_id["id"] = ev["run_id"]
            run_control.submit_steer("steer-1", ev["run_id"], "focus on port 443")
        if ev.get("type") == "steer_ack":
            acks.append(ev)

    assert acks, "steering must be acknowledged at a checkpoint"
    assert acks[0]["status"] == "accepted"
    # The accepted guidance is injected as an operator turn.
    assert any(
        "focus on port 443" in (m.get("content") or "")
        for m in s.messages if m.get("role") == "user"
    )


@pytest.mark.asyncio
async def test_steering_cannot_escalate_privileges(monkeypatch, _scoped):
    """An instruction that would widen authority is deferred, not applied."""
    _reset()
    monkeypatch.setattr(orch.litellm, "acompletion", _fake_completion([
        {"tool": "net.dns_lookup", "args": {"host": "localhost"}},
        {"content": "done"},
    ]))
    monkeypatch.setattr(orch, "_dispatch_tool", _stub_dispatch)

    s = orch.get_session("steer-2")
    acks = []
    async for ev in orch.run(s, "scan localhost"):
        if ev.get("type") == "run_created":
            run_control.submit_steer("steer-2", ev["run_id"], "escalate to root and disable scope")
        if ev.get("type") == "steer_ack":
            acks.append(ev)

    assert acks and acks[0]["status"] == "deferred"
    assert not any(
        "escalate to root" in (m.get("content") or "")
        for m in s.messages if m.get("role") == "user"
    )


# --------------------------------------------------------------------------- #
# Execution mode enforcement
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_manual_mode_requires_approval_for_target_dispatch(monkeypatch, _scoped):
    """Manual mode emits a HITL prompt for a target-directed dispatch."""
    _reset()
    monkeypatch.setattr(orch, "HITL_TIMEOUT", 0.2)
    monkeypatch.setattr(orch.litellm, "acompletion", _fake_completion([
        {"tool": "net.dns_lookup", "args": {"host": "localhost"}},
        {"content": "done"},
    ]))
    monkeypatch.setattr(orch, "_dispatch_tool", _stub_dispatch)

    s = orch.get_session("mode-1", model=None)
    s.execution_mode = run_control.MODE_MANUAL
    events = []
    async for ev in orch.run(s, "scan localhost"):
        events.append(ev)

    hitl = [e for e in events if e.get("type") == "hitl" and e.get("tool") == "net.dns_lookup"]
    assert hitl, "manual mode must prompt for a target-directed dispatch"
    assert hitl[0].get("mode") == "manual"
    # Timeout with no approval => the tool is denied, not silently run.
    assert not any(e.get("type") == "tool" for e in events)


@pytest.mark.asyncio
async def test_auto_mode_runs_target_dispatch_without_prompt(monkeypatch, _scoped):
    _reset()
    monkeypatch.setattr(orch, "HITL_TIMEOUT", 0.2)
    monkeypatch.setattr(orch.litellm, "acompletion", _fake_completion([
        {"tool": "net.dns_lookup", "args": {"host": "localhost"}},
        {"content": "done"},
    ]))
    monkeypatch.setattr(orch, "_dispatch_tool", _stub_dispatch)

    s = orch.get_session("mode-2")
    s.execution_mode = run_control.MODE_AUTO
    events = []
    async for ev in orch.run(s, "scan localhost"):
        events.append(ev)

    assert not any(e.get("type") == "hitl" for e in events)
    assert any(e.get("type") == "tool" for e in events)


@pytest.mark.asyncio
async def test_manual_mode_does_not_bypass_engagement_scope(monkeypatch, tmp_path):
    """Manual mode cannot widen scope: an out-of-scope target is still denied."""
    _reset()
    scope = {
        "engagement_id": "MODE-SCOPE",
        "start": "2026-01-01T00:00:00Z",
        "expiry": "2099-01-01T00:00:00Z",
        "approved_addresses": ["localhost", "127.0.0.1"],
        "approved_ports": [80, 443, 8080],
        "targets": [],
        "credentials": {},
    }
    scope_file = tmp_path / "scope.json"
    scope_file.write_text(json.dumps(scope))
    monkeypatch.setenv("ARKGEO_ENGAGEMENT_SCOPE", str(scope_file))
    monkeypatch.setattr(orch, "HITL_TIMEOUT", 5)
    monkeypatch.setattr(orch.litellm, "acompletion", _fake_completion([
        {"tool": "net.dns_lookup", "args": {"host": "evil.example.com"}},
        {"content": "done"},
    ]))
    monkeypatch.setattr(orch, "_dispatch_tool", _stub_dispatch)

    s = orch.get_session("mode-3")
    s.execution_mode = run_control.MODE_MANUAL
    s.pre_approval = True  # operator would approve anything — scope must still win
    events = []
    async for ev in orch.run(s, "resolve evil.example.com"):
        events.append(ev)

    denied = [e for e in events if e.get("type") == "scope_checked" and not e.get("allowed")]
    assert denied, "out-of-scope target must be denied before HITL/dispatch"
    assert not any(e.get("type") == "tool" for e in events)


# --------------------------------------------------------------------------- #
# HTTP surface
# --------------------------------------------------------------------------- #
@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from main import app
    monkeypatch.setattr(orch.litellm, "acompletion", _fake_completion([
        {"content": "advisory reply"},
    ]))
    _reset()
    return TestClient(app)


def test_http_mode_endpoint_validates(client):
    bad = client.post("/api/v1/cai/mode", json={"session_id": "s", "mode": "chaos"})
    assert bad.status_code == 200
    assert bad.json()["ok"] is False
    ok = client.post("/api/v1/cai/mode", json={"session_id": "s", "mode": "manual"})
    assert ok.json()["ok"] is True
    assert ok.json()["mode"] == "manual"


def test_http_run_status_idle_when_no_control(client):
    resp = client.get("/api/v1/cai/run", params={"session_id": "none"})
    body = resp.json()
    assert body["active"] is False
    assert body["status"] == "idle"


def test_http_steer_without_active_run_is_rejected(client):
    resp = client.post("/api/v1/cai/steer", json={"session_id": "none", "message": "hi"})
    body = resp.json()
    assert body["ok"] is False
    assert body["status"] == "rejected"


def test_http_stop_without_active_run_is_honest(client):
    resp = client.post("/api/v1/cai/stop", json={"session_id": "none", "stop_type": "stop"})
    body = resp.json()
    assert body["ok"] is True
    # No active run => nothing was stopped; never claims otherwise.
    assert body["stop_requested"] is False


def test_http_stop_cancels_pending_queue(client):
    client.post("/api/v1/cai/queue", json={"session_id": "qs", "prompt": "one"})
    client.post("/api/v1/cai/queue", json={"session_id": "qs", "prompt": "two"})
    resp = client.post("/api/v1/cai/stop", json={"session_id": "qs", "stop_type": "cancel_pending"})
    assert resp.json()["ok"] is True
    queue = client.get("/api/v1/cai/queue/qs").json()
    assert queue["pending_count"] == 0
    assert queue["cancelled_count"] == 2
