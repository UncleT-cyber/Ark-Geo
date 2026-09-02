"""Regression test: the unified engine must dispatch CAI-native tools from the
single, populated CAI registry (cai.tool_registry.TOOL_REGISTRY), not the ARK-local
empty copy. Previously _run_cai_tool imported app.engine.cai.cai.tool_registry
(an always-empty registry) so every CAI tool the model was offered failed with
'not registered'. This test proves dispatch reaches the real tool object.
"""
from __future__ import annotations

import pytest

from app.engine import orchestrator


@pytest.mark.asyncio
async def test_run_cai_tool_uses_populated_registry(monkeypatch):
    import cai.tool_registry as ctr

    class FakeTool:
        name = "execute_cli_command"

        async def on_invoke_tool(self, ctx, args):
            raise RuntimeError("REACHED_REAL_TOOL")

    def _fake_get(name):
        if name == "execute_cli_command":
            return FakeTool()
        raise Exception("unexpected tool requested: " + name)

    monkeypatch.setattr(ctr.TOOL_REGISTRY, "get", _fake_get)

    res = await orchestrator._run_cai_tool(
        "execute_cli_command", {"command": "echo hi"}
    )
    # If dispatch had used the empty registry it would return
    # status=error with "unknown tool: execute_cli_command".
    assert res["status"] == "error"
    assert "REACHED_REAL_TOOL" in res["error"]
    assert "unknown tool" not in res.get("error", "")


@pytest.mark.asyncio
async def test_run_cai_tool_unknown_returns_error(monkeypatch):
    import cai.tool_registry as ctr

    def _fake_get(name):
        raise Exception("not registered: " + name)

    monkeypatch.setattr(ctr.TOOL_REGISTRY, "get", _fake_get)
    res = await orchestrator._run_cai_tool("does_not_exist_xyz", {})
    assert res["status"] == "error"
    assert "unknown tool" in res.get("error", "")
