"""Tests for the Universal Image Intelligence API suite.

Covers the 5 registered tools (reverse_geocode, predict_geospy_coordinates,
analyze_vision_scene, search_reverse_source, fetch_streetview_panorama), the
new settings-store key surface, and the pipeline rewiring (Street View on the
direct-EXIF path + provenance-tagged evidence graph on the stripped path).
"""
import asyncio
import io
from unittest.mock import AsyncMock, MagicMock, patch

import piexif
import pytest
from PIL import Image

from app.agent import schemas as S
from app.agent.tool_registry import registry
from app.brain.pipeline import brain
from app.models import AddressInfo, VisionResult
from app.services.ai_gateway import ai_gateway
from app.services.settings_store import settings_store


def _make_image_with_full_exif(lat=48.8566, lon=2.3522, with_heading=True):
    """JPEG with GPS + camera EXIF (optionally GPSImgDirection)."""
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
    img = Image.new("RGB", (50, 50), color=(200, 200, 200))
    buf = io.BytesIO()
    img.save(buf, format="jpeg")
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Tool registry — new capability surface
# --------------------------------------------------------------------------- #
NEW_TOOL_IDS = {
    "reverse_geocode",
    "predict_geospy_coordinates",
    "analyze_vision_scene",
    "search_reverse_source",
    "fetch_streetview_panorama",
}


def test_new_tools_registered():
    ids = {t.tool_id for t in registry.list()}
    assert NEW_TOOL_IDS <= ids


def test_new_tools_specs_serializable():
    for tid in NEW_TOOL_IDS:
        spec = registry.get(tid).spec
        assert S.ToolSpec.model_validate(spec.model_dump())
        assert spec.availability in (S.Availability.AVAILABLE,
                                     S.Availability.REQUIRES_KEY)


def test_keyed_tools_report_requires_key():
    for tid in ("predict_geospy_coordinates", "analyze_vision_scene",
                "fetch_streetview_panorama", "search_reverse_source"):
        assert registry.get(tid).spec.availability == S.Availability.REQUIRES_KEY


def test_geospy_and_scene_tools_are_async():
    for tid in ("predict_geospy_coordinates", "analyze_vision_scene",
                "search_reverse_source", "fetch_streetview_panorama"):
        assert registry.get(tid).is_async()


# --------------------------------------------------------------------------- #
# Settings store — new key surface
# --------------------------------------------------------------------------- #
def test_settings_store_exposes_new_keys():
    masked = settings_store.get_keys_masked()
    for key in ("gemini_api_key", "anthropic_api_key", "mapbox_token",
                "tineye_api_key", "serper_api_key", "google_maps_api_key"):
        assert key in masked


# --------------------------------------------------------------------------- #
# Discrete handlers — honest-by-design without keys
# --------------------------------------------------------------------------- #
def test_geospy_prediction_returns_none_without_key():
    img = _make_plain_image()
    res = asyncio.run(registry.acall("predict_geospy_coordinates", image_bytes=img))
    assert res is None


@patch.object(ai_gateway, "is_configured", return_value=False)
@patch.object(ai_gateway, "has_vision_llm", return_value=False)
def test_scene_analysis_returns_none_without_key(_v, _c):
    img = _make_plain_image()
    res = asyncio.run(registry.acall("analyze_vision_scene", image_bytes=img))
    assert res is None


def test_reverse_source_unavailable_without_keys():
    img = _make_plain_image()
    res = asyncio.run(registry.acall("search_reverse_source", image_bytes=img))
    assert res["state"] == "UNAVAILABLE"
    assert res["phash"]
    assert res["exact_matches"] == []
    assert res["similar_matches"] == []
    assert res["provider"] == "none"


def test_streetview_unavailable_without_key():
    # Deterministic: whatever the dev store holds locally, this test exercises
    # the no-key path by patching the store lookup to empty.
    with patch("app.services.geo_providers._get_key", return_value=None):
        res = asyncio.run(registry.acall(
            "fetch_streetview_panorama", lat=48.8566, lon=2.3522, heading=90.0))
    assert res["state"] == "UNAVAILABLE"


def test_reverse_geocode_prefers_mapbox_when_token_set():
    with patch("app.agent.tool_registry.reverse_geocode_mapbox") as mock_mapbox:
        mock_mapbox.return_value = AddressInfo(
            country="France", state="Île-de-France", city="Paris",
            display_name="Paris, France")
        with patch("app.agent.tool_registry.reverse_geocode") as mock_nom:
            res = registry.call("reverse_geocode", lat=48.8566, lon=2.3522)
        assert res["country"] == "France"
        assert res["city"] == "Paris"
        mock_mapbox.assert_called_once_with(48.8566, 2.3522)
        mock_nom.assert_not_called()


def test_reverse_geocode_falls_back_to_nominatim():
    with patch("app.agent.tool_registry.reverse_geocode_mapbox") as mock_mapbox:
        mock_mapbox.return_value = None
        with patch("app.agent.tool_registry.reverse_geocode") as mock_nom:
            mock_nom.return_value = AddressInfo(country="Italy", city="Rome")
            res = registry.call("reverse_geocode", lat=41.9, lon=12.5)
        assert res["country"] == "Italy"
        mock_nom.assert_called_once_with(41.9, 12.5)


# --------------------------------------------------------------------------- #
# Pipeline — direct EXIF path fetches Street View on heading
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_exif_path_fetches_streetview_with_heading():
    img = _make_image_with_full_exif(with_heading=True)
    with patch("app.brain.metadata_extractor._geolocator") as mock_geo:
        mock_location = MagicMock()
        mock_location.raw = {"address": {"country": "France", "city": "Paris"}}
        mock_location.address = "Paris, France"
        mock_geo.reverse.return_value = mock_location
        with patch("app.services.geo_providers.fetch_streetview",
                   new=AsyncMock(return_value={
                       "state": "AVAILABLE", "pano_id": "P1",
                       "image_url": "http://sv/", "heading": 90.0})) as mock_sv:
            result = await brain.analyze(img)

    assert result.source == "NATIVE_EXIF_HARDWARE"
    assert result.streetview is not None
    assert result.streetview["state"] == "AVAILABLE"
    mock_sv.assert_awaited_once()


@pytest.mark.asyncio
async def test_exif_path_skips_streetview_without_heading():
    img = _make_image_with_full_exif(with_heading=False)
    with patch("app.brain.metadata_extractor._geolocator") as mock_geo:
        mock_geo.reverse.return_value = None
        with patch("app.services.geo_providers.fetch_streetview",
                   new=AsyncMock()) as mock_sv:
            result = await brain.analyze(img)
    assert result.streetview is None
    mock_sv.assert_not_awaited()


# --------------------------------------------------------------------------- #
# Pipeline — evidence graph provenance tags
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_exif_path_builds_tool_inference_graph():
    img = _make_image_with_full_exif(with_heading=False)
    with patch("app.brain.metadata_extractor._geolocator") as mock_geo:
        mock_geo.reverse.return_value = None
        result = await brain.analyze(img)

    assert result.evidence_graph is not None
    nodes = result.evidence_graph["nodes"]
    location_nodes = [n for n in nodes.values() if n["claim_type"] == "location"]
    assert location_nodes, "expected a location node"
    assert all(
        n["provenance_type"] == "tool_inference" for n in location_nodes
    )


@pytest.mark.asyncio
async def test_ai_path_builds_ai_hypothesis_graph():
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
    assert result.address is not None
    assert result.address.country == "Nigeria"
    assert result.search_radius_meters is not None
    assert result.search_radius_meters > 0
    assert result.search_radius_meters == result.consensus.search_radius_meters
    assert result.evidence_graph is not None
    nodes = result.evidence_graph["nodes"]
    location_nodes = [n for n in nodes.values() if n["claim_type"] == "location"]
    assert all(
        n["provenance_type"] == "ai_hypothesis" for n in location_nodes
    )
