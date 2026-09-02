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
            mc = self._monte_carlo(metadata_coords.lat, metadata_coords.lon, 25.0)
            return ConsensusResult(
                estimated_latitude=metadata_coords.lat,
                estimated_longitude=metadata_coords.lon,
                search_radius_meters=25.0,
                confidence_score=0.99,
                tier_used="metadata",
                visual_evidence_tags=self._merge_tags(vision_results, extractor_results),
                sources=["metadata"],
                **mc,
            )

        # 2) Telemetry (cell / Wi-Fi / last-known) – good but coarse.
        if telemetry_coords:
            consensus = self._weighted_average(
                [telemetry_coords] + self._coords_from_results(vision_results),
                [0.7] + [r.confidence_score for r in vision_results if r.estimated_latitude],
            )
            mc = self._monte_carlo(consensus.lat, consensus.lon, 500.0)
            return ConsensusResult(
                estimated_latitude=consensus.lat,
                estimated_longitude=consensus.lon,
                search_radius_meters=500.0,
                confidence_score=0.6,
                tier_used="telemetry",
                visual_evidence_tags=self._merge_tags(vision_results, extractor_results),
                sources=["telemetry"] + [r.source for r in vision_results],
                **mc,
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
                **self._monte_carlo(0.0, 0.0, 0.0),
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
            **self._monte_carlo(consensus_coord.lat, consensus_coord.lon, radius),
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _monte_carlo(self, lat: float, lon: float, radius_m: float) -> dict:
        """Draw Monte-Carlo samples around the estimate to quantify uncertainty.

        Returns ``credible_interval_radius`` (95th-percentile distance in metres)
        and a coarse ``probability_surface`` grid for map heatmap visualisation.
        Returns empty/zero fields when the estimate is degenerate (no location).
        """
        if (lat == 0.0 and lon == 0.0) or not radius_m or radius_m <= 0 or radius_m > 200_000:
            return {
                "credible_interval_radius": None,
                "probability_surface": None,
                "monte_carlo_samples": 0,
            }
        import math
        import random

        sigma = max(25.0, radius_m / 2.0)
        n = 600
        clat = math.radians(lat)
        samples: list[tuple[float, float]] = []
        for _ in range(n):
            east = random.gauss(0.0, sigma)
            north = random.gauss(0.0, sigma)
            dlat = north / 111_320.0
            dlon = east / (111_320.0 * max(math.cos(clat), 1e-6))
            samples.append((lat + dlat, lon + dlon))

        mean_lat = sum(s[0] for s in samples) / n
        mean_lon = sum(s[1] for s in samples) / n
        dists = [
            math.hypot(
                (s[0] - mean_lat) * 111_320.0,
                (s[1] - mean_lon) * 111_320.0 * max(math.cos(math.radians(mean_lat)), 1e-6),
            )
            for s in samples
        ]
        dists.sort()
        ci = dists[int(0.95 * n)] if n else radius_m

        # 7x7 normalised density grid spanning 2*radius_m.  Frontend renders
        # this as a probability heatmap centred on the resolved pin.
        half = max(radius_m, 200.0)
        size = (half * 2.0) / 7.0
        grid = [[0] * 7 for _ in range(7)]
        for s in samples:
            gi = min(6, max(0, int((s[0] - mean_lat + half) / size)))
            gj = min(6, max(0, int((s[1] - mean_lon + half) / size)))
            grid[gi][gj] += 1
        maxc = max((max(r) for r in grid), default=1) or 1
        grid = [[c / maxc for c in row] for row in grid]

        return {
            "credible_interval_radius": round(ci, 1),
            "probability_surface": {
                "center": [round(mean_lat, 6), round(mean_lon, 6)],
                "sigma_m": round(sigma, 1),
                "grid": grid,
                "grid_span_m": round(half * 2.0, 1),
            },
            "monte_carlo_samples": n,
        }

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
