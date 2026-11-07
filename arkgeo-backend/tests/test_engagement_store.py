"""Owner isolation and revocation tests for server-side engagement registry."""
from datetime import datetime, timedelta, timezone

import pytest

from app.agent.engagement_scope import check
from app.agent.engagement_store import EngagementStore


def _window():
    now = datetime.now(timezone.utc)
    return ((now - timedelta(minutes=2)).isoformat(),
            (now + timedelta(hours=1)).isoformat())


def test_owner_isolation_and_scope_check(tmp_path):
    store = EngagementStore(tmp_path / "engagements.sqlite")
    start, expiry = _window()
    alice_id = store.create(owner_id="alice", start=start, expiry=expiry,
                            addresses=["192.0.2.5"], ports=[8443])
    assert store.resolve(owner_id="bob", engagement_id=alice_id) is None
    scope = store.resolve(owner_id="alice", engagement_id=alice_id)
    assert scope is not None
    assert check("net.nmap_scan", {"host": "192.0.2.5", "port": 8443},
                 scope=scope, require_scope=True).allowed
    assert not check("net.nmap_scan", {"host": "192.0.2.5", "port": 22},
                     scope=scope, require_scope=True).allowed


def test_revoke_is_owner_scoped_and_immediate(tmp_path):
    store = EngagementStore(tmp_path / "engagements.sqlite")
    start, expiry = _window()
    eid = store.create(owner_id="alice", start=start, expiry=expiry,
                       addresses=["example.org"], ports=[443])
    assert not store.revoke(owner_id="bob", engagement_id=eid)
    assert store.resolve(owner_id="alice", engagement_id=eid)
    assert store.revoke(owner_id="alice", engagement_id=eid)
    assert store.resolve(owner_id="alice", engagement_id=eid) is None


def test_invalid_targets_and_expired_engagements(tmp_path):
    store = EngagementStore(tmp_path / "engagements.sqlite")
    start, expiry = _window()
    with pytest.raises(ValueError):
        store.create(owner_id="alice", start=start, expiry=expiry,
                     addresses=["https://example.org/path"], ports=[443])
    with pytest.raises(ValueError):
        store.create(owner_id="alice", start=start, expiry=expiry,
                     addresses=["example.org"], ports=[65536])
    past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    eid = store.create(owner_id="alice", start=past, expiry=yesterday,
                       addresses=["example.org"], ports=[443])
    assert store.resolve(owner_id="alice", engagement_id=eid) is None
