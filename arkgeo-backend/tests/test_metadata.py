"""Unit tests for EXIF metadata extraction & GPS sanity verification."""
import io
import base64

import piexif
import pytest
from PIL import Image

from app.brain.metadata_extractor import MetadataExtractor, _dms_to_decimal
from app.models.schemas import ImintPayload, AnalyzeResponse


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


def _dms(v):
    v = abs(v)
    d = int(v)
    m = int((v - d) * 60)
    s = (v - d - m / 60) * 3600
    return ((d, 1), (m, 1), (int(s * 10000), 10000))


def _make_rich_image():
    """JPEG with data across all four IMINT pillars."""
    gps = {
        piexif.GPSIFD.GPSLatitude: _dms(48.8566),
        piexif.GPSIFD.GPSLatitudeRef: b"N",
        piexif.GPSIFD.GPSLongitude: _dms(2.3522),
        piexif.GPSIFD.GPSLongitudeRef: b"E",
        piexif.GPSIFD.GPSAltitude: (12345, 100),
        piexif.GPSIFD.GPSAltitudeRef: b"\x00",
        piexif.GPSIFD.GPSImgDirection: (900, 10),
        piexif.GPSIFD.GPSImgDirectionRef: b"T",
        piexif.GPSIFD.GPSSpeed: (7, 1),
        piexif.GPSIFD.GPSSpeedRef: b"K",
        piexif.GPSIFD.GPSProcessingMethod: b"ASCII\x00\x00\x00" + b"HYBRID-FIX",
        piexif.GPSIFD.GPSDOP: (15, 10),
        piexif.GPSIFD.GPSDateStamp: b"2024:08:12",
        piexif.GPSIFD.GPSTimeStamp: ((10, 1), (0, 1), (0, 1)),
        piexif.GPSIFD.GPSDestLatitude: _dms(51.5074),
        piexif.GPSIFD.GPSDestLatitudeRef: b"N",
        piexif.GPSIFD.GPSDestLongitude: _dms(0.1278),
        piexif.GPSIFD.GPSDestLongitudeRef: b"W",
    }
    zeroth = {
        piexif.ImageIFD.Make: b"Canon",
        piexif.ImageIFD.Model: b"EOS R5",
        piexif.ImageIFD.Software: b"Adobe Photoshop 24.0",
        piexif.ImageIFD.Artist: b"J Doe",
        piexif.ImageIFD.Copyright: b"(c) 2024 J Doe",
    }
    exif_ifd = {
        piexif.ExifIFD.DateTimeOriginal: b"2024:08:12 12:00:00",
        piexif.ExifIFD.DateTimeDigitized: b"2024:08:12 12:00:00",
        piexif.ExifIFD.OffsetTimeOriginal: b"+02:00",
        piexif.ExifIFD.LensMake: b"Canon",
        piexif.ExifIFD.LensModel: b"RF 24-70mm",
        piexif.ExifIFD.LensSerialNumber: b"LENS0001",
        42033: b"BODY0001",  # SerialNumber
        42032: b"Jane",  # OwnerName
        37521: b"123",  # SubsecTimeOriginal
        37522: b"123",  # SubsecTimeDigitized
        piexif.ExifIFD.ExposureTime: (1, 250),
        piexif.ExifIFD.FNumber: (28, 10),
        piexif.ExifIFD.ApertureValue: (35, 10),
        piexif.ExifIFD.ISOSpeedRatings: 400,
        piexif.ExifIFD.Flash: 9,
        piexif.ExifIFD.FocalLength: (24, 1),
        piexif.ExifIFD.FocalLengthIn35mmFilm: 24,
        piexif.ExifIFD.MeteringMode: 5,
        piexif.ExifIFD.LightSource: 0,
        piexif.ExifIFD.SensingMethod: 2,
    }
    exif_dict = {"0th": zeroth, "Exif": exif_ifd, "GPS": gps}
    img = Image.new("RGB", (64, 64), color=(120, 120, 120))
    buf = io.BytesIO()
    img.save(buf, format="jpeg", exif=piexif.dump(exif_dict))
    return buf.getvalue()


class TestImintExtraction:
    """IMINT — 4-pillar unified Image Data Extraction engine."""

    def setup_method(self):
        self.ext = MetadataExtractor()

    def test_payload_structure_and_key_stability(self):
        result = self.ext.extract(_make_plain_image())
        ii = result["image_intelligence"]
        assert ii is not None
        assert set(ii.keys()) == {"geospatial", "temporal", "device", "capture", "analysis"}
        for pillar in ("geospatial", "temporal", "device", "capture"):
            assert isinstance(ii[pillar], dict) and ii[pillar] != {}
        assert ii["analysis"]["pillars_present"] == {
            "geospatial": False, "temporal": False, "device": False, "capture": False}

    def test_pillar1_geospatial(self):
        ii = self.ext.extract(_make_rich_image())["image_intelligence"]
        g = ii["geospatial"]
        assert g["has_coordinates"] and g["coords_plausible"]
        assert abs(g["latitude_decimal"] - 48.8566) < 0.001
        assert abs(g["longitude_decimal"] - 2.3522) < 0.001
        assert g["latitude_ref"] == "N" and g["longitude_ref"] == "E"
        assert abs(g["altitude_meters"] - 123.45) < 0.01
        assert g["altitude_ref"] == "above_sea_level"
        assert abs(g["gps_dop"] - 1.5) < 0.01
        assert g["dop_quality"] == "good"
        assert g["gps_speed"] == 7.0 and g["gps_speed_ref"] == "K"
        assert g["gps_processing_method"] == "HYBRID-FIX"
        assert abs(g["dest_latitude_decimal"] - 51.5074) < 0.001
        assert abs(g["dest_longitude_decimal"] + 0.1278) < 0.001
        assert any("dest_coordinates_differ" in c for c in ii["analysis"]["geospatial_conflicts"])

    def test_pillar2_temporal_clock_delta(self):
        ii = self.ext.extract(_make_rich_image())["image_intelligence"]
        t = ii["temporal"]
        assert t["datetime_original"] == "2024:08:12 12:00:00"
        assert t["device_clock_utc"] == "2024-08-12T10:00:00+00:00"
        assert t["satellite_clock_utc"] == "2024-08-12T10:00:00Z"
        assert t["clock_delta_seconds"] == 0
        assert t["clock_drift_detected"] is False
        assert t["subsec_time_original"] == "123"
        assert ii["analysis"]["subsec_anomaly_detected"] is True
        assert "identical_subsec_both_clocks" in ii["analysis"]["subsec_anomaly_reasons"]

    def test_pillar2_drift_detected_when_clocks_diverge(self):
        exif_ifd = {
            piexif.ExifIFD.DateTimeOriginal: b"2024:08:12 12:00:00",
            piexif.ExifIFD.OffsetTimeOriginal: b"+02:00",
        }
        gps = {
            piexif.GPSIFD.GPSDateStamp: b"2024:08:12",
            piexif.GPSIFD.GPSTimeStamp: ((8, 1), (30, 1), (0, 1)),  # 90 min drift
        }
        exif_dict = {"0th": {}, "Exif": exif_ifd, "GPS": gps}
        img = Image.new("RGB", (32, 32))
        buf = io.BytesIO()
        img.save(buf, format="jpeg", exif=piexif.dump(exif_dict))
        t = self.ext.extract(buf.getvalue())["image_intelligence"]["temporal"]
        assert t["clock_delta_seconds"] == 5400
        assert t["clock_drift_detected"] is True

    def test_pillar3_device_provenance_and_fingerprint(self):
        ii = self.ext.extract(_make_rich_image())["image_intelligence"]
        d = ii["device"]
        assert d["make"] == "Canon" and d["model"] == "EOS R5"
        assert d["body_serial_number"] == "BODY0001"
        assert d["lens_serial_number"] == "LENS0001"
        assert d["owner_name"] == "Jane"
        assert d["profile_strings"] == {"owner_name": "Jane", "artist": "J Doe", "copyright": "(c) 2024 J Doe"}
        assert d["has_provenance"] is True
        assert ii["analysis"]["unique_fingerprint"]

    def test_pillar4_capture_diagnostics(self):
        ii = self.ext.extract(_make_rich_image())["image_intelligence"]
        c = ii["capture"]
        assert c["exposure_time_str"] == "1/250"
        assert abs(c["f_number"] - 2.8) < 0.01
        assert c["iso"] == 400
        assert c["flash_fired"] is True
        assert c["focal_length"] == 24.0
        assert c["focal_length_35mm"] == 24
        assert c["has_capture"] is True

    def test_stripped_image_keeps_all_keys_null(self):
        ii = self.ext.extract(_make_plain_image())["image_intelligence"]
        derived_bools = ("has_coordinates", "coords_plausible", "clock_drift_detected")
        for pillar in ("geospatial", "temporal", "device", "capture"):
            for key, val in ii[pillar].items():
                if key.startswith("has_") or key in derived_bools:
                    assert val is False, f"{pillar}.{key} should be False"
                else:
                    assert val is None, f"{pillar}.{key} should be None"
        assert ii["analysis"]["pillars_present"] == {
            "geospatial": False, "temporal": False, "device": False, "capture": False}

    def test_pydantic_models_accept_full_and_stripped(self):
        full = ImintPayload.model_validate(
            self.ext.extract(_make_rich_image())["image_intelligence"])
        assert full.geospatial.has_coordinates is True
        assert full.device.body_serial_number == "BODY0001"
        assert full.capture.f_number == 2.8
        stripped = ImintPayload.model_validate(
            self.ext.extract(_make_plain_image())["image_intelligence"])
        assert stripped.analysis.pillars_present["geospatial"] is False
        assert stripped.geospatial.latitude is None

    def test_screenshot_likely_for_tall_png_no_metadata(self):
        # 1080×2400 PNG — typical phone screenshot via WhatsApp/messenger.
        img = Image.new("RGB", (1080, 2400), color=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="png")
        ii = self.ext.extract(buf.getvalue())["image_intelligence"]
        assert ii["analysis"]["is_screenshot_likely"] is True
        assert ii["analysis"]["screenshot_aspect_ratio"] == 0.45
        reasons = ii["analysis"]["screenshot_reasons"]
        assert "phone_aspect_ratio" in reasons
        assert "png_container" in reasons
        assert "metadata_stripped" in reasons

    def test_screenshot_not_flagged_for_camera_photo(self):
        # A real camera photo carries provenance — never mis-flagged.
        ii = self.ext.extract(_make_rich_image())["image_intelligence"]
        assert ii["analysis"]["is_screenshot_likely"] is False


class TestLenientDms:
    def test_standard_rational_triple(self):
        assert abs(_dms_to_decimal(((48, 1), (51, 1), (240000, 10000)), "N") - 48.856666) < 0.001

    def test_string_dms(self):
        assert abs(_dms_to_decimal("48 51 23.76", "N") - 48.8566) < 0.001
        assert abs(_dms_to_decimal("48 51.3958", "N") - 48.8566) < 0.01

    def test_decimal_string_with_ref(self):
        assert abs(_dms_to_decimal("2.3522", "E") - 2.3522) < 0.001
        assert abs(_dms_to_decimal("2.3522", "W") + 2.3522) < 0.001

    def test_garbage_returns_none(self):
        assert _dms_to_decimal(None, "N") is None
        assert _dms_to_decimal("not-a-coord", "N") is None
        assert _dms_to_decimal(((1, 0), (1, 1)), "N") is None  # zero denominator
