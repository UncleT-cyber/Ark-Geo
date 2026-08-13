"""Botanical clue extractor.

Uses the environmental prompt (which covers botanical & geological markers)
but isolates vegetation-specific evidence tags.  In a fuller implementation
this would use a dedicated botanical prompt; for now it reuses the
environmental prompt and filters tags by category.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.brain.clue_extractors.base import llm_client
from app.brain.system_prompts import ENVIRONMENTAL_FORENSIC_PROMPT
from app.models import VisionResult, VisualEvidenceTag

logger = logging.getLogger(__name__)


class BotanicalExtractor:
    name = "botanical"

    def extract(self, image_bytes: bytes) -> Optional[VisionResult]:
        data = llm_client.vision_query(image_bytes, ENVIRONMENTAL_FORENSIC_PROMPT)
        if not data:
            return None
        tags = [
            VisualEvidenceTag(
                category="botanical",
                label=t.get("label", ""),
                confidence=float(t.get("confidence", 0.5)),
            )
            for t in (data.get("visual_evidence_tags") or [])
            if isinstance(t, dict) and t.get("category") == "botanical"
        ]
        # Botanical extractor contributes evidence, not direct coordinates
        return VisionResult(
            source=self.name,
            estimated_latitude=data.get("estimated_latitude"),
            estimated_longitude=data.get("estimated_longitude"),
            search_radius_meters=data.get("search_radius_meters"),
            confidence_score=float(data.get("confidence_score", 0.0)) * 0.6,
            primary_country=data.get("primary_country"),
            region=data.get("region"),
            evidence_tags=tags,
            raw=data,
        )
