"""Regression tests for explicit, per-request engagement scope isolation."""
from datetime import datetime, timedelta, timezone

from app.agent.engagement_scope import check


def _scope(engagement_id: str, address: str, port: int) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "engagement_id": engagement_id,
        "start": (now - timedelta(minutes=1)).isoformat(),
        "expiry": (now + timedelta(hours=1)).isoformat(),
        "approved_addresses": [address],
        "approved_ports": [port],
    }


def test_two_users_have_isolated_targets(monkeypatch):
    monkeypatch.setenv("ARKGEO_ENGAGEMENT_SCOPE", "/not/a/real/fixture.json")
    alice = _scope("alice-1", "192.0.2.10", 8080)
    bob = _scope("bob-1", "198.51.100.20", 443)
    call = {"host": "192.0.2.10", "port": 8080}
    assert check("net.nmap_scan", call, scope=alice, require_scope=True).allowed
    assert not check("net.nmap_scan", call, scope=bob, require_scope=True).allowed
    assert check("net.nmap_scan", {"host": "198.51.100.20", "port": 443},
                 scope=bob, require_scope=True).allowed


def test_missing_user_engagement_does_not_inherit_global_fixture(tmp_path, monkeypatch):
    fixture = tmp_path / "scope.json"
    fixture.write_text('{"engagement_id":"global","approved_addresses":["192.0.2.10"],'
                       '"approved_ports":[8080],"expiry":"2099-01-01T00:00:00Z"}')
    monkeypatch.setenv("ARKGEO_ENGAGEMENT_SCOPE", str(fixture))
    denied = check("net.nmap_scan", {"host": "192.0.2.10", "port": 8080},
                   require_scope=True)
    assert not denied.allowed
    assert denied.rule_id == "scope.missing"


def test_expired_engagement_denied():
    scope = _scope("expired", "192.0.2.10", 8080)
    scope["expiry"] = "2000-01-01T00:00:00Z"
    assert not check("net.nmap_scan", {"host": "192.0.2.10", "port": 8080},
                     scope=scope, require_scope=True).allowed


def test_ports_and_missing_required_fields_denied():
    scope = _scope("user-1", "192.0.2.10", 8080)
    assert not check("net.nmap_scan", {"host": "192.0.2.10", "port": 22},
                     scope=scope, require_scope=True).allowed
    assert not check("net.nmap_scan", {"host": "192.0.2.10", "port": 8080},
                     scope={"engagement_id": "user-1"}, require_scope=True).allowed


def test_non_target_advisory_operation_still_allowed_without_engagement():
    assert check("evidence.hash", {}, require_scope=True).allowed
