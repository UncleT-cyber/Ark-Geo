"""Geocoding tool — OCR/place-name text → candidate coordinates.

Wraps the existing :mod:`app.services.geocoding_service` (Google Geocoding
when keyed, keyless OpenStreetMap Nominatim otherwise, 7-day result cache)
into a Tool-shaped async API.  Every miss degrades to an honest ``ERROR`` /
``UNAVAILABLE`` state — the orchestrator never sees fabricated pins.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.geocoding_service import geocode_batch, geocode_search

logger = logging.getLogger(__name__)


async def geocode_place(place: str) -> dict[str, Any]:
    """Forward-geocode a single place-name/OCR string → candidate coordinates."""
    place = (place or "").strip()
    if len(place) < 2:
        return {
            "state": "UNAVAILABLE", "query": place,
            "detail": "Query too short to geocode.",
            "lat": None, "lon": None,
        }
    res = await geocode_search(place)
    if not res:
        return {
            "state": "ERROR", "query": place,
            "detail": "No geocode match from Google Geocoding or OSM Nominatim.",
            "lat": None, "lon": None,
        }
    return {
        "state": "AVAILABLE", "query": place,
        "lat": res["lat"], "lon": res["lon"],
        "source": res.get("source", "nominatim"),
        "cached": bool(res.get("cached", False)),
        "detail": f"Geocoded via {res.get('source', 'nominatim')}.",
    }


async def geocode_batch_texts(places: list[str] | None = None) -> dict[str, Any]:
    """Geocode many OCR strings concurrently; unmatched queries are dropped."""
    candidates = await geocode_batch(places or [])
    if not candidates:
        return {
            "state": "ERROR", "detail": "No supplied place string matched a geocoder.",
            "candidates": [], "total": 0,
        }
    return {
        "state": "AVAILABLE",
        "detail": f"Geocoded {len(candidates)} candidate(s).",
        "candidates": [
            c.model_dump() if hasattr(c, "model_dump") else c for c in candidates
        ],
        "total": len(candidates),
    }
