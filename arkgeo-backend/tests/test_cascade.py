"""Tests for the real failover cascade pipeline.

Verifies:
  - Native EXIF extraction with full camera metadata
  - Cryptographic custody certificate (SHA-256 + MD5 + ms timestamp)
  - Telemetry fallback (last-known GPS)
  - Graceful degradation (no EXIF, no AI keys)
  - Reverse geocode integration (mocked to avoid network in CI)
"""
import io
import hashlib
import base64
from unittest.mock import patch, MagicMock

import piexif
import pytest
from PIL import Image

from app.brain.metadata_extractor import MetadataExtractor, reverse_geocode
from app.brain.pipeline import brain, CascadeResult
from app.core.security import custody_certificate, md5_hex, sha256_hex
from app.models import AddressInfo, Coordinates, DeviceTelemetry, GpsFix
from app.services.ai_gateway import ai_gateway


# --------------------------------------------------------------------------- #
# Image factories
# --------------------------------------------------------------------------- #
def _make_image_with_full_exif(lat=48.8566, lon=2.3522):
    """Create a JPEG with GPS + camera EXIF metadata."""
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
        piexif.GPSIFD.GPSAltitude: (35, 1),
        piexif.GPSIFD.GPSAltitudeRef: b"\x00",
    }
    exif_ifd = {
        piexif.ExifIFD.DateTimeOriginal: b"2024:01:15 14:30:00",
        piexif.ExifIFD.LensModel: b"iPhone 15 Pro Main",
        piexif.ExifIFD.FNumber: (18, 10),
        piexif.ExifIFD.ExposureTime: (1, 120),
        piexif.ExifIFD.ISOSpeedRatings: 100,
        piexif.ExifIFD.FocalLength: (24, 1),
    }
    zeroth_ifd = {
        piexif.ImageIFD.Make: b"Apple",
        piexif.ImageIFD.Model: b"iPhone 15 Pro",
        piexif.ImageIFD.Software: b"17.2.1",
    }
    exif_bytes = piexif.dump({
        "0th": zeroth_ifd,
        "Exif": exif_ifd,
        "GPS": gps_ifd,
    })
    buf = io.BytesIO()
    img.save(buf, format="jpeg", exif=exif_bytes)
    return buf.getvalue()


def _make_plain_image():
    img = Image.new("RGB", (50, 50), color=(200, 200, 200))
    buf = io.BytesIO()
    img.save(buf, format="jpeg")
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Cryptographic custody tests
# --------------------------------------------------------------------------- #
class TestCustodyCertificate:
    def test_sha256_matches_hashlib(self):
        data = b"forensic test image bytes"
        cert = custody_certificate(data)
        assert cert["sha256"] == hashlib.sha256(data).hexdigest()

    def test_md5_matches_hashlib(self):
        data = b"forensic test image bytes"
        cert = custody_certificate(data)
        assert cert["md5"] == hashlib.md5(data).hexdigest()

    def test_ingested_at_ms_is_millisecond_precision(self):
        cert = custody_certificate(b"x")
        # Should be ~13 digits (epoch ms)
        assert cert["ingested_at_ms"] > 1_000_000_000_000

    def test_different_bytes_different_hash(self):
        cert1 = custody_certificate(b"image1")
        cert2 = custody_certificate(b"image2")
        assert cert1["sha256"] != cert2["sha256"]
        assert cert1["md5"] != cert2["md5"]

    def test_md5_hex_helper(self):
        assert md5_hex(b"test") == hashlib.md5(b"test").hexdigest()

    def test_sha256_hex_helper_accepts_str(self):
        assert sha256_hex("test") == sha256_hex(b"test")


# --------------------------------------------------------------------------- #
# EXIF metadata extraction tests
# --------------------------------------------------------------------------- #
class TestMetadataExtraction:
    def setup_method(self):
        self.ext = MetadataExtractor()

    def test_extracts_full_camera_metadata(self):
        img = _make_image_with_full_exif()
        result = self.ext.extract(img)
        cam = result["camera"]
        assert cam["make"] == "Apple"
        assert cam["model"] == "iPhone 15 Pro"
        assert cam["lens_model"] == "iPhone 15 Pro Main"
        assert cam["software"] == "17.2.1"
        assert cam["f_number"] == pytest.approx(1.8)
        assert cam["exposure_time"] == pytest.approx(1 / 120)
        assert cam["iso"] == 100
        assert cam["focal_length"] == pytest.approx(24.0)

    def test_extracts_altitude(self):
        img = _make_image_with_full_exif()
        result = self.ext.extract(img)
        assert result["altitude"] == 35.0

    def test_extracts_datetime_original(self):
        img = _make_image_with_full_exif()
        result = self.ext.extract(img)
        assert result["datetime_original"] == "2024:01:15 14:30:00"

    def test_extracts_gps_coordinates(self):
        img = _make_image_with_full_exif(48.8566, 2.3522)
        result = self.ext.extract(img)
        assert result["gps"] is not None
        assert abs(result["gps"].lat - 48.8566) < 0.001
        assert abs(result["gps"].lon - 2.3522) < 0.001

    def test_plain_image_no_camera_metadata(self):
        img = _make_plain_image()
        result = self.ext.extract(img)
        assert result["camera"] == {}
        assert result["gps"] is None
        assert result["altitude"] is None
        assert result["datetime_original"] is None


# --------------------------------------------------------------------------- #
# Reverse geocode tests (mocked — no network in CI)
# --------------------------------------------------------------------------- #
class TestReverseGeocode:
    @patch("app.brain.metadata_extractor._geolocator")
    def test_reverse_geocode_returns_address(self, mock_geo):
        mock_location = MagicMock()
        mock_location.raw = {
            "address": {
                "country": "France",
                "state": "Île-de-France",
                "city": "Paris",
                "road": "Rue de Rivoli",
                "postcode": "75001",
            }
        }
        mock_location.address = "Rue de Rivoli, 75001, Paris, Île-de-France, France"
        mock_geo.reverse.return_value = mock_location

        addr = reverse_geocode(48.8566, 2.3522)
        assert addr is not None
        assert addr.country == "France"
        assert addr.state == "Île-de-France"
        assert addr.city == "Paris"
        assert addr.road == "Rue de Rivoli"
        assert addr.postcode == "75001"
        assert "Paris" in addr.display_name

    @patch("app.brain.metadata_extractor._geolocator")
    def test_reverse_geocode_handles_failure(self, mock_geo):
        mock_geo.reverse.side_effect = Exception("Network error")
        addr = reverse_geocode(0.0, 0.0)
        assert addr is None

    @patch("app.brain.metadata_extractor._geolocator")
    def test_reverse_geocode_returns_none_on_empty(self, mock_geo):
        mock_geo.reverse.return_value = None
        addr = reverse_geocode(10.0, 20.0)
        assert addr is None


# --------------------------------------------------------------------------- #
# Full cascade pipeline tests
# --------------------------------------------------------------------------- #
class TestCascadePipeline:
    @pytest.mark.asyncio
    @patch("app.brain.metadata_extractor._geolocator")
    async def test_tier1_exif_hardware_with_reverse_geocode(self, mock_geo):
        """EXIF GPS → NATIVE_EXIF_HARDWARE source with address."""
        mock_location = MagicMock()
        mock_location.raw = {"address": {"country": "France", "city": "Paris"}}
        mock_location.address = "Paris, France"
        mock_geo.reverse.return_value = mock_location

        img = _make_image_with_full_exif()
        result = await brain.analyze(img)

        assert result.source == "NATIVE_EXIF_HARDWARE"
        assert result.status == "SUCCESS"
        assert result.coordinates is not None
        assert abs(result.coordinates.lat - 48.8566) < 0.001
        assert result.address is not None
        assert result.address.country == "France"
        assert result.address.city == "Paris"
        assert result.camera["make"] == "Apple"
        assert result.camera["model"] == "iPhone 15 Pro"
        assert result.altitude == 35.0
        assert result.consensus.confidence_score == 0.99
        assert result.consensus.primary_country == "France"

    @pytest.mark.asyncio
    async def test_tier1_custody_certificate_always_computed(self):
        """SHA-256 + MD5 custody certificate present even on degraded results."""
        img = _make_plain_image()
        result = await brain.analyze(img)
        assert result.custody_certificate is not None
        assert result.custody_certificate["sha256"] == hashlib.sha256(img).hexdigest()
        assert result.custody_certificate["md5"] == hashlib.md5(img).hexdigest()
        assert result.custody_certificate["ingested_at_ms"] > 0
        assert result.image_sha256 == result.custody_certificate["sha256"]

    @pytest.mark.asyncio
    async def test_tier3_telemetry_fallback_last_known_gps(self):
        """No EXIF GPS → falls back to device telemetry last_known GPS."""
        img = _make_plain_image()
        telemetry = DeviceTelemetry(
            last_known_outdoor_gps=GpsFix(lat=40.7128, lon=-74.0060, timestamp=1700000000),
        )
        with patch("app.brain.metadata_extractor.reverse_geocode") as mock_rg:
            mock_rg.return_value = AddressInfo(country="USA", city="New York")
            result = await brain.analyze(img, device_telemetry=telemetry)

        assert result.source == "TELEMETRY"
        assert result.status == "SUCCESS"
        assert result.coordinates is not None
        assert abs(result.coordinates.lat - 40.7128) < 0.001
        assert abs(result.coordinates.lon - -74.0060) < 0.001
        assert result.telemetry_resolve is not None
        assert result.consensus.tier_used == "telemetry"

    @pytest.mark.asyncio
    @patch.object(ai_gateway, "is_configured", return_value=False)
    @patch.object(ai_gateway, "has_vision_llm", return_value=False)
    async def test_tier5_graceful_degradation_no_metadata_no_keys(self, _v, _c):
        """No EXIF, no telemetry, no AI keys → PARTIAL_SUCCESS with message."""
        img = _make_plain_image()
        result = await brain.analyze(img)

        assert result.source == "EXIF_MISSING_NO_AI_KEY"
        assert result.status == "PARTIAL_SUCCESS"
        assert result.coordinates is None
        assert result.message is not None
        assert "EXIF" in result.message or "AI" in result.message
        assert result.consensus.confidence_score <= 0.1

    @pytest.mark.asyncio
    @patch("app.brain.metadata_extractor._geolocator")
    async def test_exif_camera_params_in_cascade_result(self, mock_geo):
        """Camera params flow through the cascade into the result."""
        mock_geo.reverse.return_value = None  # no network
        img = _make_image_with_full_exif()
        result = await brain.analyze(img)

        assert result.camera.get("make") == "Apple"
        assert result.camera.get("model") == "iPhone 15 Pro"
        assert result.camera.get("f_number") == pytest.approx(1.8)
        assert result.altitude == 35.0
        assert result.datetime_original == "2024:01:15 14:30:00"
