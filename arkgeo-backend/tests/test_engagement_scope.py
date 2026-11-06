"""Milestone A.2 — engagement-scope enforcement unit tests.

Covers the target-authorization layer: in-scope allow, out-of-scope deny,
port discipline, window (start/expiry) enforcement, fail-closed behaviour on
a broken fixture, and no-scope (normal operation) pass-through.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.agent import engagement_scope as es


@pytest.fixture()
def scope_file(tmp_path, monkeypatch):
    """Write a lab-like fixture and point the module at it."""
    data = {
        "engagement_id": "TEST-ENG",
        "start": "2026-01-01T00:00:00Z",
        "expiry": "2099-01-01T00:00:00Z",
        "approved_addresses": ["172.30.250.10", "172.30.250.11", "172.30.250.0/24"],
        "approved_ports": [8080, 8081, 22],
        "targets": [
            {"id": "lab-http", "kind": "http",
             "addresses": ["172.30.250.10"], "ports": [8080]},
            {"id": "lab-ssh", "kind": "ssh",
             "addresses": ["172.30.250.11"], "ports": [22]},
        ],
        "credentials": {
            "lab-primary": {"target": "lab-ssh", "username": "labuser",
                            "password": "test-only-pass"},
        },
    }
    p = tmp_path / "scope.json"
    p.write_text(json.dumps(data))
    monkeypatch.setenv(es.ENV_PATH, str(p))
    return p


# --------------------------------------------------------------------------- #
def test_no_fixture_allows_non_target_calls(tmp_path, monkeypatch):
    """No scope fixture: non-target calls are allowed, target-bearing calls
    are denied (fail-closed)."""
    monkeypatch.setenv(es.ENV_PATH, str(tmp_path / "absent.json"))
    # Non-target call (evidence hashing) — allowed without scope.
    d = es.check("case.custody_hash", {"path": "/tmp/evidence.bin"})
    assert d.allowed is True
    # Target-bearing call (HTTP probe) — denied without scope.
    d = es.check("net.curl_probe", {"url": "http://example.com/"})
    assert d.allowed is False
    assert d.rule_id == "scope.missing"
    assert "fail-closed" in d.reason


def test_in_scope_http_probe_allowed(scope_file):
    d = es.check("net.curl_probe",
                 {"url": "http://172.30.250.10:8080/health"})
    assert d.allowed is True


def test_out_of_scope_host_denied(scope_file):
    d = es.check("net.curl_probe", {"url": "http://example.com/"})
    assert d.allowed is False
    assert d.rule_id == "scope.address"


def test_loopback_denied_when_not_approved(scope_file):
    d = es.check("net.nmap_scan", {"target": "127.0.0.1", "ports": "8080"})
    assert d.allowed is False


def test_unapproved_port_denied(scope_file):
    d = es.check("net.nmap_scan", {"target": "172.30.250.10", "ports": "6379"})
    assert d.allowed is False
    assert d.rule_id == "scope.port"


def test_default_port_scan_denied(scope_file):
    """A scan tool without explicit ports must not inherit a blanket range."""
    d = es.check("net.nmap_scan", {"target": "172.30.250.10"})
    assert d.allowed is False
    assert d.rule_id == "scope.port_required"


def test_implicit_scheme_port_denied(scope_file):
    d = es.check("net.curl_probe", {"url": "http://172.30.250.10/health"})
    assert d.allowed is False
    assert d.rule_id == "scope.port"


def test_non_target_tool_allowed(scope_file):
    d = es.check("case.custody_hash", {"path": "/tmp/evidence.bin"})
    assert d.allowed is True


def test_ssh_requires_approved_host_and_port(scope_file):
    assert es.check("pentest.ssh_identity",
                    {"host": "172.30.250.11", "port": 22}).allowed is True
    assert es.check("pentest.ssh_identity",
                    {"host": "172.30.250.11", "port": 2222}).allowed is False
    assert es.check("pentest.ssh_identity",
                    {"host": "10.1.2.3", "port": 22}).allowed is False


def test_expired_scope_denies_target_calls(scope_file):
    data = json.loads(scope_file.read_text())
    data["expiry"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    scope_file.write_text(json.dumps(data))
    d = es.check("net.curl_probe", {"url": "http://172.30.250.10:8080/health"})
    assert d.allowed is False
    assert d.rule_id == "scope.window"
    # Non-target calls remain unaffected.
    assert es.check("case.custody_hash", {"path": "/tmp/x"}).allowed is True


def test_future_start_denies(scope_file):
    data = json.loads(scope_file.read_text())
    data["start"] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    scope_file.write_text(json.dumps(data))
    d = es.check("net.curl_probe", {"url": "http://172.30.250.10:8080/health"})
    assert d.allowed is False


def test_broken_fixture_fails_closed(scope_file):
    scope_file.write_text("{not json")
    d = es.check("net.curl_probe", {"url": "http://172.30.250.10:8080/health"})
    assert d.allowed is False
    assert d.rule_id == "scope.invalid"


def test_summary_lines_disclose_scope(scope_file):
    lines = es.summary_lines()
    assert any("TEST-ENG" in ln for ln in lines)
    assert any("172.30.250.10" in ln for ln in lines)


def test_credentials_reachable_server_side(scope_file):
    creds = es.credentials()
    assert "lab-primary" in creds
    assert creds["lab-primary"]["username"] == "labuser"
