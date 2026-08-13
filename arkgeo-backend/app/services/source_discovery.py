"""Source discovery — provider-agnostic reverse image search architecture.

Computes a perceptual hash (pHash) of the image as a local, dependency-free
signal, and exposes an extensible provider registry for external reverse
search APIs (Google, TinEye, Yandex, etc.).

Providers are controlled via the Admin control plane (settings store).
If no provider is configured, the service reports ``UNAVAILABLE`` and
the investigation continues — never fabricating search results.
"""
from __future__ import annotations

import hashlib
import io
import logging
from typing import Any, Optional

from PIL import Image

logger = logging.getLogger(__name__)


def compute_phash(image_bytes: bytes, hash_size: int = 8) -> str:
    """Compute a perceptual hash (pHash) as a hex string.

    Uses average hashing: resize to NxN grayscale, threshold by mean,
    produce a bit string.  This is a local, no-dependency fingerprint.
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

    def analyze(self, image_bytes: bytes, exiftool_groups: dict) -> dict[str, Any]:
        """Compute local fingerprint and run any configured providers."""
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

        return {
            "state": result.state,
            "phash": result.phash,
            "embedded_urls": result.embedded_urls,
            "exact_matches": result.exact_matches,
            "similar_matches": result.similar_matches,
            "timeline": result.timeline,
            "provider": result.provider,
            "detail": result.detail,
        }


# Singleton
source_discovery = SourceDiscoveryService()
