"""Tests for forensic security features: magic-byte validation, steganography
detection, and triple-hash chain-of-custody.

Verifies:
  - JPEG 0xFFD8FF and PNG 0x89504E47 magic byte detection
  - HTTP 415 on MIME-type spoofing attempts
  - SHA-256 + SHA-1 + MD5 triple-hash in custody certificate
  - Steganography detection: trailing bytes after JPEG 0xFFD9 and PNG IEND
  - EXIF-missing flag for stripped images
  - Zero-Retention-Mode header handling
"""
import io
import hashlib
import base64

import piexif
import pytest
from PIL import Image
from fastapi.testclient import TestClient

from app.brain.metadata_extractor import MetadataExtractor, detect_eof_anomaly, detect_format
from app.core.security import (
    custody_certificate,
    sha1_hex,
    md5_hex,
    sha256_hex,
    validate_magic_bytes,
    detect_format as security_detect_format,
)


# --------------------------------------------------------------------------- #
# Image factories
# --------------------------------------------------------------------------- #
def _make_jpeg_with_exif():
    img = Image.new("RGB", (100, 100), color=(120, 120, 120))
    zeroth = {piexif.ImageIFD.Make: b"TestCam", piexif.ImageIFD.Model: b"TC-100"}
    exif_bytes = piexif.dump({"0th": zeroth})
    buf = io.BytesIO()
    img.save(buf, format="jpeg", exif=exif_bytes)
    return buf.getvalue()


def _make_png():
    img = Image.new("RGB", (50, 50), color=(200, 200, 200))
    buf = io.BytesIO()
    img.save(buf, format="png")
    return buf.getvalue()


def _make_stego_jpeg():
    """JPEG with 256 bytes of trailing data after the 0xFFD9 marker."""
    img = Image.new("RGB", (50, 50), color=(100, 100, 100))
    buf = io.BytesIO()
    img.save(buf, format="jpeg")
    data = buf.getvalue()
    # Append 256 bytes of payload after the EOI marker
    return data + b"\x41" * 256


def _make_stego_png():
    """PNG with 128 bytes of trailing data after the IEND chunk."""
    img = Image.new("RGB", (50, 50), color=(100, 100, 100))
    buf = io.BytesIO()
    img.save(buf, format="png")
    data = buf.getvalue()
    return data + b"\x42" * 128


def _make_plain_jpeg():
    img = Image.new("RGB", (50, 50), color=(200, 200, 200))
    buf = io.BytesIO()
    img.save(buf, format="jpeg")
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Magic-byte validation
# --------------------------------------------------------------------------- #
class TestMagicByteValidation:
    def test_detect_jpeg(self):
        assert security_detect_format(_make_plain_jpeg()) == "jpeg"

    def test_detect_png(self):
        assert security_detect_format(_make_png()) == "png"

    def test_detect_unknown_format(self):
        assert security_detect_format(b"\x00\x00\x00\x00abcdef") is None

    def test_validate_jpeg_correct(self):
        fmt = validate_magic_bytes(_make_plain_jpeg(), "image/jpeg")
        assert fmt == "jpeg"

    def test_validate_png_correct(self):
        fmt = validate_magic_bytes(_make_png(), "image/png")
        assert fmt == "png"

    def test_validate_spoofing_jpeg_as_png(self):
        with pytest.raises(ValueError, match="spoofing"):
            validate_magic_bytes(_make_plain_jpeg(), "image/png")

    def test_validate_spoofing_png_as_jpeg(self):
        with pytest.raises(ValueError, match="spoofing"):
            validate_magic_bytes(_make_png(), "image/jpeg")

    def test_validate_unknown_bytes(self):
        with pytest.raises(ValueError, match="Unrecognized"):
            validate_magic_bytes(b"\x00\x01\x02\x03")

    def test_validate_no_declared_type_jpeg(self):
        assert validate_magic_bytes(_make_plain_jpeg()) == "jpeg"

    def test_validate_no_declared_type_png(self):
        assert validate_magic_bytes(_make_png()) == "png"


# --------------------------------------------------------------------------- #
# HTTP 415 on spoofing (integration via TestClient)
# --------------------------------------------------------------------------- #
class TestHttpMagicByteRejection:
    def setup_method(self):
        from main import app
        self.client = TestClient(app)

    def test_valid_jpeg_accepted(self):
        resp = self.client.post(
            "/api/v1/analyze",
            files={"file": ("test.jpg", _make_plain_jpeg(), "image/jpeg")},
        )
        assert resp.status_code == 200

    def test_spoofed_jpeg_as_png_returns_415(self):
        resp = self.client.post(
            "/api/v1/analyze",
            files={"file": ("fake.png", _make_plain_jpeg(), "image/png")},
        )
        assert resp.status_code == 415
        assert "spoof" in resp.json()["detail"].lower()

    def test_non_image_bytes_returns_415(self):
        resp = self.client.post(
            "/api/v1/analyze",
            files={"file": ("fake.jpg", b"\x00\x01\x02\x03\x04", "image/jpeg")},
        )
        assert resp.status_code == 415


# --------------------------------------------------------------------------- #
# Triple-hash custody
# --------------------------------------------------------------------------- #
class TestTripleHashCustody:
    def test_certificate_contains_sha256_sha1_md5(self):
        data = b"forensic test bytes"
        cert = custody_certificate(data)
        assert "sha256" in cert
        assert "sha1" in cert
        assert "md5" in cert
        assert "ingested_at_ms" in cert

    def test_sha256_matches_hashlib(self):
        data = b"forensic test bytes"
        cert = custody_certificate(data)
        assert cert["sha256"] == hashlib.sha256(data).hexdigest()

    def test_sha1_matches_hashlib(self):
        data = b"forensic test bytes"
        cert = custody_certificate(data)
        assert cert["sha1"] == hashlib.sha1(data).hexdigest()

    def test_md5_matches_hashlib(self):
        data = b"forensic test bytes"
        cert = custody_certificate(data)
        assert cert["md5"] == hashlib.md5(data).hexdigest()

    def test_sha1_hex_helper(self):
        assert sha1_hex(b"test") == hashlib.sha1(b"test").hexdigest()

    def test_all_three_hashes_different(self):
        cert = custody_certificate(b"image123")
        assert cert["sha256"] != cert["sha1"]
        assert cert["sha1"] != cert["md5"]
        assert cert["sha256"] != cert["md5"]


# --------------------------------------------------------------------------- #
# Steganography / EOF anomaly detection
# --------------------------------------------------------------------------- #
class TestSteganographyDetection:
    def test_clean_jpeg_no_anomaly(self):
        result = detect_eof_anomaly(_make_plain_jpeg())
        assert result["steganography_detected"] is False
        assert result["trailing_bytes_count"] == 0
        assert result["file_format"] == "jpeg"

    def test_clean_png_no_anomaly(self):
        result = detect_eof_anomaly(_make_png())
        assert result["steganography_detected"] is False
        assert result["trailing_bytes_count"] == 0
        assert result["file_format"] == "png"

    def test_stego_jpeg_detected(self):
        result = detect_eof_anomaly(_make_stego_jpeg())
        assert result["steganography_detected"] is True
        assert result["trailing_bytes_count"] == 256
        assert result["file_format"] == "jpeg"
        assert result["eof_offset"] is not None

    def test_stego_png_detected(self):
        result = detect_eof_anomaly(_make_stego_png())
        assert result["steganography_detected"] is True
        assert result["trailing_bytes_count"] == 128
        assert result["file_format"] == "png"
        assert result["eof_offset"] is not None

    def test_unknown_format_returns_no_anomaly(self):
        result = detect_eof_anomaly(b"\x00\x01\x02\x03")
        assert result["steganography_detected"] is False
        assert result["file_format"] is None

    def test_extractor_flags_steganography(self):
        ext = MetadataExtractor()
        result = ext.extract(_make_stego_jpeg())
        stego = result["steganography"]
        assert stego["steganography_detected"] is True
        assert stego["trailing_bytes_count"] == 256
        assert "trailing_bytes:256" in result["tamper_flags"]

    def test_extractor_clean_jpeg_no_stego_flag(self):
        ext = MetadataExtractor()
        result = ext.extract(_make_plain_jpeg())
        stego = result["steganography"]
        assert stego["steganography_detected"] is False
        assert not any("trailing_bytes" in f for f in result["tamper_flags"])


# --------------------------------------------------------------------------- #
# EXIF-missing detection
# --------------------------------------------------------------------------- #
class TestExifMissingDetection:
    def test_plain_jpeg_flags_exif_missing(self):
        ext = MetadataExtractor()
        result = ext.extract(_make_plain_jpeg())
        assert result["exif_missing"] is True
        assert "exif_stripped" in result["tamper_flags"]

    def test_jpeg_with_exif_not_flagged(self):
        ext = MetadataExtractor()
        result = ext.extract(_make_jpeg_with_exif())
        assert result["exif_missing"] is False
        assert "exif_stripped" not in result["tamper_flags"]


# --------------------------------------------------------------------------- #
# Zero-Retention-Mode header
# --------------------------------------------------------------------------- #
class TestZeroRetentionHeader:
    def setup_method(self):
        from main import app
        self.client = TestClient(app)

    def test_zero_retention_via_header(self):
        b64 = base64.b64encode(_make_plain_jpeg()).decode()
        resp = self.client.post(
            "/api/v1/ingest",
            json={
                "image_base64": b64,
                "user_id": "test-zr",
                "zero_retention": False,
            },
            headers={"Zero-Retention-Mode": "true"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("SUCCESS", "PARTIAL_SUCCESS")

    def test_zero_retention_via_analyze_header(self):
        resp = self.client.post(
            "/api/v1/analyze",
            files={"file": ("test.jpg", _make_plain_jpeg(), "image/jpeg")},
            headers={"Zero-Retention-Mode": "true"},
        )
        assert resp.status_code == 200

    def test_no_zero_retention_header_still_works(self):
        resp = self.client.post(
            "/api/v1/analyze",
            files={"file": ("test.jpg", _make_plain_jpeg(), "image/jpeg")},
        )
        assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# Steganography in API response
# --------------------------------------------------------------------------- #
class TestSteganographyInApiResponse:
    def setup_method(self):
        from main import app
        self.client = TestClient(app)

    def test_stego_response_contains_flag(self):
        resp = self.client.post(
            "/api/v1/analyze",
            files={"file": ("stego.jpg", _make_stego_jpeg(), "image/jpeg")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["steganography_detected"] is True
        assert data["trailing_bytes_count"] == 256
        assert data["file_format"] == "jpeg"

    def test_clean_response_no_stego_flag(self):
        resp = self.client.post(
            "/api/v1/analyze",
            files={"file": ("clean.jpg", _make_plain_jpeg(), "image/jpeg")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["steganography_detected"] is False
        assert data["trailing_bytes_count"] == 0

    def test_stripped_image_response_has_exif_missing(self):
        resp = self.client.post(
            "/api/v1/analyze",
            files={"file": ("stripped.jpg", _make_plain_jpeg(), "image/jpeg")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["exif_missing"] is True

    def test_response_contains_sha1(self):
        resp = self.client.post(
            "/api/v1/analyze",
            files={"file": ("test.jpg", _make_plain_jpeg(), "image/jpeg")},
        )
        data = resp.json()
        cert = data["custody_certificate"]
        assert "sha1" in cert
        assert len(cert["sha1"]) == 40  # SHA-1 hex digest length
