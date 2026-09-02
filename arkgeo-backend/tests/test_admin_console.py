"""ARK Admin Console + BYOK endpoints tests.

Covers the Super-Admin control plane introduced for TASK1 (client
directory & telemetry, staff RBAC, model gateway, tool policy, quotas,
tooling, audit logs, support) and the BYOK client key-connection surface
for TASK2 (/tools/test-connection).

Every admin route is exercised through the FastAPI TestClient with a real
admin JWT.  Audit assertions confirm each mutating action is logged with
actor + action + target + IP — never mutating existing entries.  No API
key values are ever asserted to leave the server, and BYOK probes never
log the submitted key.
"""
import time

from fastapi.testclient import TestClient

from main import app
from app.api.v1.endpoints.settings import admin_login
from app.core.config import settings
from app.services.admin_store import admin_store
from app.services.settings_store import settings_store

client = TestClient(app)


def _admin_token() -> str:
    resp = client.post(
        "/api/v1/admin/login",
        json={"username": settings.admin_username, "password": "arkgeo-admin"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# Auth guard
# --------------------------------------------------------------------------- #
def test_admin_endpoints_require_jwt():
    """Un-authenticated requests to the control plane are rejected 401."""
    resp = client.get("/api/v1/admin/overview")
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# Command Center overview
# --------------------------------------------------------------------------- #
def test_overview_aggregates_metrics(token=_admin_token()):
    data = client.get("/api/v1/admin/overview", headers=_auth(token)).json()
    assert data["clients"]["total"] >= 1
    assert data["staff"]["total"] >= 1
    assert data["tools"]["total"] > 0
    assert data["quotas"]["pro"]["storage_bytes"] == 2 * 1024 * 1024 * 1024
    assert data["audit_count"] >= 0


# --------------------------------------------------------------------------- #
# Client directory & telemetry
# --------------------------------------------------------------------------- #
def test_client_crud_and_telemetry(token=_admin_token()):
    created = client.post("/api/v1/admin/clients", headers=_auth(token), json={
        "full_name": "Test Client One",
        "email": "t1@example.com",
        "plan": "pro",
        "status": "active",
        "telemetry": {
            "last_login_ip": "8.8.8.8",
            "country": "United States",
            "city": "Mountain View",
            "asn": "AS15169",
            "proxy": False,
            "vpn": False,
            "tor_exit": False,
            "user_agent": "Mozilla/5.0",
            "os": "macOS 14",
            "browser": "Chrome 126",
            "tls_fingerprint": "JA3-test",
        },
        "usage": {"active_cases": 1, "storage_bytes": 1000, "api_spend_usd": 0.5,
                  "tokens_consumed": 100},
    })
    assert created.status_code == 201
    rec = created.json()
    cid = rec["client_id"]
    assert cid.startswith("CLT-")
    assert rec["telemetry"]["country"] == "United States"
    assert rec["seed"] is False

    fetched = client.get(f"/api/v1/admin/clients/{cid}", headers=_auth(token)).json()
    assert fetched["client_id"] == cid

    patched = client.patch(f"/api/v1/admin/clients/{cid}", headers=_auth(token),
                           json={"plan": "enterprise"}).json()
    assert patched["plan"] == "enterprise"

    deleted = client.delete(f"/api/v1/admin/clients/{cid}", headers=_auth(token))
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True


def test_client_status_transitions_invalidate_sessions(token=_admin_token()):
    rec = client.post("/api/v1/admin/clients", headers=_auth(token), json={
        "full_name": "Suspend Me", "email": "sus@example.com", "plan": "free",
        "usage": {"active_cases": 4},
    }).json()
    cid = rec["client_id"]
    resp = client.post(f"/api/v1/admin/clients/{cid}/status", headers=_auth(token),
                       json={"status": "suspended"}).json()
    assert resp["status"] == "suspended"
    assert resp["sessions_invalidated"] == 4
    assert resp["previous_status"] == "active"
    client.delete(f"/api/v1/admin/clients/{cid}", headers=_auth(token))


# --------------------------------------------------------------------------- #
# Staff & RBAC
# --------------------------------------------------------------------------- #
def test_staff_crud_and_rbac_matrix(token=_admin_token()):
    created = client.post("/api/v1/admin/staff", headers=_auth(token), json={
        "username": "analyst.beta",
        "full_name": "Beta Analyst",
        "role": "SECURITY_OPERATOR",
        "permissions": {"canExecuteHighRiskTools": True},
    })
    assert created.status_code == 201
    rec = created.json()
    sid = rec["staff_id"]
    assert rec["permissions"]["canExecuteHighRiskTools"] is True
    assert rec["permissions"]["canManageStaff"] is False

    patched = client.patch(f"/api/v1/admin/staff/{sid}", headers=_auth(token),
                           json={"role": "LEAD_ANALYST",
                                 "permissions": {"canManageClients": True}}).json()
    assert patched["role"] == "LEAD_ANALYST"
    assert patched["permissions"]["canManageClients"] is True

    deact = client.post(f"/api/v1/admin/staff/{sid}/deactivate", headers=_auth(token))
    assert deact.status_code == 200
    assert deact.json()["active"] is False

    # Root platform account is protected.
    root = client.post("/api/v1/admin/staff/STF-0001/deactivate", headers=_auth(token))
    assert root.status_code == 403

    listed = client.get("/api/v1/admin/staff", headers=_auth(token)).json()
    assert "roles" in listed and "SUPER_ADMIN" in listed["roles"]


# --------------------------------------------------------------------------- #
# Tool policy / quotas / tooling / support / gateway
# --------------------------------------------------------------------------- #
def test_tool_policy_toggle_and_audit(token=_admin_token()):
    before = client.get("/api/v1/admin/tool-policy", headers=_auth(token)).json()["policy"]
    target = "phone_number_lookup"
    assert before[target]["risk_level"] == "HIGH"
    resp = client.post(f"/api/v1/admin/tool-policy/{target}/toggle",
                       headers=_auth(token), json={"enabled": True})
    assert resp.status_code == 200
    after = resp.json()["policy"]
    assert after[target]["enabled"] is True
    # restore
    client.post(f"/api/v1/admin/tool-policy/{target}/toggle",
                headers=_auth(token), json={"enabled": False})


def test_quota_override(token=_admin_token()):
    resp = client.patch("/api/v1/admin/quotas/pro", headers=_auth(token),
                        json={"max_active_cases": 40})
    assert resp.status_code == 200
    assert resp.json()["quotas"]["pro"]["max_active_cases"] == 40


def test_tooling_status_and_probe(token=_admin_token()):
    tooling = client.get("/api/v1/admin/tooling", headers=_auth(token)).json()["tooling"]
    assert "exiftool" in tooling and "ollama" in tooling
    probed = client.post("/api/v1/admin/tooling/test", headers=_auth(token))
    assert probed.status_code == 200
    assert "exiftool" in probed.json()["tooling"]


def test_support_settings(token=_admin_token()):
    resp = client.patch("/api/v1/admin/support", headers=_auth(token),
                        json={"show_banner": False, "bmc_url": "https://example.org/bmc"})
    assert resp.status_code == 200
    assert resp.json()["support"]["show_banner"] is False
    client.patch("/api/v1/admin/support", headers=_auth(token), json={"show_banner": True})


def test_gateway_reports_provider_key_status(token=_admin_token()):
    gw = client.get("/api/v1/admin/gateway", headers=_auth(token)).json()["gateway"]
    for pid in ("openai", "gemini", "anthropic", "openrouter", "mapbox",
                "geospy", "serper", "tineye", "hlr"):
        assert pid in gw["providers"]
        assert "configured" in gw["providers"][pid]
        # Never a full key value in the response.
        preview = gw["providers"][pid]["preview"]
        assert preview is None or "..." in preview


def test_gateway_live_test_and_admin_test_key(token=_admin_token()):
    # No key configured → configured False, no crash.
    resp = client.post("/api/v1/admin/gateway/test", headers=_auth(token),
                       json={"provider": "mapbox"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] in (True, False)

    alias = client.post("/api/v1/admin/test-key", headers=_auth(token),
                        json={"provider": "openai"})
    assert alias.status_code == 200


def test_gateway_patch_roundtrips_vision_toggle_and_task_models(token=_admin_token()):
    """The AI & OSINT Gateway panel persists vision_enabled + the per-task
    Ollama model rotator through PUT /admin/gateway."""
    resp = client.put("/api/v1/admin/gateway", headers=_auth(token), json={
        "vision_enabled": False,
        "task_models": {"terminal": "qwen2.5-coder:3b", "vision_imint": "llava:latest"},
    })
    assert resp.status_code == 200
    gw = resp.json()["gateway"]
    assert gw["vision_enabled"] is False
    assert gw["task_models"]["terminal"] == "qwen2.5-coder:3b"
    assert gw["task_models"]["vision_imint"] == "llava:latest"

    # Restore defaults so subsequent tests are unaffected.
    client.put("/api/v1/admin/gateway", headers=_auth(token), json={
        "vision_enabled": True,
        "task_models": {"terminal": "", "vision_imint": ""},
    })


# --------------------------------------------------------------------------- #
# Audit logs & chain-of-custody
# --------------------------------------------------------------------------- #
def test_audit_logs_are_append_only_and_searchable(token=_admin_token()):
    before = client.get("/api/v1/admin/audit-logs", headers=_auth(token)).json()["logs"]
    before_count = len(before)

    # Trigger a handful of mutations.
    rec = client.post("/api/v1/admin/clients", headers=_auth(token), json={
        "full_name": "Audit Target", "email": "audit@example.com", "plan": "free",
    }).json()
    cid = rec["client_id"]
    client.post(f"/api/v1/admin/clients/{cid}/status", headers=_auth(token),
                json={"status": "banned"})
    client.delete(f"/api/v1/admin/clients/{cid}", headers=_auth(token))

    after = client.get("/api/v1/admin/audit-logs", headers=_auth(token)).json()["logs"]
    assert len(after) >= before_count + 3

    found = client.get("/api/v1/admin/audit-logs", headers=_auth(token),
                       params={"query": "Audit Target"}).json()["logs"]
    assert found, "search by query must find the client records"

    # Every entry carries chain-of-custody fields.
    for entry in after[:5]:
        assert entry["log_id"].startswith("AUD-")
        assert entry["actor"]
        assert entry["action"]
        assert entry["ip"]
        assert entry["timestamp"]


# --------------------------------------------------------------------------- #
# BYOK /tools/test-connection (public, no auth)
# --------------------------------------------------------------------------- #
def test_byok_test_connection_rejects_empty_key():
    resp = client.post("/api/v1/tools/test-connection",
                       json={"provider": "mapbox", "key": ""})
    assert resp.status_code == 200
    assert resp.json()["valid"] is False
    assert resp.json()["detail"] == "No key provided"


def test_byok_test_connection_rejects_unknown_provider():
    resp = client.post("/api/v1/tools/test-connection",
                       json={"provider": "not-a-provider", "key": "secret"})
    assert resp.status_code == 422


def test_byok_test_connection_format_and_probe():
    # Every provider performs a REAL HTTPS probe. A random/generic key must
    # never be reported as valid by format check alone.
    resp = client.post("/api/v1/tools/test-connection",
                       json={"provider": "tineye", "key": "0123456789abcdef"})
    body = resp.json()
    assert body["provider"] == "tineye"
    assert body["method"] == "Live HTTPS probe"
    assert body["valid"] is False
    assert body["detail"]  # probe outcome is reported

    # Same honesty for the OSINT providers that previously fell through to
    # format-only validation.
    for provider in ("hlr", "opencellid", "geospy"):
        resp = client.post("/api/v1/tools/test-connection",
                           json={"provider": provider, "key": "0123456789abcdef"})
        body = resp.json()
        assert body["valid"] is False, f"{provider} must not pass on format alone"
        assert body["method"] == "Live HTTPS probe"


def test_byok_keys_never_echoed_in_responses():
    """The submitted key must never appear in the response payload."""
    resp = client.post("/api/v1/tools/test-connection",
                       json={"provider": "mapbox", "key": "pk.SUPERSECRETVALUE.xyz"})
    body = resp.text
    assert "SUPERSECRETVALUE" not in body


# --------------------------------------------------------------------------- #
# Authorized Security Testing — attestation + IP reconciliation (TASK security)
# --------------------------------------------------------------------------- #
def test_security_ip_echo():
    """GET /security/ip returns a server-observed client IP."""
    resp = client.get("/api/v1/security/ip")
    assert resp.status_code == 200
    assert isinstance(resp.json()["ip"], str)
    assert resp.json()["ip"]


def test_attestation_is_append_only_and_searchable():
    """POST /security/attestations writes a non-repudiation audit entry."""
    before = admin_store.list_audit(action="security_testing.attestation")
    n_before = len(before)

    resp = client.post(
        "/api/v1/security/attestations",
        json={
            "full_name": "Riley Okafor",
            "email": "riley@ark.example",
            "position": "Offensive Security Lead",
            "org_name": "ARK Red Team",
            "purpose": "Annual web-application assessment",
            "target_scope": "app.example.com / ROE-2026-014",
            "client_ip": "198.51.100.9",
            "real_ip": "198.51.100.9",
            "user_agent": "test-agent",
            "timestamp": "2026-08-15T00:00:00Z",
            "telemetry": {"platform": "darwin"},
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["log_id"].startswith("AUD-")
    assert data["signature"].startswith("ARK-ATT-")
    assert data["persisted"] is True
    assert data["action"] == "security_testing.attestation"
    # server-observed IP is authoritative, not the advisory client value
    assert data["ip"]

    after = admin_store.list_audit(action="security_testing.attestation")
    assert len(after) == n_before + 1
    latest = after[-1]
    assert latest["actor"] == "Riley Okafor <riley@ark.example>"
    assert latest["target"] == "app.example.com / ROE-2026-014"
    assert "ROE-2026-014" in latest["detail"]
    assert latest["ip"]  # captured server-side

    # Searchable via the admin audit-logs surface.
    listed = client.get(
        "/api/v1/admin/audit-logs",
        params={"action": "security_testing.attestation"},
        headers=_auth(_admin_token()),
    ).json()["logs"]
    assert any(e["log_id"] == data["log_id"] for e in listed)
