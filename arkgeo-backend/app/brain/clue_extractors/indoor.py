"""Indoor micro-forensic extractor.

Handles low-context interior images (rooms, blank walls) where traditional
outdoor landmarks are absent.  Uses the dedicated INDOOR_MICRO_FORENSIC_PROMPT
and surfaces the ``flag_low_context_indoor`` signal.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.brain.clue_extractors.base import llm_client
from app.brain.system_prompts import INDOOR_MICRO_FORENSIC_PROMPT
from app.models import VisionResult, VisualEvidenceTag

logger = logging.getLogger(__name__)


class IndoorExtractor:
    name = "indoor"

    def extract(self, image_bytes: bytes) -> Optional[VisionResult]:
        data = llm_client.vision_query(image_bytes, INDOOR_MICRO_FORENSIC_PROMPT)
        if not data:
            return None
        tags = [
            VisualEvidenceTag(
                category="infrastructure",
                label=t.get("label", ""),
                confidence=float(t.get("confidence", 0.5)),
            )
            for t in (data.get("visual_evidence_tags") or [])
            if isinstance(t, dict)
        ]
        result = VisionResult(
            source=self.name,
            estimated_latitude=data.get("estimated_latitude"),
            estimated_longitude=data.get("estimated_longitude"),
            search_radius_meters=data.get("search_radius_meters"),
            confidence_score=float(data.get("confidence_score", 0.0)),
            primary_country=data.get("primary_country"),
            region=data.get("region"),
            evidence_tags=tags,
            raw=data,
        )
        # Stash the low-context flag for the consensus engine
        result.raw = result.raw or {}
        result.raw["flag_low_context_indoor"] = bool(data.get("flag_low_context_indoor", False))
        return result
