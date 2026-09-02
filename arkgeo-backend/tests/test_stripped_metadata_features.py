"""Tests for the stripped-metadata fallback features.

Covers the four new capabilities:
  1. STRIPPED_BY_INTERMEDIARY metadata_status (full + partial strip) routing.
  2. OCR → geocoding candidates (backend `geocode_batch` + pipeline wiring).
  3. pHash reverse-search wrapper (`POST /analyze/reverse-search`).
  4. Terrain IMINT prompt + ranked candidate regions from vision-LLM reasoning.
"""
import asyncio
import base64
import io
from unittest.mock import AsyncMock, MagicMock, patch

import piexif
import pytest
from PIL import Image

from app.brain.pipeline import brain
from app.brain.vision_ensemble import VisionEnsemble
from app.brain.system_prompts import TERRAIN_IMINT_PROMPT
from app.models import VisionResult


def _make_full_exif_image(lat=48.8566, lon=2.3522):
    img = Image.new("RGB", (100, 100), color=(120, 120, 120))
    exif_bytes = piexif.dump({
        "0th": {piexif.ImageIFD.Make: b"Apple",
                piexif.ImageIFD.Model: b"iPhone 15 Pro"},
        "Exif": {piexif.ExifIFD.DateTimeOriginal: b"2024:01:15 14:30:00"},
        "GPS": {
            piexif.GPSIFD.GPSLatitude: ((48, 1), (51, 1), (23760, 1000)),
            piexif.GPSIFD.GPSLatitudeRef: b"N",
            piexif.GPSIFD.GPSLongitude: ((2, 1), (21, 1), (7920, 1000)),
            piexif.GPSIFD.GPSLongitudeRef: b"E",
        },
    })
    buf = io.BytesIO()
    img.save(buf, format="jpeg", exif=exif_bytes)
    return buf.getvalue()


def _make_partial_exif_image():
    """EXIF block survives (camera provenance) but GPS is stripped."""
    img = Image.new("RGB", (100, 100), color=(120, 120, 120))
    exif_bytes = piexif.dump({
        "0th": {piexif.ImageIFD.Make: b"Apple",
                piexif.ImageIFD.Model: b"iPhone 15 Pro"},
        "Exif": {piexif.ExifIFD.DateTimeOriginal: b"2024:01:15 14:30:00"},
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
# Feature 1 — STRIPPED_BY_INTERMEDIARY
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_full_strip_routes_to_intermediary_status():
    img = _make_plain_image()
    with patch("app.brain.metadata_extractor._geolocator") as mock_geo:
        mock_geo.reverse.return_value = None
        result = await brain.analyze(img)
    assert result.metadata_status == "STRIPPED_BY_INTERMEDIARY"
    assert result.exif_missing is True


@pytest.mark.asyncio
async def test_partial_strip_gps_removed_routes_to_intermediary():
    """Camera EXIF present but GPS stripped → still flagged STRIPPED."""
    img = _make_partial_exif_image()
    with patch("app.brain.metadata_extractor._geolocator") as mock_geo:
        mock_geo.reverse.return_value = None
        result = await brain.analyze(img)
    assert result.exif_missing is False
    assert result.exif_raw  # camera block survived
    assert result.coordinates is None
    assert result.metadata_status == "STRIPPED_BY_INTERMEDIARY"


@pytest.mark.asyncio
async def test_intact_exif_reports_exif_present():
    img = _make_full_exif_image()
    with patch("app.brain.metadata_extractor._geolocator") as mock_geo:
        mock_location = MagicMock()
        mock_location.raw = {"address": {"country": "France", "city": "Paris"}}
        mock_location.address = "Paris, France"
        mock_geo.reverse.return_value = mock_location
        with patch("app.services.geo_providers.fetch_streetview",
                   new=AsyncMock(return_value={"state": "UNAVAILABLE"})):
            result = await brain.analyze(img)
    assert result.metadata_status == "EXIF_PRESENT"
    assert result.source == "NATIVE_EXIF_HARDWARE"


@pytest.mark.asyncio
async def test_stripped_metadata_observation_recorded():
    img = _make_plain_image()
    with patch("app.brain.metadata_extractor._geolocator") as mock_geo:
        mock_geo.reverse.return_value = None
        result = await brain.analyze(img)
    states = [o for o in result.observations if o.get("type") == "METADATA_STATE"]
    assert states and states[0]["status"] == "ANOMALY"


# --------------------------------------------------------------------------- #
# Feature 2 — OCR → geocoding candidates
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_geo_candidates_populated_from_ocr_text():
    """OCR extractor text (street name) is geocoded into candidate pins."""
    img = _make_plain_image()
    vision = VisionResult(source="llm_vision", confidence_score=0.5)

    def _ocr_side_effect(image_bytes, system_prompt):
        if "street signs" in system_prompt:  # OCR_INFRASTRUCTURE_PROMPT
            return {
                "extracted_texts": [
                    {"text": "Victoria Island Road", "type": "sign", "confidence": 0.85},
                ],
                "geo_probabilistic_indicators": [],
            }
        return {}

    candidate = {"query": "Victoria Island Road", "lat": 6.4281, "lon": 3.4219,
                 "source": "nominatim", "cached": False, "matched": True}
    with patch.object(brain.vision, "locate",
                      new=AsyncMock(return_value=[vision])):
        with patch("app.brain.pipeline.reverse_geocode") as mock_rg:
            mock_rg.return_value = None
            with patch("app.brain.clue_extractors.base.llm_client.vision_query",
                       side_effect=_ocr_side_effect):
                with patch("app.services.geocoding_service.geocode_batch",
                           new=AsyncMock(return_value=[candidate])) as mock_gb:
                    result = await brain.analyze(img)

    assert result.metadata_status == "STRIPPED_BY_INTERMEDIARY"
    mock_gb.assert_awaited_once()
    assert mock_gb.await_args.args[0] == ["Victoria Island Road"]
    assert len(result.geo_candidates) == 1
    assert result.geo_candidates[0]["query"] == "Victoria Island Road"


@pytest.mark.asyncio
async def test_geocode_batch_endpoint():
    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as client:
        with patch("app.services.geocoding_service.geocode_batch",
                   new=AsyncMock(return_value=[
                       {"query": "Lagos", "lat": 6.5244, "lon": 3.3792,
                        "source": "nominatim", "cached": False, "matched": True}])):
            resp = client.post("/api/v1/maps/geocode/batch",
                               json={"queries": ["Lagos", "Victoria Island Road"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["candidates"][0]["lat"] == 6.5244


@pytest.mark.asyncio
async def test_is_location_like_filtering():
    from app.brain.pipeline import _is_location_like
    assert _is_location_like("Victoria Island Road")
    assert _is_location_like("Lagos")
    assert _is_location_like("Mumbai Central Avenue")
    assert not _is_location_like("+234 800 000 0000")
    assert not _is_location_like("ab")
    assert not _is_location_like("https://example.com")


# --------------------------------------------------------------------------- #
# Feature 3 — reverse-search wrapper endpoint
# --------------------------------------------------------------------------- #
def test_reverse_search_endpoint_unavailable_without_keys():
    from fastapi.testclient import TestClient
    from main import app

    img = _make_plain_image()
    b64 = base64.b64encode(img).decode()
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/analyze/reverse-search",
            json={"image_base64": b64},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "UNAVAILABLE"
    assert body["phash"]
    assert body["exact_matches"] == []
    assert body["similar_matches"] == []


def test_reverse_search_endpoint_rejects_invalid_base64():
    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/analyze/reverse-search",
            json={"image_base64": "not-a-real-image"},
        )
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# Feature 4 — Terrain IMINT prompt + candidate regions
# --------------------------------------------------------------------------- #
def test_terrain_imint_prompt_schema():
    assert "IMINT/GEOINT" in TERRAIN_IMINT_PROMPT
    assert "terrain and vegetation" in TERRAIN_IMINT_PROMPT.lower()
    assert "candidate_regions" in TERRAIN_IMINT_PROMPT


def test_vision_ensemble_uses_imint_prompt_and_parses_regions():
    ensemble = VisionEnsemble()
    img = _make_plain_image()
    llm_payload = {
        "estimated_latitude": 6.5244,
        "estimated_longitude": 3.3792,
        "search_radius_meters": 500,
        "confidence_score": 0.55,
        "primary_country": "Nigeria",
        "region": "Lagos",
        "candidate_regions": [
            {"region": "Lagos, Nigeria", "confidence": 0.8,
             "rationale": "Coastal lowland, tropical vegetation, signage"},
            {"region": "Coastal West Africa", "confidence": 0.5,
             "rationale": "Tropical climate band"},
            {"region": "Gulf of Guinea", "confidence": 0.3,
             "rationale": "Coastal features"},
        ],
        "visual_evidence_tags": [
            {"category": "botanical", "label": "palm", "confidence": 0.7},
        ],
    }
    with patch("app.brain.clue_extractors.base.llm_client.vision_query",
               return_value=llm_payload) as mock_vq:
        result = ensemble._query_llm_vision(img)

    assert result is not None
    assert result.source == "llm_vision"
    mock_vq.assert_called_once_with(img, TERRAIN_IMINT_PROMPT)
    assert len(result.candidate_regions) == 3
    assert result.candidate_regions[0]["region"] == "Lagos, Nigeria"
    assert result.candidate_regions[0]["confidence"] == 0.8
    # ranked descending
    confs = [r["confidence"] for r in result.candidate_regions]
    assert confs == sorted(confs, reverse=True)


def test_vision_ensemble_ignores_malformed_candidate_regions():
    ensemble = VisionEnsemble()
    img = _make_plain_image()
    llm_payload = {
        "confidence_score": 0.1,
        "candidate_regions": [
            {"region": "", "confidence": 0.9},          # empty region → dropped
            {"region": "Paris", "confidence": "high"},   # bad confidence → 0
            "not-a-dict",                                 # dropped
            {"region": "London", "confidence": 0.6, "rationale": ""},
        ],
    }
    with patch("app.brain.clue_extractors.base.llm_client.vision_query",
               return_value=llm_payload):
        result = ensemble._query_llm_vision(img)
    assert result is not None
    assert len(result.candidate_regions) == 2


@pytest.mark.asyncio
async def test_pipeline_surfaces_candidate_regions():
    img = _make_plain_image()
    vision = VisionResult(
        source="llm_vision",
        estimated_latitude=6.5244, estimated_longitude=3.3792,
        search_radius_meters=800.0, confidence_score=0.62,
        primary_country="Nigeria",
        candidate_regions=[
            {"region": "Lagos, Nigeria", "confidence": 0.8, "rationale": "coast"},
            {"region": "Coastal West Africa", "confidence": 0.5, "rationale": "tropical"},
        ],
    )
    with patch.object(brain.vision, "locate",
                      new=AsyncMock(return_value=[vision])):
        with patch("app.brain.pipeline.reverse_geocode") as mock_rg:
            mock_rg.return_value = None
            result = await brain.analyze(img)
    assert result.source == "AI_VISION"
    assert [r["region"] for r in result.candidate_regions] == [
        "Lagos, Nigeria", "Coastal West Africa",
    ]


# --------------------------------------------------------------------------- #
# Response serialization
# --------------------------------------------------------------------------- #
def test_analyze_response_serializes_new_fields():
    from app.models import AnalyzeResponse, ConsensusResult
    resp = AnalyzeResponse(
        request_id="r1",
        custody_hash="h",
        image_sha256="s",
        consensus=ConsensusResult(
            estimated_latitude=6.5244, estimated_longitude=3.3792,
            search_radius_meters=500.0, confidence_score=0.5, tier_used="consensus",
        ),
        metadata_status="STRIPPED_BY_INTERMEDIARY",
        geo_candidates=[{"query": "Lagos", "lat": 6.5, "lon": 3.4,
                         "source": "nominatim", "cached": False, "matched": True}],
        candidate_regions=[{"region": "Lagos, Nigeria", "confidence": 0.8,
                            "rationale": "coast"}],
    )
    data = resp.model_dump()
    assert data["metadata_status"] == "STRIPPED_BY_INTERMEDIARY"
    assert data["geo_candidates"][0]["query"] == "Lagos"
    assert data["candidate_regions"][0]["region"] == "Lagos, Nigeria"
