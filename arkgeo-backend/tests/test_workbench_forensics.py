"""Tests for the workbench forensic layer — ExifTool, consistency, C2PA,
source discovery, geolocation fusion, contradictions, and analyst overrides.
"""
import base64
import io

import piexif
import pytest
from PIL import Image

from app.brain.consistency_engine import consistency_engine, _parse_exif_date
from app.brain.contradiction_engine import contradiction_engine
from app.brain.geolocation_fusion import geolocation_fusion
from app.services.c2pa_service import c2pa_service
from app.services.exiftool_service import exiftool_service
from app.services.source_discovery import compute_phash, extract_embedded_urls
from app.services.analyst_overrides import analyst_override_store


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _make_gps_image(lat=48.8566, lon=2.3522, software=None):
    img = Image.new("RGB", (100, 100), color=(120, 120, 120))

    def _dms(value):
        v = abs(value)
        d = int(v)
        m = int((v - d) * 60)
        s = (v - d - m / 60) * 3600
        return ((d, 1), (m, 1), (int(s * 10000), 10000))

    exif_dict = {
        "GPS": {
            piexif.GPSIFD.GPSLatitude: _dms(lat),
            piexif.GPSIFD.GPSLatitudeRef: b"N",
            piexif.GPSIFD.GPSLongitude: _dms(lon),
            piexif.GPSIFD.GPSLongitudeRef: b"E",
        },
        "0th": {
            piexif.ImageIFD.Make: b"TestCam",
            piexif.ImageIFD.Model: b"TestModel",
        },
        "Exif": {
            piexif.ExifIFD.DateTimeOriginal: b"2025:01:15 10:00:00",
        },
    }
    if software:
        exif_dict["0th"][piexif.ImageIFD.Software] = software
    exif_bytes = piexif.dump(exif_dict)
    buf = io.BytesIO()
    img.save(buf, format="jpeg", exif=exif_bytes)
    return buf.getvalue()


def _make_plain_image():
    img = Image.new("RGB", (50, 50), color=(200, 200, 200))
    buf = io.BytesIO()
    img.save(buf, format="jpeg")
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# ExifTool service
# --------------------------------------------------------------------------- #
class TestExifToolService:
    def test_available_on_system(self):
        assert exiftool_service.available, "ExifTool should be installed"

    def test_extract_deep_gps_image(self):
        img = _make_gps_image()
        result = exiftool_service.extract_deep(img)
        assert result["available"] is True
        assert result["error"] is None
        assert "groups" in result
        # ExifTool should find EXIF and File groups
        assert "EXIF" in result["groups"] or "ExifIFD" in result["groups"]
        assert "File" in result["groups"]

    def test_extract_deep_plain_image(self):
        img = _make_plain_image()
        result = exiftool_service.extract_deep(img)
        assert result["available"] is True
        assert "File" in result["groups"]

    def test_file_info_extracted(self):
        img = _make_gps_image()
        result = exiftool_service.extract_deep(img)
        fi = result["file_info"]
        assert fi.get("mime_type") == "image/jpeg"
        assert fi.get("image_width") is not None


# --------------------------------------------------------------------------- #
# Consistency engine
# --------------------------------------------------------------------------- #
class TestConsistencyEngine:
    def test_parse_exif_date(self):
        dt = _parse_exif_date("2025:01:15 10:00:00")
        assert dt is not None
        assert dt.year == 2025

    def test_parse_exif_date_invalid(self):
        assert _parse_exif_date("not a date") is None
        assert _parse_exif_date("") is None

    def test_detects_editing_software(self):
        groups = {"EXIF": [{"tag": "Software", "value": "Adobe Photoshop 2024"}]}
        findings = consistency_engine.analyze(groups, {})
        types = [f["type"] for f in findings]
        assert "SOFTWARE_EDIT" in types

    def test_no_findings_for_clean_image(self):
        groups = {"EXIF": [{"tag": "Make", "value": "Canon"}, {"tag": "Model", "value": "EOS R5"}]}
        findings = consistency_engine.analyze(groups, {})
        assert all(f["status"] == "OK" for f in findings) or len(findings) == 0

    def test_finding_schema(self):
        groups = {"EXIF": [{"tag": "Software", "value": "GIMP 2.10"}]}
        findings = consistency_engine.analyze(groups, {})
        assert len(findings) > 0
        f = findings[0]
        assert "status" in f
        assert "type" in f
        assert "severity" in f
        assert "message" in f
        assert "evidence" in f


# --------------------------------------------------------------------------- #
# C2PA / provenance
# --------------------------------------------------------------------------- #
class TestC2PAService:
    def test_unavailable_for_plain_image(self):
        img = _make_plain_image()
        result = c2pa_service.analyze(img, {})
        assert result["state"] == "UNAVAILABLE"
        assert "not proof of manipulation" in result["detail"].lower()

    def test_never_claims_fake(self):
        img = _make_plain_image()
        result = c2pa_service.analyze(img, {})
        assert "fake" not in result["detail"].lower()

    def test_detects_manifest_in_xmp(self):
        groups = {"XMP": [{"tag": "c2pa:Manifest", "value": "issued by Adobe Photoshop 2024, edited"}]}
        img = _make_plain_image()
        result = c2pa_service.analyze(img, groups)
        assert result["manifest_found"] is True
        assert result["state"] in ("VERIFIED", "INCOMPLETE")

    def test_state_is_valid_enum(self):
        img = _make_plain_image()
        result = c2pa_service.analyze(img, {})
        assert result["state"] in ("VERIFIED", "UNAVAILABLE", "INVALID", "INCOMPLETE")


# --------------------------------------------------------------------------- #
# Source discovery
# --------------------------------------------------------------------------- #
class TestSourceDiscovery:
    def test_phash_computed(self):
        img = _make_plain_image()
        ph = compute_phash(img)
        assert len(ph) > 0
        # pHash should be deterministic
        assert ph == compute_phash(img)

    def test_phash_distinguishes_images(self):
        import random
        # Two images with different noise patterns → different pHashes
        random.seed(1)
        pixels1 = [(random.randint(0, 255),)*3 for _ in range(100*100)]
        img1 = Image.new("RGB", (100, 100))
        img1.putdata(pixels1)
        buf = io.BytesIO(); img1.save(buf, format="jpeg"); img1_bytes = buf.getvalue()
        random.seed(2)
        pixels2 = [(random.randint(0, 255),)*3 for _ in range(100*100)]
        img2 = Image.new("RGB", (100, 100))
        img2.putdata(pixels2)
        buf = io.BytesIO(); img2.save(buf, format="jpeg"); img2_bytes = buf.getvalue()
        assert compute_phash(img1_bytes) != compute_phash(img2_bytes)

    def test_embedded_urls_extracted(self):
        groups = {"XMP": [{"tag": "ArtistURL", "value": "https://example.com/photo/123"}]}
        urls = extract_embedded_urls(groups)
        assert "https://example.com/photo/123" in urls

    def test_unavailable_when_no_provider(self):
        img = _make_plain_image()
        from app.services.source_discovery import source_discovery
        result = source_discovery.analyze(img, {})
        assert result["state"] == "UNAVAILABLE"
        assert result["phash"]  # local fingerprint still works
        assert "not configured" in result["detail"].lower()


# --------------------------------------------------------------------------- #
# Geolocation fusion
# --------------------------------------------------------------------------- #
class TestGeolocationFusion:
    def test_fusion_builds_hypothesis(self):
        from app.models import ConsensusResult, Coordinates, VisualEvidenceTag
        consensus = ConsensusResult(
            estimated_latitude=48.8566, estimated_longitude=2.3522,
            search_radius_meters=100, confidence_score=0.87, tier_used="metadata",
            visual_evidence_tags=[], sources=["metadata"],
        )
        coords = Coordinates(lat=48.8566, lon=2.3522)
        result = geolocation_fusion.fuse(consensus, coords, {"display_name": "Paris, France"}, [], [], {"Make": "Canon"})
        assert result["primary_location"] == "Paris, France"
        assert result["confidence"] > 0
        assert result["independent_evidence_classes"] >= 1
        assert "supporting" in result["detail"]

    def test_explainability_structure(self):
        from app.models import ConsensusResult, Coordinates, VisualEvidenceTag
        consensus = ConsensusResult(
            estimated_latitude=0, estimated_longitude=0,
            search_radius_meters=1000000, confidence_score=0.1, tier_used="consensus",
            visual_evidence_tags=[
                VisualEvidenceTag(category="botanical", label="Sabal Palm", confidence=0.8),
                VisualEvidenceTag(category="ocr", label="Airport Road", confidence=0.9),
            ], sources=[],
        )
        result = geolocation_fusion.fuse(consensus, None, None, consensus.visual_evidence_tags, [], {})
        detail = result["detail"]
        assert "question" in detail
        assert "supporting" in detail
        assert len(detail["supporting"]) >= 2


# --------------------------------------------------------------------------- #
# Contradiction engine
# --------------------------------------------------------------------------- #
class TestContradictionEngine:
    def test_detects_gps_spoofing(self):
        contradictions = contradiction_engine.detect(
            consistency_findings=[],
            geolocation_fusion={},
            exif_raw={"Make": "Canon"},
            gps_spoofing_detected=True,
            anomaly_score=0.7,
            sanity_mismatches=["Botanical mismatch"],
        )
        assert len(contradictions) >= 1
        assert any(c["type"] == "GPS_SPOOFING" for c in contradictions)

    def test_detects_metadata_fabrication(self):
        contradictions = contradiction_engine.detect(
            consistency_findings=[],
            geolocation_fusion={},
            exif_raw={"Make": "Canon", "GPS": "present"},
            gps_spoofing_detected=True,
            anomaly_score=0.8,
            sanity_mismatches=[],
        )
        assert any(c["type"] == "METADATA_FABRICATION" for c in contradictions)

    def test_no_contradictions_for_clean_image(self):
        contradictions = contradiction_engine.detect(
            consistency_findings=[],
            geolocation_fusion={"contradicting": []},
            exif_raw={},
            gps_spoofing_detected=False,
            anomaly_score=0.0,
            sanity_mismatches=[],
        )
        assert contradictions == []

    def test_contradiction_schema(self):
        contradictions = contradiction_engine.detect(
            consistency_findings=[{
                "status": "WARNING", "type": "GPS_TIMESTAMP_CONFLICT",
                "severity": "HIGH", "message": "GPS timestamp conflicts",
                "evidence": ["GPSDateTime=..."],
            }],
            geolocation_fusion={},
            exif_raw={},
            gps_spoofing_detected=False,
            anomaly_score=0.0,
            sanity_mismatches=[],
        )
        c = contradictions[0]
        for key in ("what_conflicts", "evidence_sources", "reliability", "severity", "affects_assessment", "type"):
            assert key in c


# --------------------------------------------------------------------------- #
# Analyst overrides
# --------------------------------------------------------------------------- #
class TestAnalystOverrides:
    def test_record_and_list(self):
        store = analyst_override_store
        result = store.record(
            image_sha256="abc123def456",
            finding_key="location",
            decision="confirm",
            note="Verified location matches EXIF",
        )
        assert result["decision"] == "confirm"
        overrides = store.list_for_image("abc123def456")
        assert len(overrides) >= 1
        assert overrides[-1]["finding_key"] == "location"

    def test_invalid_decision_rejected(self):
        store = analyst_override_store
        with pytest.raises(ValueError):
            store.record("sha", "key", "invalid_decision")

    def test_supports_all_three_decisions(self):
        store = analyst_override_store
        for decision in ("confirm", "reject", "needs_review"):
            r = store.record("test_sha_" + decision, "finding", decision)
            assert r["decision"] == decision
