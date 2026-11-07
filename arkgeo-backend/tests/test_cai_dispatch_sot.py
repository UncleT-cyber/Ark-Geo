"""Regression tests: the unified engine dispatches every tool through the
single populated Unified Registry (``app.agent.unified_registry``).

The old three-tier fallback (and its ``_run_cai_tool`` helper, which imported an
always-empty CAI registry) is gone — ``orchestrator._dispatch_tool`` is now the
one execution entry point. These tests prove dispatch routes through the unified
registry and normalizes handler results/errors at that boundary.
"""
from __future__ import annotations

import pytest

from app.engine import orchestrator
from app.agent import unified_registry as ur


@pytest.mark.asyncio
async def test_dispatch_routes_through_unified_registry(monkeypatch):
    called = {}

    async def fake_acall(tool_id, **kwargs):
        called["tool_id"] = tool_id
        called["kwargs"] = kwargs
        return {"ok": True}

    monkeypatch.setattr(ur.unified_registry, "acall", fake_acall)

    res = await orchestrator._dispatch_tool("net.dns_lookup", {"host": "localhost"})

    assert called["tool_id"] == "net.dns_lookup"
    assert called["kwargs"] == {"host": "localhost"}
    assert res["status"] == "ok"
    assert res["tool"] == "net.dns_lookup"


@pytest.mark.asyncio
async def test_dispatch_unknown_tool_returns_error():
    res = await orchestrator._dispatch_tool("does.not.exist_xyz", {})
    assert res["status"] == "error"
    assert "unknown tool" in res.get("error", "")


@pytest.mark.asyncio
async def test_dispatch_preserves_tool_error_classification(monkeypatch):
    """A handler's own error code (auth_failed / timeout / ...) must survive
    normalization instead of collapsing to one opaque message."""

    async def fake_acall(tool_id, **kwargs):
        return {"status": "error", "code": "auth_failed", "error": "bad credentials"}

    monkeypatch.setattr(ur.unified_registry, "acall", fake_acall)

    res = await orchestrator._dispatch_tool("net.dns_lookup", {"host": "localhost"})
    assert res["status"] == "error"
    assert res["code"] == "auth_failed"
    assert res["error"] == "bad credentials"
