"""Unit tests for advanced signal verification features:
ELA generation, GPS spoofing detection, admin settings store.
"""
import io

import piexif
import pytest
from PIL import Image

from app.brain.metadata_extractor import (
    MetadataExtractor,
    generate_ela_heatmap,
    check_gps_spoofing,
)
from app.models import Coordinates, VisualEvidenceTag


def _make_plain_image_bytes() -> bytes:
    img = Image.new("RGB", (100, 100), color=(120, 120, 120))
    buf = io.BytesIO()
    img.save(buf, format="jpeg")
    return buf.getvalue()


def _make_image_with_gps_bytes(lat_deg=40.7589, lon_deg=-73.9851) -> bytes:
    img = Image.new("RGB", (100, 100), color=(120, 120, 120))
    zeroth = {piexif.ImageIFD.Make: b"Apple"}
    gps = {
        piexif.GPSIFD.GPSLatitudeRef: b"N" if lat_deg >= 0 else b"S",
        piexif.GPSIFD.GPSLatitude: [(abs(int(lat_deg)), 1), (45, 1), (32, 1)],
        piexif.GPSIFD.GPSLongitudeRef: b"E" if lon_deg >= 0 else b"W",
        piexif.GPSIFD.GPSLongitude: [(abs(int(lon_deg)), 1), (59, 1), (6, 1)],
    }
    exif = piexif.dump({"0th": zeroth, "GPS": gps})
    buf = io.BytesIO()
    img.save(buf, format="jpeg", exif=exif)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# ELA (Error Level Analysis)
# --------------------------------------------------------------------------- #
class TestELA:
    def test_ela_returns_base64_string(self):
        img_bytes = _make_plain_image_bytes()
        ela = generate_ela_heatmap(img_bytes)
        assert ela is not None
        assert ela.startswith("data:image/png;base64,")

    def test_ela_returns_none_for_invalid_bytes(self):
        ela = generate_ela_heatmap(b"\x00\x01\x02\x03")
        assert ela is None

    def test_ela_different_quality_different_output(self):
        """A varied image should produce different ELA at different quality levels."""
        # Create a gradient image (more realistic than uniform color)
        img = Image.new("RGB", (100, 100))
        pixels = img.load()
        for x in range(100):
            for y in range(100):
                pixels[x, y] = (x * 2, y * 2, (x + y) % 256)
        buf = io.BytesIO()
        img.save(buf, format="jpeg")
        img_bytes = buf.getvalue()
        ela1 = generate_ela_heatmap(img_bytes, quality=95)
        ela2 = generate_ela_heatmap(img_bytes, quality=50)
        assert ela1 is not None
        assert ela2 is not None
        assert ela1 != ela2

    def test_ela_included_in_metadata_extract(self):
        img_bytes = _make_plain_image_bytes()
        result = MetadataExtractor().extract(img_bytes)
        assert result.get("ela_heatmap") is not None
        assert result["ela_heatmap"].startswith("data:image/png;base64,")


# --------------------------------------------------------------------------- #
# GPS Spoofing Sanity Matrix
# --------------------------------------------------------------------------- #
class TestGPSSpoofing:
    def test_no_gps_returns_no_spoofing(self):
        tags = [VisualEvidenceTag(category="botanical", label="palm tree", confidence=0.9)]
        result = check_gps_spoofing(None, tags)
        assert result["gps_spoofing_detected"] is False
        assert result["anomaly_score"] == 0.0

    def test_tropical_tags_tropical_gps_no_spoofing(self):
        coords = Coordinates(lat=1.3521, lon=103.8198)  # Singapore (tropical)
        tags = [VisualEvidenceTag(category="botanical", label="palm tree", confidence=0.9)]
        result = check_gps_spoofing(coords, tags)
        assert result["gps_spoofing_detected"] is False
        assert result["gps_climate_zone"] == "tropical"
        assert result["visual_climate_zone"] == "tropical"

    def test_tropical_tags_arctic_gps_detected(self):
        coords = Coordinates(lat=78.0, lon=15.0)  # Svalbard (arctic)
        tags = [
            VisualEvidenceTag(category="botanical", label="coconut palm", confidence=0.9),
            VisualEvidenceTag(category="botanical", label="hibiscus", confidence=0.8),
        ]
        result = check_gps_spoofing(coords, tags)
        assert result["gps_spoofing_detected"] is True
        assert result["anomaly_score"] >= 0.5
        assert len(result["mismatches"]) > 0
        assert result["gps_climate_zone"] == "arctic"
        assert result["visual_climate_zone"] == "tropical"

    def test_arctic_tags_tropical_gps_detected(self):
        coords = Coordinates(lat=1.0, lon=0.0)  # tropical
        tags = [VisualEvidenceTag(category="botanical", label="spruce tree", confidence=0.85)]
        result = check_gps_spoofing(coords, tags)
        assert result["gps_spoofing_detected"] is True
        assert result["gps_climate_zone"] == "tropical"
        assert result["visual_climate_zone"] == "arctic"

    def test_infrastructure_hemisphere_mismatch(self):
        coords = Coordinates(lat=-35.0, lon=138.0)  # Australia (southern)
        tags = [VisualEvidenceTag(category="infrastructure", label="230V 50Hz EU standard", confidence=0.8)]
        result = check_gps_spoofing(coords, tags)
        assert result["anomaly_score"] >= 0.5
        assert len(result["mismatches"]) > 0

    def test_unknown_botanical_tags_no_spoofing(self):
        coords = Coordinates(lat=40.0, lon=-74.0)  # temperate
        tags = [VisualEvidenceTag(category="botanical", label="oak tree", confidence=0.7)]
        result = check_gps_spoofing(coords, tags)
        assert result["gps_spoofing_detected"] is False

    def test_works_with_dict_tags(self):
        coords = Coordinates(lat=78.0, lon=15.0)  # arctic
        tags = [{"category": "botanical", "label": "banana tree", "confidence": 0.9}]
        result = check_gps_spoofing(coords, tags)
        assert result["gps_spoofing_detected"] is True


# --------------------------------------------------------------------------- #
# Admin Settings Store
# --------------------------------------------------------------------------- #
class TestSettingsStore:
    def test_get_and_set_key(self):
        from app.services.settings_store import settings_store
        settings_store.set_key("geospy_api_key", "test-key-abc")
        assert settings_store.get_key("geospy_api_key") == "test-key-abc"
        settings_store.set_key("geospy_api_key", None)
        assert settings_store.get_key("geospy_api_key") is None

    def test_get_and_set_threshold(self):
        from app.services.settings_store import settings_store
        settings_store.set_threshold("min_confidence_threshold", 0.75)
        assert settings_store.get_threshold("min_confidence_threshold") == 0.75
        settings_store.set_threshold("min_confidence_threshold", 0.5)

    def test_get_keys_configured(self):
        from app.services.settings_store import settings_store
        result = settings_store.get_keys_configured()
        assert "geospy_api_key" in result
        assert "llm_api_key" in result
        assert isinstance(result["geospy_api_key"], bool)

    def test_key_values_never_in_response(self):
        from app.services.settings_store import settings_store
        settings_store.set_key("geospy_api_key", "secret-value-xyz")
        result = settings_store.get_keys_configured()
        assert result["geospy_api_key"] is True
        assert "secret-value-xyz" not in str(result)
        settings_store.set_key("geospy_api_key", None)


# --------------------------------------------------------------------------- #
# Settings API endpoint
# --------------------------------------------------------------------------- #
class TestSettingsAPI:
    def setup_method(self):
        from main import app
        from fastapi.testclient import TestClient
        self.client = TestClient(app)

    def test_get_settings(self):
        resp = self.client.get("/api/v1/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "api_keys" in data
        assert "thresholds" in data
        assert "min_confidence_threshold" in data["thresholds"]

    def test_update_thresholds(self):
        resp = self.client.put("/api/v1/settings", json={
            "thresholds": {
                "min_confidence_threshold": 0.8,
                "default_uncertainty_radius": 1000.0,
            }
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["thresholds"]["min_confidence_threshold"] == 0.8
        self.client.put("/api/v1/settings", json={
            "thresholds": {
                "min_confidence_threshold": 0.5,
                "default_uncertainty_radius": 500.0,
            }
        })

    def test_update_api_keys(self):
        resp = self.client.put("/api/v1/settings", json={
            "api_keys": {"geospy_api_key": "test-secret-key"}
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["api_keys"]["geospy_api_key"] is True
        assert "test-secret-key" not in str(data)
        self.client.put("/api/v1/settings", json={
            "api_keys": {"geospy_api_key": None}
        })

    def test_test_connection(self):
        resp = self.client.post("/api/v1/settings/test-connection?key_name=geospy_api_key")
        assert resp.status_code == 200
        data = resp.json()
        assert data["key_name"] == "geospy_api_key"
        assert "configured" in data


# --------------------------------------------------------------------------- #
# Threat Alert API
# --------------------------------------------------------------------------- #
class TestThreatAlertAPI:
    def setup_method(self):
        from main import app
        from fastapi.testclient import TestClient
        self.client = TestClient(app)

    def test_threat_alert_dispatch(self):
        resp = self.client.post("/api/v1/threat-alert", json={
            "alert_type": "geofence_violation",
            "user_id": "analyst-001",
            "coordinates": {"lat": 40.7589, "lon": -73.9851},
            "anomaly_score": 0.85,
            "description": "Target entered restricted geofence zone",
            "contacts": [{"name": "SOC Team", "phone": "+15551234567"}],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["alert_type"] == "geofence_violation"
        assert data["dispatched"] is True
        assert len(data["contacted"]) > 0

    def test_threat_alert_spoofing_type(self):
        resp = self.client.post("/api/v1/threat-alert", json={
            "alert_type": "gps_spoofing",
            "description": "GPS spoofing detected",
            "contacts": [{"name": "SOC", "phone": "+15551234567"}],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["alert_type"] == "gps_spoofing"


# --------------------------------------------------------------------------- #
# ELA + Spoofing in pipeline
# --------------------------------------------------------------------------- #
class TestPipelineAdvancedFeatures:
    def setup_method(self):
        from main import app
        from fastapi.testclient import TestClient
        self.client = TestClient(app)

    def test_analyze_response_includes_ela_heatmap(self):
        img_bytes = _make_plain_image_bytes()
        resp = self.client.post(
            "/api/v1/analyze",
            files={"file": ("test.jpg", img_bytes, "image/jpeg")},
        )
        data = resp.json()
        assert data.get("ela_heatmap") is not None
        assert data["ela_heatmap"].startswith("data:image/png;base64,")

    def test_analyze_response_includes_spoofing_fields(self):
        img_bytes = _make_plain_image_bytes()
        resp = self.client.post(
            "/api/v1/analyze",
            files={"file": ("test.jpg", img_bytes, "image/jpeg")},
        )
        data = resp.json()
        assert "gps_spoofing_detected" in data
        assert "anomaly_score" in data
        assert "sanity_mismatches" in data
        assert "gps_climate_zone" in data
        assert "visual_climate_zone" in data

    def test_no_exif_no_keys_returns_null_coordinates(self):
        img_bytes = _make_plain_image_bytes()
        resp = self.client.post(
            "/api/v1/analyze",
            files={"file": ("test.jpg", img_bytes, "image/jpeg")},
        )
        data = resp.json()
        assert data["coordinates"] is None
        assert data["source"] == "EXIF_MISSING_NO_AI_KEY"

    def test_valid_exif_returns_real_coordinates(self):
        img_bytes = _make_image_with_gps_bytes(lat_deg=40.7589, lon_deg=-73.9851)
        resp = self.client.post(
            "/api/v1/analyze",
            files={"file": ("gps.jpg", img_bytes, "image/jpeg")},
        )
        data = resp.json()
        assert data["coordinates"] is not None
        assert abs(data["coordinates"]["lat"] - 40.7589) < 0.01
        assert abs(data["coordinates"]["lon"] - (-73.9851)) < 0.01
        assert data["source"] == "NATIVE_EXIF_HARDWARE"
