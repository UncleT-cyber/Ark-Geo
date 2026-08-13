"""Integration tests for the full Brain pipeline & API."""
import io
import base64

import piexif
import pytest
from PIL import Image
from fastapi.testclient import TestClient

from main import app


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


class TestBrainPipeline:
    @pytest.mark.asyncio
    async def test_metadata_tier_short_circuit(self):
        from app.brain.pipeline import brain
        img = _make_image_with_gps()
        consensus, raw = await brain.analyze(img)
        assert consensus.tier_used == "metadata"
        assert consensus.confidence_score == 0.99

    @pytest.mark.asyncio
    async def test_no_metadata_no_keys_returns_low_confidence(self):
        """Without API keys, vision & extractors are skipped → low confidence."""
        from app.brain.pipeline import brain
        img = _make_plain_image()
        consensus, raw = await brain.analyze(img)
        assert consensus.confidence_score <= 0.1
        assert consensus.tier_used == "consensus"


class TestAPI:
    def setup_method(self):
        self.client = TestClient(app)

    def test_health(self):
        resp = self.client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "services" in data

    def test_analyze_with_gps(self):
        img = _make_image_with_gps()
        resp = self.client.post(
            "/api/v1/analyze",
            files={"file": ("test.jpg", img, "image/jpeg")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["consensus"]["tier_used"] == "metadata"
        assert data["image_sha256"]
        assert data["custody_hash"]

    def test_analyze_base64(self):
        img = _make_image_with_gps()
        b64 = base64.b64encode(img).decode()
        resp = self.client.post(
            "/api/v1/analyze/base64",
            json={"image_base64": b64},
        )
        assert resp.status_code == 200
        assert resp.json()["consensus"]["tier_used"] == "metadata"

    def test_ingest_with_gps(self):
        img = _make_image_with_gps()
        b64 = base64.b64encode(img).decode()
        resp = self.client.post(
            "/api/v1/ingest",
            json={"image_base64": b64, "user_id": "test-user"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["consensus"]["tier_used"] == "metadata"

    def test_sos_endpoint(self):
        resp = self.client.post(
            "/api/v1/sos",
            json={
                "user_id": "test-user",
                "last_known_gps": {"lat": 40.7128, "lon": -74.0060},
                "contacts": [{"name": "Jane", "phone": "+15551234567"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["sos_id"]
        assert "maps.google.com" in data["map_link"]

    def test_deadman_lifecycle(self):
        from app.core.security import hash_password
        pin = hash_password("1234")
        # Arm
        resp = self.client.post(
            "/api/v1/deadman/arm",
            json={
                "user_id": "dm-user",
                "duration_minutes": 5,
                "pin_hash": pin,
                "emergency_contacts": [{"name": "Jane", "phone": "+15551234567"}],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["armed"] is True

        # Status
        resp = self.client.get("/api/v1/deadman/status/dm-user")
        assert resp.status_code == 200
        assert resp.json()["armed"] is True

        # Disarm
        resp = self.client.post("/api/v1/deadman/disarm?user_id=dm-user")
        assert resp.status_code == 200
        assert resp.json()["armed"] is False
