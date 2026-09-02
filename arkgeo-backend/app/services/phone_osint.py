"""OSINT Aggregator — non-licensed phone-number intelligence.

Runs a set of independent workers in parallel against a single E.164 number:

  * ``e164``       — free, deterministic: country / MCC / MNC / carrier /
                     line type derived from public numbering plans.
  * ``ref``        — free: Google libphonenumber metadata (validity, number
                     type, carrier, geocoding, timezone, formats).
  * ``geo_zone``   — free: geographic registration zone from public area-code
                     and national-dialling registries.
  * ``hlr_ipqs``   — IP Quality Score phone API (carrier, live state, risk).
  * ``hlr_twilio`` — Twilio Lookup carrier API.
  * ``hlr_infobip``— Infobip Number Lookup API (live / ported / roaming).
  * ``cnam_opencnam`` — OpenCNAM Caller-ID name.
  * ``social``     — public presence *link builders* only; no account
                     enumeration is performed (see caveat in response).

Provider tiers activate only when a key is supplied (BYOK in the request, an
Admin system key in the SettingsStore, or an env var).  A missing or failing
provider never blocks the free tier — each worker is wrapped in a timeout and
reports ``requires_key`` when credentials are absent.

NO SIMULATION: every layer above is either real public reference data or a
real provider call.  The historical-billing and spam-reputation blocks are
**not** fabricated — there is no lawful keyless source for them, so they are
omitted unless a licensed provider supplies real values.

ATTRIBUTION / SOCIAL LAYER CAVEAT: live account enumeration, profile-avatar
scraping, "last seen" polling and data-leak harvesting are **not** implemented.
They require either explicit platform access approval or a licensed data
source, and are documented as gaps for operator sign-off rather than being
silently attempted.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import re
import time
from typing import Any, Callable

import httpx

from app.core.config import settings
from app.services.phone_registry import (
    derive_free_e164,
    derive_phonenumbers_intel,
    resolve_geo_zone,
)
from app.services.settings_store import settings_store

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = settings.osint_request_timeout


# --------------------------------------------------------------------------- #
# Key resolution helpers (BYOK → Admin system key → env).
# --------------------------------------------------------------------------- #
def _resolve(keys: dict[str, str] | None, name: str, env_attr: str | None = None) -> str | None:
    """Resolve a credential: request BYOK key, then Admin store, then env."""
    if keys:
        v = keys.get(name)
        if v and str(v).strip():
            return str(v).strip()
    stored = settings_store.get_key(name)
    if stored:
        return stored
    if env_attr and getattr(settings, env_attr, None):
        return str(getattr(settings, env_attr))
    return None


# --------------------------------------------------------------------------- #
# Provider workers
# --------------------------------------------------------------------------- #
def _ipqs_url(key: str, e164: str) -> str:
    # IPQS phone lookups expect a bare national/E.164 string in the path —
    # a literal '+' breaks the route (HTTP 400).
    return f"{settings.ipqs_api_url}/{key}/{e164.lstrip('+')}"


async def _worker_ipqs(e164: str, keys: dict[str, str] | None) -> dict[str, Any]:
    key = _resolve(keys, "ipqs", "hlr_api_key") or _resolve(keys, "hlr_api_key")
    if not key:
        return {"status": "requires_key", "note": "IPQS key not configured (BYOK 'ipqs' or Admin 'hlr_api_key')."}
    started = time.time()
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(_ipqs_url(key, e164))
        if r.status_code != 200:
            msg = ""
            try:
                msg = (r.json() or {}).get("message") or ""
            except Exception:  # noqa: BLE001
                msg = ""
            return {
                "status": "error",
                "note": f"IPQS HTTP {r.status_code}{(' — ' + msg) if msg else ''}",
            }
        data = r.json()
        if not data.get("success", True):
            return {"status": "error", "note": data.get("message") or "IPQS lookup failed"}
        latency = round((time.time() - started) * 1000)
        return {
            "status": "ok",
            "data": {
                "carrier": data.get("carrier") or None,
                "line_type": data.get("line_type") or None,
                "active": data.get("active"),
                "country_code": data.get("country_code"),
                "city": data.get("city"),
                "region": data.get("region"),
                "zip_code": data.get("zip_code"),
                "is_voip": data.get("is_voip"),
                "is_prepaid": data.get("is_prepaid"),
                "mcc": data.get("mcc") or None,
                "mnc": data.get("mnc") or None,
                "caller_name": data.get("caller_name") or None,
                "fraud_score": data.get("fraud_score"),
                "spam": data.get("spam"),
                "risky": data.get("risky"),
                "leaktory": data.get("leaktory"),
                "provider": f"IPQS · {latency}ms",
            },
        }
    except Exception as exc:  # noqa: BLE001 - provider failures must not block
        logger.info("IPQS lookup failed for %s: %s", e164, type(exc).__name__)
        return {"status": "error", "note": f"IPQS: {type(exc).__name__}"}


async def _worker_twilio(e164: str, keys: dict[str, str] | None) -> dict[str, Any]:
    sid = _resolve(keys, "twilio_account_sid", "twilio_account_sid")
    token = _resolve(keys, "twilio_auth_token", "twilio_auth_token")
    if not sid or not token:
        return {"status": "requires_key", "note": "Twilio Lookup credentials not configured."}
    try:
        basic = base64.b64encode(f"{sid}:{token}".encode()).decode()
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(
                f"{settings.twilio_lookup_url}/{e164.lstrip('+')}",
                params={"Type": "carrier"},
                headers={"Authorization": f"Basic {basic}"},
            )
        if r.status_code != 200:
            return {"status": "error", "note": f"Twilio HTTP {r.status_code}"}
        data = r.json()
        carrier = data.get("carrier") or {}
        if carrier.get("error_code"):
            return {"status": "error", "note": f"Twilio carrier lookup error {carrier['error_code']}"}
        return {
            "status": "ok",
            "data": {
                "carrier": carrier.get("name") or None,
                "line_type": carrier.get("type") or None,
                "mcc": carrier.get("mobile_country_code") or None,
                "mnc": carrier.get("mobile_network_code") or None,
                "country_code": data.get("country_code"),
                "provider": "Twilio Lookup",
            },
        }
    except Exception as exc:  # noqa: BLE001
        logger.info("Twilio lookup failed for %s: %s", e164, type(exc).__name__)
        return {"status": "error", "note": f"Twilio: {type(exc).__name__}"}


async def _worker_infobip(e164: str, keys: dict[str, str] | None) -> dict[str, Any]:
    key = _resolve(keys, "infobip", "infobip_api_key") or _resolve(keys, "infobip_api_key")
    if not key:
        return {"status": "requires_key", "note": "Infobip key not configured."}
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(
                settings.infobip_lookup_url,
                params={"to": e164},
                headers={"Authorization": f"App {key}"},
            )
        if r.status_code != 200:
            return {"status": "error", "note": f"Infobip HTTP {r.status_code}"}
        data = r.json()
        operator = data.get("operator") or {}
        return {
            "status": "ok",
            "data": {
                "carrier": operator.get("name") or None,
                "mcc_mnc": operator.get("networkCode") or None,
                "ported": data.get("ported"),
                "roaming": data.get("roaming"),
                "roaming_country": (data.get("roamingInfo") or {}).get("country") if isinstance(data.get("roamingInfo"), dict) else None,
                "live": data.get("live") or (data.get("status") or {}).get("groupName"),
                "country_code": (data.get("country") or {}).get("code"),
                "provider": "Infobip",
            },
        }
    except Exception as exc:  # noqa: BLE001
        logger.info("Infobip lookup failed for %s: %s", e164, type(exc).__name__)
        return {"status": "error", "note": f"Infobip: {type(exc).__name__}"}


async def _worker_opencnam(e164: str, keys: dict[str, str] | None) -> dict[str, Any]:
    sid = _resolve(keys, "opencnam_account_sid", "opencnam_account_sid")
    token = _resolve(keys, "opencnam_auth_token", "opencnam_auth_token")
    if not sid or not token:
        return {"status": "requires_key", "note": "OpenCNAM credentials not configured."}
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(
                f"{settings.opencnam_api_url}/{e164.lstrip('+')}",
                params={"format": "json", "account_sid": sid, "auth_token": token},
            )
        if r.status_code != 200:
            return {"status": "error", "note": f"OpenCNAM HTTP {r.status_code}"}
        data = r.json()
        if "message" in data:
            return {"status": "error", "note": data["message"]}
        return {"status": "ok", "data": {"caller_name": data.get("name") or None, "provider": "OpenCNAM"}}
    except Exception as exc:  # noqa: BLE001
        logger.info("OpenCNAM lookup failed for %s: %s", e164, type(exc).__name__)
        return {"status": "error", "note": f"OpenCNAM: {type(exc).__name__}"}


async def _worker_social(e164: str, keys: dict[str, str] | None) -> dict[str, Any]:
    """Public presence link builders (no enumeration). Returns links the
    operator can open in a browser; existence must be verified by the operator
    or via an approved platform integration."""
    e = e164.lstrip("+")
    return {
        "status": "ok",
        "data": {
            "presence_links": [
                {"platform": "WhatsApp", "kind": "chat link", "url": f"https://wa.me/{e}"},
                {"platform": "Telegram", "kind": "invite-by-number", "url": f"https://t.me/+{e}"},
                {"platform": "Viber", "kind": "chat link", "url": f"viber://chat?number=%2B{e}"},
                {"platform": "Signal", "kind": "signal.me", "url": f"https://signal.me/#p/%2B{e}"},
            ],
            "note": "Presence links only — live profile, avatar or last-seen "
                    "enumeration requires approved platform integration.",
        },
    }


async def _worker_directory(e164: str, keys: dict[str, str] | None) -> dict[str, Any]:
    """Best-effort keyless name resolution from public phone directories.

    These are server-rendered lookups only — no account enumeration, no
    platform scraping of private profiles. Most directories (Truecaller,
    Sync.me, etc.) are JS-gated and will not return a name via plain HTTP; this
    worker reports whatever a directory *does* expose and never fabricates a
    name. For numbers outside those directories (or behind JS) the result is
    simply empty, and the licensed CNAM/IPQS tier remains the authoritative
    path for caller-name.
    """
    e = e164.lstrip("+")
    # Country hint from the E.164 prefix (NG -> ng); only add Truecaller when known.
    cc = "ng" if e.startswith("234") else ""
    sources = [
        ("truecaller", f"https://www.truecaller.com/search/{cc}/{e}") if cc else None,
        ("syncme", f"https://sync.me/phone/{e}/"),
    ]
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    # Generic page titles / boilerplate that must NOT be mistaken for a name.
    _BOILER = (
        "truecaller", "lookup", "phone number", "who called", "find out",
        "sync.me", "shouldianswer", "reverse", "caller", "directory",
    )
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, headers=headers) as client:
            for entry in sources:
                if not entry:
                    continue
                name, url = entry
                try:
                    r = await client.get(url)
                except Exception:  # noqa: BLE001
                    continue
                t = r.text
                for pat in (
                    r'"name"\s*:\s*"([^"]{2,60})"',
                    r'property="og:title"\s+content="([^"]{2,60})"',
                ):
                    m = re.search(pat, t)
                    if not m:
                        continue
                    cand = m.group(1).strip()
                    low = cand.lower()
                    if any(b in low for b in _BOILER):
                        continue
                    if len(cand) < 2 or len(cand) > 60:
                        continue
                    return {
                        "status": "ok",
                        "data": {"caller_name": cand, "provider": name, "simulated": False},
                    }
    except Exception:  # noqa: BLE001
        pass
    return {"status": "ok", "data": {"caller_name": None}, "note": "No keyless directory exposed a name."}


async def _worker_simswap(e164: str, keys: dict[str, str] | None) -> dict[str, Any]:
    """SIM-swap / SIM-last-changed indicators.

    Provider order: Telesign PhoneID → Tru.ID phone_check.  Neither provider
    is probed without its key — the worker reports ``requires_key`` instead of
    inventing a swap verdict.
    """
    ts_cust = _resolve(keys, "telesign_customer_id", "telesign_customer_id")
    ts_key = _resolve(keys, "telesign_rest_key", "telesign_rest_key")
    truid_id = _resolve(keys, "truid_client_id", "truid_client_id")
    truid_secret = _resolve(keys, "truid_client_secret", "truid_client_secret")

    if ts_cust and ts_key:
        try:
            basic = base64.b64encode(f"{ts_cust}:{ts_key}".encode()).decode()
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
                r = await client.get(
                    f"{settings.telesign_api_url}/{e164.lstrip('+')}",
                    params={"fields": "sim_swap,device,number_type"},
                    headers={"Authorization": f"Basic {basic}"},
                )
            if r.status_code == 200:
                data = r.json()
                ss = data.get("sim_swap") or {}
                swapped = ss.get("sim_swap_status") in ("yes", "true", True)
                return {
                    "status": "ok",
                    "data": {
                        "sim_swap": swapped,
                        "sim_last_changed": ss.get("device_change_date") or None,
                        "same_device_score": ss.get("same_device") if ss.get("same_device") is not None else None,
                        "risk": 0.85 if swapped else 0.0,
                        "provider": "Telesign PhoneID",
                        "simulated": False,
                    },
                }
            return {"status": "error", "note": f"Telesign HTTP {r.status_code}"}
        except Exception as exc:  # noqa: BLE001
            logger.info("Telesign lookup failed for %s: %s", e164, type(exc).__name__)
            return {"status": "error", "note": f"Telesign: {type(exc).__name__}"}

    if truid_id and truid_secret:
        try:
            basic = base64.b64encode(f"{truid_id}:{truid_secret}".encode()).decode()
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
                r = await client.post(
                    settings.truid_api_url,
                    json={"phone_number": e164},
                    headers={"Authorization": f"Basic {basic}"},
                )
            if r.status_code in (200, 201):
                data = r.json()
                ss = data.get("sim_swap") or {}
                swapped = ss.get("sim_swap_occured") in (True, "true", "yes")
                return {
                    "status": "ok",
                    "data": {
                        "sim_swap": swapped,
                        "sim_last_changed": ss.get("device_change_date") or None,
                        "same_device_score": None,
                        "risk": 0.85 if swapped else 0.0,
                        "provider": "Tru.ID Phone Check",
                        "simulated": False,
                    },
                }
            return {"status": "error", "note": f"Tru.ID HTTP {r.status_code}"}
        except Exception as exc:  # noqa: BLE001
            logger.info("Tru.ID lookup failed for %s: %s", e164, type(exc).__name__)
            return {"status": "error", "note": f"Tru.ID: {type(exc).__name__}"}

    return {
        "status": "requires_key",
        "note": "SIM-swap indicators need a Telesign PhoneID or Tru.ID key (BYOK or Admin system key).",
    }


async def _worker_footprint(e164: str, keys: dict[str, str] | None) -> dict[str, Any]:
    """Digital-footprint indicators for the OSINT matrix.

    When ``ARKGEO_SOCIAL_PROBE_ENABLED`` is true the worker actively probes
    public platform resolvers (availability signal only — no account data is
    scraped).  When disabled it reports ``requires_key`` rather than returning
    a fabricated footprint.
    """
    e = e164.lstrip("+")
    if settings.social_probe_enabled:
        urls = {
            "whatsapp": f"https://wa.me/{e}",
            "telegram": f"https://t.me/+{e}",
            "viber": f"https://chats.viber.com/{e}",
            "signal": f"https://signal.me/#p/%2B{e}",
        }
        probes = []
        async with httpx.AsyncClient(timeout=settings.social_probe_timeout, follow_redirects=True) as client:
            for platform, url in urls.items():
                try:
                    r = await client.get(url)
                    probes.append({"platform": platform, "status_code": r.status_code, "reachable": r.status_code < 400})
                except Exception:  # noqa: BLE001
                    probes.append({"platform": platform, "status_code": 0, "reachable": False})
        presence = {p["platform"]: p["reachable"] for p in probes}
        return {
            "status": "ok",
            "data": {
                "presence": presence,
                "probed": True,
                "simulated": False,
                "note": "Active probes against public platform resolvers — availability signal only.",
                "probes": probes,
            },
        }
    return {
        "status": "requires_key",
        "note": ("Digital-footprint probes disabled — set "
                 "ARKGEO_SOCIAL_PROBE_ENABLED=true (availability probes only; "
                 "no account enumeration)."),
    }


async def _run_worker(name: str, coro: Callable[[], Any]) -> dict[str, Any]:
    try:
        return {"name": name, **await asyncio.wait_for(coro(), timeout=_DEFAULT_TIMEOUT)}
    except asyncio.TimeoutError:
        return {"name": name, "status": "error", "note": "timeout"}
    except Exception as exc:  # noqa: BLE001
        return {"name": name, "status": "error", "note": type(exc).__name__}


def _merge(workers: dict[str, dict[str, Any]], free: dict[str, Any], intel: dict[str, Any], geo_zone: str | None) -> dict[str, Any]:
    """Collapse per-worker outputs into a single aggregated intelligence view."""
    def first(*names: str, field: str):
        for n in names:
            w = workers.get(n)
            if w and w.get("status") == "ok":
                v = (w.get("data") or {}).get(field)
                if v is not None:
                    return v
        return None

    hlr_fields = {
        "carrier": first("hlr_ipqs", "hlr_twilio", "hlr_infobip", field="carrier"),
        "line_type": first("hlr_ipqs", "hlr_twilio", field="line_type"),
        "mcc": first("hlr_ipqs", "hlr_twilio", field="mcc"),
        "mnc": first("hlr_ipqs", "hlr_twilio", field="mnc"),
        "active": first("hlr_ipqs", field="active"),
        "ported": first("hlr_infobip", field="ported"),
        "roaming_country": first("hlr_infobip", field="roaming_country"),
        "live": first("hlr_infobip", field="live"),
    }
    ipqs_data = (workers.get("hlr_ipqs") or {}).get("data") or {}
    risk = {}
    if ipqs_data.get("fraud_score") is not None:
        risk = {
            "fraud_score": ipqs_data.get("fraud_score"),
            "spam": ipqs_data.get("spam"),
            "risky": ipqs_data.get("risky"),
            "leaktory": ipqs_data.get("leaktory"),
            "is_voip": ipqs_data.get("is_voip"),
            "is_prepaid": ipqs_data.get("is_prepaid"),
        }
    caller = first("cnam_opencnam", "hlr_ipqs", "directory", field="caller_name")

    simswap = (workers.get("simswap") or {}).get("data") or {}
    footprint = (workers.get("footprint") or {}).get("data") or {}

    # Reputation is only ever real: live IPQS risk fields when a key is
    # configured. Nothing is fabricated when the provider tier is absent.
    rep = {}
    if risk.get("fraud_score") is not None:
        rep = {
            "spam_score": risk["fraud_score"],
            "spam": risk.get("spam"),
            "risky": risk.get("risky"),
            "leaktory": risk.get("leaktory"),
            "fraud_score": risk["fraud_score"],
            "is_voip": risk.get("is_voip"),
            "is_prepaid": risk.get("is_prepaid"),
            "simulated": False,
            "note": "Risk indicators from configured provider tier (IPQS).",
        }

    return {
        "carrier": hlr_fields["carrier"] or intel.get("carrier") or free.get("carrier"),
        "mcc": hlr_fields["mcc"] or free.get("mcc"),
        "mnc": hlr_fields["mnc"] or free.get("mnc"),
        "line_type": hlr_fields["line_type"] or free.get("line_type") or intel.get("number_type"),
        "active": hlr_fields["active"],
        "ported": hlr_fields["ported"],
        "roaming_country": hlr_fields["roaming_country"],
        "live_state": hlr_fields["live"],
        "caller_name": caller,
        "risk": risk,
        "geo_zone": geo_zone,
        "location_hint": ipqs_data.get("city") or None,
        "sim_last_changed": simswap.get("sim_last_changed") or None,
        "sim_swap_risk": simswap.get("risk"),
        "sim_swap": simswap.get("sim_swap"),
        "same_device_score": simswap.get("same_device_score"),
        "line_state": None,  # computed in run_osint (needs provider context)
        "footprint": footprint,
        "reputation": rep,
        "provider_note": " | ".join(
            (w.get("data") or {}).get("provider", "")
            for w in workers.values()
            if w.get("status") == "ok" and (w.get("data") or {}).get("provider")
        ),
    }


async def run_osint(phone: str, keys: dict[str, str] | None = None) -> dict[str, Any]:
    """Run the full OSINT aggregation pipeline for an E.164 number."""
    keys = dict(keys or {})
    free = derive_free_e164(phone)
    if not free.get("ok"):
        return {"ok": False, "reason": free.get("reason", "unparseable number")}
    intel = derive_phonenumbers_intel(phone)

    geo_zone = None
    if free.get("iso2") and free.get("sn"):
        geo_zone = resolve_geo_zone(free["iso2"], free["sn"])

    workers = await asyncio.gather(
        _run_worker("hlr_ipqs", lambda: _worker_ipqs(phone, keys)),
        _run_worker("hlr_twilio", lambda: _worker_twilio(phone, keys)),
        _run_worker("hlr_infobip", lambda: _worker_infobip(phone, keys)),
        _run_worker("cnam_opencnam", lambda: _worker_opencnam(phone, keys)),
        _run_worker("social", lambda: _worker_social(phone, keys)),
        _run_worker("simswap", lambda: _worker_simswap(phone, keys)),
        _run_worker("footprint", lambda: _worker_footprint(phone, keys)),
        _run_worker("directory", lambda: _worker_directory(phone, keys)),
    )
    by_name: dict[str, dict[str, Any]] = {w["name"]: w for w in workers}

    merged = _merge(by_name, free, intel, geo_zone)

    # No-licence coarse region estimate from the open cell-tower DB (E.164 ->
    # MCC -> operator region centroid). Never a device fix — clearly labelled.
    try:
        from app.services.cell_geolocator import geolocate_by_phone
        nlr = geolocate_by_phone(phone)
        no_license_region = {
            "lat": nlr.lat, "lon": nlr.lon, "radius_m": nlr.radius_m,
            "confidence": nlr.confidence, "method": nlr.method,
            "operator": nlr.operator, "towers_used": nlr.towers_used,
        }
    except Exception:  # noqa: BLE001
        no_license_region = None

    # Live ON/OFF + roaming require a real HLR provider; without a key there is
    # no lawful way to know whether a line is currently attached, so the state
    # is left unknown rather than fabricated.
    has_hlr_provider = any(
        name.startswith("hlr_") and w.get("status") == "ok"
        for name, w in by_name.items()
    )
    active = merged["active"]
    line_state = None
    if active is True:
        line_state = "ACTIVE / ONLINE"
    elif active is False:
        line_state = "DISCONNECTED"
    elif merged["live_state"]:
        line_state = f"LIVE · {merged['live_state']}"

    requires_key = [
        name for name, w in by_name.items()
        if w.get("status") == "requires_key"
    ]
    if not has_hlr_provider:
        requires_key.append("line-state")
    requires_key.sort()

    return {
        "ok": True,
        "phone_e164": free["phone_e164"],
        "country_code": free["country_code"],
        "iso2": intel.get("iso2") or free["iso2"],
        "carrier": merged["carrier"],
        "mcc": merged["mcc"],
        "mnc": merged["mnc"],
        "line_type": merged["line_type"],
        "valid": bool(intel.get("valid")),
        "possible": bool(intel.get("possible")),
        "number_type": intel.get("number_type"),
        "national_number": intel.get("national_number"),
        "ndc": intel.get("ndc"),
        "subscriber_number": intel.get("subscriber_number"),
        "national_format": intel.get("national_format") or "",
        "international_format": intel.get("international_format") or "",
        "geo_city": intel.get("geo_city"),
        "routing_location": intel.get("routing_location"),
        "timezone": intel.get("timezone") or [],
        "geo_zone": merged["geo_zone"],
        "active": merged["active"],
        "ported": merged["ported"],
        "roaming_country": merged["roaming_country"],
        "live_state": merged["live_state"],
        "line_state": line_state,
        "sim_last_changed": merged["sim_last_changed"],
        "sim_swap_risk": merged["sim_swap_risk"],
        "same_device_score": merged["same_device_score"],
        "caller_name": merged["caller_name"],
        "risk": merged["risk"],
        "reputation": merged["reputation"],
        "footprint": merged["footprint"],
        "location_hint": merged["location_hint"],
        "provider_note": merged["provider_note"],
        "requires_key": requires_key,
        "free_source": free["source"],
        "no_license_region": no_license_region,
        "workers": by_name,
    }
