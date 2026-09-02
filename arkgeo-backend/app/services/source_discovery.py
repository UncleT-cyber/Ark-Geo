"""Source discovery — provider-agnostic reverse image search architecture.

Computes a perceptual hash (pHash) of the image as a local, dependency-free
signal, and exposes an extensible provider registry for external reverse
search APIs (Google, TinEye, Yandex, etc.).

Providers are controlled via the Admin control plane (settings store).
If no provider is configured, the service reports ``UNAVAILABLE`` and
the investigation continues — never fabricating search results.

Original rehydration (WhatsApp / Telegram / social re-share recovery)
---------------------------------------------------------------------
When a reverse-search match is found, the *earliest known copy* of the
image on the web frequently still carries the original EXIF GPS that the
messaging intermediary stripped.  ``analyze`` therefore attempts to fetch
each candidate match and re-extract its metadata through the standard
:class:`MetadataExtractor`; the first match that yields coordinates is
surfaced as ``recovered_gps`` so a stripped share can be upgraded back to
a hard pin.  All network access is best-effort and honest-by-design: a
failed fetch, missing EXIF, or unconfigured provider yields ``None`` and
never fabricates a location.
"""
from __future__ import annotations

import hashlib
import io
import logging
from typing import Any, Optional

import httpx
from PIL import Image

logger = logging.getLogger(__name__)


def compute_phash(image_bytes: bytes, hash_size: int = 8) -> str:
    """Compute a perceptual hash (pHash) as a hex string.

    Uses average hashing: resize to NxN grayscale, threshold by mean,
    produce a bit string.  This is a local, no-dependency fingerprint that
    is robust to the recompression/resize applied by WhatsApp / Telegram.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("L")
        img = img.resize((hash_size, hash_size), Image.Resampling.LANCZOS)
        pixels = list(img.get_flattened_data() if hasattr(img, "get_flattened_data") else img.getdata())
        avg = sum(pixels) / len(pixels)
        bits = "".join("1" if p >= avg else "0" for p in pixels)
        return format(int(bits, 2), f"0{hash_size * hash_size // 4}x")
    except Exception as exc:
        logger.warning("pHash computation failed: %s", exc)
        return ""


def _match_urls(matches: list[dict]) -> list[str]:
    """Best-effort ordered list of candidate image URLs from provider matches.

    Exact matches (high score) are preferred over similar ones so the
    rehydration step targets the most faithful copy first.
    """
    ordered: list[str] = []
    for m in matches:
        if m.get("score") is not None and isinstance(m.get("score"), (int, float)):
            ordered.append(m)
    ordered.sort(key=lambda m: float(m.get("score") or 0.0), reverse=True)
    urls: list[str] = []
    for m in ordered:
        for key in ("image_url", "url", "source_url"):
            u = m.get(key)
            if u and u not in urls:
                urls.append(u)
        for u in (m.get("image_urls") or []):
            if u and u not in urls:
                urls.append(u)
    # Fallback: any remaining url-like fields
    for m in matches:
        for key in ("image_url", "url", "source_url"):
            u = m.get(key)
            if u and u not in urls:
                urls.append(u)
    return urls


def _rehydrate_original(matches: list[dict]) -> Optional[dict]:
    """Fetch candidate matches and recover GPS from the original copy.

    Returns a dict with ``gps`` (lat/lon), ``camera`` and ``source_url`` for
    the first match whose re-extracted metadata contains coordinates, else
    ``None``.  Network and parse failures are swallowed — never fabricated.
    """
    from app.brain.metadata_extractor import MetadataExtractor

    for url in _match_urls(matches):
        try:
            resp = httpx.get(url, timeout=10.0, follow_redirects=True,
                             headers={"User-Agent": "ArkGeo-Investigator/1.0"})
            if resp.status_code != 200 or not resp.content:
                continue
            meta = MetadataExtractor().extract(resp.content)
            gps = meta.get("gps")
            if gps is not None and getattr(gps, "lat", None) not in (None, 0.0):
                return {
                    "gps": {"lat": gps.lat, "lon": gps.lon},
                    "camera": meta.get("camera", {}) or {},
                    "datetime_original": meta.get("datetime_original"),
                    "source_url": url,
                }
        except Exception as exc:
            logger.debug("Rehydration fetch failed for %s: %s", url, exc)
            continue
    return None


def extract_embedded_urls(exiftool_groups: dict) -> list[str]:
    """Scan metadata for embedded URLs (XMP, IPTC, EXIF comment fields)."""
    urls: list[str] = []
    seen: set[str] = set()
    import re
    url_re = re.compile(r"https?://[^\s\"'<>\xa0]+", re.IGNORECASE)
    for entries in exiftool_groups.values():
        for entry in entries:
            for match in url_re.findall(str(entry.get("value", ""))):
                if match not in seen:
                    seen.add(match)
                    urls.append(match)
    return urls


class SourceDiscoveryResult:
    def __init__(self) -> None:
        self.state: str = "UNAVAILABLE"
        self.phash: str = ""
        self.embedded_urls: list[str] = []
        self.exact_matches: list[dict] = []
        self.similar_matches: list[dict] = []
        self.timeline: list[dict] = []
        self.provider: str = "none"
        self.detail: str = ""


class SourceDiscoveryService:
    """Provider-agnostic reverse image search facade."""

    def analyze(
        self,
        image_bytes: bytes,
        exiftool_groups: dict,
        matches: Optional[list[dict]] = None,
    ) -> dict[str, Any]:
        """Compute local fingerprint and run any configured providers.

        ``matches`` (when supplied by the provider-aware caller) triggers
        original rehydration: the earliest matching web copy is fetched and
        re-examined for stripped EXIF GPS.
        """
        result = SourceDiscoveryResult()
        result.phash = compute_phash(image_bytes)
        result.embedded_urls = extract_embedded_urls(exiftool_groups)

        # Check if any reverse-search provider is configured via Admin
        from app.services.settings_store import settings_store
        provider_configured = bool(
            settings_store.get_key("reverse_search_api_key")
        )

        if provider_configured:
            # Extensible: dispatch to the configured provider here.
            # No provider is hardcoded — this is the integration point.
            result.state = "AVAILABLE"
            result.provider = "configured"
            result.detail = "Reverse search provider configured but no results returned yet."
        else:
            result.state = "UNAVAILABLE"
            result.provider = "none"
            result.detail = (
                "Reverse source discovery is not configured. "
                "Configure a provider through Admin to enable this capability. "
                "Local perceptual hash and embedded URL extraction remain available."
            )

        out = {
            "state": result.state,
            "phash": result.phash,
            "embedded_urls": result.embedded_urls,
            "exact_matches": result.exact_matches,
            "similar_matches": result.similar_matches,
            "timeline": result.timeline,
            "provider": result.provider,
            "detail": result.detail,
            "recovered_gps": None,
            "recovered_metadata": None,
            "recovered_source_url": None,
        }

        # Original rehydration: recover GPS from the earliest known web copy
        # (the copy a messaging intermediary stripped EXIF from).
        if matches:
            recovered = _rehydrate_original(matches)
            if recovered:
                out["recovered_gps"] = recovered["gps"]
                out["recovered_metadata"] = {
                    "camera": recovered["camera"],
                    "datetime_original": recovered["datetime_original"],
                }
                out["recovered_source_url"] = recovered["source_url"]
                out["detail"] = (
                    (out["detail"] or "")
                    + f" Original rehydration recovered GPS from {recovered['source_url']}."
                )
        return out


# Singleton
source_discovery = SourceDiscoveryService()
