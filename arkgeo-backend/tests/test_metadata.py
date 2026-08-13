"""Unit tests for EXIF metadata extraction & GPS sanity verification."""
import io
import base64

import piexif
import pytest
from PIL import Image

from app.brain.metadata_extractor import MetadataExtractor


def _make_image_with_gps(lat, lon, lat_ref="N", lon_ref="E"):
    """Create a JPEG with embedded EXIF GPS coordinates."""
    img = Image.new("RGB", (100, 100), color=(120, 120, 120))

    def _dms(value):
        v = abs(value)
        d = int(v)
        m = int((v - d) * 60)
        s = (v - d - m / 60) * 3600
        return ((d, 1), (m, 1), (int(s * 10000), 10000))

    gps_ifd = {
        piexif.GPSIFD.GPSLatitude: _dms(lat),
        piexif.GPSIFD.GPSLatitudeRef: lat_ref.encode(),
        piexif.GPSIFD.GPSLongitude: _dms(lon),
        piexif.GPSIFD.GPSLongitudeRef: lon_ref.encode(),
    }
    exif_dict = {"GPS": gps_ifd}
    exif_bytes = piexif.dump(exif_dict)

    buf = io.BytesIO()
    img.save(buf, format="jpeg", exif=exif_bytes)
    return buf.getvalue()


def _make_plain_image():
    img = Image.new("RGB", (50, 50), color=(200, 200, 200))
    buf = io.BytesIO()
    img.save(buf, format="jpeg")
    return buf.getvalue()


class TestMetadataExtractor:
    def setup_method(self):
        self.ext = MetadataExtractor()

    def test_extracts_valid_gps(self):
        img = _make_image_with_gps(48.8566, 2.3522)  # Paris
        result = self.ext.extract(img)
        assert result["gps"] is not None
        assert abs(result["gps"].lat - 48.8566) < 0.001
        assert abs(result["gps"].lon - 2.3522) < 0.001

    def test_rejects_null_island(self):
        img = _make_image_with_gps(0.0, 0.0)
        result = self.ext.extract(img)
        assert result["gps"] is None
        assert any("implausible_gps" in f for f in result["tamper_flags"])

    def test_no_gps_returns_none(self):
        img = _make_plain_image()
        result = self.ext.extract(img)
        assert result["gps"] is None

    def test_negative_coordinates_south_west(self):
        img = _make_image_with_gps(-33.8688, -151.2093, lat_ref="S", lon_ref="W")
        result = self.ext.extract(img)
        assert result["gps"] is not None
        assert result["gps"].lat < 0
        assert result["gps"].lon < 0

    def test_decode_base64_with_prefix(self):
        img = _make_plain_image()
        b64 = "data:image/jpeg;base64," + base64.b64encode(img).decode()
        decoded = MetadataExtractor.decode_base64_image(b64)
        assert decoded == img
