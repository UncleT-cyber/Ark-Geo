"""Operator-declared engagement — the execution authorization surface.

Covers the declaration store (owner isolation, validation, window, revocation),
its resolution into the scope guard (the operator's directive is the source of
truth), and the admin API that installs it as the active scope.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.agent import engagement_scope as es
from app.agent.engagement_store import EngagementStore
from app.core.security import create_access_token
from main import app


def _window(hours: int = 1) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return (now - timedelta(minutes=2)).isoformat(), (now + timedelta(hours=hours)).isoformat()


@pytest.fixture(autouse=True)
def _clean_operator_scope():
    """No operator engagement leaks between tests."""
    es.set_operator_engagement(None)
    yield
    es.set_operator_engagement(None)


@pytest.fixture()
def store(tmp_path):
    return EngagementStore(tmp_path / "engagements.sqlite")


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #
def test_declare_and_resolve(store):
    start, expiry = _window()
    scope = store.create(owner_id="operator", addresses=["10.0.0.5"],
                         ports=[443, 80], start=start, expiry=expiry, label="eng-1")
    assert scope["approved_addresses"] == ["10.0.0.5"]
    assert scope["approved_ports"] == [80, 443]
    assert scope["all_ports"] is False
    assert store.get_active(owner_id="operator")["engagement_id"] == scope["engagement_id"]


def test_all_ports_declaration(store):
    scope = store.create(owner_id="operator", addresses=["127.0.0.1"], all_ports=True)
    assert scope["all_ports"] is True
    assert scope["approved_ports"] == []


def test_owner_isolation(store):
    start, expiry = _window()
    eid = store.create(owner_id="alice", addresses=["10.0.0.5"], ports=[443],
                       start=start, expiry=expiry)["engagement_id"]
    assert store.get(owner_id="bob", engagement_id=eid) is None
    assert store.get(owner_id="alice", engagement_id=eid) is not None


def test_revoke_is_owner_scoped_and_immediate(store):
    start, expiry = _window()
    eid = store.create(owner_id="alice", addresses=["example.org"], ports=[443],
                       start=start, expiry=expiry)["engagement_id"]
    assert store.revoke(owner_id="bob", engagement_id=eid) is False
    assert store.get(owner_id="alice", engagement_id=eid) is not None
    assert store.revoke(owner_id="alice", engagement_id=eid) is True
    assert store.get(owner_id="alice", engagement_id=eid) is None


def test_expired_engagement_does_not_resolve(store):
    past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    eid = store.create(owner_id="alice", addresses=["example.org"], ports=[443],
                       start=past, expiry=yesterday)["engagement_id"]
    assert store.get(owner_id="alice", engagement_id=eid) is None
    assert store.get_active(owner_id="alice") is None


@pytest.mark.parametrize("bad", ["https://example.org/path", "10.0.0.1:443",
                                 "user:pass@example.org", "not a host", ""])
def test_invalid_targets_rejected(store, bad):
    with pytest.raises(ValueError):
        store.create(owner_id="operator", addresses=[bad], ports=[443])


def test_invalid_ports_rejected(store):
    with pytest.raises(ValueError):
        store.create(owner_id="operator", addresses=["example.org"], ports=[65536])
    with pytest.raises(ValueError):
        store.create(owner_id="operator", addresses=["example.org"], ports=None)
    with pytest.raises(ValueError):
        store.create(owner_id="operator", addresses=[], ports=[443])


def test_cidr_and_ip_normalization(store):
    scope = store.create(owner_id="operator",
                         addresses=["10.0.0.9/24", "Example.ORG."], ports=[443])
    assert "10.0.0.0/24" in scope["approved_addresses"]
    assert "example.org" in scope["approved_addresses"]


def test_ipv6_targets_accepted(store):
    scope = store.create(owner_id="operator",
                         addresses=["2001:db8::1", "2001:db8::/32"], ports=[443])
    assert "2001:db8::1" in scope["approved_addresses"]
    assert "2001:db8::/32" in scope["approved_addresses"]


# --------------------------------------------------------------------------- #
# Scope resolution — the operator directive is the source of truth
# --------------------------------------------------------------------------- #
def test_operator_engagement_authorizes_targets(store):
    scope = store.create(owner_id="operator", addresses=["127.0.0.1"], all_ports=True)
    es.set_operator_engagement(scope)
    assert es.check("net.nmap_scan", {"target": "127.0.0.1"}).allowed is True
    assert es.check("net.curl_probe", {"url": "http://127.0.0.1:8080/"}).allowed is True


def test_operator_engagement_still_refuses_out_of_scope(store):
    scope = store.create(owner_id="operator", addresses=["127.0.0.1"], all_ports=True)
    es.set_operator_engagement(scope)
    d = es.check("net.nmap_scan", {"target": "8.8.8.8"})
    assert d.allowed is False
    assert d.rule_id == "scope.address"


def test_declared_ports_enforced_without_all_ports(store):
    scope = store.create(owner_id="operator", addresses=["10.0.0.5"], ports=[443])
    es.set_operator_engagement(scope)
    assert es.check("net.curl_probe", {"url": "https://10.0.0.5/"}).allowed is True
    assert es.check("net.curl_probe", {"url": "https://10.0.0.5:8080/"}).allowed is False


def test_no_engagement_denies_targets_but_allows_non_target(store):
    assert es.check("net.nmap_scan", {"target": "127.0.0.1"}).allowed is False
    assert es.check("case.custody_hash", {"path": "/tmp/e.bin"}).allowed is True


def test_summary_discloses_operator_engagement(store):
    scope = store.create(owner_id="operator", addresses=["127.0.0.1"],
                         all_ports=True, label="my-eng")
    es.set_operator_engagement(scope)
    lines = es.summary_lines()
    assert any("my-eng" in ln for ln in lines)
    assert any("127.0.0.1" in ln for ln in lines)
    assert any("all ports" in ln for ln in lines)


# --------------------------------------------------------------------------- #
# Admin API
# --------------------------------------------------------------------------- #
@pytest.fixture()
def client(monkeypatch, tmp_path):
    import app.api.v1.endpoints.engagement as eng

    monkeypatch.setattr(eng, "_store", EngagementStore(tmp_path / "api.sqlite"))
    return TestClient(app)


def _admin_headers() -> dict:
    return {"Authorization": f"Bearer {create_access_token('admin', {'role': 'admin'})}"}


def test_declare_requires_admin(client):
    assert client.post("/api/v1/engagement",
                       json={"targets": ["127.0.0.1"], "all_ports": True}).status_code == 401


def test_declare_installs_active_scope(client):
    r = client.post("/api/v1/engagement",
                    json={"targets": ["127.0.0.1"], "all_ports": True, "label": "op"},
                    headers=_admin_headers())
    assert r.status_code == 200, r.text
    assert r.json()["engagement"]["targets"] == ["127.0.0.1"]
    # The declared engagement is now the in-force scope.
    assert es.get_operator_engagement() is not None
    assert es.check("net.nmap_scan", {"target": "127.0.0.1"}).allowed is True
    assert es.check("net.nmap_scan", {"target": "8.8.8.8"}).allowed is False


def test_get_engagement_reports_active(client):
    client.post("/api/v1/engagement",
                json={"targets": ["10.0.0.5"], "ports": [443]},
                headers=_admin_headers())
    r = client.get("/api/v1/engagement", headers=_admin_headers())
    assert r.status_code == 200
    assert r.json()["active"]["targets"] == ["10.0.0.5"]


def test_revoke_clears_active_scope(client):
    eid = client.post("/api/v1/engagement",
                      json={"targets": ["127.0.0.1"], "all_ports": True},
                      headers=_admin_headers()).json()["engagement"]["engagement_id"]
    assert es.get_operator_engagement() is not None
    r = client.post(f"/api/v1/engagement/{eid}/revoke", headers=_admin_headers())
    assert r.status_code == 200
    assert es.get_operator_engagement() is None
    assert es.check("net.nmap_scan", {"target": "127.0.0.1"}).allowed is False


def test_declare_rejects_invalid_target(client):
    r = client.post("/api/v1/engagement",
                    json={"targets": ["https://example.org/x"], "ports": [443]},
                    headers=_admin_headers())
    assert r.status_code == 422
