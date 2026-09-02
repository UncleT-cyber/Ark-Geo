"""OCR & infrastructure text extractor.

Returns extracted text strings and geo-probabilistic indicators rather than
direct coordinates.  These are folded into the consensus engine as evidence.

When the vision LLM fails or returns zero text regions the extractor falls
back to the deterministic pytesseract engine (if installed), so a degraded
model path still surfaces real on-image text instead of exiting empty.
"""
from __future__ import annotations

import io
import logging
import shutil
from typing import Any, Optional

from app.brain.clue_extractors.base import llm_client
from app.brain.system_prompts import OCR_INFRASTRUCTURE_PROMPT
from app.models import VisionResult, VisualEvidenceTag

logger = logging.getLogger(__name__)

_tesseract_check: dict[str, Any] = {"checked": False, "ok": False}


def _tesseract_available() -> bool:
    if not _tesseract_check["checked"]:
        _tesseract_check["checked"] = True
        _tesseract_check["ok"] = shutil.which("tesseract") is not None
    return bool(_tesseract_check["ok"])


def _fallback_ocr(image_bytes: bytes) -> list[VisualEvidenceTag]:
    """Deterministic OCR via pytesseract.

    Honest-by-design: when the engine (or the tesseract binary) is missing,
    the fallback yields no tags rather than fabricating text.
    """
    if not _tesseract_available():
        return []
    try:
        import pytesseract
        from PIL import Image

        text = pytesseract.image_to_string(Image.open(io.BytesIO(image_bytes)))
    except Exception as exc:  # noqa: BLE001 — fallback must never raise
        logger.warning("OCR fallback unavailable: %s", exc)
        return []
    return [
        VisualEvidenceTag(category="ocr", label=line, confidence=0.6)
        for line in (text or "").splitlines()
        if line.strip()
    ]


class OcrTextExtractor:
    name = "ocr"

    @staticmethod
    def _parse_tags(data: dict) -> list[VisualEvidenceTag]:
        tags: list[VisualEvidenceTag] = []
        for item in (data.get("extracted_texts") or []):
            if isinstance(item, dict):
                tags.append(VisualEvidenceTag(
                    category="ocr",
                    label=item.get("text", ""),
                    confidence=float(item.get("confidence", 0.5)),
                ))
        for ind in (data.get("geo_probabilistic_indicators") or []):
            if isinstance(ind, dict):
                tags.append(VisualEvidenceTag(
                    category="infrastructure",
                    label=ind.get("indicator", ""),
                    confidence=float(ind.get("weight", 0.5)),
                ))
        return tags

    def extract(self, image_bytes: bytes) -> Optional[VisionResult]:
        data = llm_client.vision_query(image_bytes, OCR_INFRASTRUCTURE_PROMPT)
        tags = self._parse_tags(data) if data else []

        if not any(t.category == "ocr" for t in tags):
            # Vision LLM failed or returned no text regions → deterministic OCR.
            tags += _fallback_ocr(image_bytes)

        if not tags:
            return None

        return VisionResult(
            source=self.name,
            confidence_score=min(0.8, max(t.confidence for t in tags)),
            evidence_tags=tags,
            raw=data,
        )
