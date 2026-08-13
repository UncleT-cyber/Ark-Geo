"""Tier 2 – Vision Ensemble.

Queries external geo-vision APIs (GeoSpy, GeoInfer) concurrently and
normalises their responses into :class:`VisionResult` objects.  Each provider
is optional — if a key is missing the provider is simply skipped.

In addition to dedicated geo-vision APIs, the ensemble can fall back to a
generic vision-capable LLM (e.g. GPT-4o) using the environmental forensic
prompt.  This makes Tier 2 functional with just a single LLM API key, which
is the most common deployment, rather than requiring GeoSpy/GeoInfer
credentials specifically.
"""
from __future__ import annotations

import asyncio
import base64
import logging
from typing import List

import httpx

from app.brain.clue_extractors.base import llm_client
from app.brain.system_prompts import ENVIRONMENTAL_FORENSIC_PROMPT
from app.core.config import settings
from app.models import VisionResult, VisualEvidenceTag
from app.services.settings_store import settings_store

logger = logging.getLogger(__name__)


class VisionEnsemble:
    """Aggregate multiple geo-vision API predictions."""

    def __init__(self) -> None:
        self._timeout = settings.vision_request_timeout

    async def locate(self, image_bytes: bytes) -> List[VisionResult]:
        """Run all configured vision providers concurrently.

        Reads API keys dynamically from the settings store (updated via the
        Admin Panel) so new keys take effect immediately without a restart.
        """
        # Read keys dynamically from settings store (falls back to config env)
        geospy_key = settings_store.get_key("geospy_api_key")
        geoinfer_key = settings_store.get_key("geoinfer_api_key")
        llm_key = settings_store.get_key("llm_api_key")

        b64 = base64.b64encode(image_bytes).decode()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            tasks = []
            if geospy_key:
                tasks.append(self._query_geospy(client, b64, geospy_key))
            if geoinfer_key:
                tasks.append(self._query_geoinfer(client, b64, geoinfer_key))
            results = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []

        vision_results: List[VisionResult] = []
        for r in results:
            if isinstance(r, Exception):
                logger.warning("Vision provider error: %s", r)
            elif r is not None:
                vision_results.append(r)

        # LLM vision geolocator fallback / additional signal.
        # Update the shared LLM client key from the settings store at runtime.
        if llm_key and llm_key != llm_client._key:
            llm_client._key = llm_key
        if llm_client.is_configured():
            llm_result = await asyncio.to_thread(
                self._query_llm_vision, image_bytes
            )
            if llm_result is not None:
                vision_results.append(llm_result)

        if not vision_results:
            logger.info("No vision providers configured; skipping ensemble")
        return vision_results

    # ------------------------------------------------------------------ #
    async def _query_geospy(self, client: httpx.AsyncClient, b64: str, api_key: str) -> VisionResult | None:
        try:
            resp = await client.post(
                settings.geospy_api_url,
                headers={"Authorization": f"Bearer {api_key}"},
                json={"image": b64},
            )
            resp.raise_for_status()
            data = resp.json()
            return VisionResult(
                source="geospy",
                estimated_latitude=data.get("lat"),
                estimated_longitude=data.get("lon"),
                search_radius_meters=data.get("radius_m"),
                confidence_score=float(data.get("confidence", 0.0)),
                primary_country=data.get("country"),
                region=data.get("region"),
                raw=data,
            )
        except Exception as exc:
            logger.warning("GeoSpy query failed: %s", exc)
            return None

    async def _query_geoinfer(self, client: httpx.AsyncClient, b64: str, api_key: str) -> VisionResult | None:
        try:
            resp = await client.post(
                settings.geoinfer_api_url,
                headers={"Authorization": f"Bearer {api_key}"},
                json={"image_base64": b64},
            )
            resp.raise_for_status()
            data = resp.json()
            return VisionResult(
                source="geoinfer",
                estimated_latitude=data.get("latitude"),
                estimated_longitude=data.get("longitude"),
                search_radius_meters=data.get("radius_meters"),
                confidence_score=float(data.get("score", data.get("confidence", 0.0))),
                primary_country=data.get("country"),
                region=data.get("state"),
                raw=data,
            )
        except Exception as exc:
            logger.warning("GeoInfer query failed: %s", exc)
            return None

    # ------------------------------------------------------------------ #
    def _query_llm_vision(self, image_bytes: bytes) -> VisionResult | None:
        """Use a generic vision-capable LLM as a geo-locator.

        Sends the environmental forensic prompt alongside the image and
        normalises the JSON response into a :class:`VisionResult`.  The
        confidence is capped below the dedicated geo-vision APIs so the
        consensus engine weights them appropriately.
        """
        data = llm_client.vision_query(image_bytes, ENVIRONMENTAL_FORENSIC_PROMPT)
        if not data:
            return None
        tags = [
            VisualEvidenceTag(
                category=t.get("category", "architecture"),
                label=t.get("label", ""),
                confidence=float(t.get("confidence", 0.5)),
            )
            for t in (data.get("visual_evidence_tags") or [])
            if isinstance(t, dict)
        ]
        lat = data.get("estimated_latitude")
        lon = data.get("estimated_longitude")
        return VisionResult(
            source="llm_vision",
            estimated_latitude=float(lat) if lat is not None else None,
            estimated_longitude=float(lon) if lon is not None else None,
            search_radius_meters=data.get("search_radius_meters"),
            confidence_score=min(0.75, float(data.get("confidence_score", 0.0))),
            primary_country=data.get("primary_country"),
            region=data.get("region"),
            evidence_tags=tags,
            raw=data,
        )
