"""Tier 4 – Consensus & confidence engine.

Aggregates evidence from all upstream tiers (metadata, telemetry, vision
ensemble, clue extractors) into a single :class:`ConsensusResult`.

Approach:
* Coordinates are weighted by each source's confidence score.
* A Bayesian-style update blends independent estimates.
* The final search radius widens when disagreement is high.
* Evidence tags from all sources are deduplicated and merged.
"""
from __future__ import annotations

import logging
import math
from typing import List, Optional

from app.models import Coordinates, VisionResult, VisualEvidenceTag
from app.models.schemas import ConsensusResult

logger = logging.getLogger(__name__)


class ConsensusEngine:
    """Bayesian-flavoured aggregator for multi-source location estimates."""

    # ------------------------------------------------------------------ #
    def aggregate(
        self,
        metadata_coords: Optional[Coordinates],
        telemetry_coords: Optional[Coordinates],
        vision_results: List[VisionResult],
        extractor_results: List[VisionResult],
    ) -> ConsensusResult:
        # 1) Trust deterministic metadata above everything else.
        if metadata_coords:
            return ConsensusResult(
                estimated_latitude=metadata_coords.lat,
                estimated_longitude=metadata_coords.lon,
                search_radius_meters=25.0,
                confidence_score=0.99,
                tier_used="metadata",
                visual_evidence_tags=self._merge_tags(vision_results, extractor_results),
                sources=["metadata"],
            )

        # 2) Telemetry (cell / Wi-Fi / last-known) – good but coarse.
        if telemetry_coords:
            consensus = self._weighted_average(
                [telemetry_coords] + self._coords_from_results(vision_results),
                [0.7] + [r.confidence_score for r in vision_results if r.estimated_latitude],
            )
            return ConsensusResult(
                estimated_latitude=consensus.lat,
                estimated_longitude=consensus.lon,
                search_radius_meters=500.0,
                confidence_score=0.6,
                tier_used="telemetry",
                visual_evidence_tags=self._merge_tags(vision_results, extractor_results),
                sources=["telemetry"] + [r.source for r in vision_results],
            )

        # 3) Pure AI consensus – vision + extractors only.
        all_results = vision_results + extractor_results
        coord_results = [r for r in all_results if r.estimated_latitude is not None]

        if not coord_results:
            # No coordinate estimates at all – return evidence-only, low confidence.
            tags = self._merge_tags(vision_results, extractor_results)
            low_context = any(
                (r.raw or {}).get("flag_low_context_indoor") for r in extractor_results
            )
            return ConsensusResult(
                estimated_latitude=0.0,
                estimated_longitude=0.0,
                search_radius_meters=1_000_000.0,
                confidence_score=0.05 if low_context else 0.1,
                tier_used="consensus",
                flag_low_context_indoor=low_context,
                visual_evidence_tags=tags,
                sources=[r.source for r in all_results],
            )

        coords = self._coords_from_results(coord_results)
        weights = [r.confidence_score for r in coord_results]
        consensus_coord = self._weighted_average(coords, weights)

        # Confidence: weighted average, penalised by disagreement.
        avg_conf = sum(weights) / len(weights) if weights else 0.0
        disagreement = self._spread(coords)
        confidence = max(0.0, min(1.0, avg_conf * (1.0 - disagreement)))

        # Radius scales with disagreement (100 m → 50 km).
        radius = min(50_000.0, 100.0 + disagreement * 50_000.0)

        # Pick the most confident source for country/region.
        best = max(coord_results, key=lambda r: r.confidence_score)

        low_context = any(
            (r.raw or {}).get("flag_low_context_indoor") for r in extractor_results
        )

        return ConsensusResult(
            estimated_latitude=consensus_coord.lat,
            estimated_longitude=consensus_coord.lon,
            search_radius_meters=radius,
            confidence_score=confidence,
            primary_country=best.primary_country,
            region=best.region,
            tier_used="consensus",
            flag_low_context_indoor=low_context,
            visual_evidence_tags=self._merge_tags(vision_results, extractor_results),
            sources=[r.source for r in all_results],
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _coords_from_results(results: List[VisionResult]) -> List[Coordinates]:
        return [
            Coordinates(lat=r.estimated_latitude, lon=r.estimated_longitude)
            for r in results
            if r.estimated_latitude is not None and r.estimated_longitude is not None
        ]

    @staticmethod
    def _weighted_average(coords: List[Coordinates], weights: List[float]) -> Coordinates:
        if not coords:
            return Coordinates(lat=0.0, lon=0.0)
        weights = [max(w, 1e-6) for w in weights] if weights else [1.0] * len(coords)
        if len(weights) < len(coords):
            weights += [1e-6] * (len(coords) - len(weights))
        total_w = sum(weights)
        lat = sum(c.lat * w for c, w in zip(coords, weights)) / total_w
        lon = sum(c.lon * w for c, w in zip(coords, weights)) / total_w
        return Coordinates(lat=lat, lon=lon)

    @staticmethod
    def _spread(coords: List[Coordinates]) -> float:
        """Normalised disagreement metric in [0, 1]."""
        if len(coords) < 2:
            return 0.0
        lats = [c.lat for c in coords]
        lons = [c.lon for c in coords]
        lat_range = max(lats) - min(lats)
        lon_range = max(lons) - min(lons)
        # Haversine-ish normalisation (degrees → rough km)
        dist = math.sqrt(lat_range ** 2 + lon_range ** 2) * 111.0
        return min(1.0, dist / 2000.0)

    @staticmethod
    def _merge_tags(
        vision_results: List[VisionResult],
        extractor_results: List[VisionResult],
    ) -> List[VisualEvidenceTag]:
        seen: set[tuple[str, str]] = set()
        merged: List[VisualEvidenceTag] = []
        for r in vision_results + extractor_results:
            for tag in r.evidence_tags:
                key = (tag.category.lower(), tag.label.lower())
                if key not in seen and tag.label:
                    seen.add(key)
                    merged.append(tag)
        return merged
