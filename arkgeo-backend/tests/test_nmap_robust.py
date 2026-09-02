"""Tests for robust nmap execution (timeout capture + auto-degrade)."""
from __future__ import annotations

import pytest

import app.tools.pen_test.nmap_scanner_tool as nm
from unittest.mock import patch

SAMPLE_XML = (
    '<?xml version="1.0"?><nmaprun>'
    '<host><status state="up"/>'
    '<address addr="102.88.18.159" addrtype="ipv4"/>'
    '<ports><port portid="22" protocol="tcp"><state state="open"/>'
    '<service name="ssh" product="OpenSSH" version="8.0"/></port>'
    '<port portid="443" protocol="tcp"><state state="open"/>'
    '<service name="https"/></port></ports></host></nmaprun>'
)


def test_parse_nmap_xml():
    hosts = nm._parse_nmap_xml(SAMPLE_XML)
    assert len(hosts) == 1
    assert hosts[0]["ip"] == "102.88.18.159"
    assert {p["port"] for p in hosts[0]["ports"]} == {"22", "443"}
    assert hosts[0]["ports"][0]["product"] == "OpenSSH"


def test_parse_nmap_xml_empty_on_garbage():
    assert nm._parse_nmap_xml("not xml at all") == []


@pytest.mark.asyncio
async def test_autodegrade_on_timeout(monkeypatch):
    """Primary scan times out (partial XML), fast fallback succeeds -> degraded AVAILABLE."""
    state = {"calls": 0}

    async def fake_run(argv, timeout):
        state["calls"] += 1
        if state["calls"] == 1:
            return None, SAMPLE_XML, ""
        return 0, SAMPLE_XML, ""

    monkeypatch.setattr(nm, "_run_nmap", fake_run)
    monkeypatch.setattr(nm.shutil, "which", lambda _x: "/usr/bin/nmap")

    res = await nm.nmap_scan(host="102.88.18.159")
    assert res["state"] == "AVAILABLE"
    assert res.get("degraded") is True
    assert res["total_open_ports"] == 2
    assert state["calls"] == 2


@pytest.mark.asyncio
async def test_timeout_with_no_results_is_reported(monkeypatch):
    """Both primary and fallback time out with no XML -> structured TIMEOUT, not a crash."""
    async def fake_run(argv, timeout):
        return None, "", ""

    monkeypatch.setattr(nm, "_run_nmap", fake_run)
    monkeypatch.setattr(nm.shutil, "which", lambda _x: "/usr/bin/nmap")

    res = await nm.nmap_scan(host="102.88.18.159")
    assert res["state"] == "TIMEOUT"
    assert "top-100" in res["detail"]


@pytest.mark.asyncio
async def test_net_nmap_scan_delegates_to_robust(monkeypatch):
    """The ARK net.nmap_scan tool returns structured (parsed) JSON, not raw stdout."""
    async def fake_run(argv, timeout):
        return 0, SAMPLE_XML, ""

    monkeypatch.setattr(nm, "_run_nmap", fake_run)
    monkeypatch.setattr(nm.shutil, "which", lambda _x: "/usr/bin/nmap")

    from app.engine import tool_adapter as ta
    out = ta._net_nmap_scan("102.88.18.159")
    assert '"state": "AVAILABLE"' in out or '"state":"AVAILABLE"' in out
    assert "102.88.18.159" in out
    assert "total_open_ports" in out
