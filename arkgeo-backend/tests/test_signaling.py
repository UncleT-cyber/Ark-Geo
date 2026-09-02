"""Tests for the certified live-signaling subsystem (RBAC + audit + drivers)."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from main import app
from app.signaling import audit as audit_module
from app.signaling.audit import audit_log
from app.signaling.schema import SignalingResult, SignalingTarget, SubscriberRecord

client = TestClient(app)

SIGOPS = {"username": "sigops", "password": "sigops-cert"}
SIGADMIN = {"username": "sigadmin", "password": "sigadmin-cert"}
SIGAUDIT = {"username": "sigaudit", "password": "sigaudit-cert"}


@pytest.fixture(autouse=True)
def _isolate_audit(tmp_path, monkeypatch):
    audit_log._path = str(tmp_path / "signaling.jsonl")  # noqa: SLF001
    yield
    audit_log._path = audit_module.AuditLog._default_path()  # noqa: SLF001


class FakeLiveBackend:
    id = "fakelive"
    live = True

    async def sri(self, msisdn):
        return SignalingResult(
            op="sri", backend=self.id, live=True,
            target=SignalingTarget(msisdn=msisdn, mcc="621", mnc="30"),
            subscriber=SubscriberRecord(msisdn=msisdn, imsi="62130FAKE000001", mcc="621", mnc="30"),
            raw={}, detail="fake live SRI",
        )

    async def cgi(self, mcc, mnc, lac=None, cell_id=None):
        return SignalingResult(
            op="cgi", backend=self.id, live=True,
            target=SignalingTarget(msisdn="", mcc=mcc, mnc=mnc, lac=lac, cell_id=cell_id),
            raw={}, detail="fake live CGI",
        )

    def _testbed_label(self):
        return "fake live backend"


def _login(creds: dict) -> str:
    resp = client.post("/api/v1/signaling/auth/token", json=creds)
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _admin_operator_token(scope: str = "sri,ulr,ati,plr,imsi,cgi,silent_sms,imsi_catcher") -> str:
    token = _login(SIGADMIN)
    resp = client.post(
        "/api/v1/signaling/auth/operator-token",
        json={"operator": "MTN NG", "mcc": "621", "scope": scope, "valid_hours": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def _signaling(backend_patch):
    return __import__("unittest.mock").mock.patch(
        "app.api.v1.endpoints.signaling.get_backend",
        return_value=backend_patch,
    )


# --------------------------------------------------------------------------- #
class TestStatusAndLogin:
    def test_status_public(self):
        resp = client.get("/api/v1/signaling/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["backend"] in {"simulated", "osmocom", "sdr", "commercial"}

    def test_login_bad_credentials(self):
        resp = client.post("/api/v1/signaling/auth/token", json={"username": "sigops", "password": "wrong"})
        assert resp.status_code == 401

    def test_login_success_role_claims(self):
        body = client.post("/api/v1/signaling/auth/token", json=SIGOPS).json()
        assert body["role"] == "CERTIFIED_OPERATOR"
        me = client.get(
            "/api/v1/signaling/auth/me",
            headers={"Authorization": f"Bearer {body['access_token']}"},
        )
        assert me.status_code == 200
        assert me.json()["username"] == "sigops"

    def test_login_rejected_for_auditor_accessing_ops(self):
        token = _login(SIGAUDIT)
        resp = client.post(
            "/api/v1/signaling/auth/operator-token",
            json={"operator": "MTN NG", "mcc": "621", "valid_hours": 1},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    def test_operator_token_requires_admin_role(self):
        op_token = _login(SIGOPS)
        resp = client.post(
            "/api/v1/signaling/auth/operator-token",
            json={"operator": "MTN NG", "mcc": "621", "valid_hours": 1},
            headers={"Authorization": f"Bearer {op_token}"},
        )
        assert resp.status_code == 403


# --------------------------------------------------------------------------- #
class TestBoundary:
    def test_sri_requires_personnel_token(self):
        resp = client.post("/api/v1/signaling/sri", json={"msisdn": "+2348030001111"})
        assert resp.status_code == 401

    def test_sri_requires_operator_token(self):
        token = _login(SIGOPS)
        with _signaling(FakeLiveBackend()):
            resp = client.post(
                "/api/v1/signaling/sri",
                json={"msisdn": "+2348030001111"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 403
        assert "Operator-Authorization" in resp.json()["detail"]

    def test_sri_wrong_mcc_token(self):
        token = _login(SIGOPS)
        admin_token = _login(SIGADMIN)
        resp = client.post(
            "/api/v1/signaling/auth/operator-token",
            json={"operator": "Vodafone DE", "mcc": "262", "valid_hours": 1},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        op_token = resp.json()["token"]
        with _signaling(FakeLiveBackend()):
            resp = client.post(
                "/api/v1/signaling/sri",
                json={"msisdn": "+2348030001111"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Operator-Authorization": op_token,
                },
            )
        assert resp.status_code == 403
        assert "MCC 262" in resp.json()["detail"]

    def test_sri_scope_mismatch(self):
        token = _login(SIGOPS)
        op_token = _admin_operator_token(scope="ulr,ati")
        with _signaling(FakeLiveBackend()):
            resp = client.post(
                "/api/v1/signaling/sri",
                json={"msisdn": "+2348030001111"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Operator-Authorization": op_token,
                },
            )
        assert resp.status_code == 403
        assert "does not permit 'sri'" in resp.json()["detail"]

    def test_sri_allowed_with_valid_token(self):
        token = _login(SIGOPS)
        op_token = _admin_operator_token()
        with _signaling(FakeLiveBackend()):
            resp = client.post(
                "/api/v1/signaling/sri",
                json={"msisdn": "+2348030001111"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Operator-Authorization": op_token,
                },
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["live"] is True
        assert body["backend"] == "fakelive"
        assert body["trace_id"].startswith("sig-")
        assert body["subscriber"]["imsi"] == "62130FAKE000001"

    def test_cgi_requires_matching_mcc(self):
        token = _login(SIGOPS)
        op_token = _admin_operator_token()
        with _signaling(FakeLiveBackend()):
            resp = client.post(
                "/api/v1/signaling/cgi",
                json={"mcc": "621", "mnc": "30", "lac": 45678, "cell_id": 5123},
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Operator-Authorization": op_token,
                },
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["op"] == "cgi"


# --------------------------------------------------------------------------- #
class TestAuditTrail:
    def test_allowed_and_denied_are_recorded(self):
        token = _login(SIGOPS)
        op_token = _admin_operator_token()
        with _signaling(FakeLiveBackend()):
            client.post(
                "/api/v1/signaling/sri",
                json={"msisdn": "+2348030001111"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Operator-Authorization": op_token,
                },
            )
            client.post(
                "/api/v1/signaling/sri",
                json={"msisdn": "+2348030001111"},
                headers={"Authorization": f"Bearer {token}"},
            )
        audit_token = _login(SIGADMIN)
        resp = client.get(
            "/api/v1/signaling/audit", headers={"Authorization": f"Bearer {audit_token}"}
        )
        assert resp.status_code == 200
        entries = resp.json()["entries"]
        outcomes = {(e["op"], e["outcome"]) for e in entries}
        assert ("sri", "allowed") in outcomes
        assert ("sri", "denied") in outcomes

    def test_audit_endpoint_scopes_own_entries(self):
        token = _login(SIGOPS)
        resp = client.get(
            "/api/v1/signaling/audit", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200
        entries = resp.json()["entries"]
        assert len(entries) >= 1
        assert all(e["actor"] == "sigops" for e in entries)
        assert any(e["op"] == "auth.login" and e["outcome"] == "allowed" for e in entries)


# --------------------------------------------------------------------------- #
class TestDriverRouting:
    def test_simulated_backend_is_non_live(self):
        with _signaling(__import__("app.signaling.backends.simulated", fromlist=["SimulatedBackend"]).SimulatedBackend()):
            token = _login(SIGOPS)
            op_token = _admin_operator_token()
            resp = client.post(
                "/api/v1/signaling/sri",
                json={"msisdn": "+2348030001111"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Operator-Authorization": op_token,
                },
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["live"] is False
        assert body["simulated"] is True
        assert body["subscriber"]["imsi"].startswith("621")
        assert body["cell"]["cgi"] is not None

    def test_unprovisioned_backend_returns_503(self):
        backend = __import__("app.signaling.backends.osmocom", fromlist=["OsmocomBackend"]).OsmocomBackend()
        with _signaling(backend):
            token = _login(SIGOPS)
            op_token = _admin_operator_token()
            resp = client.post(
                "/api/v1/signaling/silent-sms",
                json={"target": "+2348030001111", "text": ""},
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Operator-Authorization": op_token,
                },
            )
        assert resp.status_code == 503
        assert "SMSC" in resp.json()["detail"]

    def test_sdr_imsi_catcher_radius_gate(self):
        backend = __import__("app.signaling.backends.sdr", fromlist=["SdrBackend"]).SdrBackend()
        with _signaling(backend):
            token = _login(SIGOPS)
            op_token = _admin_operator_token()
            resp = client.post(
                "/api/v1/signaling/imsi-catcher",
                json={"band": "GSM-1800", "radius_m": 50000, "capture_seconds": 15},
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Operator-Authorization": op_token,
                },
            )
        assert resp.status_code == 503
        assert "ceiling" in resp.json()["detail"]

    def test_dry_run_certified_no_operator_token(self):
        with _signaling(__import__("app.signaling.backends.simulated", fromlist=["SimulatedBackend"]).SimulatedBackend()):
            token = _login(SIGOPS)
            resp = client.post(
                "/api/v1/signaling/dry-run",
                json={"msisdn": "+2348030001111"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        assert resp.json()["simulated"] is True


# --------------------------------------------------------------------------- #
class TestOsmocomCtrlClient:
    """Validates the real osmo-hlr Control-Interface protocol client."""

    def _run_server(self, handler):
        import asyncio
        from app.signaling.osmocom_ctrl import OsmocomCtrlClient

        async def scenario():
            async def handle(reader, writer):
                while True:
                    raw = await reader.readline()
                    if not raw:
                        break
                    req = raw.decode().strip()
                    var = req[len("GET "):].strip() if req.startswith("GET ") else req
                    if "by-msisdn-2348030001111.info" in var:
                        payload = '{"imsi": "621301234567890", "mcc": "621", "mnc": "30", "operator": "MTN"}'
                        writer.write(f"GET REPLY 200 {var} {payload}\r\n".encode())
                    elif "by-imsi-999.notfound" in var:
                        writer.write(b"GET REPLY 400 unknown no-such-subscriber\r\n")
                    else:
                        writer.write(b"GET REPLY 200 unknown \r\n")
                    await writer.drain()
                writer.close()
                await writer.wait_closed()

            server = await asyncio.start_server(handle, "127.0.0.1", 0)
            port = server.sockets[0].getsockname()[1]
            client = OsmocomCtrlClient(host="127.0.0.1", port=port, timeout=3)
            try:
                ok = await client.get_ok("subscriber.by-msisdn-2348030001111.info")
                missing = await client.get("subscriber.by-imsi-999.notfound")
                empty = await client.get_ok("subscriber.by-id-1.info")
            finally:
                await client.close()
                server.close()
            return ok, missing, empty

        return asyncio.run(scenario())

    def test_parses_subscriber_record(self):
        ok, _, _ = self._run_server(lambda: None)
        assert ok["status"] == 200
        assert ok["value"]["imsi"] == "621301234567890"
        assert ok["value"]["mcc"] == "621"

    def test_error_reply_surface(self):
        _, missing, _ = self._run_server(lambda: None)
        assert missing["status"] == 400
        assert "no-such-subscriber" in missing.get("error", "")

    def test_empty_value_ok(self):
        _, _, empty = self._run_server(lambda: None)
        assert empty["status"] == 200


# --------------------------------------------------------------------------- #
# OSINT aggregation (certified personnel; free registry tier + providers)
# --------------------------------------------------------------------------- #
class TestOsintAggregator:
    def _osint(self, phone: str, keys: dict | None = None):
        token = _login(SIGOPS)
        return client.post(
            "/api/v1/signaling/osint",
            json={"phone": phone, "keys": keys or {}},
            headers={"Authorization": f"Bearer {token}"},
        )

    def test_requires_certified(self):
        resp = client.post("/api/v1/signaling/osint", json={"phone": "+2348030001111"})
        assert resp.status_code == 401

    def test_free_tier_nigeria(self):
        resp = self._osint("+2348030001111")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["ok"] is True
        assert data["iso2"] == "NG"
        assert data["country_code"] == "+234"
        assert data["mcc"] == "621"
        assert data["mnc"] == "30"
        assert data["carrier"] == "MTN"
        assert data["line_type"] == "mobile"
        # No configured IPQS key → requires_key; a stored-but-rejected key → error.
        assert data["workers"]["hlr_ipqs"]["status"] in ("requires_key", "error")
        assert data["workers"]["social"]["status"] == "ok"
        assert data["trace_id"].startswith("sig-")

    def test_free_tier_us_geo_zone(self):
        resp = self._osint("+12125551234")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["iso2"] == "US"
        assert data["geo_zone"] == "New York (Manhattan)"

    def test_free_tier_uk_carrier(self):
        resp = self._osint("+447700900123")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["iso2"] == "GB"
        assert data["line_type"] == "mobile"

    def test_invalid_phone_422(self):
        resp = self._osint("abc")
        assert resp.status_code == 422

    def test_tier1_real_reference_extraction(self):
        """Tier-1 keyless facts come from libphonenumber metadata — no sim."""
        resp = self._osint("+2348030001111")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["valid"] is True
        assert data["possible"] is True
        assert data["number_type"] == "MOBILE"
        assert data["carrier"] == "MTN"
        assert data["national_number"] == "8030001111"
        assert data["ndc"] == "803"
        assert data["subscriber_number"] == "0001111"
        assert data["international_format"] == "+234 803 000 1111"
        assert data["timezone"] == ["Africa/Lagos"]
        # City===Country is a routing fact, not a city — fall back cleanly to
        # the core routing-gateway location and never echo the country as a city.
        assert data["geo_city"] is None
        assert data["routing_location"] == "national mobile core routing gateway (no fixed city)"

    def test_tier1_us_reference_extraction(self):
        resp = self._osint("+14155552671")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["valid"] is True
        assert data["geo_city"] == "San Francisco, CA"
        assert data["timezone"] == ["America/Los_Angeles"]

    def test_no_fabrication_without_keys(self):
        """Without keys there must be no invented state or billing — only real
        free-tier signals (public numbering plans + live platform availability
        probes)."""
        resp = self._osint("+2348030001111")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["line_state"] is None
        assert data["active"] is None
        assert data["sim_swap_risk"] is None
        assert data["sim_last_changed"] is None
        assert "billing" not in data
        assert "simulated_flags" not in data
        assert data["footprint"]["probed"] is True
        assert data["footprint"]["simulated"] is False
        assert data["footprint"]["presence"]  # live availability probes ran
        assert data["footprint"]["probes"]  # per-platform probe results present
        assert data["reputation"]["spam_score"] is None
        assert data["reputation"]["fraud_score"] is None
        assert "line-state" in data["requires_key"]
        assert "simswap" in data["requires_key"]
        assert "footprint" not in data["requires_key"]
        for name, w in data["workers"].items():
            if w["status"] == "ok":
                assert not (w.get("data") or {}).get("simulated"), name

    def test_audited(self):
        before = len([e for e in audit_log.recent(limit=500) if e["op"] == "osint"])
        self._osint("+2348030001111")
        entries = [e for e in audit_log.recent(limit=500) if e["op"] == "osint"]
        assert len(entries) == before + 1
        last = entries[-1]
        assert last["outcome"] == "allowed"
        assert last["actor"] == "sigops"


class TestCanarySurface:
    """Canary links: generation is certified; visiting is anonymous and benign."""

    def _create(self):
        token = _login(SIGOPS)
        return client.post(
            "/api/v1/signaling/canary",
            json={"phone": "+2348030001111", "pretext": "canary-webhook"},
            headers={"Authorization": f"Bearer {token}"},
        )

    def test_requires_certified(self):
        resp = client.post("/api/v1/signaling/canary", json={"phone": "+2348030001111"})
        assert resp.status_code == 401

    def test_create_visit_hits(self):
        created = self._create()
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["ok"] is True
        assert body["token"]
        assert body["url"].endswith(f"/api/v1/signaling/canary/{body['token']}")

        page = client.get(body["url"])
        assert page.status_code == 200
        assert b"Callback registered" in page.content

        hits = client.get(
            f"/api/v1/signaling/canary/{body['token']}/hits",
            headers={"Authorization": f"Bearer {_login(SIGOPS)}"},
        )
        assert hits.status_code == 200
        ledger = hits.json()
        assert ledger["phone"] == "+2348030001111"
        assert ledger["pretext"] == "canary-webhook"
        assert len(ledger["hits"]) == 1
        assert ledger["hits"][0]["ip"]

    def test_hits_require_certified(self):
        created = self._create().json()
        resp = client.get(f"/api/v1/signaling/canary/{created['token']}/hits")
        assert resp.status_code == 401

    def test_unknown_visit_404(self):
        resp = client.get("/api/v1/signaling/canary/deadbeefdeadbeef")
        assert resp.status_code == 404
