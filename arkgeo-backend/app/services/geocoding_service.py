"""Forward geocoding service — OCR text strings → candidate coordinates.

Feature 2 (OCR → geocoding).  Geocodes location-relevant text extracted from
an image (street names, place names, landmark tokens) and returns candidate
pins for the spatial canvas.

Google Geocoding is used when a ``google_maps_api_key`` is configured;
otherwise (or when the Google project rejects the request) the keyless
OpenStreetMap Nominatim geocoder is the fallback.  Results are cached 7 days
so repeat lookups never hit the wire again.  Every failure degrades to an
empty candidate list — the investigation never crashes on a geocode miss.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.models import GeoCandidate
from app.services.settings_store import settings_store

logger = logging.getLogger(__name__)

_GEO_CACHE: dict[str, dict[str, float]] = {}
_GEO_LOCK = threading.Lock()
_CACHE_TTL_SECONDS = 7 * 24 * 3600
_cache_ts: dict[str, float] = {}


def _maps_key() -> Optional[str]:
    return settings_store.get_key("google_maps_api_key") or settings.google_maps_api_key


async def _google_geocode(query: str) -> Optional[dict[str, float]]:
    key = _maps_key()
    if not key:
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"address": query, "key": key, "language": "en"},
            )
        if r.status_code != 200:
            return None
        payload = r.json() or {}
        if payload.get("status") != "OK" or not payload.get("results"):
            return None
        loc = payload["results"][0].get("geometry", {}).get("location") or {}
        lat, lon = loc.get("lat"), loc.get("lng")
        if lat is None or lon is None:
            return None
        return {"lat": float(lat), "lon": float(lon)}
    except Exception as exc:  # noqa: BLE001 — geocode must degrade, not crash
        logger.warning("Google geocode failed for %r: %s", query, exc)
        return None


async def _nominatim_geocode(query: str) -> Optional[dict[str, float]]:
    if not settings.geo_nominatim_fallback:
        return None
    try:
        async with httpx.AsyncClient(
            timeout=15,
            headers={"User-Agent": "arkgeo-lab/0.1 (personal security lab)"},
        ) as client:
            r = await client.get(
                settings.geo_nominatim_url,
                params={"q": query, "format": "json", "limit": 1, "addressdetails": 0},
            )
        if r.status_code != 200:
            return None
        results = r.json()
        if not results:
            return None
        lat = float(results[0].get("lat"))
        lon = float(results[0].get("lon"))
        return {"lat": lat, "lon": lon}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Nominatim geocode failed for %r: %s", query, exc)
        return None


async def geocode_search(query: str) -> Optional[dict[str, Any]]:
    """Geocode a single search string → {lat, lon, source, cached} or None."""
    query = (query or "").strip()
    if len(query) < 2:
        return None

    with _GEO_LOCK:
        hit = _GEO_CACHE.get(query)
        if hit is not None and _cache_ts.get(query, 0) > _now() - _CACHE_TTL_SECONDS:
            return {"lat": hit["lat"], "lon": hit["lon"], "source": "cache", "cached": True}

    coords = await _google_geocode(query)
    source = "google"
    if coords is None:
        coords = await _nominatim_geocode(query)
        source = "nominatim"
    if coords is None:
        return None

    with _GEO_LOCK:
        _GEO_CACHE[query] = {"lat": coords["lat"], "lon": coords["lon"]}
        _cache_ts[query] = _now()
    return {"lat": coords["lat"], "lon": coords["lon"], "source": source, "cached": False}


async def geocode_batch(queries: list[str]) -> list[GeoCandidate]:
    """Geocode many OCR strings concurrently; unmatched queries are dropped."""
    import asyncio

    queries = list(dict.fromkeys(q.strip() for q in (queries or []) if q and q.strip()))
    if not queries:
        return []
    results = await asyncio.gather(
        *(geocode_search(q) for q in queries), return_exceptions=True,
    )
    candidates: list[GeoCandidate] = []
    for query, res in zip(queries, results):
        if isinstance(res, Exception) or res is None:
            continue
        candidates.append(
            GeoCandidate(
                query=query,
                lat=res["lat"],
                lon=res["lon"],
                source=res.get("source", "nominatim"),
                cached=bool(res.get("cached", False)),
                matched=True,
            )
        )
    return candidates


def _now() -> float:
    import time
    return time.time()
