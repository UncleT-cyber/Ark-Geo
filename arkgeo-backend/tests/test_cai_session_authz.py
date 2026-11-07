"""Authorization boundary for the durable investigation-session API.

Regression coverage for the "Scenario F" gap: ``GET /cai/sessions/{id}`` and
``DELETE /cai/sessions/{id}`` used to return or destroy any session for any
caller. They now resolve the request principal and refuse a session owned by a
different principal, reporting it exactly like an unknown session.

These tests exercise the real route handlers through the ASGI app so the
principal resolution path (the ``X-ARK-Principal`` header) is what is being
verified, not a hand-rolled predicate.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from main import app
from app.services import session_store as session_store_module


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def seeded():
    """Seed two principals' sessions plus an anonymous one in the real store."""
    store = session_store_module.session_store
    store.upsert_session("sess-alice", principal_subject="alice", case_id="CASE-A")
    store.upsert_session("sess-bob", principal_subject="bob", case_id="CASE-B")
    store.upsert_session("sess-anon")
    # The orchestrator records the resolved anonymous subject literally.
    store.upsert_session("sess-anon-lit", principal_subject="anonymous")
    yield store
    for sid in ("sess-alice", "sess-bob", "sess-anon", "sess-anon-lit"):
        store.delete_session(sid)


def test_owner_can_read_own_session(client, seeded):
    r = client.get("/api/v1/cai/sessions/sess-alice", headers={"X-ARK-Principal": "alice"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["session"]["case_id"] == "CASE-A"


def test_other_principal_cannot_read_session(client, seeded):
    r = client.get("/api/v1/cai/sessions/sess-alice", headers={"X-ARK-Principal": "bob"})
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert r.json()["error"] == "unknown session"


def test_anonymous_cannot_read_owned_session(client, seeded):
    r = client.get("/api/v1/cai/sessions/sess-alice")
    assert r.json()["ok"] is False


def test_list_is_scoped_to_caller(client, seeded):
    # Alice sees only her own session — not bob's, not the anonymous ones.
    r = client.get("/api/v1/cai/sessions", headers={"X-ARK-Principal": "alice"})
    ids = {s["session_id"] for s in r.json()["sessions"]}
    assert ids == {"sess-alice"}


def test_list_anonymous_sees_anonymous_and_unowned(client, seeded):
    r = client.get("/api/v1/cai/sessions")
    ids = {s["session_id"] for s in r.json()["sessions"]}
    assert "sess-anon" in ids and "sess-anon-lit" in ids
    assert "sess-alice" not in ids and "sess-bob" not in ids


def test_anonymous_cannot_read_named_principal_session(client, seeded):
    r = client.get("/api/v1/cai/sessions/sess-alice")
    assert r.json()["ok"] is False


def test_anonymous_cannot_delete_named_principal_session(client, seeded):
    r = client.delete("/api/v1/cai/sessions/sess-alice")
    assert r.json()["ok"] is False
    assert seeded.get_session_meta("sess-alice") is not None


def test_anonymous_can_read_anonymous_session(client, seeded):
    r = client.get("/api/v1/cai/sessions/sess-anon")
    assert r.json()["ok"] is True


def test_anonymous_can_read_literally_owned_anonymous_session(client, seeded):
    # Regression: ANONYMOUS.subject is the string "anonymous", which the
    # orchestrator stores as the owner — the check must still match it.
    r = client.get("/api/v1/cai/sessions/sess-anon-lit")
    assert r.json()["ok"] is True


def test_principal_cannot_read_anonymous_session(client, seeded):
    r = client.get("/api/v1/cai/sessions/sess-anon", headers={"X-ARK-Principal": "alice"})
    assert r.json()["ok"] is False


def test_other_principal_cannot_delete_session(client, seeded):
    r = client.delete("/api/v1/cai/sessions/sess-alice", headers={"X-ARK-Principal": "bob"})
    assert r.json()["ok"] is False
    # Still present for its owner.
    assert seeded.get_session_meta("sess-alice") is not None


def test_owner_can_delete_own_session(client, seeded):
    r = client.delete("/api/v1/cai/sessions/sess-bob", headers={"X-ARK-Principal": "bob"})
    assert r.json()["ok"] is True
    assert seeded.get_session_meta("sess-bob") is None


def test_list_is_scoped_to_principal(client, seeded):
    r = client.get("/api/v1/cai/sessions", headers={"X-ARK-Principal": "alice"})
    ids = {s["session_id"] for s in r.json()["sessions"]}
    assert "sess-alice" in ids
    assert "sess-bob" not in ids
