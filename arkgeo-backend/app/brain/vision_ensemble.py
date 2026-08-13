"""Tier 2 – Vision Ensemble.

Queries external geo-vision APIs (GeoSpy, GeoInfer) concurrently and
normalises their responses into :class:`VisionResult` objects.  Each provider
is optional — if a key is missing the provider is simply skipped.
"""
from __future__ import annotations

import asyncio
import base64
import logging
from typing import List

import httpx

from app.core.config import settings
from app.models import VisionResult, VisualEvidenceTag

logger = logging.getLogger(__name__)


class VisionEnsemble:
    """Aggregate multiple geo-vision API predictions."""

    def __init__(self) -> None:
        self._timeout = settings.vision_request_timeout

    async def locate(self, image_bytes: bytes) -> List[VisionResult]:
        """Run all configured vision providers concurrently."""
        b64 = base64.b64encode(image_bytes).decode()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            tasks = []
            if settings.geospy_api_key:
                tasks.append(self._query_geospy(client, b64))
            if settings.geoinfer_api_key:
                tasks.append(self._query_geoinfer(client, b64))
            if not tasks:
                logger.info("No vision API keys configured; skipping ensemble")
                return []
            results = await asyncio.gather(*tasks, return_exceptions=True)

        vision_results: List[VisionResult] = []
        for r in results:
            if isinstance(r, Exception):
                logger.warning("Vision provider error: %s", r)
            elif r is not None:
                vision_results.append(r)
        return vision_results

    # ------------------------------------------------------------------ #
    async def _query_geospy(self, client: httpx.AsyncClient, b64: str) -> VisionResult | None:
        try:
            resp = await client.post(
                settings.geospy_api_url,
                headers={"Authorization": f"Bearer {settings.geospy_api_key}"},
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

    async def _query_geoinfer(self, client: httpx.AsyncClient, b64: str) -> VisionResult | None:
        try:
            resp = await client.post(
                settings.geoinfer_api_url,
                headers={"Authorization": f"Bearer {settings.geoinfer_api_key}"},
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
