"""Contradiction engine — surfaces structured inconsistencies across evidence.

A contradiction is *not* a judgement that an image is fake.  It is a
structured finding that two or more evidence signals conflict, with
enough metadata for an analyst to evaluate the conflict.

Each contradiction answers:
  - what_conflicts     – human description of the conflict
  - evidence_sources   – which signals produced the conflict
  - reliability        – how trustworthy the conflicting signals are
  - severity           – LOW | MEDIUM | HIGH
  - affects_assessment – does this impact the final location hypothesis?
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ContradictionEngine:
    """Cross-reference all evidence layers for structured contradictions."""

    def detect(
        self,
        consistency_findings: list[dict],
        geolocation_fusion: dict,
        exif_raw: dict,
        gps_spoofing_detected: bool,
        anomaly_score: float,
        sanity_mismatches: list[str],
    ) -> list[dict]:
        contradictions: list[dict] = []

        # 1. Metadata consistency findings → contradictions
        for finding in consistency_findings:
            if finding.get("status") in ("WARNING", "ERROR"):
                contradictions.append({
                    "what_conflicts": finding["message"],
                    "evidence_sources": finding.get("evidence", []),
                    "reliability": "high" if finding.get("severity") == "HIGH" else "medium",
                    "severity": finding.get("severity", "MEDIUM"),
                    "affects_assessment": finding.get("type") in (
                        "GPS_TIMESTAMP_CONFLICT", "DEVICE_SOFTWARE_MISMATCH",
                    ),
                    "type": finding.get("type", "METADATA_CONFLICT"),
                })

        # 2. GPS spoofing signals
        if gps_spoofing_detected:
            contradictions.append({
                "what_conflicts": (
                    "Visual environment evidence contradicts the GPS coordinates "
                    f"(anomaly score {anomaly_score * 100:.0f}%)."
                ),
                "evidence_sources": sanity_mismatches,
                "reliability": "high",
                "severity": "HIGH",
                "affects_assessment": True,
                "type": "GPS_SPOOFING",
            })

        # 3. Geolocation contradicting evidence
        fusion = geolocation_fusion or {}
        for contra in fusion.get("contradicting", []):
            contradictions.append({
                "what_conflicts": contra.get("label", "Unspecified contradiction"),
                "evidence_sources": [contra.get("layer", "unknown")],
                "reliability": "medium",
                "severity": "MEDIUM",
                "affects_assessment": True,
                "type": "LOCATION_CONTRADICTION",
            })

        # 4. EXIF presence vs claimed source
        exif_missing = not bool(exif_raw)
        if not exif_missing and gps_spoofing_detected:
            # EXIF exists but conflicts with visual — metadata may be fabricated
            contradictions.append({
                "what_conflicts": (
                    "EXIF metadata is present but conflicts with visual scene "
                    "analysis — metadata may have been fabricated or transplanted."
                ),
                "evidence_sources": ["exif_raw", "visual_analysis"],
                "reliability": "medium",
                "severity": "HIGH",
                "affects_assessment": True,
                "type": "METADATA_FABRICATION",
            })

        return contradictions


# Singleton
contradiction_engine = ContradictionEngine()
