"""External geo & reverse-source providers — optional, honest-by-design.

Each function here wraps a real external API (Mapbox Geocoding, Google
Street View Static, TinEye, Serper).  Keys are read live from the settings
store so Admin updates take effect without a restart.  When a key is missing
or a call fails, functions return a structured ``UNAVAILABLE`` result and
the investigation continues — results are never fabricated.
"""
from __future__ import annotations

import base64
import logging
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.models import AddressInfo
from app.services.settings_store import settings_store

logger = logging.getLogger(__name__)


def _get_key(name: str) -> Optional[str]:
    return settings_store.get_key(name)


# --------------------------------------------------------------------------- #
# Mapbox reverse geocoding (server-side)
# --------------------------------------------------------------------------- #
def reverse_geocode_mapbox(lat: float, lon: float) -> Optional[AddressInfo]:
    """Reverse-geocode via Mapbox Geocoding API.  Returns None on failure."""
    token = _get_key("mapbox_token")
    if not token:
        return None
    try:
        url = f"{settings.mapbox_geocoding_url}/{lon:.6f},{lat:.6f}.json"
        resp = httpx.get(
            url,
            params={"access_token": token, "language": "en", "limit": 1},
            timeout=settings.vision_request_timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        features = data.get("features") or []
        if not features:
            return None
        feat = features[0]
        context: dict[str, str] = {}
        for c in feat.get("context", []):
            cid = c.get("id", "")
            if cid.startswith("country"):
                context["country"] = c.get("text")
            elif cid.startswith("region"):
                context["state"] = c.get("text")
            elif cid.startswith("place"):
                context["city"] = c.get("text")
            elif cid.startswith("postcode"):
                context["postcode"] = c.get("text")
        return AddressInfo(
            country=context.get("country"),
            state=context.get("state"),
            city=context.get("city") or feat.get("text"),
            road=None,
            postcode=context.get("postcode"),
            display_name=feat.get("place_name"),
        )
    except Exception as exc:
        logger.warning("Mapbox reverse geocode failed for %s,%s: %s", lat, lon, exc)
        return None


# --------------------------------------------------------------------------- #
# Google Maps Geocoding (reverse — street-level address)
# --------------------------------------------------------------------------- #
def reverse_geocode_google(lat: float, lon: float) -> Optional[AddressInfo]:
    """Reverse-geocode via Google Maps Geocoding API.  Returns None on failure."""
    key = _get_key("google_maps_api_key")
    if not key:
        return None
    try:
        resp = httpx.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={
                "latlng": f"{lat:.6f},{lon:.6f}",
                "key": key,
                "language": "en",
            },
            timeout=settings.vision_request_timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status")
        if status != "OK":
            logger.warning("Google Geocoding status for %s,%s: %s", lat, lon, status)
            return None
        results = data.get("results") or []
        if not results:
            return None
        res = results[0]
        comps: dict[str, str] = {}
        road_parts: list[str] = []
        for comp in res.get("address_components", []):
            kinds = set(comp.get("types", []))
            for target in ("country", "administrative_area_level_1", "locality",
                           "postal_code", "route", "street_number"):
                if target in kinds:
                    comps[target] = comp.get("long_name", "")
            if "route" in kinds:
                road_parts.append(comp.get("long_name", ""))
            if "street_number" in kinds:
                road_parts.append(comp.get("long_name", ""))
        return AddressInfo(
            country=comps.get("country"),
            state=comps.get("administrative_area_level_1"),
            city=comps.get("locality"),
            road=", ".join(reversed(road_parts)) or None,
            postcode=comps.get("postal_code"),
            display_name=res.get("formatted_address"),
        )
    except Exception as exc:
        logger.warning("Google Geocoding failed for %s,%s: %s", lat, lon, exc)
        return None


# --------------------------------------------------------------------------- #
# Google Street View Static (panorama forensics)
# --------------------------------------------------------------------------- #
async def fetch_streetview(
    lat: float, lon: float, heading: Optional[float] = None
) -> dict[str, Any]:
    """Query Street View metadata + build a static image URL.

    Returns a structured result:
      state: "AVAILABLE" (pano found) | "NO_PANORAMA" | "UNAVAILABLE"
      pano_id, date, image_url, detail
    """
    key = _get_key("google_maps_api_key")
    if not key:
        return {
            "state": "UNAVAILABLE",
            "detail": (
                "Google Maps API key not configured. "
                "Set GOOGLE_MAPS_API_KEY via Admin to enable Street View."
            ),
        }
    base = settings.google_streetview_api_url
    try:
        async with httpx.AsyncClient(timeout=settings.vision_request_timeout) as client:
            meta_resp = await client.get(
                f"{base}/metadata",
                params={
                    "location": f"{lat:.6f},{lon:.6f}",
                    "key": key,
                },
            )
            meta_resp.raise_for_status()
            meta = meta_resp.json()
    except Exception as exc:
        logger.warning("Street View metadata query failed: %s", exc)
        return {"state": "UNAVAILABLE", "detail": f"Street View query failed: {exc}"}

    if meta.get("status") != "OK":
        return {
            "state": "NO_PANORAMA",
            "status": meta.get("status", "UNKNOWN"),
            "pano_id": None,
            "date": None,
            "image_url": None,
            "detail": meta.get("status", "No Street View panorama available."),
        }

    pano_id = meta.get("pano_id")
    date = meta.get("date")
    size = "640x400"
    params = {
        "location": f"{lat:.6f},{lon:.6f}",
        "size": size,
        "fov": 90,
        "pitch": 0,
        "key": key,
    }
    if heading is not None:
        params["heading"] = float(heading)
    image_url = f"{base}?{'&'.join(f'{k}={v}' for k, v in params.items())}"
    return {
        "state": "AVAILABLE",
        "status": "OK",
        "pano_id": pano_id,
        "date": date,
        "heading": heading,
        "image_url": image_url,
        "detail": "Street View panorama located.",
    }


# --------------------------------------------------------------------------- #
# TinEye reverse source discovery (upload-based)
# --------------------------------------------------------------------------- #
async def search_tineye(image_bytes: bytes, limit: int = 20) -> dict[str, Any]:
    """Upload an image to TinEye and return reverse matches."""
    key = _get_key("tineye_api_key")
    if not key:
        return {
            "provider": "tineye",
            "state": "UNAVAILABLE",
            "detail": "TinEye API key not configured via Admin.",
            "matches": [],
        }
    try:
        auth = base64.b64encode(f"{key}:{key}".encode()).decode()
        async with httpx.AsyncClient(timeout=settings.vision_request_timeout) as client:
            resp = await client.post(
                settings.tineye_api_url,
                headers={"Authorization": f"Basic {auth}"},
                data={"offset": 0, "limit": limit, "sort": "score", "order": "desc"},
                files={"image": ("image", image_bytes, "application/octet-stream")},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("TinEye query failed: %s", exc)
        return {
            "provider": "tineye",
            "state": "ERROR",
            "detail": f"TinEye query failed: {exc}",
            "matches": [],
        }
    matches = []
    for m in data.get("results") or []:
        matches.append({
            "filepath": m.get("filepath"),
            "score": m.get("score"),
            "url": m.get("url"),
            "backlinks": m.get("backlinks") or [],
            "image_urls": [b.get("url") for b in (m.get("backlinks") or []) if b.get("url")],
        })
    return {
        "provider": "tineye",
        "state": "AVAILABLE",
        "detail": f"TinEye returned {len(matches)} match(es).",
        "matches": matches,
    }


# --------------------------------------------------------------------------- #
# Serper image search (web reverse-source via text/URL query)
# --------------------------------------------------------------------------- #
async def search_serper(
    search_query: Optional[str] = None,
    image_url: Optional[str] = None,
    num: int = 10,
) -> dict[str, Any]:
    """Image-search the web via Serper.

    ``image_url`` enables true reverse-image search when the asset is
    already reachable on the web; otherwise ``search_query`` (e.g. derived
    from OCR text / scene tags) performs a keyword image search.
    """
    key = _get_key("serper_api_key")
    if not key:
        return {
            "provider": "serper",
            "state": "UNAVAILABLE",
            "detail": "Serper API key not configured via Admin.",
            "matches": [],
        }
    if not image_url and not search_query:
        return {
            "provider": "serper",
            "state": "UNAVAILABLE",
            "detail": (
                "Serper requires a reachable image_url (reverse image search) "
                "or a search_query (keyword image search) — neither supplied."
            ),
            "matches": [],
        }
    payload: dict[str, Any] = {"num": num}
    if image_url:
        payload["imageUrl"] = image_url
    else:
        payload["q"] = search_query
    try:
        async with httpx.AsyncClient(timeout=settings.vision_request_timeout) as client:
            resp = await client.post(
                settings.serper_api_url,
                headers={
                    "X-API-KEY": key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("Serper query failed: %s", exc)
        return {
            "provider": "serper",
            "state": "ERROR",
            "detail": f"Serper query failed: {exc}",
            "matches": [],
        }
    matches = []
    for it in data.get("images") or []:
        matches.append({
            "title": it.get("title"),
            "image_url": it.get("imageUrl"),
            "source_url": it.get("sourceUrl"),
            "snippet": it.get("snippet"),
        })
    return {
        "provider": "serper",
        "state": "AVAILABLE",
        "detail": f"Serper returned {len(matches)} image result(s).",
        "matches": matches,
    }
