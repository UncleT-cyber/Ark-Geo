"""Tests for the native tool-calling ReAct loop (app.services.agent.loop).

Covers:
  * Round-trip — model proposes a tool → ARK executes it → the result is
    re-appended as ``role: "tool"`` → the model answers.
  * No-tool path — a conversational model turn terminates immediately with no
    tools executed.
  * Policy denial — an unauthorized tool is never executed; the denial is fed
    back as a tool result and the model can continue.
  * Offline / unresponsive gateway — degrades to a guard message, never
    raises, never hangs.
  * Event sink — tool invocations are broadcast live (tool_started /
    tool_done) so the Terminal SSE stream can render them as they run.
"""
import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from app.agent import local_inspector as li  # noqa: E402
from app.services.agent.loop import _MAX_STEPS_MSG, ToolCallingLoop  # noqa: E402


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class _ScriptedGateway:
    """Returns queued chat_tool_round responses; records call count."""

    default_model = "loop-test"

    def __init__(self, script):
        self.script = list(script)
        self.rounds = 0

    async def chat_tool_round(self, messages, *, tools=None, **kwargs):
        self.rounds += 1
        if self.script:
            return self.script.pop(0)
        return {"content": "no more turns", "tool_calls": []}


class _OfflineGateway:
    default_model = "loop-test"

    async def chat_tool_round(self, messages, *, tools=None, **kwargs):
        return None


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


def _msgs():
    return [
        {"role": "system", "content": "You are ARK AGENT."},
        {"role": "user", "content": "inspect case-001"},
    ]


# --------------------------------------------------------------------------- #
# Round-trip
# --------------------------------------------------------------------------- #
def test_loop_proposes_tool_executes_then_answers(monkeypatch, tmp_path):
    _make_sandbox(_patch_sandbox(monkeypatch, tmp_path))
    gw = _ScriptedGateway([
        {"content": "", "tool_calls": [{
            "id": "call_1", "name": "inspect_local_path",
            "arguments": {"target_path": "case-001"},
        }]},
        {"content": "Inspected the sandbox and flagged a payload.", "tool_calls": []},
    ])
    result = asyncio.run(ToolCallingLoop(gateway=gw, max_steps=4).run(_msgs()))

    assert result["answer"] == "Inspected the sandbox and flagged a payload."
    assert result["model_calls"] == 2
    assert len(result["tool_calls"]) == 1
    call = result["tool_calls"][0]
    assert call["tool_id"] == "inspect_local_path"
    assert call["status"] == "ran"
    assert call["result"]["file_count"] == 2
    assert call["step_id"].startswith("STEP-")


def test_loop_feeds_tool_result_back_as_role_tool(monkeypatch, tmp_path):
    _make_sandbox(_patch_sandbox(monkeypatch, tmp_path))
    seen: list[list[dict]] = []

    class _Recording(_ScriptedGateway):
        async def chat_tool_round(self, messages, *, tools=None, **kwargs):
            seen.append(list(messages))
            return await super().chat_tool_round(messages, tools=tools, **kwargs)

    gw = _Recording([
        {"content": "", "tool_calls": [{
            "id": "call_1", "name": "inspect_local_path",
            "arguments": {"target_path": "case-001"},
        }]},
        {"content": "done", "tool_calls": []},
    ])
    asyncio.run(ToolCallingLoop(gateway=gw, max_steps=4).run(_msgs()))

    second = seen[1]
    assert any(m.get("role") == "assistant" and m.get("tool_calls") for m in second)
    assert any(
        m.get("role") == "tool" and "payload.bin" in m.get("content", "")
        for m in second
    )


def test_loop_conversational_turn_runs_no_tools():
    gw = _ScriptedGateway([
        {"content": "I can inspect sandboxed directories. What target?", "tool_calls": []},
    ])
    result = asyncio.run(ToolCallingLoop(gateway=gw, max_steps=4).run(_msgs()))
    assert result["tool_calls"] == []
    assert result["model_calls"] == 1
    assert "What target" in result["answer"]


def test_loop_step_cap_terminates_with_guard_message():
    gw = _ScriptedGateway([
        {"content": "", "tool_calls": [{
            "id": "call_1", "name": "inspect_local_path",
            "arguments": {"target_path": "case-001"},
        }]},
        {"content": "", "tool_calls": [{
            "id": "call_2", "name": "inspect_local_path",
            "arguments": {"target_path": "case-001"},
        }]},
        {"content": "", "tool_calls": [{
            "id": "call_3", "name": "inspect_local_path",
            "arguments": {"target_path": "case-001"},
        }]},
    ])
    result = asyncio.run(ToolCallingLoop(gateway=gw, max_steps=2).run(_msgs()))
    assert len(result["tool_calls"]) == 2
    assert all(c["status"] == "ran" for c in result["tool_calls"])
    assert result["answer"] == _MAX_STEPS_MSG


# --------------------------------------------------------------------------- #
# Policy gate
# --------------------------------------------------------------------------- #
def test_loop_denied_tool_is_never_executed(monkeypatch, tmp_path):
    _make_sandbox(_patch_sandbox(monkeypatch, tmp_path))
    gw = _ScriptedGateway([
        {"content": "", "tool_calls": [{
            "id": "call_1", "name": "inspect_local_path",
            "arguments": {"target_path": "case-001"},
        }]},
        {"content": "That tool is not authorized here.", "tool_calls": []},
    ])

    def deny(tool_id):
        return SimpleNamespace(allowed=False, reason="missing permissions")

    result = asyncio.run(ToolCallingLoop(gateway=gw, max_steps=4).run(
        _msgs(), authorize=deny))
    assert result["tool_calls"][0]["status"] == "denied"
    assert "missing permissions" in result["tool_calls"][0]["message"]
    assert result["answer"] == "That tool is not authorized here."


# --------------------------------------------------------------------------- #
# Offline / unresponsive
# --------------------------------------------------------------------------- #
def test_loop_offline_gateway_degrades_gracefully():
    result = asyncio.run(ToolCallingLoop(gateway=_OfflineGateway()).run(_msgs()))
    assert result["tool_calls"] == []
    assert result["answer"]


# --------------------------------------------------------------------------- #
# Event sink (Terminal SSE)
# --------------------------------------------------------------------------- #
def test_loop_emits_tool_events_to_sink(monkeypatch, tmp_path):
    _make_sandbox(_patch_sandbox(monkeypatch, tmp_path))
    events: list[dict] = []

    async def sink(event):
        events.append(event)

    gw = _ScriptedGateway([
        {"content": "", "tool_calls": [{
            "id": "call_1", "name": "inspect_local_path",
            "arguments": {"target_path": "case-001"},
        }]},
        {"content": "done", "tool_calls": []},
    ])
    asyncio.run(ToolCallingLoop(gateway=gw, max_steps=4, sink=sink).run(_msgs()))

    started = [e for e in events if e["event"] == "tool_started"]
    done = [e for e in events if e["event"] == "tool_done"]
    assert len(started) == 1
    assert started[0]["tool_id"] == "inspect_local_path"
    assert len(done) == 1
    assert done[0]["status"] == "ran"


def test_loop_sink_error_never_breaks_the_loop(monkeypatch, tmp_path):
    _make_sandbox(_patch_sandbox(monkeypatch, tmp_path))

    async def broken_sink(_event):
        raise RuntimeError("stream gone")

    gw = _ScriptedGateway([
        {"content": "", "tool_calls": [{
            "id": "call_1", "name": "inspect_local_path",
            "arguments": {"target_path": "case-001"},
        }]},
        {"content": "done", "tool_calls": []},
    ])
    result = asyncio.run(ToolCallingLoop(
        gateway=gw, max_steps=4, sink=broken_sink).run(_msgs()))
    assert result["answer"] == "done"
    assert result["tool_calls"][0]["status"] == "ran"
