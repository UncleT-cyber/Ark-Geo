"""Integration tests for Phase 3 — AI pipeline & map integration.

Verifies the full request/response cycle between the mobile/web clients
and the backend Brain pipeline, including:
  * Ingest with device telemetry fallback (no EXIF GPS)
  * Vision ensemble LLM path (mocked httpx calls)
  * Response structure matching what the mobile MapRenderer and web
    Dashboard expect (coordinates, confidence, evidence tags, custody hash)
  * Zero-retention mode cleanup
  * SOS with consensus attached
"""
import base64
import io
import json
from unittest.mock import patch, MagicMock

import piexif
import pytest
from PIL import Image
from fastapi.testclient import TestClient

from app.services.ai_gateway import ai_gateway
from main import app


# --------------------------------------------------------------------------- #
# Image helpers
# --------------------------------------------------------------------------- #
def _make_image_with_gps(lat=48.8566, lon=2.3522):
    img = Image.new("RGB", (100, 100), color=(120, 120, 120))

    def _dms(value):
        v = abs(value)
        d = int(v)
        m = int((v - d) * 60)
        s = (v - d - m / 60) * 3600
        return ((d, 1), (m, 1), (int(s * 10000), 10000))

    gps_ifd = {
        piexif.GPSIFD.GPSLatitude: _dms(lat),
        piexif.GPSIFD.GPSLatitudeRef: b"N",
        piexif.GPSIFD.GPSLongitude: _dms(lon),
        piexif.GPSIFD.GPSLongitudeRef: b"E",
    }
    exif_bytes = piexif.dump({"GPS": gps_ifd})
    buf = io.BytesIO()
    img.save(buf, format="jpeg", exif=exif_bytes)
    return buf.getvalue()


def _make_plain_image():
    img = Image.new("RGB", (50, 50), color=(200, 200, 200))
    buf = io.BytesIO()
    img.save(buf, format="jpeg")
    return buf.getvalue()


def _b64(img_bytes):
    return base64.b64encode(img_bytes).decode()


# --------------------------------------------------------------------------- #
# Mock LLM vision response (what _query_llm_vision expects to parse)
# --------------------------------------------------------------------------- #
MOCK_LLM_VISION_RESPONSE = {
    "estimated_latitude": 35.6762,
    "estimated_longitude": 139.6503,
    "search_radius_meters": 5000.0,
    "confidence_score": 0.65,
    "primary_country": "Japan",
    "region": "Tokyo",
    "visual_evidence_tags": [
        {"category": "architecture", "label": "Japanese tile roof", "confidence": 0.85},
        {"category": "botanical", "label": "Ginkgo biloba", "confidence": 0.7},
        {"category": "infrastructure", "label": "JIS pole mount", "confidence": 0.6},
    ],
}


class TestIngestWithTelemetryFallback:
    """Telemetry (last-known GPS) should drive the consensus when EXIF is missing."""

    def setup_method(self):
        self.client = TestClient(app)

    def test_ingest_telemetry_fallback_to_last_known_gps(self):
        """No EXIF GPS → device telemetry last_known_outdoor_gps should be used."""
        img = _make_plain_image()
        b64 = _b64(img)
        resp = self.client.post(
            "/api/v1/ingest",
            json={
                "image_base64": b64,
                "user_id": "tel-user",
                "device_telemetry": {
                    "last_known_outdoor_gps": {
                        "lat": 51.5074,
                        "lon": -0.1278,
                        "timestamp": 1700000000,
                    },
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        consensus = data["consensus"]
        assert consensus["tier_used"] == "telemetry"
        assert abs(consensus["estimated_latitude"] - 51.5074) < 0.01
        assert abs(consensus["estimated_longitude"] - (-0.1278)) < 0.01
        assert consensus["confidence_score"] == 0.6
        # Telemetry resolve should appear in the response
        assert data["telemetry_resolve"] is not None
        assert abs(data["telemetry_resolve"]["lat"] - 51.5074) < 0.01

    @patch.object(ai_gateway, "is_configured", return_value=False)
    @patch.object(ai_gateway, "has_vision_llm", return_value=False)
    def test_ingest_no_gps_no_telemetry_returns_low_confidence(self, _v, _c):
        img = _make_plain_image()
        b64 = _b64(img)
        resp = self.client.post(
            "/api/v1/ingest",
            json={"image_base64": b64, "user_id": "no-gps-user"},
        )
        assert resp.status_code == 200
        consensus = resp.json()["consensus"]
        assert consensus["confidence_score"] <= 0.1
        assert consensus["tier_used"] == "consensus"


class TestVisionEnsembleLLMPath:
    """When the LLM key is configured, the vision ensemble should produce a
    coordinate-bearing VisionResult even without GeoSpy/GeoInfer keys."""

    def setup_method(self):
        self.client = TestClient(app)

    @patch("app.brain.clue_extractors.base.llm_client")
    @patch("app.brain.vision_ensemble.llm_client")
    def test_llm_vision_geolocation(self, mock_ve_llm, mock_ext_llm):
        # Both the vision ensemble and the clue extractors share the same
        # llm_client singleton, so patch it consistently.
        mock_ve_llm.is_configured.return_value = True
        mock_ext_llm.is_configured.return_value = True
        mock_ve_llm.vision_query.return_value = MOCK_LLM_VISION_RESPONSE
        mock_ext_llm.vision_query.return_value = MOCK_LLM_VISION_RESPONSE

        img = _make_plain_image()  # no EXIF GPS
        b64 = _b64(img)
        resp = self.client.post(
            "/api/v1/ingest",
            json={"image_base64": b64, "user_id": "vision-user"},
        )
        assert resp.status_code == 200
        consensus = resp.json()["consensus"]
        # The LLM provided coordinates, so consensus tier should engage
        assert consensus["tier_used"] == "consensus"
        assert abs(consensus["estimated_latitude"] - 35.6762) < 0.1
        assert abs(consensus["estimated_longitude"] - 139.6503) < 0.1
        assert consensus["primary_country"] == "Japan"
        assert consensus["confidence_score"] > 0.0
        # Evidence tags should include the mocked architectural / botanical tags
        labels = [t["label"] for t in consensus["visual_evidence_tags"]]
        assert "Japanese tile roof" in labels

    @patch("app.brain.clue_extractors.base.llm_client")
    @patch("app.brain.vision_ensemble.llm_client")
    def test_llm_vision_confidence_capped(self, mock_ve_llm, mock_ext_llm):
        """The LLM vision geolocator confidence is capped at 0.75."""
        mock_ve_llm.is_configured.return_value = True
        mock_ext_llm.is_configured.return_value = True
        high_conf_response = dict(MOCK_LLM_VISION_RESPONSE, confidence_score=0.99)
        mock_ve_llm.vision_query.return_value = high_conf_response
        mock_ext_llm.vision_query.return_value = high_conf_response

        img = _make_plain_image()
        b64 = _b64(img)
        resp = self.client.post(
            "/api/v1/analyze/base64",
            json={"image_base64": b64},
        )
        assert resp.status_code == 200
        consensus = resp.json()["consensus"]
        # Consensus confidence is a weighted average; with only the capped
        # LLM source it should be <= 0.75
        assert consensus["confidence_score"] <= 0.75


class TestResponseStructureForFrontend:
    """Ensure the AnalyzeResponse has every field the mobile MapRenderer and
    web Dashboard need to render the map, evidence inspector, and custody log."""

    def setup_method(self):
        self.client = TestClient(app)

    def test_response_has_all_required_fields(self):
        img = _make_image_with_gps()
        b64 = _b64(img)
        resp = self.client.post(
            "/api/v1/ingest",
            json={"image_base64": b64, "user_id": "struct-user"},
        )
        assert resp.status_code == 200
        data = resp.json()

        # Top-level fields
        for field in ("request_id", "custody_hash", "image_sha256", "consensus", "created_at"):
            assert field in data, f"Missing top-level field: {field}"

        # Consensus fields (needed by MapRenderer + DualDataCards)
        c = data["consensus"]
        for field in ("estimated_latitude", "estimated_longitude", "search_radius_meters",
                       "confidence_score", "tier_used", "visual_evidence_tags",
                       "flag_low_context_indoor", "sources"):
            assert field in c, f"Missing consensus field: {field}"

        # Evidence tag shape (needed by FeatureInspector)
        for tag in c["visual_evidence_tags"]:
            for field in ("category", "label", "confidence"):
                assert field in tag, f"Missing tag field: {field}"

        # Custody hash is a valid hex SHA-256
        assert len(data["custody_hash"]) == 64
        assert all(ch in "0123456789abcdef" for ch in data["custody_hash"])
        assert len(data["image_sha256"]) == 64


class TestZeroRetentionMode:
    """Zero-retention mode should still return a full response but not persist the image."""

    def setup_method(self):
        self.client = TestClient(app)

    def test_zero_retention_returns_response(self):
        img = _make_image_with_gps()
        b64 = _b64(img)
        resp = self.client.post(
            "/api/v1/analyze/base64",
            json={"image_base64": b64, "zero_retention": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["consensus"]["tier_used"] == "metadata"
        assert data["image_sha256"]  # hash still computed
        assert data["custody_hash"]  # custody still sealed


class TestSOSWithConsensus:
    """SOS endpoint should accept a consensus result and include the map link."""

    def setup_method(self):
        self.client = TestClient(app)

    def test_sos_with_consensus_coordinates(self):
        resp = self.client.post(
            "/api/v1/sos",
            json={
                "user_id": "sos-user",
                "consensus": {
                    "estimated_latitude": 35.6762,
                    "estimated_longitude": 139.6503,
                    "search_radius_meters": 5000.0,
                    "confidence_score": 0.72,
                    "tier_used": "consensus",
                    "visual_evidence_tags": [],
                    "flag_low_context_indoor": False,
                    "sources": ["llm_vision"],
                },
                "contacts": [{"name": "Jane", "phone": "+15551234567"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["dispatched"] is True
        assert "35.6762" in data["map_link"]
        assert "139.6503" in data["map_link"]


class TestHealthServiceStatus:
    """Health endpoint should report which vision/LLM services are configured."""

    def setup_method(self):
        self.client = TestClient(app)

    def test_health_reports_service_config(self):
        resp = self.client.get("/api/v1/health")
        assert resp.status_code == 200
        services = resp.json()["services"]
        for key in ("vision_geospy", "vision_geoinfer", "llm", "twilio", "opencellid", "storage"):
            assert key in services
