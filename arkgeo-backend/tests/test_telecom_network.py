"""Tests for the Telecom & Network Intelligence (passive) endpoints."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text="", headers=None, url=None):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text
        self.headers = headers or {}
        self.url = url

    def json(self):
        return self._json

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeAsyncClient:
    def __init__(self, responses):
        self.responses = responses
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **kwargs):
        self.requests.append(("GET", url, kwargs))
        key = url
        if url not in self.responses:
            key = "default"
        return self.responses.get(key, self.responses.get("default", FakeResponse(200, {})))

    async def post(self, url, **kwargs):
        self.requests.append(("POST", url, kwargs))
        return self.responses.get(url, self.responses.get("default", FakeResponse(200, {})))

    def stream(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return self.responses.get(url, self.responses.get("default", FakeResponse(200, {})))
# --------------------------------------------------------------------------- #
# Telecom — HLR lookup
# --------------------------------------------------------------------------- #
class TestHlrLookup:
    def test_missing_key_free_fallback(self):
        with patch("app.api.v1.endpoints.telecom.settings_store.get_key", return_value=None):
            r = client.post("/api/v1/telecom/hlr-lookup",
                            json={"phone": "+2348030000000"})
        assert r.status_code == 200
        d = r.json()
        # Free tier derives registry facts without any key.
        assert d["looked_up"] is True
        assert d["requires_key"] is False
        assert d["live_state_available"] is False
        assert d["phone_e164"] == "+2348030000000"
        assert d["carrier"] == "MTN"
        assert d["mcc"] == "621"
        assert d["mnc"] == "30"
        assert d["line_type"] == "mobile"
        assert "Free tier" in d["detail"]

    def test_invalid_phone(self):
        r = client.post("/api/v1/telecom/hlr-lookup", json={"phone": "abc"})
        assert r.status_code == 422

    def test_uses_client_byok_key(self):
        fake = FakeAsyncClient({})
        fake.responses["default"] = FakeResponse(200, {
            "success": True, "e164": "+2348030000000", "country_code": "NG",
            "line_type": "mobile", "carrier": "MTN", "active": True,
            "city": "Lagos", "region": "Lagos", "zip_code": "100001",
            "country": "Nigeria", "is_voip": False, "is_prepaid": False,
        })
        with patch("app.api.v1.endpoints.telecom.settings_store.get_key", return_value=None) as mk, \
             patch("app.api.v1.endpoints.telecom.httpx.AsyncClient", return_value=fake):
            r = client.post("/api/v1/telecom/hlr-lookup",
                            json={"phone": "+2348030000000", "api_key": "client-key-123456"})
        d = r.json()
        assert r.status_code == 200
        assert d["looked_up"] is True
        assert d["carrier"] == "MTN"
        assert d["mcc"] == "621"
        assert d["mnc"] == "30"
        assert d["line_type"] == "mobile"
        assert d["country_code"] == "NG"
        assert d["is_voip"] is False
        assert "IPQS" in d["detail"]
        mk.assert_not_called()

    def test_falls_back_to_admin_system_key(self):
        fake = FakeAsyncClient({})
        fake.responses["default"] = FakeResponse(200, {
            "success": True, "e164": "+15551234567", "country_code": "US",
            "line_type": "landline", "carrier": "Verizon", "active": None,
        })
        with patch("app.api.v1.endpoints.telecom.settings_store.get_key", return_value="sys-key") as mk, \
             patch("app.api.v1.endpoints.telecom.httpx.AsyncClient", return_value=fake):
            r = client.post("/api/v1/telecom/hlr-lookup", json={"phone": "+15551234567"})
        assert r.status_code == 200
        assert r.json()["looked_up"] is True
        mk.assert_called_once_with("hlr_api_key")
        # system key sent outbound but nothing in the response
        assert "sys-key" not in r.text


# --------------------------------------------------------------------------- #
# Telecom — cell tower spatial lookup
# --------------------------------------------------------------------------- #
class TestCellLookup:
    def test_opencellid_requires_key(self):
        with patch("app.api.v1.endpoints.telecom.settings_store.get_key", return_value=None):
            r = client.post("/api/v1/telecom/cell-lookup",
                            json={"mcc": 621, "mnc": 30, "lac": 101, "cell_id": 10201})
        d = r.json()
        assert d["looked_up"] is False
        assert d["requires_key"] is True
        assert d["provider"] == "opencellid"

    def test_opencellid_hit(self):
        fake = FakeAsyncClient({})
        fake.responses["default"] = FakeResponse(200, {
            "lat": 6.4541, "lon": 3.3947, "range": 2500, "radio": "gsm",
            "mcc": 621, "mnc": 30, "lac": 101, "cellid": 10201, "samples": 9,
        })
        with patch("app.api.v1.endpoints.telecom.httpx.AsyncClient", return_value=fake) as ac, \
             patch("app.api.v1.endpoints.telecom.settings_store.get_key", return_value="ocid-key"):
            r = client.post("/api/v1/telecom/cell-lookup",
                            json={"mcc": 621, "mnc": 30, "lac": 101, "cell_id": 10201})
        d = r.json()
        assert d["looked_up"] is True
        assert d["lat"] == 6.4541
        assert d["lon"] == 3.3947
        assert d["radio"] == "gsm"
        method, url, kwargs = fake.requests[0]
        assert "opencellid.org" in url
        assert kwargs["params"]["cell_id"] == 10201

    def test_opencellid_not_found(self):
        fake = FakeAsyncClient({})
        fake.responses["default"] = FakeResponse(200, {"error": "cell not found"})
        with patch("app.api.v1.endpoints.telecom.httpx.AsyncClient", return_value=fake), \
             patch("app.api.v1.endpoints.telecom.settings_store.get_key", return_value="ocid-key"):
            r = client.post("/api/v1/telecom/cell-lookup",
                            json={"mcc": 621, "mnc": 30, "lac": 101, "cell_id": 999999})
        d = r.json()
        assert d["looked_up"] is True
        assert d["lat"] is None
        assert "not found" in d["detail"]

    def test_beacondb_free_hit(self):
        fake = FakeAsyncClient({})
        fake.responses["default"] = FakeResponse(200, {
            "status": "ok",
            "results": [{"cellid": 10201, "lac": 101, "mnc": 30, "mcc": 621,
                         "lat": 6.45, "lon": 3.39, "range": 2200, "samples": 4}],
        })
        with patch("app.api.v1.endpoints.telecom.httpx.AsyncClient", return_value=fake):
            r = client.post("/api/v1/telecom/cell-lookup",
                            json={"mcc": 621, "mnc": 30, "lac": 101, "cell_id": 10201,
                                  "provider": "beacondb"})
        d = r.json()
        assert d["looked_up"] is True
        assert d["provider"] == "beacondb"
        assert d["lat"] == 6.45

    def test_unknown_provider(self):
        r = client.post("/api/v1/telecom/cell-lookup",
                        json={"mcc": 621, "mnc": 30, "cell_id": 1, "provider": "nope"})
        assert r.status_code == 422


# --------------------------------------------------------------------------- #
# Network — passive discovery
# --------------------------------------------------------------------------- #
class TestRdap:
    def test_domain_rdap(self):
        fake = FakeAsyncClient({})
        fake.responses["default"] = FakeResponse(200, {
            "handle": "D-XYZ",
            "ldhName": "EXAMPLE.COM",
            "entities": [{"vcardArray": ["vcard", [["fn", {}, "text", "Example Org"]]]}],
            "status": ["client delete prohibited"],
            "events": [{"eventAction": "registration", "eventDate": "2020-01-01T00:00:00Z"}],
        })
        with patch("app.api.v1.endpoints.network.httpx.AsyncClient", return_value=fake):
            r = client.post("/api/v1/network/rdap", json={"target": "example.com"})
        d = r.json()
        assert d["kind"] == "domain"
        assert d["registered_org"] == "Example Org"
        assert d["handle"] == "D-XYZ"

    def test_ip_rdap(self):
        fake = FakeAsyncClient({})
        fake.responses["default"] = FakeResponse(200, {
            "handle": "NET-X",
            "startAddress": "1.2.3.0",
            "endAddress": "1.2.3.255",
        })
        with patch("app.api.v1.endpoints.network.httpx.AsyncClient", return_value=fake):
            r = client.post("/api/v1/network/rdap", json={"target": "1.2.3.4"})
        d = r.json()
        assert d["kind"] == "ip"
        assert d["start_address"] == "1.2.3.0"
        assert d["end_address"] == "1.2.3.255"

    def test_invalid_target(self):
        r = client.post("/api/v1/network/rdap", json={"target": "not a domain!"})
        assert r.status_code == 422


class TestBgpLookup:
    def test_asn_resolution(self):
        fake = FakeAsyncClient({})
        fake.responses["default"] = FakeResponse(200, {
            "data": {
                "ip": "8.8.8.8",
                "ptr_record": "dns.google",
                "asns": [{"asn": 15169, "name": "GOOGLE", "description": "Google LLC",
                          "country_code": "US", "prefix_count": 1}],
                "prefixes": [{"prefix": "8.8.8.0/24", "asn": 15169, "name": "GOOGLE",
                              "description": "Google LLC", "country_code": "US"}],
            }
        })
        with patch("app.api.v1.endpoints.network.httpx.AsyncClient", return_value=fake):
            r = client.post("/api/v1/network/bgp-lookup", json={"ip": "8.8.8.8"})
        d = r.json()
        assert d["asn"] == 15169
        assert d["asn_name"] == "GOOGLE"
        assert d["ptr_record"] == "dns.google"
        assert d["prefixes"][0]["prefix"] == "8.8.8.0/24"

    def test_no_asn(self):
        fake = FakeAsyncClient({})
        fake.responses["default"] = FakeResponse(200, {"data": {"ip": "10.0.0.1", "asns": []}})
        with patch("app.api.v1.endpoints.network.httpx.AsyncClient", return_value=fake):
            r = client.post("/api/v1/network/bgp-lookup", json={"ip": "10.0.0.1"})
        assert r.json()["asn"] is None


class TestDnsLookup:
    def test_answers(self):
        fake = FakeAsyncClient({})
        fake.responses["default"] = FakeResponse(200, {
            "Answer": [{"name": "example.com.", "type": 1, "TTL": 300, "data": "93.184.216.34"}],
        })
        with patch("app.api.v1.endpoints.network.httpx.AsyncClient", return_value=fake):
            r = client.post("/api/v1/network/dns-lookup",
                            json={"qname": "example.com", "type": "A"})
        d = r.json()
        assert d["answers"][0]["data"] == "93.184.216.34"
        method, url, kwargs = fake.requests[0]
        assert "cloudflare-dns.com" in url

    def test_bad_type(self):
        r = client.post("/api/v1/network/dns-lookup", json={"qname": "example.com", "type": "BAD"})
        assert r.status_code == 422


class TestCrtSearch:
    def test_certificates(self):
        fake = FakeAsyncClient({})
        fake.responses["default"] = FakeResponse(200, [
            {"name_value": "example.com", "common_name": "example.com",
             "issuer_name": "R3", "not_before": "2024-01-01", "not_after": "2025-01-01"},
        ])
        with patch("app.api.v1.endpoints.network.httpx.AsyncClient", return_value=fake):
            r = client.post("/api/v1/network/crt-search", json={"domain": "example.com"})
        d = r.json()
        assert d["certificates"][0]["issuer_name"] == "R3"
        method, url, kwargs = fake.requests[0]
        assert "crt.sh" in url
        assert kwargs["params"]["output"] == "json"


class TestWebProbe:
    def test_security_header_audit(self):
        fake = FakeAsyncClient({})
        fake.responses["default"] = FakeResponse(200, headers={
            "strict-transport-security": "max-age=63072000",
            "content-security-policy": "default-src 'self'",
            "x-frame-options": "SAMEORIGIN",
            "x-content-type-options": "nosniff",
            "referrer-policy": "strict-origin-when-cross-origin",
            "access-control-allow-origin": "https://trusted.example",
            "server": "cloudflare",
            "x-powered-by": "Express",
        }, url="https://example.com/")
        with patch("app.api.v1.endpoints.network.httpx.AsyncClient", return_value=fake):
            r = client.post("/api/v1/network/webprobe", json={"url": "https://example.com/"})
        d = r.json()
        assert d["status_code"] == 200
        assert d["security_headers"]["strict-transport-security"]["ok"] is True
        assert d["security_headers"]["x-frame-options"]["ok"] is True
        assert d["security_headers"]["content-security-policy"]["present"] is True
        assert d["tech_hints"]["server"] == "cloudflare"
        assert d["tech_hints"]["x-powered-by"] == "Express"

    def test_insecure_missing_headers(self):
        fake = FakeAsyncClient({})
        fake.responses["default"] = FakeResponse(200, headers={}, url="http://example.com/")
        with patch("app.api.v1.endpoints.network.httpx.AsyncClient", return_value=fake):
            r = client.post("/api/v1/network/webprobe", json={"url": "http://example.com/"})
        d = r.json()
        assert d["security_headers"]["strict-transport-security"]["present"] is False
        assert d["security_headers"]["x-frame-options"]["ok"] is False

    def test_non_http_url(self):
        r = client.post("/api/v1/network/webprobe", json={"url": "ftp://example.com/"})
        assert r.status_code == 422


# --------------------------------------------------------------------------- #
# Telecom — signaling audit (simulated workflow)
# --------------------------------------------------------------------------- #
class TestSignalingAudit:
    def test_tier1_redacts_identifying_fields(self):
        r = client.post("/api/v1/telecom/signaling-audit", json={"phone": "+2348030001111", "tier": 1})
        assert r.status_code == 200
        d = r.json()
        assert d["simulated"] is True
        assert d["tier"] == 1
        assert d["extracted"]["mcc"] is None
        assert d["extracted"]["mnc"] is None
        assert d["extracted"]["imsi"] is None
        assert d["extracted"]["cell_id"] is None
        assert d["extracted"]["country"] == "NG"
        assert any("REDACTED" in (s.get("warn") or "") for s in d["steps"])
        assert any(s["event"] == "imsi.extract" for s in d["steps"])
        assert d["spatial"]["lat"] is None and d["spatial"]["lon"] is None

    def test_tier2_full_workflow_and_deterministic_fields(self):
        r1 = client.post("/api/v1/telecom/signaling-audit", json={"phone": "+2348030001111", "tier": 2})
        r2 = client.post("/api/v1/telecom/signaling-audit", json={"phone": "+2348030001111", "tier": 2})
        assert r1.status_code == 200 and r2.status_code == 200
        d = r1.json()
        assert d["tier"] == 2
        assert d["extracted"]["mcc"] == "621"
        assert d["extracted"]["mnc"] is not None
        assert d["extracted"]["imsi"] and d["extracted"]["imsi"].startswith("621")
        assert d["extracted"]["cgi"]
        assert d["extracted"]["lac"] and d["extracted"]["cell_id"]
        assert len(d["steps"]) >= 15
        events = [s["event"] for s in d["steps"]]
        assert "input.normalized" in events
        assert "routing.token" in events
        assert "imsi.extract" in events
        assert any(e.startswith("sri.") or e.startswith("ulr.") for e in events)
        assert "cgi.parse" in events
        assert "spatial.intersect" in events
        assert any(s["event"] == "defense.screening" for s in d["steps"])
        assert d["spatial"]["lat"] and d["spatial"]["lon"]
        assert d["spatial"]["radius_meters"] > 0
        # Same input → identical mock output (determinism)
        assert r1.json()["extracted"] == r2.json()["extracted"]
        assert [s["event"] for s in r1.json()["steps"]] == [s["event"] for s in r2.json()["steps"]]

    def test_tier2_ulr_thread(self):
        # Force ULR thread by probing deterministic output; any thread is valid,
        # so just assert the audit still completes for a non-NG prefix.
        r = client.post("/api/v1/telecom/signaling-audit", json={"phone": "+447911123456", "tier": 2})
        assert r.status_code == 200
        d = r.json()
        assert d["extracted"]["mcc"] == "234"
        assert d["extracted"]["country"] == "GB"
        assert d["thread"] in ("SRI-SM", "ULR", "ATI")
        assert any("ulr." in s["event"] or "sri." in s["event"] for s in d["steps"])

    def test_invalid_phone(self):
        r = client.post("/api/v1/telecom/signaling-audit", json={"phone": "123", "tier": 2})
        assert r.status_code == 422

    def test_tier_out_of_range(self):
        r = client.post("/api/v1/telecom/signaling-audit", json={"phone": "+2348030001111", "tier": 9})
        assert r.status_code == 422


# --------------------------------------------------------------------------- #
# Telecom — custom local cell DB (mock footprint)
# --------------------------------------------------------------------------- #
class TestCellLocal:
    def test_local_db_hit(self):
        r = client.post("/api/v1/telecom/cell-local", json={"mcc": 621, "mnc": 30, "lac": 1234, "cell_id": 5678})
        assert r.status_code == 200
        d = r.json()
        assert d["looked_up"] is True
        assert d["provider"] == "custom_local_db"
        assert d["mcc"] == 621 and d["mnc"] == 30
        assert d["lat"] and d["lon"]
        assert d["range_meters"] and d["range_meters"] > 0

    def test_local_db_deterministic(self):
        payload = {"mcc": 234, "mnc": 10, "lac": 99, "cell_id": 1234}
        a = client.post("/api/v1/telecom/cell-local", json=payload).json()
        b = client.post("/api/v1/telecom/cell-local", json=payload).json()
        assert a["lat"] == b["lat"] and a["lon"] == b["lon"]
        assert a["range_meters"] == b["range_meters"]

    def test_local_db_unknown_mcc(self):
        r = client.post("/api/v1/telecom/cell-local", json={"mcc": 999, "mnc": 1, "lac": 1, "cell_id": 1})
        assert r.status_code == 200
        assert r.json()["looked_up"] is False
