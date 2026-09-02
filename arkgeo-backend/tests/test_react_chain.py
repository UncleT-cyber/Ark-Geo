"""Tests for the Level-4 RE-ACT chain (Plan → Scan → Exploit → Escalate → Mitigate).

All deterministic — no AI, no live network, no subprocess execution (dry_run
mode throughout; the read-only DFIR tools operate on tmp fixtures).
"""
import os

import pytest

from app.agent.react_chain import (
    EngagementKind,
    ReactRequest,
    ReactTarget,
    react_chain,
)


def _target(**kw) -> ReactTarget:
    return ReactTarget(**kw)


def _req(authorized: bool = True, mode: str = "dry_run", **target_kw) -> ReactRequest:
    return ReactRequest(
        operator="test-analyst",
        authorized=authorized,
        mode=mode,
        target=_target(**target_kw),
    )


# --------------------------------------------------------------------------- #
# Authorization gate
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_chain_refuses_without_authorization():
    s = await react_chain.run(_req(authorized=False, kind=EngagementKind.NETWORK,
                                   host="10.0.0.1"))
    assert s.status == "rejected"
    assert "authorization" in (s.rejection_reason or "").lower()
    assert s.activity == []


@pytest.mark.asyncio
async def test_chain_refuses_unresolvable_scope():
    s = await react_chain.run(_req(authorized=True, kind=EngagementKind.WEB))
    assert s.status == "rejected"
    assert "scope" in (s.rejection_reason or "").lower()


# --------------------------------------------------------------------------- #
# Network engagement
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_network_chain_runs_plan_scan_mitigate():
    s = await react_chain.run(_req(kind=EngagementKind.NETWORK,
                                   host="192.168.10.0/30"))
    assert s.status == "done"
    phases = {p["phase"]: p["tool_ids"] for p in s.phases}
    assert phases["scan"] == ["nmap_scan"]
    assert phases["exploit"] == []
    assert phases["escalate"] == []
    tools_run = {a.get("tool_id") for a in s.activity if a.get("status") == "ran"}
    assert "nmap_scan" in tools_run
    assert s.activity and s.activity[0]["phase"] == "plan"
    # Evidence + audit nodes were recorded on the graph.
    node_tools = {n.tool_id for n in s.graph.nodes.values()}
    assert "nmap_scan" in node_tools
    assert "react_chain" in node_tools  # authorization node


# --------------------------------------------------------------------------- #
# Web engagement — webshell detection + default-cred testing (dry-run)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_web_chain_detects_webshell_fixture(tmp_path):
    root = tmp_path / "webroot"
    root.mkdir()
    (root / "shell.php").write_text(
        '<?php if(isset($_POST["cmd"])){system($_POST["cmd"]);} ?>'
    )
    (root / "index.html").write_text("<html>ok</html>")

    s = await react_chain.run(_req(
        kind=EngagementKind.WEB,
        target_url="https://192.168.10.50:8443",
        web_root=str(root),
    ))
    assert s.status == "done"
    titles = [f["title"] for f in s.findings]
    assert "webshell indicators detected" in titles
    assert any(m["tool_id"] == "scan_webshells" for m in s.mitigation)
    # default_cred_tester ran in dry-run (authorized was passed through).
    assert any(a.get("tool_id") == "default_cred_tester"
               for a in s.activity)


@pytest.mark.asyncio
async def test_web_chain_without_web_root_skips_priv_esc():
    s = await react_chain.run(_req(
        kind=EngagementKind.WEB, target_url="https://192.168.10.60",
    ))
    assert s.status == "done"
    assert not any(a.get("tool_id") == "analyze_privilege_escalation"
                   for a in s.activity)


# --------------------------------------------------------------------------- #
# Offline hash engagement
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_offline_chain_runs_hash_crack_dry_run():
    s = await react_chain.run(_req(
        kind=EngagementKind.OFFLINE,
        hash_value="5f4dcc3b5aa765d61d8327deb882cf99",
        wordlist="/usr/share/wordlists/rockyou.txt",
    ))
    assert s.status == "done"
    assert any(a.get("tool_id") == "crack_hash"
               and a.get("status") == "ran" for a in s.activity)


@pytest.mark.asyncio
async def test_offline_without_wordlist_skips_crack():
    s = await react_chain.run(_req(
        kind=EngagementKind.OFFLINE,
        hash_value="5f4dcc3b5aa765d61d8327deb882cf99",
    ))
    assert s.status == "done"
    assert not any(a.get("tool_id") == "crack_hash" for a in s.activity)


# --------------------------------------------------------------------------- #
# OT engagement — safety-config drift detection
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_ot_chain_detects_safety_drift(tmp_path):
    observed = tmp_path / "safety_config.yaml"
    reference = tmp_path / "reference.yaml"
    observed.write_text("safety_config:\n  max_velocity: 3.0\n")
    reference.write_text("safety_config:\n  max_velocity: 0.8\n")

    s = await react_chain.run(_req(
        kind=EngagementKind.OT, ros2=True,
        safety_config_path=str(observed),
        reference_config_path=str(reference),
    ))
    assert s.status == "done"
    assert any(f["tool_id"] == "analyze_safety_config" for f in s.findings)
    assert any(a.get("tool_id") == "inspect_ros" for a in s.activity)


# --------------------------------------------------------------------------- #
# Budget + plan integrity
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_custom_budget_applied():
    s = await react_chain.run(_req(
        kind=EngagementKind.NETWORK, host="10.1.1.0/30",
        budget={"max_steps": 1},
    ))
    # The single nmap run already burns max_steps — subsequent phases are
    # denied honestly; the chain reports paused (not failed).
    assert s.status in ("paused", "done")
    assert s.guard_usage.get("steps", 0) >= 1


def test_planned_tools_cover_all_phases():
    chain = react_chain
    target = _target(kind=EngagementKind.WEB,
                     target_url="https://x.example", host="x.example",
                     web_root="/tmp/wr")
    assert set(chain._planned_tools(target)) == {
        "nmap_scan", "scan_webshells", "default_cred_tester",
        "analyze_privilege_escalation",
    }
    offline = _target(kind=EngagementKind.OFFLINE,
                      hash_value="abc", wordlist="/tmp/wl")
    assert chain._planned_tools(offline) == ["crack_hash"]


def test_scope_resolvability_matrix():
    chain = react_chain
    assert chain._scope_resolvable(_target(kind=EngagementKind.NETWORK, host="x"))
    assert not chain._scope_resolvable(_target(kind=EngagementKind.NETWORK))
    assert chain._scope_resolvable(_target(kind=EngagementKind.HOST))
    assert not chain._scope_resolvable(_target(kind=EngagementKind.OT))
    assert chain._scope_resolvable(_target(kind=EngagementKind.OT, ros2=True))
    assert chain._scope_resolvable(
        _target(kind=EngagementKind.OFFLINE, hash_value="x"))
