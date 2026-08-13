"""Multi-layer geolocation fusion engine.

Builds a structured evidence model from multiple location signals,
distinguishing FACTS (directly extracted) from OBSERVATIONS (interpretations)
and INFERENCE (combined conclusion).  The final location is a hypothesis
supported by evidence — never a single-model dictate.

Evidence layers:
  1. EXIF GPS         (fact)
  2. OCR text         (observation)
  3. Visual scene     (observation)
  4. Landmark recogn. (observation)
  5. Physical clues   (observation)
  6. Sun/shadow       (observation)
  7. Weather/time     (observation)
  8. External geo-intel(observation)

Each evidence item is tagged with an evidence class so the fusion engine
can count *independent* corroboration rather than double-counting.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from app.models import Coordinates, ConsensusResult, VisualEvidenceTag

logger = logging.getLogger(__name__)


@dataclass
class EvidenceItem:
    """A single piece of geolocation evidence."""
    layer: str
    label: str
    direction: str  # "supporting" | "contradicting" | "neutral"
    confidence: float
    evidence_class: str
    value: str = ""


@dataclass
class GeoFusionResult:
    """Structured geolocation hypothesis with explainability."""
    hypothesis: Optional[Coordinates]
    primary_location: str
    confidence: float
    supporting: list[EvidenceItem]
    contradicting: list[EvidenceItem]
    independent_evidence_classes: int
    detail: str


class GeolocationFusion:
    """Fuse multi-layer evidence into a defensible location hypothesis."""

    def fuse(
        self,
        consensus: Optional[ConsensusResult],
        coordinates: Optional[Coordinates],
        address: Optional[dict],
        visual_tags: list[VisualEvidenceTag],
        consistency_findings: list[dict],
        exif_raw: dict,
    ) -> dict:
        """Build the fusion result from available evidence layers."""
        evidence: list[EvidenceItem] = []

        # Layer 1: EXIF GPS (fact)
        if coordinates and coordinates.lat != 0.0 and coordinates.lon != 0.0:
            evidence.append(EvidenceItem(
                layer="EXIF GPS",
                label=f"GPS coordinates {coordinates.lat:.4f}, {coordinates.lon:.4f}",
                direction="supporting",
                confidence=0.99,
                evidence_class="hardware_metadata",
                value=f"{coordinates.lat},{coordinates.lon}",
            ))

        # Layer 2: Visual scene tags (observations)
        for tag in visual_tags:
            if tag.category in ("botanical", "infrastructure", "architecture"):
                evidence.append(EvidenceItem(
                    layer="Visual Scene",
                    label=tag.label,
                    direction="supporting",
                    confidence=tag.confidence,
                    evidence_class=f"visual_{tag.category}",
                ))

        # Layer 3: OCR text tags
        for tag in visual_tags:
            if tag.category == "ocr":
                evidence.append(EvidenceItem(
                    layer="OCR Text",
                    label=tag.label,
                    direction="supporting",
                    confidence=tag.confidence,
                    evidence_class="ocr_text",
                ))

        # Contradictions from consistency findings
        for finding in consistency_findings:
            if finding.get("type") == "GPS_TIMESTAMP_CONFLICT":
                evidence.append(EvidenceItem(
                    layer="GPS Timestamp",
                    label=finding["message"],
                    direction="contradicting",
                    confidence=0.8,
                    evidence_class="timestamp_analysis",
                ))

        supporting = [e for e in evidence if e.direction == "supporting"]
        contradicting = [e for e in evidence if e.direction == "contradicting"]
        classes = {e.evidence_class for e in supporting}

        # Confidence: blend consensus with evidence corroboration
        base_conf = consensus.confidence_score if consensus else 0.0
        class_bonus = min(0.1, len(classes) * 0.025)
        contradiction_penalty = min(0.3, len(contradicting) * 0.15)
        confidence = max(0.0, min(1.0, base_conf + class_bonus - contradiction_penalty))

        location_label = ""
        if address and address.get("display_name"):
            location_label = address["display_name"]
        elif consensus and consensus.primary_country:
            location_label = consensus.primary_country
        elif coordinates:
            location_label = f"{coordinates.lat:.4f}, {coordinates.lon:.4f}"

        detail = self._build_explainability(supporting, contradicting, classes, confidence, location_label)

        return {
            "hypothesis": {"lat": coordinates.lat, "lon": coordinates.lon} if coordinates else None,
            "primary_location": location_label,
            "confidence": round(confidence, 4),
            "supporting": [self._serialize(e) for e in supporting],
            "contradicting": [self._serialize(e) for e in contradicting],
            "independent_evidence_classes": len(classes),
            "detail": detail,
        }

    # ------------------------------------------------------------------ #
    def _build_explainability(
        self, supporting: list, contradicting: list, classes: set,
        confidence: float, location: str,
    ) -> dict:
        return {
            "question": f"WHY DOES ARKGEO THINK THIS IS {location or 'UNKNOWN'}?",
            "supporting": [f"+ {e.layer} → {e.label}" for e in supporting],
            "against": [f"- {e.label}" for e in contradicting],
            "independent_evidence_classes": len(classes),
            "confidence_pct": round(confidence * 100),
            "note": (
                "Confidence reflects corroborating evidence classes minus "
                "contradiction penalties. This is a hypothesis, not a certainty."
            ),
        }

    @staticmethod
    def _serialize(e: EvidenceItem) -> dict:
        return {
            "layer": e.layer,
            "label": e.label,
            "direction": e.direction,
            "confidence": round(e.confidence, 4),
            "evidence_class": e.evidence_class,
            "value": e.value,
        }


# Singleton
geolocation_fusion = GeolocationFusion()
