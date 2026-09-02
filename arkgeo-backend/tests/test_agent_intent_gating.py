"""Tests for terminal agent intent gating + conversational / synthesized replies.

Covers:
  * Prompt classification — directive vs guidance vs conversational
  * Vague / conversational input NEVER auto-runs tools (offline + online)
  * Directive input runs the tool; offline → deterministic fallback answer
  * Tool-result synthesis — directive output is fed back through the LLM to
    produce a natural-language ARK AGENT reply when the model is online
  * Conversational input uses the LLM reply when the model is online
"""
import asyncio
import os

from fastapi.testclient import TestClient

from app.agent import agent_loop as al
from app.agent import local_inspector as li
from main import app


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class _OfflineGateway:
    default_model = "offline-test"

    async def available(self):
        return False

    async def chat(self, *args, **kwargs):
        raise AssertionError("chat must not be called when the model is down")


class _OnlineGateway:
    """Model online: native tool-calling — proposes the inspect tool on the
    first round, then synthesizes the final answer once the tool result is in
    context."""

    default_model = "online-test"

    async def available(self):
        return True

    async def chat(self, messages, *, json_mode=False, **kwargs):
        user = messages[-1]["content"]
        if "is NOT a tool directive" in user:
            return "Understood. I can inspect sandboxed directories and run OSINT lookups. Which target should I inspect?"
        return "ok"

    async def chat_tool_round(self, messages, *, tools=None, **kwargs):
        if any(m.get("role") == "tool" for m in messages):
            return {
                "content": (
                    "Fake synthesis: inspected the target and flagged 1 "
                    "high-entropy payload."
                ),
                "tool_calls": [],
            }
        return {
            "content": "",
            "tool_calls": [{
                "id": "call_inspect",
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


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #
def test_classify_intent_directive_requires_target():
    assert al._classify_intent("inspect case-001 and report status") == al._INTENT_DIRECTIVE
    assert al._classify_intent("scan evidence/case-001") == al._INTENT_DIRECTIVE
    assert al._classify_intent("examine payload.bin") == al._INTENT_DIRECTIVE
    assert al._classify_intent("inspect case-001", target_path="case-001") == al._INTENT_DIRECTIVE


def test_classify_intent_capability_asks_are_inquiries():
    assert al._classify_intent("first list all your capabilities") == al._INTENT_CONVERSATIONAL
    assert al._classify_intent("what can you do?") == al._INTENT_CONVERSATIONAL
    assert al._classify_intent("how can you assist me") == al._INTENT_CONVERSATIONAL
    assert al._classify_intent("tell me about yourself and your tools") == al._INTENT_CONVERSATIONAL


def test_classify_intent_vague_requests_are_not_directives():
    assert al._classify_intent("i wish to run an investigation") == al._INTENT_GUIDANCE
    assert al._classify_intent("scan the evidence folder") == al._INTENT_GUIDANCE
    assert al._classify_intent("this is a conversation") == al._INTENT_CONVERSATIONAL
    assert al._classify_intent("what is the status?") == al._INTENT_CONVERSATIONAL
    assert al._classify_intent("how do i use authorized testing?") == al._INTENT_CONVERSATIONAL
    assert al._classify_intent("hello") == al._INTENT_CONVERSATIONAL
    assert al._classify_intent("thanks") == al._INTENT_CONVERSATIONAL


# --------------------------------------------------------------------------- #
# Intent-gated execution
# --------------------------------------------------------------------------- #
def test_conversational_never_runs_tools_offline(monkeypatch, tmp_path):
    _make_sandbox(_patch_sandbox(monkeypatch, tmp_path))
    monkeypatch.setattr(al, "gateway", _OfflineGateway())
    result = asyncio.run(al.agent_loop.run(prompt="this is a conversation"))
    assert result["status"] == "done"
    assert result["tool_calls"] == []
    assert result["observations"] == []
    assert result["answer"] == al._GUIDANCE_REPLY


def test_guidance_never_runs_tools(monkeypatch, tmp_path):
    _make_sandbox(_patch_sandbox(monkeypatch, tmp_path))
    monkeypatch.setattr(al, "gateway", _OnlineGateway())
    result = asyncio.run(al.agent_loop.run(prompt="i wish to run an investigation"))
    assert result["status"] == "done"
    assert result["tool_calls"] == []
    assert result["observations"] == []
    assert result["answer"] == al._GUIDANCE_REPLY
    assert result["model_calls"] == 0


def test_conversational_uses_llm_reply_when_online(monkeypatch, tmp_path):
    _make_sandbox(_patch_sandbox(monkeypatch, tmp_path))
    monkeypatch.setattr(al, "gateway", _OnlineGateway())
    result = asyncio.run(al.agent_loop.run(prompt="this is a conversation"))
    assert result["status"] == "done"
    assert result["tool_calls"] == []
    assert "Understood" in result["answer"]
    assert result["model_calls"] == 1


def test_capability_ask_never_runs_tools(monkeypatch, tmp_path):
    _make_sandbox(_patch_sandbox(monkeypatch, tmp_path))
    monkeypatch.setattr(al, "gateway", _OnlineGateway())
    result = asyncio.run(
        al.agent_loop.run(prompt="first list all your capabilities")
    )
    assert result["status"] == "done"
    assert result["tool_calls"] == []
    assert result["observations"] == []
    assert result["model_calls"] == 1


def test_guidance_reply_enumerates_real_capabilities():
    from app.agent import capabilities as cap
    reply = cap.guidance_reply()
    assert "registered tool" in reply
    assert "Image Intelligence" in reply
    assert "Network" in reply
    assert "SecOps" in reply


def test_capability_inventory_includes_all_domains_and_platform():
    from app.agent import capabilities as cap
    text = cap.capability_inventory_text()
    assert "Image Intelligence" in text
    assert "Network" in text
    assert "SecOps" in text
    assert "OSINT / Intelligence" in text
    assert "Adaptive AI Investigation" in text
    assert "Case Vault" in text
    assert "inspect_local_path" in text
    assert "extract_exif" in text
    assert "reverse_geocode" in text


def test_capabilities_endpoint_returns_catalog():
    resp = TestClient(app).get("/api/v1/agent/capabilities")
    assert resp.status_code == 200
    body = resp.json()
    assert any(g["domain"] == "image" for g in body["tools"])
    assert any(g["domain"] == "osint" for g in body["tools"])
    assert body["platform"]


def test_directive_offline_falls_back_to_deterministic_answer(monkeypatch, tmp_path):
    _make_sandbox(_patch_sandbox(monkeypatch, tmp_path))
    monkeypatch.setattr(al, "gateway", _OfflineGateway())
    result = asyncio.run(
        al.agent_loop.run(prompt="inspect case-001", target_path="case-001")
    )
    assert result["tool_calls"][0]["tool_id"] == "inspect_local_path"
    assert result["observations"]
    assert "payload.bin" in result["answer"]


def test_directive_synthesizes_natural_language_reply_when_online(monkeypatch, tmp_path):
    _make_sandbox(_patch_sandbox(monkeypatch, tmp_path))
    monkeypatch.setattr(al, "gateway", _OnlineGateway())
    result = asyncio.run(
        al.agent_loop.run(prompt="inspect case-001", target_path="case-001")
    )
    assert result["tool_calls"][0]["tool_id"] == "inspect_local_path"
    assert result["tool_calls"][0]["status"] == "ran"
    assert "Fake synthesis" in result["answer"]
    assert result["model_calls"] == 3  # probe + tool turn + synthesis


# --------------------------------------------------------------------------- #
# HTTP endpoint
# --------------------------------------------------------------------------- #
def test_agent_task_endpoint_conversational_over_http(monkeypatch, tmp_path):
    _make_sandbox(_patch_sandbox(monkeypatch, tmp_path))
    monkeypatch.setattr(al, "gateway", _OfflineGateway())
    resp = TestClient(app).post(
        "/api/v1/agent/task",
        json={"prompt": "this is a conversation"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["tool_calls"] == []
    assert body["observations"] == []
    assert body["answer"] == al._GUIDANCE_REPLY
