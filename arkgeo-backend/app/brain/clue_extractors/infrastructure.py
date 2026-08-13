"""Infrastructure clue extractor.

Focuses on utility poles, street lamps, road markings, and electrical
standards.  Reuses the OCR/infrastructure prompt and isolates
infrastructure-category tags.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.brain.clue_extractors.base import llm_client
from app.brain.system_prompts import OCR_INFRASTRUCTURE_PROMPT
from app.models import VisionResult, VisualEvidenceTag

logger = logging.getLogger(__name__)


class InfrastructureExtractor:
    name = "infrastructure"

    def extract(self, image_bytes: bytes) -> Optional[VisionResult]:
        data = llm_client.vision_query(image_bytes, OCR_INFRASTRUCTURE_PROMPT)
        if not data:
            return None

        tags: list[VisualEvidenceTag] = []
        for ind in (data.get("geo_probabilistic_indicators") or []):
            if isinstance(ind, dict):
                tags.append(VisualEvidenceTag(
                    category="infrastructure",
                    label=ind.get("indicator", ""),
                    confidence=float(ind.get("weight", 0.5)),
                ))

        return VisionResult(
            source=self.name,
            confidence_score=min(0.7, max(t.confidence for t in tags)) if tags else 0.0,
            evidence_tags=tags,
            raw=data,
        )
