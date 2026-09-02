"""Continuous Image Intelligence lifecycle tests.

Verifies the full investigation pipeline end-to-end as one connected flow:

  Upload → Evidence Preservation → Analysis → Findings/Observations →
  Evidence Fusion → Investigation View → Investigate Next (tool calls) →
  Updated Findings → Case/Report.

Every stage is exercised honestly-by-design: an unconfigured provider produces
an explicit UNAVAILABLE / NOT_OBSERVED state rather than a silent blank, and
no assertion ever fabricates coordinates, EXIF, or source matches.
"""
import asyncio
import io
from unittest.mock import AsyncMock, MagicMock, patch

import piexif
import pytest
from PIL import Image

from app.agent.tool_registry import registry
from app.api.v1.endpoints.analyze import _run_cascade
from app.brain.contradiction_engine import contradiction_engine
from app.brain.pipeline import brain
from app.models import AddressInfo, VisionResult
from app.services.ai_gateway import ai_gateway


def _make_exif_image(lat=48.8566, lon=2.3522, with_heading=False):
    """JPEG with GPS + camera EXIF (Apple iPhone), optionally heading."""
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
    if with_heading:
        gps_ifd[piexif.GPSIFD.GPSImgDirection] = (90, 1)
        gps_ifd[piexif.GPSIFD.GPSImgDirectionRef] = b"T"
    exif_bytes = piexif.dump({
        "0th": {piexif.ImageIFD.Make: b"Apple",
                piexif.ImageIFD.Model: b"iPhone 15 Pro"},
        "Exif": {piexif.ExifIFD.DateTimeOriginal: b"2024:01:15 14:30:00"},
        "GPS": gps_ifd,
    })
    buf = io.BytesIO()
    img.save(buf, format="jpeg", exif=exif_bytes)
    return buf.getvalue()


def _make_plain_image():
    """Metadata-stripped JPEG — no EXIF, no camera provenance."""
    img = Image.new("RGB", (50, 50), color=(200, 200, 200))
    buf = io.BytesIO()
    img.save(buf, format="jpeg")
    return buf.getvalue()


OBS_STATUSES = {"OBSERVED", "NOT_OBSERVED", "UNAVAILABLE", "ANOMALY", "HYPOTHESIS"}
OBS_SOURCES = {"cryptographic", "tool_inference", "ai_hypothesis"}
CLASSIFICATIONS = {"Likely Screenshot", "Likely Camera Photograph",
                   "Likely Exported Image", "Unknown"}


# --------------------------------------------------------------------------- #
# 1. Upload → Evidence Preservation
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_lifecycle_upload_preserves_evidence_hashes():
    """Ingesting an asset through the API surface preserves a stable
    triple-hash custody certificate and a case request id."""
    img = _make_exif_image()
    with patch("app.brain.metadata_extractor._geolocator") as mock_geo:
        mock_geo.reverse.return_value = None
        result = await _run_cascade(
            image_bytes=img, request_id="LC-1001", zero_retention=True,
            run_indoor=False,
        )

    assert result.request_id == "LC-1001"
    cert = result.custody_certificate
    assert cert is not None
    assert cert.sha256 == result.image_sha256
    assert cert.sha1
    assert cert.md5
    assert result.custody_hash
    assert len(result.image_sha256) == 64


# --------------------------------------------------------------------------- #
# 2. Analysis → Findings / Observations (honest-by-design)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
@patch.object(ai_gateway, "is_configured", return_value=False)
@patch.object(ai_gateway, "has_vision_llm", return_value=False)
async def test_lifecycle_analysis_emits_observations_for_every_layer(_v, _c):
    """Even a fully-stripped image with no provider keys yields structured
    observations for every forensic layer — never a silent blank."""
    result = await brain.analyze(_make_plain_image())

    assert result.status == "PARTIAL_SUCCESS"
    assert result.source == "EXIF_MISSING_NO_AI_KEY"

    obs = result.observations
    assert obs, "expected at least one observation for a stripped asset"
    for o in obs:
        assert o["id"].startswith("OBS-")
        assert o["status"] in OBS_STATUSES
        assert o["source"] in OBS_SOURCES
        assert o["layer"] and o["label"] and o["detail"]

    layers = {o["layer"] for o in obs}
    assert {"File Forensics", "OCR & Vision", "Source Discovery",
            "Provenance / C2PA"} <= layers

    statuses = {o["status"] for o in obs}
    assert "UNAVAILABLE" in statuses or "NOT_OBSERVED" in statuses
    assert result.image_classification in CLASSIFICATIONS


# --------------------------------------------------------------------------- #
# 3. Analysis → Direct EXIF path (preserved metadata wins)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_lifecycle_exif_path_yields_direct_evidence():
    """EXIF GPS + camera metadata drives the deterministic Tier-1 path."""
    img = _make_exif_image(with_heading=False)
    with patch("app.brain.metadata_extractor._geolocator") as mock_geo:
        mock_geo.reverse.return_value = None
        result = await brain.analyze(img)

    assert result.source == "NATIVE_EXIF_HARDWARE"
    assert result.coordinates is not None
    assert abs(result.coordinates.lat - 48.8566) < 1e-4
    assert abs(result.coordinates.lon - 2.3522) < 1e-4
    assert result.exif_missing is False

    device = (result.image_intelligence or {}).get("device") or {}
    assert device.get("make") == "Apple"
    assert device.get("model") == "iPhone 15 Pro"

    nodes = (result.evidence_graph or {}).get("nodes", {})
    location_nodes = [n for n in nodes.values() if n["claim_type"] == "location"]
    assert location_nodes
    assert all(n["provenance_type"] == "tool_inference" for n in location_nodes)


# --------------------------------------------------------------------------- #
# 4. Analysis → Stripped asset falls back to AI vision
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_lifecycle_stripped_image_uses_ai_vision_fallback():
    """No EXIF + configured vision → AI_VISION source with ai_hypothesis nodes."""
    img = _make_plain_image()
    vision_result = VisionResult(
        source="llm_vision",
        estimated_latitude=6.5244, estimated_longitude=3.3792,
        search_radius_meters=800.0, confidence_score=0.62,
        primary_country="Nigeria",
    )
    with patch.object(brain.vision, "locate",
                      new=AsyncMock(return_value=[vision_result])):
        with patch("app.brain.pipeline.reverse_geocode") as mock_rg:
            mock_rg.return_value = AddressInfo(country="Nigeria", city="Lagos")
            result = await brain.analyze(img)

    assert result.source == "AI_VISION"
    assert result.coordinates is not None
    assert result.consensus.primary_country == "Nigeria"
    assert result.search_radius_meters == result.consensus.search_radius_meters

    nodes = (result.evidence_graph or {}).get("nodes", {})
    location_nodes = [n for n in nodes.values() if n["claim_type"] == "location"]
    assert location_nodes
    assert all(n["provenance_type"] == "ai_hypothesis" for n in location_nodes)


# --------------------------------------------------------------------------- #
# 5. Evidence Fusion → Contradictions surfaced into findings
# --------------------------------------------------------------------------- #
def test_lifecycle_fusion_surfaces_contradictions():
    """Conflicting evidence produces structured contradictions that the report
    layer can surface — never a silent merge."""
    contradictions = contradiction_engine.detect(
        consistency_findings=[],
        geolocation_fusion={},
        exif_raw={},
        gps_spoofing_detected=True,
        anomaly_score=0.9,
        sanity_mismatches=["Botanical mismatch"],
    )
    assert contradictions
    assert any(c["type"] == "GPS_SPOOFING" for c in contradictions)
    for c in contradictions:
        assert c["what_conflicts"]
        assert c["severity"] in ("LOW", "MEDIUM", "HIGH")
        assert isinstance(c["evidence_sources"], list)


@pytest.mark.asyncio
async def test_lifecycle_fusion_wired_into_report_payload():
    """The full analysis result exposes the contradiction surface even when
    clean, and the investigation summary mirrors it exactly."""
    result = await brain.analyze(_make_plain_image())
    assert isinstance(result.contradictions, list)
    assert result.evidence_summary["contradictions"] == len(result.contradictions)
    assert result.evidence_summary["evidence_count"] == len(result.observations)


# --------------------------------------------------------------------------- #
# 6. Investigation View → Summary + ladder + next steps
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_lifecycle_investigation_view_is_ready():
    """The shared investigation view exposes known/unknown/suspicious, the
    fallback ladder state, and Investigate-Next recommendations."""
    result = await brain.analyze(_make_plain_image())
    summary = result.evidence_summary

    assert isinstance(summary["known"], list)
    assert isinstance(summary["unknown"], list)
    assert isinstance(summary["suspicious"], list)
    assert summary["unknown"], "a stripped asset must report unknowns"

    ladder = summary["ladder"]
    assert "steps" in ladder and "ran" in ladder and "total" in ladder
    assert 0 < ladder["total"] <= 20
    assert ladder["ran"] >= 1  # deterministic layers always ran
    assert "blocked" in ladder

    steps = {s["id"]: s for s in ladder["steps"]}
    assert steps["local_fingerprint"]["status"] == "ran"
    assert steps["exif_geolocation"]["status"] in ("blocked", "reachable", "ran")

    next_steps = summary["next_steps"]
    assert next_steps, "Investigate Next must propose follow-up actions"
    for ns in next_steps:
        assert ns["action"] and ns["goal"] and ns["priority"]


# --------------------------------------------------------------------------- #
# 7. Investigate Next → Additional tool call appends evidence
# --------------------------------------------------------------------------- #
def test_lifecycle_investigate_next_tool_call_appends_evidence():
    """Launching an 'investigate next' tool call (reverse source search) with a
    configured provider returns structured matches + timeline + pHash."""
    img = _make_plain_image()
    tineye_match = {"title": "First online copy", "score": 98,
                    "url": "https://example.com/original.jpg"}
    serper_match = {"title": "Similar crop", "score": 87,
                    "image_url": "https://example.net/crop.jpg"}
    with patch("app.agent.tool_registry.settings_store.get_key",
               return_value="configured"):
        with patch("app.agent.tool_registry.search_tineye",
                   new=AsyncMock(return_value={
                       "state": "AVAILABLE", "provider": "tineye",
                       "matches": [tineye_match]})) as mock_tineye:
            with patch("app.agent.tool_registry.search_serper",
                       new=AsyncMock(return_value={
                           "state": "AVAILABLE", "provider": "serper",
                           "matches": [serper_match]})) as mock_serper:
                res = asyncio.run(registry.acall(
                    "search_reverse_source", image_bytes=img))

    assert res["state"] == "AVAILABLE"
    assert res["phash"]
    assert len(res["exact_matches"]) == 1
    assert len(res["similar_matches"]) == 1
    assert res["timeline"], "provider matches must reconstruct a timeline"
    assert "tineye" in res["provider"]
    mock_tineye.assert_awaited_once()
    mock_serper.assert_awaited_once()


# --------------------------------------------------------------------------- #
# 8. Additional tool calls → Updated Findings (re-analysis)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_lifecycle_reanalysis_with_providers_updates_findings():
    """Re-running analysis with providers configured grows the observation set
    and populates discrete AI evidence (geospy + scene)."""
    base = await brain.analyze(_make_plain_image())
    baseline_count = len(base.observations)
    assert "geospy" not in (base.ai_evidence or {})
    assert "scene" not in (base.ai_evidence or {})

    vision_result = VisionResult(
        source="llm_vision",
        estimated_latitude=6.5244, estimated_longitude=3.3792,
        search_radius_meters=800.0, confidence_score=0.62,
        primary_country="Nigeria",
    )
    scene_result = {
        "description": "Street with mango trees and tropical architecture",
        "visual_evidence_tags": [
            {"category": "botanical", "label": "mango tree", "confidence": 0.8},
        ],
        "confidence_score": 0.6,
        "primary_country": "Nigeria",
    }
    with patch.object(brain.vision, "locate",
                      new=AsyncMock(return_value=[vision_result])):
        with patch("app.brain.pipeline.reverse_geocode") as mock_rg:
            mock_rg.return_value = AddressInfo(country="Nigeria", city="Lagos")
            with patch("app.agent.tool_registry._vision.predict_geospy",
                       new=AsyncMock(return_value=vision_result)):
                with patch("app.brain.clue_extractors.base.llm_client.vision_query",
                           return_value=scene_result):
                    enriched = await brain.analyze(_make_plain_image())

    assert enriched.source == "AI_VISION"
    assert enriched.ai_evidence is not None
    assert enriched.ai_evidence["geospy"]["primary_country"] == "Nigeria"
    assert enriched.ai_evidence["scene"]["evidence_tags"]
    assert len(enriched.observations) > baseline_count

    types = {o["type"] for o in enriched.observations}
    assert "AI_HYPOTHESIS" in types


# --------------------------------------------------------------------------- #
# 9. Case / Report payload completeness
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_lifecycle_report_payload_is_complete():
    """The serialized API response contains every section the Case/Report
    surface renders (custody, consensus, findings, fusion, graph, log)."""
    result = await _run_cascade(
        image_bytes=_make_plain_image(), request_id="LC-2000",
        zero_retention=True, run_indoor=False,
    )
    payload = result.model_dump()

    for key in (
        "request_id", "image_sha256", "custody_certificate", "custody_hash",
        "consensus", "observations", "contradictions", "evidence_summary",
        "analysis_log", "source_discovery", "evidence_graph",
        "image_classification", "geolocation_fusion", "deep_metadata",
    ):
        assert key in payload, f"report payload missing {key}"

    assert payload["custody_certificate"]["sha256"] == payload["image_sha256"]
    assert isinstance(payload["observations"], list)
    assert isinstance(payload["analysis_log"], list)
    assert payload["evidence_summary"]["image_classification"] \
        == payload["image_classification"]
