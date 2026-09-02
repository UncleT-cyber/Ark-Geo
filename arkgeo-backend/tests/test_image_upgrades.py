"""Tests for the IMAGE workspace upgrades:

* Step 1  — original rehydration (GPS recovery from stripped shares)
* Step 2  — agentic enhance -> re-analyze loop
* Step 3  — Monte-Carlo uncertainty + satellite cross-reference
"""
from __future__ import annotations

import io

from PIL import Image

from app.brain import consensus_engine as ce
from app.brain import geolocation_fusion as gf
from app.agent import tool_registry as tr
from app.agent.tool_registry import registry
from app.services import source_discovery as sd
from app.models import Coordinates, ConsensusResult, VisualEvidenceTag
from app.agent import schemas as S
from app.agent import specialists as SP


def _coords(lat: float, lon: float) -> Coordinates:
    return Coordinates(lat=lat, lon=lon)


# --------------------------------------------------------------------------- #
# Step 1 - original rehydration
# --------------------------------------------------------------------------- #
def test_match_urls_orders_exact_first():
    matches = [
        {"image_url": "http://b/y.jpg", "score": 40},
        {"url": "http://a/x.jpg", "score": 99},
    ]
    urls = sd._match_urls(matches)
    assert urls[0] == "http://a/x.jpg"
    assert "http://b/y.jpg" in urls


def test_analyze_no_matches_no_recovery():
    out = sd.source_discovery.analyze(b"\x00notanimage", {}, matches=None)
    assert out["recovered_gps"] is None
    assert out["recovered_source_url"] is None


def test_analyze_with_matches_triggers_rehydration(monkeypatch):
    class FakeResp:
        status_code = 200
        content = b"fakebytes"

    monkeypatch.setattr(sd.httpx, "get", lambda *a, **k: FakeResp())

    class FakeMeta:
        def extract(self, b):
            return {"gps": _coords(12.5, 34.5), "camera": {"Make": "Test"},
                    "datetime_original": "2020:01:01 00:00:00"}

    monkeypatch.setattr("app.brain.metadata_extractor.MetadataExtractor", lambda: FakeMeta())

    out = sd.source_discovery.analyze(b"img", {}, matches=[{"url": "http://x/y.jpg", "score": 99}])
    assert out["recovered_gps"] == {"lat": 12.5, "lon": 34.5}
    assert out["recovered_source_url"] == "http://x/y.jpg"


def test_rehydrate_no_gps_yields_none(monkeypatch):
    class FakeResp:
        status_code = 200
        content = b"fakebytes"

    monkeypatch.setattr(sd.httpx, "get", lambda *a, **k: FakeResp())

    class FakeMeta:
        def extract(self, b):
            return {"gps": None, "camera": {}, "datetime_original": None}

    monkeypatch.setattr("app.brain.metadata_extractor.MetadataExtractor", lambda: FakeMeta())
    assert sd._rehydrate_original([{"url": "http://x/y.jpg"}]) is None


# --------------------------------------------------------------------------- #
# Step 2 - agentic enhance
# --------------------------------------------------------------------------- #
def test_enhance_image_returns_decoded_bytes():
    img = Image.new("RGB", (20, 20), color=(120, 80, 40))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    out = tr._enhance_image(buf.getvalue(), scale=2)
    assert isinstance(out, bytes) and len(out) > 0
    reloaded = Image.open(io.BytesIO(out))
    assert reloaded.size == (40, 40)


def test_enhance_image_tool_registered():
    spec = registry.get("enhance_image")
    assert spec is not None
    assert spec.spec.domain == "image"


# --------------------------------------------------------------------------- #
# Step 3 - Monte-Carlo + satellite cross-reference
# --------------------------------------------------------------------------- #
def test_consensus_monte_carlo_metadata():
    c = ce.ConsensusEngine().aggregate(_coords(12.34, 56.78), None, [], [])
    assert c.credible_interval_radius is not None
    assert c.credible_interval_radius > 0
    assert c.monte_carlo_samples == 600
    assert c.probability_surface is not None
    assert "grid" in c.probability_surface


def test_consensus_monte_carlo_empty_is_none():
    c = ce.ConsensusEngine().aggregate(None, None, [], [])
    assert c.credible_interval_radius is None
    assert c.monte_carlo_samples == 0


def test_consensus_monte_carlo_consensus_branch():
    tag = VisualEvidenceTag(category="architecture", label="tower", confidence=0.6)
    vr = type("V", (), {"estimated_latitude": 10.0, "estimated_longitude": 20.0,
                        "confidence_score": 0.5, "source": "geospy",
                        "primary_country": "X", "region": "Y",
                        "raw": {}, "evidence_tags": [tag]})()
    c = ce.ConsensusEngine().aggregate(None, None, [vr], [])
    assert c.credible_interval_radius is not None
    assert c.tier_used == "consensus"


def test_satellite_crossref_unavailable_without_key():
    out = gf.geolocation_fusion.cross_reference(_coords(1.0, 2.0))
    assert out["state"] == "UNAVAILABLE"


def test_fuse_includes_satellite_and_recovered():
    consensus = ConsensusResult(
        estimated_latitude=5.0, estimated_longitude=6.0, search_radius_meters=100,
        confidence_score=0.8, tier_used="metadata", sources=["metadata"],
    )
    satellite = {"state": "AVAILABLE", "provider": "mapbox", "tile_url": "http://x", "zoom": 16}
    recovered = {"recovered_gps": {"gps": {"lat": 5.0, "lon": 6.0}}, "recovered_source_url": "http://orig"}
    out = gf.geolocation_fusion.fuse(
        consensus, _coords(5.0, 6.0), None, [], [], {},
        satellite=satellite, recovered_gps=recovered,
    )
    assert out["satellite_crossref"] == satellite
    assert out["recovered_original"] == recovered
    layers = [e["layer"] for e in out["supporting"]]
    assert "Satellite Cross-Ref" in layers
    assert "Recovered Original" in layers


def test_image_specialist_has_enhance():
    spec = SP.SpecialistRegistry().get("image")
    assert "enhance_image" in spec.tool_ids
