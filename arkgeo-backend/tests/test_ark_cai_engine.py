"""Verification tests for THE ARK's CAI unified engine.

These tests validate the REAL orchestration wiring (intent routing, genuine tool
dispatch, HITL gating, SSE contract) without depending on the live Ollama model:
``litellm.acompletion`` is monkeypatched so the orchestrator's ReAct loop, real
tool calls, and approval gate are exercised deterministically and offline.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.engine import router, slash, tool_adapter, orchestrator as orch


# --------------------------------------------------------------------------- #
# 1. Intent router — conversational vs autonomous
# --------------------------------------------------------------------------- #
def test_classify_advisory_no_tools():
    d = router.classify_intent("How should we approach assessing this network?")
    assert d.mode is router.IntentMode.ADVISORY
    assert d.confidence >= 0.5


def test_classify_autonomous_with_target():
    d = router.classify_intent("Perform directory enumeration on 192.168.2.11")
    assert d.mode is router.IntentMode.AUTONOMOUS
    assert d.detected_target == "192.168.2.11"


def test_classify_autonomous_with_tool_reference():
    d = router.classify_intent("Resolve DNS for localhost using THE ARK tools.")
    assert d.mode is router.IntentMode.AUTONOMOUS


# --------------------------------------------------------------------------- #
# 2. Slash command registry — unified CAI + ARK surface
# --------------------------------------------------------------------------- #
def test_slash_contains_engine_and_ark_commands():
    cmds = slash.all_commands()
    names = {c["name"] for c in cmds}
    assert {"agent", "model", "sessions", "env"}.issubset(names)
    assert {"case", "evidence", "clear"}.issubset(names)
    groups = {c["group"] for c in cmds}
    assert "engine" in groups
    assert "ark" in groups


# --------------------------------------------------------------------------- #
# 3. ARK tool registry — real tools bound into CAI schemas
# --------------------------------------------------------------------------- #
def test_tool_catalogue_size():
    assert len(tool_adapter.get_tool_specs()) >= 10


def test_tool_domains():
    domains = {t["domain"] for t in tool_adapter.get_tool_specs()}
    assert {"imint", "network", "siem", "recon", "case"}.issubset(domains)


def test_tool_schemas_generated_by_cai():
    ot = tool_adapter.get_openai_tools()
    assert len(ot) >= 10
    for spec in ot:
        assert spec["type"] == "function"
        assert spec["function"]["name"].startswith(
            ("imint.", "net.", "recon.", "siem.", "case.", "telecom.", "pentest.", "ot.", "evidence.")
        )
        assert "parameters" in spec["function"]


def test_call_real_tool():
    # Real local binary execution (dig), no network/mock required.
    res = tool_adapter.call_tool("net.dns_lookup", host="localhost")
    assert res["status"] == "ok"
    assert "127.0.0.1" in res["result"]


def test_call_unknown_tool_errors():
    res = tool_adapter.call_tool("does.not_exist")
    assert res["status"] == "error"


# --------------------------------------------------------------------------- #
# 4. Orchestrator — routed ReAct loop with REAL tool dispatch (offline)
# --------------------------------------------------------------------------- #
def _fake_completion(response_plan):
    """Build an async litellm.acompletion fake driven by ``response_plan``.

    Supports both modes used by the orchestrator:
      * stream=False → returns a response object with ``.choices[0].message``.
      * stream=True  → returns an async iterator of chunks with ``.choices[0].delta``.
    """
    state = {"i": 0}

    def _build_msg(spec):
        class _Fn:
            def __init__(self, name, args):
                self.name = name
                self.arguments = json.dumps(args)

        class _TC:
            def __init__(self, name, args):
                self.id = "call_x"
                self.function = _Fn(name, args)

        class _Msg:
            def __init__(self, content, tcs):
                self.content = content
                self.tool_calls = tcs

        return _Msg(spec.get("content"), [_TC(spec["tool"], spec["args"])] if spec.get("tool") else [])

    async def fake(**kw):
        idx = state["i"]
        state["i"] += 1
        spec = response_plan[min(idx, len(response_plan) - 1)]
        msg = _build_msg(spec)
        if kw.get("stream"):
            async def _gen():
                yield type("Chunk", (), {"choices": [type("C", (), {"delta": type("D", (), {"content": msg.content})()})()]})()
            return _gen()
        return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()

    return fake


async def _collect(session, prompt):
    events = []
    async for ev in orch.run(session, prompt):
        events.append(ev)
    return events


def test_orchestrator_advisory_streams_answer(monkeypatch):
    monkeypatch.setattr(orch.litellm, "acompletion", _fake_completion([
        {"content": "Advisory insight about SMB risk."},
    ]))
    s = orch.get_session("adv-1")
    events = asyncio.get_event_loop().run_until_complete(_collect(s, "what are the risks of SMB?"))
    assert any(e["type"] == "final" for e in events)
    assert not any(e["type"] == "tool" for e in events)


def test_orchestrator_autonomous_runs_real_tool(monkeypatch):
    monkeypatch.setattr(orch.litellm, "acompletion", _fake_completion([
        {"tool": "net.dns_lookup", "args": {"host": "localhost"}},
        {"content": "DNS resolved to 127.0.0.1."},
    ]))
    s = orch.get_session("auto-1")
    events = asyncio.get_event_loop().run_until_complete(_collect(s, "resolve DNS for localhost"))
    assert any(e["type"] == "tool" and e["tool"] == "net.dns_lookup" for e in events)
    assert any(e["type"] == "final" for e in events)


def test_orchestrator_hitl_denied_blocks_risky_tool(monkeypatch):
    monkeypatch.setattr(orch, "HITL_TIMEOUT", 0.2)
    monkeypatch.setattr(orch.litellm, "acompletion", _fake_completion([
        {"tool": "net.nmap_scan", "args": {"target": "127.0.0.1"}},
        {"content": "No tools run — engagement closed."},
    ]))
    s = orch.get_session("hitl-1")
    events = asyncio.get_event_loop().run_until_complete(_collect(s, "nmap scan 127.0.0.1"))
    assert any(e["type"] == "hitl" for e in events)
    assert any(e["type"] == "status" and e["stage"] == "tool_denied" for e in events)


def test_orchestrator_hitl_approved_runs_tool(monkeypatch):
    monkeypatch.setattr(orch, "HITL_TIMEOUT", 5)
    monkeypatch.setattr(orch.litellm, "acompletion", _fake_completion([
        {"tool": "net.nmap_scan", "args": {"target": "127.0.0.1"}},
        {"content": "Scan complete."},
    ]))

    async def scenario():
        import asyncio as _a
        s = orch.get_session("hitl-2")
        events = []

        async def runner():
            async for ev in orch.run(s, "nmap scan 127.0.0.1"):
                events.append(ev)

        task = _a.create_task(runner())
        for _ in range(200):
            if s.pending_tool:
                break
            await _a.sleep(0.01)
        orch.approve(s.session_id, True)
        await task
        return events

    events = asyncio.get_event_loop().run_until_complete(scenario())
    assert any(e["type"] == "status" and e["stage"] == "tool_running" and e["tool"] == "net.nmap_scan" for e in events)
    assert any(e["type"] == "final" for e in events)


def test_orchestrator_hitl_allow_always_auto_approves(monkeypatch):
    """`Allow Always` approves the first call, then auto-approves the rest."""
    monkeypatch.setattr(orch, "HITL_TIMEOUT", 5)
    monkeypatch.setattr(orch.litellm, "acompletion", _fake_completion([
        {"tool": "net.nmap_scan", "args": {"target": "127.0.0.1"}},
        {"tool": "net.nmap_scan", "args": {"target": "127.0.0.1"}},
        {"content": "Both scans complete."},
    ]))
    # Avoid real network scans in the unit test.
    monkeypatch.setattr(orch.tools, "call_tool", lambda tid, **kw: {"status": "ok", "tool": tid, "result": "stub"})

    async def scenario():
        import asyncio as _a
        s = orch.get_session("hitl-always")
        events = []

        async def runner():
            async for ev in orch.run(s, "scan both hosts"):
                events.append(ev)

        task = _a.create_task(runner())
        for _ in range(400):
            if s.pending_tool:
                break
            await _a.sleep(0.01)
        orch.approve(s.session_id, True, allow_always=True)
        await task
        return events

    events = asyncio.get_event_loop().run_until_complete(scenario())
    hitls = [e for e in events if e["type"] == "hitl"]
    assert len(hitls) == 1, f"expected 1 HITL prompt, got {len(hitls)}"
    assert any(e.get("stage") == "auto_approve" for e in events)
    assert sum(1 for e in events if e["type"] == "tool" and e["tool"] == "net.nmap_scan") == 2
    assert any(e["type"] == "final" for e in events)


# --------------------------------------------------------------------------- #
# 5. HTTP wiring — SSE endpoints are live (offline model fake)
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(orch.litellm, "acompletion", _fake_completion([
        {"content": "Advisory answer over HTTP."},
    ]))
    from main import app

    return TestClient(app)


def test_http_classify(client):
    r = client.post("/api/v1/cai/classify", json={"prompt": "What are the risks of open port 3389?"})
    assert r.status_code == 200
    assert r.json()["mode"] == "advisory"


def test_http_terminal_stream_emits_events(client):
    events = []
    with client.stream("POST", "/api/v1/cai/terminal/stream",
                       json={"prompt": "what are the risks of SMB?", "session_id": "http-1"}) as resp:
        for line in resp.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
    assert any(e["event"] == "session" for e in events)
    assert any(e["event"] == "final" for e in events)


def test_http_approve_endpoint(client):
    r = client.post("/api/v1/cai/terminal/approve", json={"session_id": "x", "decision": True})
    assert r.status_code == 200 and r.json()["ok"] is True
