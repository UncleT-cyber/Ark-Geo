"""Operator browser transport — endpoint contract + egress-guard invariants.

The managed-browser runtime is the untrusted-content execution environment, so
these tests pin three things:

* the **operator-plane HTTP contract** (``/api/v1/browser/*``) — status, list,
  single-session fetch, operator control hand-off, close, and the 404/400 edges;
* the **egress guard** — private/loopback/metadata/non-http targets are refused,
  including via the per-context request interceptor (which increments
  ``blocked_requests`` and aborts the route);
* the **tool-surface contract** — the ``browser.*`` tools are registered with the
  risk levels the approval tier derives from.

Most of the suite is hermetic. The end-to-end lifecycle test drives a real
Chromium through the ASGI ``TestClient`` portal (the only event loop), and is
skipped when the runtime is unavailable.
"""
from __future__ import annotations

import functools

import pytest
from fastapi.testclient import TestClient

from main import app
from app.tools.web_intel import browser as rt
from app.tools.web_intel import guard

client = TestClient(app)


# --------------------------------------------------------------------------- #
# Availability + 404 edges (no browser launch required)
# --------------------------------------------------------------------------- #
def test_status_reports_runtime_and_sessions():
    resp = client.get("/api/v1/browser/status")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) >= {"available", "reason", "executable", "engine", "sessions"}
    assert isinstance(body["sessions"], list)
    assert body["engine"] == "playwright"


def test_list_sessions_shape():
    resp = client.get("/api/v1/browser/sessions")
    assert resp.status_code == 200
    assert isinstance(resp.json()["sessions"], list)


def test_unknown_session_is_404():
    assert client.get("/api/v1/browser/sessions/nope").status_code == 404
    assert client.post("/api/v1/browser/sessions/nope/close").status_code == 404
    assert client.get("/api/v1/browser/sessions/nope/frame").status_code == 404


def test_control_requires_valid_action_on_known_session():
    # Unknown session fails the existence check before action validation.
    resp = client.post("/api/v1/browser/sessions/nope/control", json={"action": "take"})
    assert resp.status_code == 404


def test_history_unknown_session_is_404():
    resp = client.post("/api/v1/browser/sessions/nope/history", json={"action": "back"})
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Tool wrappers classify runtime errors instead of raising
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_navigate_unknown_session_is_classified_error():
    from app.tools.web_intel import tools as W

    res = await W.browser_navigate("does-not-exist", "https://example.com")
    assert res["state"] == "ERROR"
    assert res["ok"] is False
    assert res["code"] == "session_not_found"


@pytest.mark.asyncio
async def test_close_unknown_session_is_classified_error():
    from app.tools.web_intel import tools as W

    res = await W.browser_close("does-not-exist")
    assert res["state"] == "ERROR"
    assert res["code"] == "session_not_found"


# --------------------------------------------------------------------------- #
# Egress guard — address/scheme policy (hermetic; literal IPs, no DNS)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",   # AWS/GCP/Azure IMDS
    "http://100.100.100.200/",                    # Alibaba IMDS
    "http://metadata.google.internal/",           # GCP metadata host
    "http://127.0.0.1:12000/api/v1/health",       # loopback
    "http://10.0.0.5/",                           # private
    "http://192.168.1.1/",                        # private
    "file:///etc/passwd",                         # scheme
    "ftp://example.com/",                         # scheme
])
def test_guard_blocks_unsafe_targets(url, monkeypatch):
    monkeypatch.delenv("ARK_WEB_ALLOW_INTERNAL", raising=False)
    with pytest.raises(guard.SSRFBlocked):
        guard.check_url(url, allow_internal_targets=False)


def test_guard_blocks_metadata_even_with_internal_override():
    """Cloud metadata is refused regardless of the internal-target override."""
    with pytest.raises(guard.SSRFBlocked):
        guard.check_url("http://169.254.169.254/", allow_internal_targets=True)


def test_guard_allows_public_literal_ip():
    decision = guard.check_url("http://8.8.8.8/", allow_internal_targets=False)
    assert decision.resolved_ip == "8.8.8.8"
    assert guard.is_public_url("http://8.8.8.8/")


def test_pinned_url_swaps_fqdn_for_validated_ip():
    d = guard.EgressDecision(url="https://example.com/a?b=1", resolved_ip="93.184.216.34",
                             host_header="example.com", host="example.com")
    assert guard.pinned_url(d) == "https://93.184.216.34/a?b=1"


# --------------------------------------------------------------------------- #
# Route interceptor — aborts + counts blocked requests
# --------------------------------------------------------------------------- #
class _FakeRequest:
    def __init__(self, url: str):
        self.url = url


class _FakeRoute:
    def __init__(self):
        self.aborted = None
        self.continued = False

    async def abort(self, reason):  # noqa: D102
        self.aborted = reason

    async def continue_(self):  # noqa: D102
        self.continued = True


class _FakeSession:
    def __init__(self):
        self.blocked_requests = 0


class _FakeManager:
    def __init__(self, session):
        self._sessions = {"bws_test": session}


@pytest.mark.asyncio
async def test_route_handler_aborts_and_counts_blocked_request():
    session = _FakeSession()
    handler = rt._make_route_handler("bws_test", _FakeManager(session))
    route = _FakeRoute()

    await handler(route, _FakeRequest("http://169.254.169.254/latest/meta-data/"))

    assert route.aborted == "blockedbyclient"
    assert route.continued is False
    assert session.blocked_requests == 1


@pytest.mark.asyncio
async def test_route_handler_continues_public_request():
    session = _FakeSession()
    handler = rt._make_route_handler("bws_test", _FakeManager(session))
    route = _FakeRoute()

    await handler(route, _FakeRequest("http://8.8.8.8/"))

    assert route.continued is True
    assert route.aborted is None
    assert session.blocked_requests == 0


# --------------------------------------------------------------------------- #
# Registered tool surface (risk levels drive the approval tier)
# --------------------------------------------------------------------------- #
def test_browser_tools_registered_with_expected_risk():
    from app.agent.unified_registry import unified_registry

    unified_registry.populate()
    risks = {t.tool_id: t.risk for t in unified_registry.list()
             if t.tool_id.startswith("browser.")}
    assert risks == {
        "browser.open": "medium",
        "browser.navigate": "medium",
        "browser.snapshot": "low",
        "browser.extract": "low",
        "browser.screenshot": "low",
        "browser.click": "medium",
        "browser.type": "high",
        "browser.scroll": "medium",
        "browser.history": "medium",
        "browser.tabs": "medium",
        "browser.close": "medium",
    }


# --------------------------------------------------------------------------- #
# End-to-end operator lifecycle (real Chromium, single portal event loop)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not rt.availability()["available"],
                    reason="managed browser runtime unavailable")
def test_operator_session_lifecycle_end_to_end():
    with TestClient(app) as c:
        assert c.portal is not None
        session = c.portal.call(functools.partial(
            rt.browser_manager.open, investigation_id="inv-e2e", case_id="case-e2e"))
        sid = session.session_id
        try:
            # Reflected on the operator plane.
            listed = c.get("/api/v1/browser/sessions").json()["sessions"]
            assert sid in {s["session_id"] for s in listed}

            one = c.get(f"/api/v1/browser/sessions/{sid}")
            assert one.status_code == 200
            assert one.json()["investigation_id"] == "inv-e2e"
            assert one.json()["case_id"] == "case-e2e"

            # Operator control hand-off.
            taken = c.post(f"/api/v1/browser/sessions/{sid}/control",
                           json={"action": "take"})
            assert taken.status_code == 200 and taken.json()["control"] == "operator"
            returned = c.post(f"/api/v1/browser/sessions/{sid}/control",
                              json={"action": "return"})
            assert returned.status_code == 200 and returned.json()["control"] == "agent"

            # Invalid action is rejected once the session exists.
            bad = c.post(f"/api/v1/browser/sessions/{sid}/control",
                         json={"action": "sideways"})
            assert bad.status_code == 400

            # No frame until one is captured.
            assert c.get(f"/api/v1/browser/sessions/{sid}/frame").status_code == 404

            captured = c.get(f"/api/v1/browser/sessions/{sid}/capture")
            assert captured.status_code == 200
            assert captured.headers["content-type"] == "image/png"
            assert captured.content[:8] == b"\x89PNG\r\n\x1a\n"

            frame = c.get(f"/api/v1/browser/sessions/{sid}/frame")
            assert frame.status_code == 200
            assert frame.headers["content-type"] == "image/png"

            # Operator navigation and history work on the real session — and
            # keep working while the operator holds control (the operator plane
            # is not gated by the agent-plane suspension).
            c.post(f"/api/v1/browser/sessions/{sid}/control", json={"action": "take"})
            nav = c.post(f"/api/v1/browser/sessions/{sid}/navigate",
                         json={"url": "https://example.com/"})
            assert nav.status_code == 200, nav.text
            hist = c.post(f"/api/v1/browser/sessions/{sid}/history",
                          json={"action": "reload"})
            assert hist.status_code == 200, hist.text
            assert hist.json()["url"].startswith("https://example.com")
            # An unsupported history action is rejected.
            bad_hist = c.post(f"/api/v1/browser/sessions/{sid}/history",
                              json={"action": "sideways"})
            assert bad_hist.status_code == 400
            c.post(f"/api/v1/browser/sessions/{sid}/control", json={"action": "return"})

            # Close removes it from the operator plane.
            closed = c.post(f"/api/v1/browser/sessions/{sid}/close")
            assert closed.status_code == 200 and closed.json()["closed"] is True
            assert c.get(f"/api/v1/browser/sessions/{sid}").status_code == 404

            # The operator plane can also *start* a session directly.
            opened = c.post("/api/v1/browser/sessions",
                            json={"url": "https://example.com/", "investigation_id": "op-open",
                                  "case_id": "case-op"})
            assert opened.status_code == 200, opened.text
            opened_sid = opened.json()["session_id"]
            assert opened_sid.startswith("bws_")
            reopened = c.get(f"/api/v1/browser/sessions/{opened_sid}").json()
            assert reopened["investigation_id"] == "op-open"
            assert reopened["case_id"] == "case-op"
            assert c.post(f"/api/v1/browser/sessions/{opened_sid}/close").json()["closed"] is True
        finally:
            c.portal.call(rt.browser_manager.close_all)
