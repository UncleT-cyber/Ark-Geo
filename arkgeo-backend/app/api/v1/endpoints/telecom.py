"""Telecom & Phone Intelligence — passive OSINT endpoints.

Phone parsing itself runs client-side (E.164). The backend resolves the
lookup key through the global chain and queries public/commercial APIs:

  * ``POST /telecom/hlr-lookup`` — HLR / line-type carrier telemetry (IPQS).
  * ``POST /telecom/cell-lookup`` — cell tower spatial resolution
    (OpenCelliD keyed API or beaconDB free API).

Key resolution for outbound lookups:
  client-supplied BYOK key (request body, never stored/logged)
  → admin system key (encrypted SettingsStore)
  → structured ``requires_key`` response.

These endpoints perform passive lookups only. No signaling-network access,
no silent-SMS, no IMSI-catcher functionality is implemented or intended.
"""
from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.cell_geolocator import get_store, ensure_seed, geolocate_by_phone  # noqa: F401
from app.services.phone_analysis import run_phone_analysis
from app.services.phone_osint import run_osint
from app.services.phone_registry import derive_free_e164, derive_phonenumbers_intel, resolve_geo_zone
from app.services.settings_store import settings_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telecom")

# Keyless community BeaconDB instance (successor to Mozilla Location Services).
# No API key required — submissions/lookups are accepted anonymously (rate-limited).
BEACONDB_OPEN_URL = "https://beacondb.net/api/geolocate"

# Make sure the embedded seed is loaded so the local DB is useful immediately.
ensure_seed()

_DEFAULT_TIMEOUT = 8.0


# --------------------------------------------------------------------------- #
# Carrier → MCC/MNC best-effort derivation (public carrier registry facts).
# --------------------------------------------------------------------------- #
_CARRIER_MCC_MNC: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("mtn",), "621", "30"),
    (("airtel",), "621", "20"),
    (("glo",), "621", "50"),
    (("9mobile", "etisalat"), "621", "60"),
    (("smile",), "621", "00"),
    (("starlink", "spacex"), "621", "00"),
    (("at&t", "att"), "310", "410"),
    (("t-mobile", "tmobile"), "310", "260"),
    (("verizon",), "310", "004"),
    (("vodafone",), "234", "15"),
    (("o2",), "234", "10"),
    (("orange",), "208", "01"),
    (("telenor",), "242", "01"),
    (("telia",), "240", "01"),
    (("etisalat",), "424", "03"),
)


def derive_mcc_mnc(carrier: str | None) -> dict[str, str]:
    """Best-effort MCC/MNC from the carrier name. Returns {} when unknown."""
    if not carrier:
        return {}
    name = carrier.lower()
    for subs, mcc, mnc in _CARRIER_MCC_MNC:
        if any(s in name for s in subs):
            return {"mcc": mcc, "mnc": mnc}
    return {}


def normalize_e164(phone: str) -> str:
    """Return a canonical +CCNNNNNNNNN or raise on obviously invalid input."""
    cleaned = "".join(ch for ch in phone.strip() if ch.isdigit())
    if not cleaned.startswith(("0", "1", "2", "3", "4", "5", "6", "7", "8", "9")):
        raise HTTPException(status_code=422, detail="Phone must be numeric E.164")
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]
    if not (7 <= len(cleaned) <= 15):
        raise HTTPException(status_code=422, detail="Phone length outside E.164 range (7-15 digits)")
    return f"+{cleaned}"


class HlrLookupRequest(BaseModel):
    phone: str = Field(..., description="International phone number (E.164)")
    provider: str = Field("ipqs", description="HLR provider id")
    api_key: Optional[str] = Field(None, description="Client BYOK key (never stored/logged)")


class HlrLookupResponse(BaseModel):
    looked_up: bool
    requires_key: bool = False
    live_state_available: bool = False
    phone_e164: str = ""
    country_code: Optional[str] = None
    iso2: Optional[str] = None
    line_type: Optional[str] = None
    carrier: Optional[str] = None
    carrier_ported: Optional[str] = None
    active: Optional[bool] = None
    mcc: Optional[str] = None
    mnc: Optional[str] = None
    location: Optional[dict] = None
    is_voip: Optional[bool] = None
    is_prepaid: Optional[bool] = None
    caller_name: Optional[str] = None
    region: Optional[str] = None
    zip_code: Optional[str] = None
    fraud_score: Optional[int] = None
    valid: bool = False
    possible: bool = False
    number_type: Optional[str] = None
    national_number: Optional[str] = None
    ndc: Optional[str] = None
    subscriber_number: Optional[str] = None
    national_format: str = ""
    international_format: str = ""
    geo_city: Optional[str] = None
    routing_location: Optional[str] = None
    timezone: list[str] = Field(default_factory=list)
    detail: str = ""


async def _resolve_hlr_key(requested: str | None) -> str | None:
    if requested and requested.strip():
        return requested.strip()
    store = settings_store
    return store.get_key("hlr_api_key")


def _free_tier_lookup(phone: str, note: str = "") -> HlrLookupResponse:
    """Keyless registry intelligence from public numbering plans.

    Deterministic, no network call. Used directly when no provider key is
    configured, and as a graceful fallback when a configured provider fails
    (non-200 / transport error / unusable payload) so the keyless facts still
    render instead of an empty 400 shell.
    """
    free = derive_free_e164(phone)
    if not free.get("ok"):
        return HlrLookupResponse(
            looked_up=False, requires_key=True, phone_e164=phone,
            detail=f"Unparseable number: {free.get('reason', 'unknown')}.",
        )
    intel = derive_phonenumbers_intel(phone)
    zone = resolve_geo_zone(free["iso2"], free["sn"]) if free.get("iso2") and free.get("sn") else None
    base = "Free tier · Google libphonenumber metadata + public numbering plans."
    if note:
        base = f"{base} {note}"
    base = (base + " Live ON/OFF, porting and roaming state need a working HLR "
            "API key (set a client BYOK key or an Admin system key).")
    return HlrLookupResponse(
        looked_up=True,
        requires_key=False,
        live_state_available=False,
        phone_e164=intel.get("e164") or phone,
        country_code=free.get("country_code"),
        iso2=intel.get("iso2") or free.get("iso2"),
        line_type=free.get("line_type") or intel.get("number_type"),
        carrier=intel.get("carrier") or free.get("carrier"),
        mcc=free.get("mcc"),
        mnc=free.get("mnc"),
        valid=bool(intel.get("valid")),
        possible=bool(intel.get("possible")),
        number_type=intel.get("number_type"),
        national_number=intel.get("national_number"),
        ndc=intel.get("ndc"),
        subscriber_number=intel.get("subscriber_number"),
        national_format=intel.get("national_format") or "",
        international_format=intel.get("international_format") or "",
        geo_city=intel.get("geo_city"),
        routing_location=intel.get("routing_location"),
        timezone=intel.get("timezone") or [],
        location={"zone": zone, "iso2": intel.get("iso2") or free.get("iso2"), "city": intel.get("geo_city"), "routing_location": intel.get("routing_location")} if (zone or intel.get("geo_city") or free.get("iso2")) else None,
        detail=base,
    )


@router.post("/hlr-lookup", response_model=HlrLookupResponse)
async def hlr_lookup(body: HlrLookupRequest):
    phone = normalize_e164(body.phone)
    key = await _resolve_hlr_key(body.api_key)
    if not key:
        # Free tier — registry-derived intelligence from public numbering
        # plans. No key, no external call, fully deterministic.
        return _free_tier_lookup(phone)

    started = time.time()
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(
                f"https://ipqualityscore.com/api/json/phone/{key}/{phone}"
            )
        latency = round((time.time() - started) * 1000)
        if r.status_code != 200:
            # Provider rejected the request (bad key, region, plan limit) —
            # never blank the keyless facts. Degrade gracefully.
            return _free_tier_lookup(
                phone,
                note=f"Configured HLR provider returned HTTP {r.status_code} (latency {latency}ms) — keyless facts shown.",
            )
        data = r.json()
        if not isinstance(data, dict) or data.get("success") is False:
            return _free_tier_lookup(
                phone,
                note=f"Configured HLR provider rejected the lookup ({data.get('message', 'unknown') if isinstance(data, dict) else 'unusable payload'}) — keyless facts shown.",
            )
    except Exception as exc:  # noqa: BLE001
        return _free_tier_lookup(
            phone,
            note=f"Configured HLR provider errored ({type(exc).__name__}) — keyless facts shown.",
        )

    carrier = (data.get("carrier") or None) if data.get("carrier") else None
    mcc_mnc = derive_mcc_mnc(carrier)
    intel = derive_phonenumbers_intel(phone) if mcc_mnc.get("mcc") else {}
    city = (data.get("city") or None)
    routing_location = None
    if not city or (intel.get("routing_location") and city and intel.get("geo_city") is None):
        routing_location = intel.get("routing_location") or None
        city = None

    return HlrLookupResponse(
        looked_up=True,
        live_state_available=True,
        phone_e164=data.get("e164") or phone,
        country_code=data.get("country_code"),
        line_type=(data.get("line_type") or None),
        carrier=carrier,
        carrier_ported=None,  # IPQS does not expose porting state
        active=(data.get("active") if data.get("active") is not None else None),
        mcc=mcc_mnc.get("mcc"),
        mnc=mcc_mnc.get("mnc"),
        location={
            "city": city,
            "region": data.get("region"),
            "zip_code": data.get("zip_code"),
            "country": data.get("country"),
            "routing_location": routing_location,
        },
        geo_city=city,
        routing_location=routing_location,
        is_voip=bool(data.get("is_voip")),
        is_prepaid=bool(data.get("is_prepaid")),
        caller_name=(data.get("caller_name") or None),
        region=(data.get("region") or None),
        zip_code=(data.get("zip_code") or None),
        fraud_score=data.get("fraud_score"),
        detail=f"Provider: IPQS · latency {latency}ms",
    )


class PresenceProbeResponse(BaseModel):
    ok: bool
    phone_e164: str = ""
    probed: bool = False
    simulated: bool = False
    enabled: bool = False
    presence: dict[str, bool] = Field(default_factory=dict)
    probes: list[dict[str, Any]] = Field(default_factory=list)
    presence_links: list[dict[str, str]] = Field(default_factory=list)
    note: str = ""


@router.post("/presence-probe", response_model=PresenceProbeResponse)
async def presence_probe(body: HlrLookupRequest):
    """Keyless digital-footprint availability probe.

    Legal availability checks against public platform resolvers
    (wa.me / t.me / chats.viber.com / signal.me) — an availability signal
    only, never account enumeration. No license gate: these probes run for
    the free tier too, matching the certified ``/signaling/osint`` footprint.
    """
    from app.services.phone_osint import _worker_footprint, _worker_social

    phone = normalize_e164(body.phone)
    footprint = await _worker_footprint(phone, None)
    social = await _worker_social(phone, None)
    data = footprint.get("data") or {}
    links = (social.get("data") or {}).get("presence_links") or []
    return PresenceProbeResponse(
        ok=footprint.get("status") == "ok",
        phone_e164=phone,
        probed=bool(data.get("probed")),
        simulated=bool(data.get("simulated")),
        enabled=settings.social_probe_enabled,
        presence=data.get("presence") or {},
        probes=data.get("probes") or [],
        presence_links=links,
        note=str(data.get("note") or social.get("data", {}).get("note") or ""),
    )


class CellLookupRequest(BaseModel):
    mcc: int = Field(..., description="Mobile Country Code")
    mnc: int = Field(..., description="Mobile Network Code")
    lac: Optional[int] = Field(None, description="Location Area Code")
    cell_id: int = Field(..., description="Cell Tower ID")
    provider: str = Field("opencellid", description="opencellid | beacondb | beacondb-open | local")
    api_key: Optional[str] = Field(None, description="OpenCelliD key (BYOK; never stored/logged)")


class CellLookupResponse(BaseModel):
    looked_up: bool
    requires_key: bool = False
    provider: str = ""
    mcc: int
    mnc: int
    lac: Optional[int] = None
    cell_id: int
    lat: Optional[float] = None
    lon: Optional[float] = None
    range_meters: Optional[float] = None
    radio: Optional[str] = None
    samples: Optional[int] = None
    method: Optional[str] = None
    confidence: Optional[float] = None
    towers_used: Optional[int] = None
    detail: str = ""


@router.post("/cell-lookup", response_model=CellLookupResponse)
async def cell_lookup(body: CellLookupRequest):
    provider = (body.provider or "opencellid").lower().strip()

    if provider == "local":
        # Keyless, offline local open cell-tower DB (no provider licence).
        store = get_store()
        res = store.resolve_cgi(body.mcc, body.mnc, body.lac, body.cell_id)
        return CellLookupResponse(
            looked_up=res.lat is not None,
            provider="local",
            mcc=body.mcc, mnc=body.mnc, lac=body.lac, cell_id=body.cell_id,
            lat=res.lat, lon=res.lon, range_meters=res.radius_m,
            radio=None, samples=res.towers_used,
            method=res.method, confidence=res.confidence,
            towers_used=res.towers_used,
            detail=res.detail or "Local open cell DB resolution.",
        )

    if provider == "beacondb-open":
        # Keyless community BeaconDB instance (no API key, rate-limited).
        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
                r = await client.post(
                    BEACONDB_OPEN_URL,
                    json={
                        "radioType": "gsm",
                        "cellTowers": [{
                            "mobileCountryCode": body.mcc,
                            "mobileNetworkCode": body.mnc,
                            "locationAreaCode": body.lac or 0,
                            "cellId": body.cell_id,
                        }],
                    },
                )
            if r.status_code != 200:
                return CellLookupResponse(
                    looked_up=True, provider=provider,
                    mcc=body.mcc, mnc=body.mnc, lac=body.lac, cell_id=body.cell_id,
                    detail=f"BeaconDB-open returned HTTP {r.status_code}",
                )
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            return CellLookupResponse(
                looked_up=True, provider=provider,
                mcc=body.mcc, mnc=body.mnc, lac=body.lac, cell_id=body.cell_id,
                detail=f"BeaconDB-open lookup failed: {type(exc).__name__}",
            )
        loc = data.get("location") or {}
        acc = data.get("accuracy")
        if loc.get("lat") is None or loc.get("lng") is None:
            return CellLookupResponse(
                looked_up=True, provider=provider,
                mcc=body.mcc, mnc=body.mnc, lac=body.lac, cell_id=body.cell_id,
                detail="Cell not found in BeaconDB-open community DB.",
            )
        return CellLookupResponse(
            looked_up=True, provider=provider,
            mcc=body.mcc, mnc=body.mnc, lac=body.lac, cell_id=body.cell_id,
            lat=float(loc["lat"]), lon=float(loc["lng"]),
            range_meters=float(acc) if acc else None,
            method="exact_cgi", confidence=0.8,
            detail=f"BeaconDB-open · accuracy={acc}",
        )

    if provider == "opencellid":
        key = body.api_key.strip() if body.api_key else None
        if not key:
            store = settings_store
            key = store.get_key("opencellid_api_key")
        if not key:
            return CellLookupResponse(
                looked_up=False, requires_key=True, provider=provider,
                mcc=body.mcc, mnc=body.mnc, lac=body.lac, cell_id=body.cell_id,
                detail="No OpenCelliD API key configured — set a client BYOK key or an Admin system key.",
            )
        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
                r = await client.get(
                    "https://opencellid.org/ajax/getCell.php",
                    params={
                        "key": key,
                        "mcc": body.mcc,
                        "mnc": body.mnc,
                        "lac": body.lac or "",
                        "cell_id": body.cell_id,
                        "format": "json",
                    },
                )
            if r.status_code != 200:
                return CellLookupResponse(
                    looked_up=True, provider=provider,
                    mcc=body.mcc, mnc=body.mnc, lac=body.lac, cell_id=body.cell_id,
                    detail=f"OpenCelliD returned HTTP {r.status_code}",
                )
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            return CellLookupResponse(
                looked_up=True, provider=provider,
                mcc=body.mcc, mnc=body.mnc, lac=body.lac, cell_id=body.cell_id,
                detail=f"Cell lookup failed: {type(exc).__name__}",
            )
        if data.get("lat") is None or data.get("lon") is None:
            return CellLookupResponse(
                looked_up=True, provider=provider,
                mcc=body.mcc, mnc=body.mnc, lac=body.lac, cell_id=body.cell_id,
                detail=data.get("error") or "Cell not found in OpenCelliD.",
            )
        return CellLookupResponse(
            looked_up=True, provider=provider,
            mcc=body.mcc, mnc=body.mnc, lac=body.lac, cell_id=body.cell_id,
            lat=float(data.get("lat")), lon=float(data.get("lon")),
            range_meters=float(data.get("range") or 0) or None,
            radio=data.get("radio"),
            samples=data.get("samples"),
            detail=f"OpenCelliD · samples={data.get('samples', '?')}",
        )

    if provider == "beacondb":
        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
                r = await client.post(
                    "https://api.beaconfyre.com/v2/cell/lookup",
                    json={
                        "mcc": body.mcc, "mnc": body.mnc,
                        "lac": body.lac or 0, "cellid": body.cell_id,
                        "format": "json",
                    },
                )
            if r.status_code != 200:
                return CellLookupResponse(
                    looked_up=True, provider=provider,
                    mcc=body.mcc, mnc=body.mnc, lac=body.lac, cell_id=body.cell_id,
                    detail=f"beaconDB returned HTTP {r.status_code}",
                )
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            return CellLookupResponse(
                looked_up=True, provider=provider,
                mcc=body.mcc, mnc=body.mnc, lac=body.lac, cell_id=body.cell_id,
                detail=f"Cell lookup failed: {type(exc).__name__}",
            )
        results = data.get("results") or []
        hit = results[0] if results else None
        if not hit or hit.get("lat") is None or hit.get("lon") is None:
            return CellLookupResponse(
                looked_up=True, provider=provider,
                mcc=body.mcc, mnc=body.mnc, lac=body.lac, cell_id=body.cell_id,
                detail="Cell not found in beaconDB.",
            )
        return CellLookupResponse(
            looked_up=True, provider=provider,
            mcc=body.mcc, mnc=body.mnc, lac=body.lac, cell_id=body.cell_id,
            lat=float(hit.get("lat")), lon=float(hit.get("lon")),
            range_meters=float(hit.get("range") or 0) or None,
            detail=f"beaconDB · samples={hit.get('samples', '?')}",
        )

    raise HTTPException(status_code=422, detail="Unsupported provider (opencellid | beacondb | beacondb-open | local)")


# --------------------------------------------------------------------------- #
# Keyless geolocation endpoints (no provider licence).
# --------------------------------------------------------------------------- #

class PhoneLocateRequest(BaseModel):
    phone: str = Field(..., description="International phone number (E.164)")


class PhoneLocateResponse(BaseModel):
    looked_up: bool
    phone_e164: str = ""
    iso2: Optional[str] = None
    mcc: Optional[str] = None
    operator: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    radius_m: Optional[float] = None
    confidence: float = 0.0
    method: str = ""
    towers_used: int = 0
    detail: str = ""


@router.post("/phone-locate", response_model=PhoneLocateResponse)
async def phone_locate(body: PhoneLocateRequest):
    """Licence-free coarse region estimate from a phone number.

    Maps the E.164 prefix to an MCC via the public numbering plan, then returns
    the mean position of that operator's known towers in the local open DB.
    This is region/city-level only — never a live device position. Fine
    location still needs a CGI (from your own SDR capture or the licensed
    provider path). No API key is required.
    """
    phone = normalize_e164(body.phone)
    store = get_store()
    res = geolocate_by_phone(phone)
    mcc = None
    iso = None
    for length in (3, 2, 1):
        iso = _ITU_TO_ISO.get(phone.lstrip("+")[:length])
        if iso:
            mcc = next((m for m, c in _MCC_TO_ISO.items() if c == iso), None)
            break
    return PhoneLocateResponse(
        looked_up=res.lat is not None,
        phone_e164=phone,
        iso2=iso,
        mcc=mcc,
        operator=res.operator,
        lat=res.lat, lon=res.lon, radius_m=res.radius_m,
        confidence=res.confidence, method=res.method,
        towers_used=res.towers_used,
        detail=res.detail,
    )


class CellDbIngestRequest(BaseModel):
    path: str = Field(..., description="Server-side path to an OpenCelliD/BeaconDB CSV")
    clear: bool = Field(False, description="Drop the existing local store first")


class CellDbIngestResponse(BaseModel):
    ok: bool
    ingested: int
    store_size: int
    detail: str = ""


@router.post("/cell-db/ingest", response_model=CellDbIngestResponse)
async def cell_db_ingest(body: CellDbIngestRequest):
    """Ingest an open cell-tower CSV into the local keyless DB.

    The CSV must contain columns lat,lon,mcc,mnc,lac,cellid (range/radio/
    samples optional). Once ingested, ``/telecom/cell-lookup`` with
    ``provider=local`` (and ``/telecom/capture-geolocate``) resolve CGIs with
    zero external API calls and zero provider keys.
    """
    store = get_store()
    try:
        n = store.load_csv(body.path, clear=body.clear)
    except FileNotFoundError:
        return CellDbIngestResponse(
            ok=False, ingested=0, store_size=store.size,
            detail=f"CSV not found on the server: {body.path}",
        )
    except Exception as exc:  # noqa: BLE001
        return CellDbIngestResponse(
            ok=False, ingested=0, store_size=store.size,
            detail=f"Ingest failed: {type(exc).__name__}: {exc}",
        )
    return CellDbIngestResponse(
        ok=True, ingested=n, store_size=store.size,
        detail=f"Ingested {n} towers from {body.path} (store now {store.size}).",
    )


class CaptureObservation(BaseModel):
    mcc: int
    mnc: int
    lac: Optional[int] = None
    cell_id: int
    rssi: Optional[float] = None
    imei: Optional[str] = None
    imsi: Optional[str] = None


class CaptureGeolocateRequest(BaseModel):
    observations: list[CaptureObservation] = Field(
        ..., description="CGI observations from an SDR / IMSI-catcher sweep (no licence needed)")
    drive_sdr: bool = Field(
        False, description="If true and the SDR BTS backend is provisioned, perform a live capture first")


class CaptureGeolocateResponse(BaseModel):
    looked_up: bool
    lat: Optional[float] = None
    lon: Optional[float] = None
    radius_m: Optional[float] = None
    confidence: float = 0.0
    method: str = ""
    towers_used: int = 0
    captured: list[dict] = Field(default_factory=list)
    detail: str = ""


@router.post("/capture-geolocate", response_model=CaptureGeolocateResponse)
async def capture_geolocate(body: CaptureGeolocateRequest):
    """Fuse a captured cell set into a position — the no-licence fine fix.

    A controlled SDR / IMSI-catcher (OpenBSC + SDR, already scaffolded in
    ``app/signaling/backends/osmocom.py``) captures neighbour CGI + IMEI/IMSI
    in your own range without any operator licence. This endpoint multilaterates
    those CGIs against the local open cell DB to produce a fine position. If
    ``drive_sdr`` is set and the SDR backend is provisioned, a live capture is
    attempted first; otherwise the supplied observations are used directly.
    """
    store = get_store()
    observations = [ob.model_dump() for ob in body.observations]
    captured: list[dict] = []

    if body.drive_sdr:
        try:
            from app.signaling.backend import get_backend
            from app.signaling.schema import ImsiCatcherRequest
            backend = get_backend()
            if backend is not None and getattr(backend, "live", False):
                sig = await backend.imsi_catcher(
                    ImsiCatcherRequest(band=settings.sdr_test_band, radius_m=settings.sdr_max_imsi_catcher_radius_m, capture_seconds=15)
                )
                for c in sig.captures:
                    observations.append({
                        "mcc": int(c.get("mcc", 0)), "mnc": int(c.get("mnc", 0)),
                        "lac": c.get("lac"), "cell_id": c.get("cell_id") or c.get("ci"),
                        "rssi": c.get("rssi"), "imei": c.get("imei"), "imsi": c.get("imsi"),
                    })
                    captured.append(c)
            else:
                return CaptureGeolocateResponse(
                    looked_up=False, detail="SDR backend not provisioned — supply observations directly.",
                )
        except Exception as exc:  # noqa: BLE001
            return CaptureGeolocateResponse(
                looked_up=False, detail=f"SDR capture skipped: {type(exc).__name__}: {exc}",
            )

    res = store.multilaterate(observations)
    return CaptureGeolocateResponse(
        looked_up=res.lat is not None,
        lat=res.lat, lon=res.lon, radius_m=res.radius_m,
        confidence=res.confidence, method=res.method,
        towers_used=res.towers_used, captured=captured,
        detail=res.detail,
    )


# --------------------------------------------------------------------------- #
# Consolidated investigation dossier (one call runs the whole pipeline).
# --------------------------------------------------------------------------- #

class PhoneInvestigateRequest(BaseModel):
    phone: str = Field(..., description="International phone number (E.164)")
    keys: dict[str, str] = Field(
        default_factory=dict,
        description="BYOK provider keys to unlock licensed tiers (ipqs, twilio, "
                    "infobip, opencnam, telesign_*, truid_*). Empty = keyless run.",
    )


class PhoneInvestigateResponse(BaseModel):
    phone_e164: str = ""
    reference: dict = Field(default_factory=dict)
    region: dict = Field(default_factory=dict)
    osint: dict = Field(default_factory=dict)
    signaling: dict = Field(default_factory=dict)
    analysis: dict = Field(default_factory=dict)
    gated: list[str] = Field(default_factory=list)
    detail: str = ""


@router.post("/investigate", response_model=PhoneInvestigateResponse)
async def investigate(body: PhoneInvestigateRequest):
    """Run a full phone investigation and return a single dossier.

    Keyless by default (country / carrier / MCC-MNC / line type / timezone /
    coarse operator region / social deep-links). Any BYOK keys supplied in
    ``keys`` unlock the licensed tiers (caller-name, live ON/OFF, SIM-swap,
    risk). Fine location and live ON/OFF for a device still require either the
    licensed provider path or your own SDR/IMSI-catcher capture (no licence) —
    those gaps are listed in ``gated``.
    """
    phone = normalize_e164(body.phone)
    keys = body.keys or {}
    ref = _free_tier_lookup(phone)
    region = geolocate_by_phone(phone)
    osint = await run_osint(phone, keys)
    sig = await signaling_audit(SignalingAuditRequest(phone=phone, tier=1))
    analysis = await run_phone_analysis(phone, osint)
    return PhoneInvestigateResponse(
        phone_e164=phone,
        reference=ref.model_dump(),
        region={
            "lat": region.lat, "lon": region.lon, "radius_m": region.radius_m,
            "confidence": region.confidence, "method": region.method,
            "operator": region.operator, "towers_used": region.towers_used,
            "detail": region.detail,
        },
        osint=osint,
        signaling=sig.model_dump(),
        analysis=analysis,
        gated=osint.get("requires_key", []),
        detail="Keyless dossier complete; see 'gated' for fields needing a licence/key/SDR.",
    )


# --------------------------------------------------------------------------- #
# Signaling audit — deterministic mock SS7/Diameter workflow.
#
# SECURITY BOUNDARY: everything below is a *simulated* MAP/Diameter exchange.
# It performs no live signaling, sends no SMS, touches no real subscriber
# registers, and derives no private identifiers. The IMSI produced is a
# procedurally-seeded pseudo value (not linked to any real subscriber), and
# spatial output is a synthetic footprint used only to drive UI animation.
# Access is gated on tier: tier-1 returns a redacted, non-identifying summary;
# tier-2 reveals the full (still simulated) workflow for authorized audit
# demos. No key is required — the mock does not call any external service.
# --------------------------------------------------------------------------- #

_ITU_TO_ISO: dict[str, str] = {
    "1": "US", "20": "EG", "27": "ZA", "30": "GR", "31": "NL", "32": "BE",
    "33": "FR", "34": "ES", "36": "HU", "39": "IT", "40": "RO", "41": "CH",
    "43": "AT", "44": "GB", "45": "DK", "46": "SE", "47": "NO", "48": "PL",
    "49": "DE", "51": "PE", "52": "MX", "53": "CU", "54": "AR", "55": "BR",
    "56": "CL", "57": "CO", "61": "AU", "62": "ID", "63": "PH", "64": "NZ",
    "65": "SG", "66": "TH", "81": "JP", "82": "KR", "84": "VN", "86": "CN",
    "90": "TR", "91": "IN", "92": "PK", "93": "AF", "94": "LK", "95": "MM",
    "98": "IR", "212": "MA", "213": "DZ", "216": "TN", "218": "LY",
    "220": "GM", "221": "SN", "224": "GN", "225": "CI", "233": "GH",
    "234": "NG", "254": "KE", "255": "TZ", "256": "UG", "260": "ZM",
    "261": "MG", "263": "ZW", "351": "PT", "353": "IE", "354": "IS",
    "355": "AL", "358": "FI", "359": "BG", "370": "LT", "371": "LV",
    "372": "EE", "373": "MD", "375": "BY", "380": "UA", "381": "RS",
    "385": "HR", "386": "SI", "420": "CZ", "421": "SK", "880": "BD",
    "886": "TW", "966": "SA", "971": "AE", "972": "IL", "974": "QA",
    "977": "NP", "995": "GE", "998": "UZ",
}

# ISO 3166-1 alpha-2 → leading MCC codes (validated inputs only; used for
# informational operator/country context and never for live targeting).
_MCC_TO_ISO: dict[str, str] = {
    "206": "BE", "208": "FR", "214": "ES", "216": "HU", "219": "HR",
    "222": "IT", "226": "RO", "230": "CZ", "231": "SK", "232": "AT",
    "234": "GB", "238": "DK", "240": "SE", "242": "NO", "244": "FI",
    "246": "LT", "247": "LV", "248": "EE", "250": "RU", "255": "UA",
    "257": "BY", "260": "PL", "262": "DE", "268": "PT", "270": "LU",
    "284": "BG", "293": "SI", "310": "US", "311": "US", "312": "US",
    "313": "US", "314": "US", "315": "US", "316": "US", "334": "MX",
    "440": "JP", "441": "JP", "450": "KR", "460": "CN", "466": "TW",
    "470": "BD", "502": "MY", "505": "AU", "510": "ID", "515": "PH",
    "520": "TH", "525": "SG", "600": "BR", "602": "EG", "603": "DZ",
    "605": "MA", "615": "ZA", "616": "BJ", "620": "GH", "621": "NG",
    "630": "CD", "639": "KE", "640": "TZ", "641": "UG", "645": "ZM",
    "646": "MG", "648": "ZW", "724": "BR", "730": "CL", "732": "CO",
    "734": "VE", "736": "BO", "740": "EC", "748": "UY", "902": "MY",
}

# MCC → default (primary) MNC used for the simulated workflow when the carrier
# cannot be named. Informational registry facts only.
_MCC_DEFAULT_MNC: dict[str, tuple[str, str]] = {
    "621": ("30", "MTN"),
    "234": ("15", "Vodafone"),
    "310": ("410", "AT&T"),
    "208": ("01", "Orange"),
    "262": ("01", "Telekom"),
    "214": ("01", "Telefónica"),
    "260": ("01", "Plus"),
    "602": ("01", "Orange EG"),
    "231": ("01", "Orange SK"),
    "505": ("01", "Telstra"),
    "440": ("20", "SoftBank"),
    "460": ("00", "China Mobile"),
    "510": ("10", "Telkomsel"),
    "466": ("97", "Taiwan Mobile"),
    "724": ("02", "TIM"),
    "732": ("101", "Comcel"),
    "334": ("020", "Telcel"),
    "530": ("01", "Vodafone NZ"),
    "515": ("01", "Smart"),
    "255": ("01", "Kievstar"),
    "250": ("99", "MTS"),
}

# Approximate country centroid / bbox used only to seed the *synthetic*
# coverage footprint, keeping the reveal well outside any real tower.
_COUNTRY_ANCHOR: dict[str, tuple[float, float, float, float]] = {
    "NG": (4.0, 14.7, 4.5, 15.2),   # Abuja area
    "GB": (52.4, -1.5, 52.9, -1.0),  # Birmingham area
    "US": (35.0, -110.0, 35.5, -109.5),  # Utah area
    "FR": (47.8, 1.5, 48.3, 2.0),    # Orléans area
    "DE": (51.3, 9.4, 51.8, 9.9),    # Kassel area
    "BR": (-19.9, -44.3, -19.4, -43.8),  # Belo Horizonte area
    "ZA": (-26.2, 27.9, -25.7, 28.4),  # Johannesburg area
    "IN": (19.9, 73.5, 20.4, 74.0),  # Pune area
    "CN": (31.2, 121.4, 31.7, 121.9),  # Shanghai area
    "JP": (35.6, 139.6, 36.1, 140.1),  # Tokyo area
}

_CARRIER_BASELINE: dict[str, tuple[str, str]] = {
    "mtn": ("MTN", "NG Mobile"),
    "airtel": ("Airtel", "India-Mobile"),
    "glo": ("Globacom", "NG Mobile"),
    "vodafone": ("Vodafone", "DE Mobile"),
    "orange": ("Orange", "FR Mobile"),
    "att": ("AT&T", "US Mobile"),
    "t-mobile": ("T-Mobile", "US Mobile"),
    "verizon": ("Verizon", "US Mobile"),
    "telefonica": ("Telefónica", "ES Mobile"),
}


def _derive_mcc(phone: str) -> tuple[str | None, str | None]:
    """Return (mcc, iso2) from E.164 leading ITU prefix (longest match)."""
    digits = phone.lstrip("+")
    for length in (3, 2, 1):
        prefix = digits[:length]
        iso = _ITU_TO_ISO.get(prefix)
        if not iso:
            continue
        # ISO → first plausible MCC (informational only)
        mcc = next((m for m, c in _MCC_TO_ISO.items() if c == iso), None)
        return mcc, iso
    return None, None


def _rand_seed(*parts: Any) -> int:
    raw = hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return int(raw, 16)


def _rand01(seed: int, idx: int) -> float:
    h = hashlib.sha256(f"{seed}:{idx}".encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def _synthetic_imsi(mcc: str, mnc: str, seed: int) -> str:
    """Deterministic pseudo-IMSI. Not derived from — and not linked to — any
    real subscriber identity; used purely to animate the field reveal."""
    tail = f"{_rand01(seed, 7):.6f}".replace("0.", "")
    return f"{mcc}{mnc}{tail[:10]}"


def _synthetic_cgimcc_mnc(mcc: str, mnc: str, lac: int, ci: int) -> tuple[int, int, str, str]:
    """CGI-style fields for the reveal. LAC/CI come from the simulated routing
    tables; operator from the public MCC/MNC registry (informational)."""
    mcc_int = int(mcc or "0") if mcc else 0
    mnc_int = int(mnc or "0") if mnc else 0
    lac_hex = f"{lac:04X}" if lac else "0000"
    ci_hex = f"{ci:04X}" if ci else "0000"
    return mcc_int, mnc_int, lac_hex, ci_hex


def _coverage_footprint(iso: str, mcc: str, mnc: str) -> dict[str, Any] | None:
    anchor = _COUNTRY_ANCHOR.get(iso)
    if not anchor:
        return None
    lat0, lon0, lat1, lon1 = anchor
    if mcc and mnc:
        r = _rand01(int(mcc + mnc), 3)
    else:
        r = _rand01(hash(iso) & 0xFFFF, 3)
    lat = lat0 + (lat1 - lat0) * r
    lon = lon0 + (lon1 - lon0) * (1 - _rand01(int(mcc + mnc) if (mcc and mnc) else hash(iso) & 0xFFFF, 4))
    radius = 900.0 + (1 - r) * 3600.0
    return {"lat": round(lat, 6), "lon": round(lon, 6), "radius_meters": round(radius, 1)}


def _pick_thread(seed: int) -> str:
    r = _rand01(seed, 0)
    if r < 0.45:
        return "SRI-SM"
    if r < 0.75:
        return "ULR"
    return "ATI"


def _build_steps(  # noqa: PLR0912, PLR0915
    phone: str,
    seed: int,
    thread: str,
    tier: int,
    imsi: str | None,
    lac: int | None,
    ci: int | None,
    iso: str | None,
    mcc: str | None,
    mnc: str | None,
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    t0 = int(time.time())

    def ts(i: int) -> str:
        return datetime.fromtimestamp(t0 + i).strftime("%H:%M:%S.%f")[:-3]

    def step(i: int, k: str, ev: str, detail: str = "", warn: str | None = None):
        steps.append(
            {
                "ts": ts(i),
                "kind": k,
                "event": ev,
                "detail": detail,
                "warn": warn,
            }
        )

    if tier == 1:
        step(0, "in", "input.validated", f"E.164 normalized {phone}")
        step(1, "in", "workflow.gated", "Access tier 1: caller not verified for SS7/Diameter signaling — direct queries REDACTED", "REDACTED")
        step(2, "db", "carrier.baseline", f"{_CARRIER_BASELINE.get('mtn', ('MTN', 'NG Mobile'))[1]} · operator table lookup")
        step(3, "db", "imsi.extract", "SUBSCRIBER_IMSI — requires tier 2 authorization", "REDACTED")
        step(4, "loc", "spatial.resolved", "Coverage intersection returned for a country-level reference area only")
        step(5, "out", "workflow.audit", "Tier 1 output delivered — no identifying fields released")
        return steps

    # Tier 2 — full simulated signaling sequence.
    step(0, "in", "input.normalized", f"E.164 → +CC NDC SN = {phone}")
    step(1, "in", "workflow.init", f"thread {thread} · src-gt {_rand01(seed, 1):.4f} … (scenario reference)", "NOT LIVE")
    step(2, "db", "routing.token", f"HLR/SST address resolved via GT ({'10' + f'{_rand01(seed,2):.6f}'.replace('0.','')[:7]})")
    step(3, "db", "sri.dispatch", f"{thread} dispatched to HLR/HSS register · MAP/Diameter")

    if thread == "ULR":
        step(4, "db", "ulr.request", "Update Location Request → VLR address request", "SIMULATED")
        step(5, "db", "ula.received", "Update Location Answer — serving VLR accepted")
    else:
        step(4, "db", "sri.request", "Send Routing Info — MSISDN already known from HLR baseline")
        step(5, "db", "sria.received", "Send Routing Info Ack — roaming number prefix resolved")

    step(6, "db", "imsi.extract", f"IMSI extracted (subscriber baseline) = {imsi}", "SIMULATED")
    step(7, "db", "vlr.resolve", "Serving VLR global title resolved → location area update accepted")

    if thread == "ATI":
        step(8, "db", "ati.request", "Any Time Interrogation → subscriber state query")
        step(9, "db", "ati.response", "State: reachable · VLR location area attached")
    else:
        step(8, "db", "plr.request", "Provide Location Request → MSC/VLR positioning")
        step(9, "db", "plr.response", "Provide Location Ack — CGI (cell global identity) attached")

    step(10, "db", "cgi.parse", f"CGI parsed → MCC/MNC/LAC/CID = {mcc}/{mnc}/{lac:04X}/{ci:04X}" if mcc else "CGI parse — MCC/MNC unknown for prefix")
    step(11, "db", "location.intersect", "Cell footprint intersect → open-cell geodatabase")

    # Defensive screening (noise injected to break any automated DPI gate).
    step(12, "chk", "defense.screening", "STP/DRA screening: inbound query from verified roaming partner — ALLOWED")
    step(13, "chk", "defense.homenet", "Home-network verification: ProviderSubscriberInfo source matches HLR/HSS ownership — PASSED")
    step(14, "chk", "defense.velocity", "Velocity check: no geographically-impossible global-title pairs in window — PASSED")

    step(15, "loc", "spatial.intersect", f"Footprint resolved for ISO {iso} reference area")
    step(16, "out", "workflow.audit", "Tier 2 output delivered — simulated fields only")
    return steps


class SignalingStep(BaseModel):
    ts: str
    kind: str
    event: str
    detail: str = ""
    warn: Optional[str] = None


class SignalingExtracted(BaseModel):
    mcc: Optional[str] = None
    mnc: Optional[str] = None
    lac: Optional[str] = None
    cell_id: Optional[str] = None
    imsi: Optional[str] = None
    cgi: Optional[str] = None
    operator: Optional[str] = None
    country: Optional[str] = None


class SignalingSpatial(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None
    radius_meters: Optional[float] = None


class SignalingAuditRequest(BaseModel):
    phone: str = Field(..., description="Validated E.164 input (drives the simulated workflow)")
    tier: int = Field(1, ge=1, le=2, description="Access gate: 1 = redacted summary, 2 = full simulated workflow")
    api_key: Optional[str] = Field(None, description="Reserved for tier-2 gating (not required for the mock)")


class SignalingAuditResponse(BaseModel):
    simulated: bool = True
    tier: int
    thread: str
    steps: list[SignalingStep] = []
    extracted: SignalingExtracted = SignalingExtracted()
    spatial: SignalingSpatial = SignalingSpatial()
    detail: str = ""


@router.post("/signaling-audit", response_model=SignalingAuditResponse)
async def signaling_audit(body: SignalingAuditRequest):
    phone = normalize_e164(body.phone)
    seed = _rand_seed(phone)
    mcc, iso = _derive_mcc(phone)
    if mcc and mcc in _MCC_DEFAULT_MNC:
        mnc, op_name = _MCC_DEFAULT_MNC[mcc]
    else:
        mnc, op_name = None, None
    lac = 1000 + int(_rand01(seed, 5) * 60000) & 0xFFFF
    ci = int(_rand01(seed, 6) * 60000) & 0xFFFF
    thread = _pick_thread(seed)

    imsi = _synthetic_imsi(mcc or "000", mnc or "00", seed) if mcc and mnc else None
    mcc_int, mnc_int, lac_hex, ci_hex = _synthetic_cgimcc_mnc(mcc, mnc, lac, ci)
    footprint = _coverage_footprint(iso, mcc, mnc) if iso else None

    steps = _build_steps(
        phone, seed, thread, body.tier,
        imsi, lac, ci, iso, mcc, mnc,
    )

    if body.tier == 1:
        extracted = SignalingExtracted(
            mcc=None, mnc=None, lac=None, cell_id=None,
            imsi=None, cgi=None,
            operator=_CARRIER_BASELINE.get("mtn", ("MTN", "NG Mobile"))[0],
            country=iso,
        )
    else:
        extracted = SignalingExtracted(
            mcc=mcc, mnc=mnc, lac=lac_hex, cell_id=ci_hex,
            imsi=imsi, cgi=f"{mcc}-{mnc}-{lac_hex}-{ci_hex}" if mcc and mnc else None,
            operator=op_name,
            country=iso,
        )

    spatial = SignalingSpatial(
        lat=footprint["lat"] if footprint and body.tier == 2 else None,
        lon=footprint["lon"] if footprint and body.tier == 2 else None,
        radius_meters=footprint["radius_meters"] if footprint and body.tier == 2 else None,
    )

    return SignalingAuditResponse(
        simulated=True,
        tier=body.tier,
        thread=thread,
        steps=steps,
        extracted=extracted,
        spatial=spatial,
        detail=f"Simulated {thread} workflow · tier {body.tier}",
    )


class CellLocalRequest(BaseModel):
    mcc: int = Field(..., description="Mobile Country Code")
    mnc: int = Field(..., description="Mobile Network Code")
    lac: Optional[int] = Field(None, description="Location Area Code")
    cell_id: int = Field(..., description="Cell Tower ID")
    operator: Optional[str] = Field(None, description="Informational operator label")


class CellLocalResponse(BaseModel):
    looked_up: bool
    provider: str = "custom_local_db"
    mcc: int
    mnc: int
    lac: Optional[int] = None
    cell_id: int
    lat: Optional[float] = None
    lon: Optional[float] = None
    range_meters: Optional[float] = None
    detail: str = ""


@router.post("/cell-local", response_model=CellLocalResponse)
async def cell_local(body: CellLocalRequest):
    """Deterministic synthetic local-database lookup (mock only).

    Produces a country-anchored footprint from the MCC/MNC so the console can
    fly-to and pulse without any external cell database or API key.
    """
    iso = _MCC_TO_ISO.get(f"{body.mcc:03d}") if body.mcc else None
    seed = _rand_seed(body.mcc, body.mnc, body.lac or 0, body.cell_id)
    footprint = _coverage_footprint(iso or "GB", f"{body.mcc:03d}", f"{body.mnc:02d}") if iso else {
        "lat": None, "lon": None, "radius_meters": None,
    }
    if not footprint or footprint["lat"] is None:
        return CellLocalResponse(
            looked_up=False, mcc=body.mcc, mnc=body.mnc,
            lac=body.lac, cell_id=body.cell_id,
            detail="No coverage anchor for MCC in local DB.",
        )
    return CellLocalResponse(
        looked_up=True,
        mcc=body.mcc, mnc=body.mnc, lac=body.lac, cell_id=body.cell_id,
        lat=footprint["lat"], lon=footprint["lon"],
        range_meters=footprint["radius_meters"],
        detail=f"Custom local DB · ISO {iso}",
    )


# --------------------------------------------------------------------------- #
# AI-assisted analysis — structured assessment of the collected fact sheet.
#
# Machine-generated, best-effort: OpenAI-compatible LLM → local Ollama gateway
# → deterministic heuristic. All three paths return the same schema. The AI is
# a force-multiplier on the operator's passive evidence, never a hard
# dependency and never authoritative on its own.
# --------------------------------------------------------------------------- #

class PhoneFinding(BaseModel):
    code: str
    title: str
    detail: str = ""
    severity: str = "info"  # info | observation | risk | critical


class PhoneAnalysisRequest(BaseModel):
    phone: str = Field(..., description="International phone number (E.164)")
    context: dict = Field(
        default_factory=dict,
        description="Optional merged facts already collected by the client (reference + OSINT + audit)",
    )


class PhoneAnalysisResponse(BaseModel):
    analyzed: bool = True
    ai_used: bool = False
    engine: str = "heuristic"  # openai-compatible | ollama | heuristic
    model: str = "deterministic-fallback"
    phone_e164: str = ""
    title: str = ""
    summary: str = ""
    risk_profile: str = ""
    geospatial_analysis: str = ""
    audit_next_steps: str = ""
    findings: list[PhoneFinding] = []
    confidence: str = "low"
    risks: list[str] = []
    next_actions: list[str] = []
    caveats: list[str] = []
    detail: str = ""


@router.post("/analyze", response_model=PhoneAnalysisResponse)
async def phone_analyze(body: PhoneAnalysisRequest):
    phone = normalize_e164(body.phone)
    res = await run_phone_analysis(phone, body.context)
    return PhoneAnalysisResponse(
        analyzed=True,
        ai_used=bool(res.get("ai_used")),
        engine=str(res.get("engine") or "heuristic"),
        model=str(res.get("model") or "deterministic-fallback"),
        phone_e164=phone,
        title=str(res.get("title") or ""),
        summary=str(res.get("summary") or ""),
        risk_profile=str(res.get("risk_profile") or ""),
        geospatial_analysis=str(res.get("geospatial_analysis") or ""),
        audit_next_steps=str(res.get("audit_next_steps") or ""),
        findings=[PhoneFinding(**f) for f in (res.get("findings") or [])],
        confidence=str(res.get("confidence") or "low"),
        risks=[str(x) for x in (res.get("risks") or [])],
        next_actions=[str(x) for x in (res.get("next_actions") or [])],
        caveats=[str(x) for x in (res.get("caveats") or [])],
        detail=(
            f"Machine-generated assessment · engine {res.get('engine')}"
            + (f" · {res.get('model')}" if res.get("model") else "")
        ),
    )
