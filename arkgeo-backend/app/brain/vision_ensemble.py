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
from app.brain.system_prompts import TERRAIN_IMINT_PROMPT
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
        # Wrap in a timeout so Ollama's 90s default doesn't stall the entire
        # pipeline — the deterministic fallbacks are more important.
        if llm_key and llm_key != llm_client._key:
            llm_client._key = llm_key
        if llm_client.is_configured():
            try:
                llm_result = await asyncio.wait_for(
                    asyncio.to_thread(self._query_llm_vision, image_bytes),
                    timeout=45.0,
                )
                if llm_result is not None:
                    vision_results.append(llm_result)
            except asyncio.TimeoutError:
                logger.warning("LLM vision query timed out after 45s; continuing without it")
            except Exception as exc:
                logger.warning("LLM vision query failed: %s", exc)

        if not vision_results:
            logger.info("No vision providers configured; skipping ensemble")
        return vision_results

    async def predict_geospy(self, image_bytes: bytes) -> Optional[VisionResult]:
        """Discrete GeoSpy-only prediction (the ``predict_geospy_coordinates`` tool).

        Returns ``None`` (no fabrication) when the GeoSpy key is missing or
        the provider call fails.
        """
        geospy_key = settings_store.get_key("geospy_api_key")
        if not geospy_key:
            logger.info("GeoSpy key not configured; skipping discrete prediction")
            return None
        b64 = base64.b64encode(image_bytes).decode()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await self._query_geospy(client, b64, geospy_key)

    # ------------------------------------------------------------------ #
    async def _query_geospy(self, client: httpx.AsyncClient, b64: str, api_key: str) -> VisionResult | None:
        try:
            resp = await client.post(
                settings.geospy_api_url,
                headers={"Authorization": f"Bearer {api_key}"},
                json={"image": b64, "top_k": 5},
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                data = data[0] if data else {}
            predictions = data.get("geo_predictions") or []
            if not predictions:
                return None
            top = predictions[0]
            coords = top.get("coordinates") or []
            lat = coords[0] if len(coords) > 0 else None
            lon = coords[1] if len(coords) > 1 else None
            try:
                confidence = float(top.get("similarity_score_1km") or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
            return VisionResult(
                source="geospy",
                estimated_latitude=lat,
                estimated_longitude=lon,
                search_radius_meters=1000.0,
                confidence_score=min(1.0, max(0.0, confidence)),
                primary_country=None,
                region=top.get("address"),
                raw=data,
            )
        except Exception as exc:
            logger.warning("GeoSpy query failed: %s", exc)
            return None

    async def _query_geoinfer(self, client: httpx.AsyncClient, b64: str, api_key: str) -> VisionResult | None:
        try:
            # GeoInfer's real API: api.geoinfer.com, X-GeoInfer-Key header,
            # multipart file upload + model_id query param.  The response is
            # wrapped in a {"data": {...}} envelope.
            image_bytes = base64.b64decode(b64)
            resp = await client.post(
                settings.geoinfer_api_url,
                headers={"X-GeoInfer-Key": api_key},
                files={"file": ("upload.jpg", image_bytes, "image/jpeg")},
                params={"model_id": settings.geoinfer_model} if settings.geoinfer_model else None,
            )
            resp.raise_for_status()
            data = resp.json()
            payload = (data or {}).get("data") or data or {}
            prediction = payload.get("prediction") or {}
            result_type = prediction.get("result_type")

            if result_type == "accuracy":
                top = prediction.get("top_prediction")
                if not top:
                    return None
                loc = top.get("location") or {}
                return VisionResult(
                    source="geoinfer",
                    estimated_latitude=top.get("latitude"),
                    estimated_longitude=top.get("longitude"),
                    search_radius_meters=None,
                    confidence_score=float(top.get("confidence") or 0.0),
                    primary_country=loc.get("country_code"),
                    region=loc.get("admin1") or loc.get("name"),
                    raw=data,
                )

            clusters = prediction.get("clusters") or []
            if not clusters:
                return None
            top = clusters[0]
            center = top.get("center") or {}
            loc = top.get("location") or {}
            radius_km = top.get("radius_km") or 0.0
            return VisionResult(
                source="geoinfer",
                estimated_latitude=center.get("latitude"),
                estimated_longitude=center.get("longitude"),
                search_radius_meters=radius_km * 1000,
                confidence_score=0.6,
                primary_country=loc.get("country_code"),
                region=loc.get("admin1") or loc.get("name"),
                raw=data,
            )
        except Exception as exc:
            logger.warning("GeoInfer query failed: %s", exc)
            return None

    # ------------------------------------------------------------------ #
    def _query_llm_vision(self, image_bytes: bytes) -> VisionResult | None:
        """Use a generic vision-capable LLM as a geo-locator.

        Sends the terrain IMINT / GEOINT forensic prompt alongside the image
        and normalises the JSON response into a :class:`VisionResult`.  The
        prompt ranks the top-3 candidate regions from terrain, vegetation,
        architecture, language and shadow analysis; those rankings surface
        as ``candidate_regions``.  Confidence is capped below the dedicated
        geo-vision APIs so the consensus engine weights them appropriately.

        Routes through the global ARK-CAI model (ai_gateway → cloud/Ollama
        cascade), NOT Ollama directly.  The async caller enforces a hard
        timeout so a slow model never stalls the pipeline.
        """
        data = llm_client.vision_query(image_bytes, TERRAIN_IMINT_PROMPT)
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
        candidate_regions: list[dict] = []
        for r in (data.get("candidate_regions") or []):
            if not isinstance(r, dict):
                continue
            try:
                conf = float(r.get("confidence", 0.0))
            except (TypeError, ValueError):
                conf = 0.0
            region = (r.get("region") or "").strip()
            if not region:
                continue
            candidate_regions.append({
                "region": region,
                "confidence": min(1.0, max(0.0, conf)),
                "rationale": (r.get("rationale") or "").strip() or None,
            })
        candidate_regions.sort(key=lambda r: r["confidence"], reverse=True)
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
            candidate_regions=candidate_regions,
            raw=data,
        )
