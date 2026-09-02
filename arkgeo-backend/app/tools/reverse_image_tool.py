"""Reverse image search tool — configured providers (TinEye / Serper).

Wraps :mod:`app.services.geo_providers`: TinEye upload-based matching when a
``tineye_api_key`` is set, and Serper image search when a ``serper_api_key``
is set plus either a reachable ``image_url`` (true reverse-image) or a
``search_query`` (keyword image search).  No configured provider degrades to
an honest ``UNAVAILABLE`` state — nothing is fabricated.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.services.geo_providers import search_serper, search_tineye
from app.services.settings_store import settings_store

logger = logging.getLogger(__name__)


async def reverse_image_search(
    image_bytes: bytes,
    search_query: Optional[str] = None,
    image_url: Optional[str] = None,
) -> dict[str, Any]:
    """Reverse-image search a cropped region/asset via configured providers."""
    providers: list[str] = []
    matches: list[dict[str, Any]] = []
    notes: list[str] = []

    if settings_store.get_key("tineye_api_key"):
        res = await search_tineye(image_bytes)
        if res.get("state") == "AVAILABLE":
            providers.append("tineye")
            matches.extend(res.get("matches") or [])
        notes.append(res.get("detail") or res.get("state", "tineye"))

    if settings_store.get_key("serper_api_key") and (image_url or search_query):
        res = await search_serper(search_query=search_query, image_url=image_url)
        if res.get("state") == "AVAILABLE":
            providers.append("serper")
            matches.extend(res.get("matches") or [])
        notes.append(res.get("detail") or res.get("state", "serper"))

    if not providers:
        return {
            "state": "UNAVAILABLE", "provider": None,
            "detail": (
                "No reverse-image provider configured (set tineye_api_key and/or "
                "serper_api_key via Admin)."
            ),
            "matches": [], "total": 0,
        }
    return {
        "state": "AVAILABLE",
        "provider": ", ".join(providers),
        "detail": "; ".join(n for n in notes if n),
        "matches": matches,
        "total": len(matches),
    }
