"""Provider key connectivity probes.

Used by the BYOK ``/tools/test-connection`` endpoint and the admin Model
Gateway live-test endpoint.  The submitted key is used only inside the
outgoing request (Authorization header / query param) and is NEVER logged
or persisted by these functions.

Every provider performs a REAL HTTP probe against the provider and only
reports ``valid=True`` on a definitive success (2xx plus any provider
body-level success marker).  There is deliberately NO format-validation
fallback: a random/generic key must never be reported as connected.
Providers whose probe turns out ambiguous report ``valid=False`` with an
honest detail message.
"""
from __future__ import annotations

import base64
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 8.0

# Providers whose probe needs a paired credential. Primary id → secondary
# store/request key name.  BYOK requests may supply the secondary via the
# request "extra" dict; admin tests read both from the encrypted store.
PAIRED_PROVIDERS = {
    "twilio": "twilio_auth_token",
    "opencnam": "opencnam_auth_token",
    "telesign": "telesign_rest_key",
    "truid": "truid_client_secret",
}

# Store key fields each provider needs for an admin live probe.
PROVIDER_KEY_FIELDS: dict[str, tuple[str, ...]] = {
    "openai": ("llm_api_key",),
    "gemini": ("gemini_api_key",),
    "anthropic": ("anthropic_api_key",),
    "openrouter": ("openrouter_api_key",),
    "huggingface": ("huggingface_api_key",),
    "geospy": ("geospy_api_key",),
    "geoinfer": ("geoinfer_api_key",),
    "serper": ("serper_api_key",),
    "tineye": ("tineye_api_key",),
    "tavily": ("tavily_api_key",),
    "hlr": ("hlr_api_key",),
    "opencellid": ("opencellid_api_key",),
    "mapbox": ("mapbox_token",),
    "google_maps": ("google_maps_api_key",),
    "infobip": ("infobip_api_key",),
    "twilio": ("twilio_account_sid", "twilio_auth_token"),
    "opencnam": ("opencnam_account_sid", "opencnam_auth_token"),
    "telesign": ("telesign_customer_id", "telesign_rest_key"),
    "truid": ("truid_client_id", "truid_client_secret"),
}

# Provider id → primary store key (for status surfaces / admin config).
PROVIDER_KEY_MAP: dict[str, str] = {
    pid: fields[0] for pid, fields in PROVIDER_KEY_FIELDS.items()
}
KEY_TO_PROVIDER: dict[str, str] = {v: k for k, v in PROVIDER_KEY_MAP.items()}


def _basic(identity: str, secret: str) -> str:
    raw = f"{identity}:{secret}"
    return "Basic " + base64.b64encode(raw.encode("utf-8")).decode("ascii")


async def _probe_google_maps(client: httpx.AsyncClient, key: str) -> dict[str, Any]:
    r = await client.get(
        "https://maps.googleapis.com/maps/api/geocode/json",
        params={"address": "1600 Amphitheatre Pkwy, Mountain View, CA", "key": key},
    )
    if r.status_code != 200:
        return {"ok": False, "detail": f"HTTP {r.status_code}"}
    try:
        payload = r.json() or {}
        status = payload.get("status")
        err = payload.get("error_message") or ""
    except Exception:  # noqa: BLE001
        return {"ok": False, "detail": "Non-JSON response"}
    if status in ("OK", "ZERO_RESULTS"):
        return {"ok": True, "detail": f"Google Maps Geocoding OK ({status})"}
    # Google's own error_message tells us exactly why (ApiNotEnabled,
    # RefererNotAllowed, KeyInvalid, ...) — surface it verbatim.
    hint = f"Google Maps rejected key: {status}"
    if err:
        hint = f"{hint} — {err.strip()}"
    return {"ok": False, "detail": hint}


async def _probe_google_tiles(client: httpx.AsyncClient, key: str) -> dict[str, Any]:
    """Probe the Map Tiles API — the server-to-server API the map proxy uses.
    Requires the 'Map Tiles API' to be enabled; referer restrictions do not
    apply to server-side calls."""
    r = await client.post(
        "https://tile.googleapis.com/v1/createSession",
        params={"key": key},
        json={"mapType": "satellite", "language": "en-US", "region": "US"},
    )
    if r.status_code != 200:
        try:
            payload = r.json() or {}
            err = payload.get("error", {}).get("message") or payload.get("error_message") or ""
        except Exception:  # noqa: BLE001
            err = ""
        hint = f"Map Tiles session failed: HTTP {r.status_code}"
        if err:
            hint = f"{hint} — {err.strip()}"
        return {"ok": False, "detail": hint}
    try:
        token = (r.json() or {}).get("session")
    except Exception:  # noqa: BLE001
        token = None
    if not token:
        return {"ok": False, "detail": "Map Tiles session response missing session token"}
    return {"ok": True, "detail": "Google Map Tiles session created (server-to-server, no referer needed)"}


async def _probe_ipqs(client: httpx.AsyncClient, key: str) -> dict[str, Any]:
    r = await client.get(f"https://ipqualityscore.com/api/json/account/{key}")
    if r.status_code != 200:
        return {"ok": False, "detail": f"HTTP {r.status_code}"}
    try:
        data = r.json() or {}
    except Exception:  # noqa: BLE001
        return {"ok": False, "detail": "Non-JSON response"}
    if data.get("success") is True:
        return {"ok": True, "detail": "IPQualityScore account accepted"}
    return {"ok": False, "detail": str(data.get("message") or "IPQS rejected key")}


async def _probe_tineye(client: httpx.AsyncClient, key: str) -> dict[str, Any]:
    r = await client.get(
        "https://api.tineye.com/rest/v3/remaining_limit",
        headers={"api_key": key, "X-Api-Key": key},
    )
    if r.status_code == 200:
        return {"ok": True, "detail": "TinEye accepted key"}
    return {"ok": False, "detail": f"HTTP {r.status_code}"}


async def _probe_opencellid(client: httpx.AsyncClient, key: str) -> dict[str, Any]:
    r = await client.get(
        "https://opencellid.org/cell/get",
        params={"key": key, "mcc": 310, "mnc": 260, "lac": 1, "cellid": 1},
    )
    if r.status_code != 200:
        return {"ok": False, "detail": f"HTTP {r.status_code}"}
    # OpenCelliD answers HTTP 200 with an XML body; unknown keys return
    # <rsp stat="fail"><err code="2" .../></rsp>.  The body is authoritative.
    if 'stat="ok"' in r.text:
        return {"ok": True, "detail": "OpenCelliD accepted key"}
    return {"ok": False, "detail": "OpenCelliD rejected key"}


async def _probe_infobip(client: httpx.AsyncClient, key: str) -> dict[str, Any]:
    r = await client.get(
        "https://api.infobip.com/account/balance",
        headers={"Authorization": f"App {key}"},
    )
    if r.status_code == 200:
        return {"ok": True, "detail": "Infobip accepted key"}
    return {"ok": False, "detail": f"HTTP {r.status_code}"}


async def _probe_twilio(client: httpx.AsyncClient, sid: str, token: str) -> dict[str, Any]:
    if not sid or not token:
        return {"ok": False, "detail": "Twilio needs both Account SID and Auth Token"}
    r = await client.get(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}.json",
        headers={"Authorization": _basic(sid, token)},
    )
    if r.status_code == 200:
        return {"ok": True, "detail": "Twilio credentials accepted"}
    return {"ok": False, "detail": f"HTTP {r.status_code}"}


async def _probe_opencnam(client: httpx.AsyncClient, sid: str, token: str) -> dict[str, Any]:
    if not sid or not token:
        return {"ok": False, "detail": "OpenCNAM needs both Account SID and Auth Token"}
    r = await client.get(
        "https://api.opencnam.com/v3/phone/+15005550006",
        params={"account_sid": sid, "auth_token": token, "format": "json"},
    )
    if r.status_code == 200:
        return {"ok": True, "detail": "OpenCNAM credentials accepted"}
    return {"ok": False, "detail": f"HTTP {r.status_code}"}


async def _probe_telesign(client: httpx.AsyncClient, customer_id: str, rest_key: str) -> dict[str, Any]:
    if not customer_id or not rest_key:
        return {"ok": False, "detail": "Telesign needs both Customer ID and Rest Key"}
    r = await client.post(
        "https://rest-ww.telesign.com/v1/phoneid/+15005550006",
        headers={"Authorization": _basic(customer_id, rest_key)},
        data={"ucid": "ATFI", "template": "phoneid"},
    )
    if r.status_code == 200:
        return {"ok": True, "detail": "Telesign credentials accepted"}
    return {"ok": False, "detail": f"HTTP {r.status_code}"}


async def _probe_truid(client: httpx.AsyncClient, client_id: str, secret: str) -> dict[str, Any]:
    if not client_id or not secret:
        return {"ok": False, "detail": "Tru.ID needs both Client ID and Client Secret"}
    r = await client.get(
        "https://api.tru.id/phone_check/v1/phonechecks",
        headers={"Authorization": _basic(client_id, secret)},
    )
    if r.status_code == 200:
        return {"ok": True, "detail": "Tru.ID credentials accepted"}
    return {"ok": False, "detail": f"HTTP {r.status_code}"}


async def live_probe(provider: str, key: str, extra: dict[str, str] | None = None) -> dict[str, Any]:
    """Probe a provider key. Returns {valid, detail, latency_ms}.

    ``key`` is the primary credential; ``extra`` may carry a paired
    credential for providers that need two (twilio, opencnam, telesign,
    truid).
    """
    provider = (provider or "").lower().strip()
    extra = extra or {}
    started = time.time()
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
            if provider == "openai":
                r = await client.get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {key}"})
                ok, detail = r.status_code == 200, f"HTTP {r.status_code}"
            elif provider == "gemini":
                r = await client.get("https://generativelanguage.googleapis.com/v1beta/models", params={"key": key})
                ok, detail = r.status_code == 200, f"HTTP {r.status_code}"
            elif provider == "anthropic":
                r = await client.get("https://api.anthropic.com/v1/models", headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
                ok, detail = r.status_code == 200, f"HTTP {r.status_code}"
            elif provider == "openrouter":
                r = await client.get("https://openrouter.ai/api/v1/auth/key", headers={"Authorization": f"Bearer {key}"})
                ok, detail = r.status_code == 200, f"HTTP {r.status_code}"
            elif provider == "huggingface":
                # HuggingFace Inference Providers — OpenAI-compatible router.
                # GET /v1/models lists models available to the token; 401/403
                # means the token is missing the "Inference Providers" scope.
                r = await client.get("https://router.huggingface.co/v1/models", headers={"Authorization": f"Bearer {key}"})
                if r.status_code == 401:
                    ok, detail = False, "Unauthorized — invalid or revoked hf_ token"
                elif r.status_code == 403:
                    ok, detail = False, "Forbidden — token lacks 'Inference Providers' permission"
                else:
                    ok = r.status_code == 200
                    detail = f"HTTP {r.status_code}" + (" (token valid, models reachable)" if ok else "")
            elif provider == "serper":
                r = await client.post("https://google.serper.dev/images", headers={"X-API-KEY": key}, json={"q": "test"})
                ok, detail = r.status_code == 200, f"HTTP {r.status_code}"
            elif provider == "mapbox":
                r = await client.get("https://api.mapbox.com/styles/v1/mapbox/streets-v12", params={"access_token": key})
                ok, detail = r.status_code == 200, f"HTTP {r.status_code}"
            elif provider == "geospy":
                # GeoSpy (Graylark) — dev.geospy.ai/predict with Bearer auth.
                # An empty body reaches body validation (422) only AFTER auth
                # passes, so 200/400/422 all prove the key without spending a
                # prediction credit.
                r = await client.post("https://dev.geospy.ai/predict", headers={"Authorization": f"Bearer {key}"}, json={})
                if r.status_code == 401:
                    ok, detail = False, "Unauthorized — invalid GeoSpy key"
                elif r.status_code == 403:
                    ok, detail = False, "Forbidden — key lacks GeoSpy access"
                else:
                    ok = r.status_code in (200, 400, 422)  # auth accepted (body empty)
                    detail = f"HTTP {r.status_code}" + (" (GeoSpy accepted key)" if ok else "")
            elif provider == "geoinfer":
                # GeoInfer — the official API is at api.geoinfer.com (NOT
                # .ai), authenticated via the X-GeoInfer-Key header.  The
                # models list is a free (no-credit) endpoint that proves the
                # key without burning a prediction.
                r = await client.get(
                    "https://api.geoinfer.com/v1/prediction/models",
                    headers={"X-GeoInfer-Key": key},
                )
                if r.status_code == 401:
                    ok, detail = False, "Unauthorized — invalid GeoInfer key"
                elif r.status_code == 403:
                    ok, detail = False, "Forbidden — key lacks model access"
                else:
                    ok = r.status_code == 200
                    detail = f"HTTP {r.status_code}" + (" (GeoInfer accepted key)" if ok else "")
            elif provider == "tineye":
                res = await _probe_tineye(client, key)
                ok, detail = res["ok"], res["detail"]
            elif provider == "tavily":
                r = await client.post(
                    "https://api.tavily.com/search",
                    headers={"Authorization": f"Bearer {key}"},
                    json={"query": "test", "max_results": 1},
                )
                ok = r.status_code == 200
                detail = f"HTTP {r.status_code}" + (" (Tavily accepted key)" if ok else "")
            elif provider == "hlr":
                res = await _probe_ipqs(client, key)
                ok, detail = res["ok"], res["detail"]
            elif provider == "opencellid":
                res = await _probe_opencellid(client, key)
                ok, detail = res["ok"], res["detail"]
            elif provider == "google_maps":
                geo = await _probe_google_maps(client, key)
                tiles = await _probe_google_tiles(client, key)
                ok = bool(geo["ok"] or tiles["ok"])
                if ok:
                    passed = " + ".join(
                        d for d in (geo["detail"] if geo["ok"] else "", tiles["detail"] if tiles["ok"] else "") if d
                    )
                    detail = f"OK — {passed}"
                else:
                    detail = f"{geo['detail']} | {tiles['detail']}"
            elif provider == "infobip":
                res = await _probe_infobip(client, key)
                ok, detail = res["ok"], res["detail"]
            elif provider == "twilio":
                res = await _probe_twilio(client, key, extra.get("twilio_auth_token", ""))
                ok, detail = res["ok"], res["detail"]
            elif provider == "opencnam":
                res = await _probe_opencnam(client, key, extra.get("opencnam_auth_token", ""))
                ok, detail = res["ok"], res["detail"]
            elif provider == "telesign":
                res = await _probe_telesign(client, key, extra.get("telesign_rest_key", ""))
                ok, detail = res["ok"], res["detail"]
            elif provider == "truid":
                res = await _probe_truid(client, key, extra.get("truid_client_secret", ""))
                ok, detail = res["ok"], res["detail"]
            else:
                ok, detail = False, f"No probe defined for provider '{provider}'"

            latency = round((time.time() - started) * 1000)
            return {"valid": ok, "detail": detail, "latency_ms": latency}
    except Exception as exc:  # noqa: BLE001
        return {
            "valid": False,
            "detail": f"Connection failed: {type(exc).__name__}",
            "latency_ms": round((time.time() - started) * 1000),
        }


def probe_description(provider: str) -> str:
    """Human-readable label describing how a provider key is validated."""
    return "Live HTTPS probe"
