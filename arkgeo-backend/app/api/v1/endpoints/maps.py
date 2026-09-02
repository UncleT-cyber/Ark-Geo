"""Google Map Tiles proxy.

The browser never sees the Google Maps API key. The backend owns the key, caches
a Map Tiles API session token (valid ~2 weeks, refreshed lazily), and proxies
individual 2D tiles over `/api/v1/maps/tile/{z}/{x}/{y}?map_type=...`.

Because the requests are server-to-server, referer-based key restrictions do
not break the map, and the frontend keeps using Leaflet unchanged — only the
tile template points at this proxy.
"""
from __future__ import annotations

import logging
import threading
import time

import httpx
from fastapi import APIRouter, HTTPException, Response

from app.core.config import settings
from app.models import BatchGeocodeRequest
from app.services.settings_store import settings_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/maps", tags=["maps"])

_SESSIONS: dict[str, dict[str, object]] = {}
_LOCK = threading.Lock()

_TILE_TYPES = ("satellite", "hybrid")

# Geocode cache: cleaned query → (lat, lon). TTL 7 days; Google geocoding is
# quota-billed, so repeat city lookups must not hit the wire again.
_GEO_CACHE: dict[str, dict[str, float]] = {}
_GEO_LOCK = threading.Lock()


def _maps_key() -> str:
    """Key resolution: encrypted admin store → .env (never the browser)."""
    key = settings_store.get_key("google_maps_api_key") or settings.google_maps_api_key
    if not key:
        raise HTTPException(503, "google_maps_api_key not configured (Admin Settings or ARKGEO_GOOGLE_MAPS_API_KEY)")
    return str(key)


def _session_body(map_type: str) -> dict[str, object]:
    body: dict[str, object] = {"mapType": "satellite", "language": "en-US", "region": "US"}
    if map_type == "hybrid":
        body["layerTypes"] = ["layerRoadmap"]
    return body


async def _session(map_type: str) -> str:
    now = time.time()
    with _LOCK:
        cached = _SESSIONS.get(map_type)
        if cached and float(cached.get("expires") or 0) > now + 300:
            return str(cached["token"])
    body = _session_body(map_type)
    key = _maps_key()
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            f"{settings.google_maps_tile_api_url}/v1/createSession",
            params={"key": key},
            json=body,
        )
    if resp.status_code != 200:
        raise HTTPException(502, f"Google tile session failed: {resp.status_code} {resp.text[:240]}")
    data = resp.json()
    token = data.get("session")
    if not token:
        raise HTTPException(502, "Google tile session response missing session token")
    with _LOCK:
        _SESSIONS[map_type] = {
            "token": token,
            "expires": float(data.get("expiry") or now + 3600),
        }
    return str(token)


async def _tile(z: int, x: int, y: int, map_type: str) -> Response:
    url = f"{settings.google_maps_tile_api_url}/v1/2dtiles/{z}/{x}/{y}"
    key = _maps_key()
    session = await _session(map_type)
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            url,
            params={"session": session, "key": key, "orientation": 0},
        )
    if resp.status_code == 200:
        return Response(
            content=resp.content,
            media_type=resp.headers.get("content-type", "image/png"),
        )
    if resp.status_code in (401, 403, 404):
        # Session may have expired server-side — drop it and retry once.
        with _LOCK:
            _SESSIONS.pop(map_type, None)
        session = await _session(map_type)
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                url,
                params={"session": session, "key": key, "orientation": 0},
            )
        if resp.status_code == 200:
            return Response(
                content=resp.content,
                media_type=resp.headers.get("content-type", "image/png"),
            )
    raise HTTPException(502, f"Google tile fetch failed: {resp.status_code} {resp.text[:240]}")


@router.get("/tile/{z}/{x}/{y}")
async def google_tile(z: int, x: int, y: int, map_type: str = "satellite"):
    if map_type not in _TILE_TYPES:
        raise HTTPException(422, f"map_type must be one of {_TILE_TYPES}")
    if not (0 <= z <= 22 and 0 <= x < 2**z and 0 <= y < 2**z):
        raise HTTPException(422, "tile coordinates out of range")
    return await _tile(z, x, y, map_type)


async def _nominatim_geocode(query: str) -> dict[str, float] | None:
    if not settings.geo_nominatim_fallback:
        return None
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "arkgeo-lab/0.1 (personal security lab)"}) as client:
        r = await client.get(
            settings.geo_nominatim_url,
            params={"q": query, "format": "json", "limit": 1, "addressdetails": 0},
        )
    if r.status_code != 200:
        return None
    try:
        results = r.json()
    except Exception:  # noqa: BLE001
        return None
    if not results:
        return None
    try:
        lat = float(results[0].get("lat"))
        lon = float(results[0].get("lon"))
    except (TypeError, ValueError):
        return None
    return {"lat": lat, "lon": lon}


@router.get("/geocode")
async def geocode_city(q: str = ""):
    """Geocode a city name (from the keyless libphonenumber tier) to lat/lon.

    City-level targets without live cell telemetry: resolve the clean city to
    coordinates so the map flies to a real place, not a country centroid.
    Google Geocoding is used when configured; otherwise (or when the Google
    project rejects the request — e.g. billing disabled) the keyless
    OpenStreetMap Nominatim geocoder is the fallback. Cached 7 days.
    """
    query = (q or "").strip()
    if len(query) < 2:
        raise HTTPException(422, "q must be at least 2 characters")
    with _GEO_LOCK:
        hit = _GEO_CACHE.get(query)
        if hit is not None:
            return {"ok": True, "cached": True, **hit}

    # Path A — Google Geocoding (requires billing-enabled project).
    try:
        key = _maps_key()
    except HTTPException:
        key = None
    if key:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"address": query, "key": key, "language": "en"},
            )
        if r.status_code == 200:
            payload = r.json() or {}
            status = payload.get("status")
            if status == "OK" and payload.get("results"):
                loc = payload["results"][0].get("geometry", {}).get("location") or {}
                lat, lon = loc.get("lat"), loc.get("lng")
                if lat is not None and lon is not None:
                    with _GEO_LOCK:
                        _GEO_CACHE[query] = {"lat": float(lat), "lon": float(lon)}
                    return {"ok": True, "lat": float(lat), "lon": float(lon), "cached": False}
            if status not in ("OK", "ZERO_RESULTS", "OVER_QUERY_LIMIT"):
                # e.g. REQUEST_DENIED (billing disabled) — fall through to Nominatim.
                logger.warning("Google geocode rejected (%s) — using Nominatim fallback", status)

    # Path B — keyless OSM Nominatim fallback.
    coords = await _nominatim_geocode(query)
    if coords:
        with _GEO_LOCK:
            _GEO_CACHE[query] = coords
        return {"ok": True, "cached": False, "fallback": "nominatim", **coords}
    return {"ok": False, "detail": "No results for that location (Google rejected and Nominatim miss)"}


@router.post("/geocode/batch")
async def geocode_batch(payload: BatchGeocodeRequest):
    """Forward-geocode a batch of OCR text strings into candidate pins.

    Feeds the OCR → geocoding pipeline (Feature 2): the client extracts
    street / place text from an image and the backend resolves each string
    to coordinates (Google → keyless Nominatim fallback, cached 7 days).
    Unmatched queries are omitted — candidates are never fabricated.
    """
    from app.services.geocoding_service import geocode_batch as _batch

    candidates = await _batch(payload.queries)
    return {
        "ok": True,
        "candidates": [
            c.model_dump() if hasattr(c, "model_dump") else c
            for c in candidates
        ],
    }
