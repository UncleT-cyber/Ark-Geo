"""Unit tests for the consensus engine."""
import pytest

from app.brain.consensus_engine import ConsensusEngine
from app.models import Coordinates, VisionResult, VisualEvidenceTag


class TestConsensusEngine:
    def setup_method(self):
        self.ce = ConsensusEngine()

    def test_metadata_trusts_directly(self):
        coords = Coordinates(lat=40.7128, lon=-74.0060)
        result = self.ce.aggregate(coords, None, [], [])
        assert result.tier_used == "metadata"
        assert result.confidence_score == 0.99
        assert result.estimated_latitude == 40.7128

    def test_telemetry_fallback(self):
        coords = Coordinates(lat=51.5074, lon=-0.1278)
        result = self.ce.aggregate(None, coords, [], [])
        assert result.tier_used == "telemetry"
        assert result.confidence_score == 0.6
        assert abs(result.estimated_latitude - 51.5074) < 0.01

    def test_vision_consensus_weighted_average(self):
        v1 = VisionResult(
            source="geospy", estimated_latitude=48.85, estimated_longitude=2.35,
            confidence_score=0.8, primary_country="France",
        )
        v2 = VisionResult(
            source="geoinfer", estimated_latitude=48.86, estimated_longitude=2.36,
            confidence_score=0.6,
        )
        result = self.ce.aggregate(None, None, [v1, v2], [])
        assert result.tier_used == "consensus"
        assert 48.85 <= result.estimated_latitude <= 48.86
        assert 0.0 < result.confidence_score < 1.0
        assert result.primary_country == "France"

    def test_no_coordinates_low_confidence(self):
        v = VisionResult(source="ocr", confidence_score=0.0)
        result = self.ce.aggregate(None, None, [v], [])
        assert result.confidence_score <= 0.1
        assert result.search_radius_meters >= 1_000_000

    def test_low_context_indoor_flag(self):
        from app.brain.clue_extractors.indoor import IndoorExtractor  # noqa
        v = VisionResult(
            source="indoor", confidence_score=0.03,
            raw={"flag_low_context_indoor": True},
        )
        result = self.ce.aggregate(None, None, [], [v])
        assert result.flag_low_context_indoor is True
        assert result.confidence_score <= 0.05

    def test_tags_deduplicated(self):
        v1 = VisionResult(
            source="geospy", estimated_latitude=48.85, estimated_longitude=2.35,
            confidence_score=0.8,
            evidence_tags=[VisualEvidenceTag(category="architecture", label="Haussmann", confidence=0.9)],
        )
        v2 = VisionResult(
            source="ocr", confidence_score=0.5,
            evidence_tags=[VisualEvidenceTag(category="architecture", label="haussmann", confidence=0.7)],
        )
        result = self.ce.aggregate(None, None, [v1, v2], [])
        labels = [t.label.lower() for t in result.visual_evidence_tags]
        assert labels.count("haussmann") == 1
