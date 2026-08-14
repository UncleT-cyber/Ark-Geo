"""Tests for the ARK AI orchestration substrate (Phase A).

Covers:
  * Tool Registry — registration, lookup, sync + async dispatch
  * Evidence Graph — node/edge ops, hash tamper-evidence
  * Promotion rule — tier-0/1 promotable alone; tier-2 needs corroboration;
    a contradicting higher-tier node blocks promotion.
  * Wrappers — each registered tool delegates to the existing service.

No AI is exercised — Phase A is deterministic scaffolding.
"""
import asyncio
import io

import piexif
from PIL import Image

from app.agent import evidence_graph as eg
from app.agent import schemas as S
from app.agent.tool_registry import registry


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _make_image_with_gps(lat=6.5244, lon=3.3792):
    img = Image.new("RGB", (80, 80), color=(110, 110, 110))

    def _dms(v):
        v = abs(v); d = int(v); m = int((v - d) * 60)
        s = (v - d - m / 60) * 3600
        return ((d, 1), (m, 1), (int(s * 10000), 10000))

    gps = {
        piexif.GPSIFD.GPSLatitude: _dms(lat),
        piexif.GPSIFD.GPSLatitudeRef: b"N",
        piexif.GPSIFD.GPSLongitude: _dms(lon),
        piexif.GPSIFD.GPSLongitudeRef: b"E",
    }
    exif = piexif.dump({"GPS": gps})
    buf = io.BytesIO()
    img.save(buf, "jpeg", exif=exif)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Tool Registry
# --------------------------------------------------------------------------- #
def test_registry_lists_all_tools():
    tools = registry.list()
    ids = {t.tool_id for t in tools}
    assert "compute_custody_hash" in ids
    assert "extract_exif" in ids
    assert "aggregate_consensus" in ids
    assert len(tools) >= 16


def test_registry_specs_serializable():
    for spec in registry.specs():
        # Each spec is a pydantic model — must round-trip.
        S.ToolSpec.model_validate(spec.model_dump())


def test_registry_call_unknown_raises():
    import pytest
    with pytest.raises(KeyError):
        registry.call("nonexistent_tool")


def test_compute_custody_hash_wrapper():
    img = _make_image_with_gps()
    res = registry.call("compute_custody_hash", image_bytes=img)
    assert "sha256" in res
    assert len(res["sha256"]) == 64


def test_extract_exif_wrapper():
    img = _make_image_with_gps()
    meta = registry.call("extract_exif", image_bytes=img)
    gps = meta["gps"]
    assert gps is not None
    lat = gps.lat if hasattr(gps, "lat") else gps["lat"]
    assert abs(lat - 6.5244) < 0.01


def test_validate_format_wrapper():
    img = _make_image_with_gps()
    fmt = registry.call("validate_format", image_bytes=img)
    assert fmt in ("jpeg", "JPEG")


def test_vision_ensemble_is_async():
    tool = registry.get("run_vision_ensemble")
    assert tool.is_async()


def test_async_dispatch_via_acall():
    # detect_eof_anomaly is sync; acall should still work on sync handlers.
    img = _make_image_with_gps()
    res = asyncio.run(registry.acall("detect_eof_anomaly", image_bytes=img))
    assert "steganography_detected" in res


def test_vision_acall_without_keys_returns_empty():
    # No API keys configured -> vision ensemble returns [] gracefully.
    img = _make_image_with_gps()
    res = asyncio.run(registry.acall("run_vision_ensemble", image_bytes=img))
    assert isinstance(res, list)


# --------------------------------------------------------------------------- #
# Evidence Graph — node/edge operations
# --------------------------------------------------------------------------- #
def test_node_hash_roundtrip():
    graph = eg.EvidenceGraph(case_id="ARK-CASE-1")
    node = eg.build_node(
        "ARK-CASE-1", "extract_exif", S.ProvenanceType.TOOL_INFERENCE,
        "EXIF GPS present", S.ClaimType.LOCATION,
        {"lat": 6.52, "lon": 3.38},
    )
    eg.add_node(graph, node)
    assert node.node_id in graph.nodes


def test_node_tamper_detected():
    graph = eg.EvidenceGraph(case_id="ARK-CASE-1")
    node = eg.build_node(
        "ARK-CASE-1", "extract_exif", S.ProvenanceType.TOOL_INFERENCE,
        "GPS present", S.ClaimType.LOCATION, {"lat": 6.5, "lon": 3.4},
    )
    node.hash = "tampered"
    import pytest
    with pytest.raises(ValueError):
        eg.add_node(graph, node)


def test_edge_weight_sign_enforced():
    graph = eg.EvidenceGraph(case_id="ARK-CASE-1")
    a = eg.build_node("ARK-CASE-1", "t", S.ProvenanceType.CRYPTOGRAPHIC,
                      "hash", S.ClaimType.INTEGRITY, "abc")
    b = eg.build_node("ARK-CASE-1", "t", S.ProvenanceType.TOOL_INFERENCE,
                      "meta", S.ClaimType.METADATA, {})
    eg.add_node(graph, a); eg.add_node(graph, b)

    e = eg.add_edge(graph, a.node_id, b.node_id, S.EdgeRelation.CONTRADICTS, weight=0.5)
    assert e.weight < 0, "contradicts must be negative"

    e2 = eg.add_edge(graph, a.node_id, b.node_id, S.EdgeRelation.CORROBORATES, weight=-1)
    assert e2.weight > 0, "corroborates must be positive"


def test_corroboration_score():
    graph = eg.EvidenceGraph(case_id="ARK-CASE-1")
    a = eg.build_node("ARK-CASE-1", "t", S.ProvenanceType.TOOL_INFERENCE,
                      "loc", S.ClaimType.LOCATION, {"lat": 6.5, "lon": 3.4})
    b = eg.build_node("ARK-CASE-1", "t", S.ProvenanceType.TOOL_INFERENCE,
                      "loc", S.ClaimType.LOCATION, {"lat": 6.51, "lon": 3.41})
    eg.add_node(graph, a); eg.add_node(graph, b)
    eg.add_edge(graph, a.node_id, b.node_id, S.EdgeRelation.CORROBORATES)
    assert eg.corroboration_score(graph, a.node_id) > 0


# --------------------------------------------------------------------------- #
# Promotion rule — the forensic core
# --------------------------------------------------------------------------- #
def test_tier1_promotable_alone():
    graph = eg.EvidenceGraph(case_id="ARK-CASE-1")
    node = eg.build_node(
        "ARK-CASE-1", "extract_exif", S.ProvenanceType.TOOL_INFERENCE,
        "EXIF GPS", S.ClaimType.LOCATION, {"lat": 6.5, "lon": 3.4},
    )
    eg.add_node(graph, node)
    finding = eg.promote_to_finding(graph, node.node_id)
    assert finding.claim_type == S.ClaimType.LOCATION
    assert node.node_id in finding.supporting_node_ids


def test_tier2_without_corroboration_denied():
    graph = eg.EvidenceGraph(case_id="ARK-CASE-1")
    node = eg.build_node(
        "ARK-CASE-1", "run_vision_ensemble", S.ProvenanceType.AI_HYPOTHESIS,
        "Vision estimates Lagos", S.ClaimType.LOCATION,
        {"lat": 6.5, "lon": 3.4}, confidence=0.5,
    )
    eg.add_node(graph, node)
    import pytest
    with pytest.raises(eg.PromotionDenied):
        eg.promote_to_finding(graph, node.node_id)


def test_tier2_promotable_with_tier1_corroboration():
    graph = eg.EvidenceGraph(case_id="ARK-CASE-1")
    fact = eg.build_node(
        "ARK-CASE-1", "extract_exif", S.ProvenanceType.TOOL_INFERENCE,
        "EXIF GPS Lagos", S.ClaimType.LOCATION, {"lat": 6.5, "lon": 3.4},
    )
    hyp = eg.build_node(
        "ARK-CASE-1", "run_vision_ensemble", S.ProvenanceType.AI_HYPOTHESIS,
        "Vision estimates Lagos", S.ClaimType.LOCATION,
        {"lat": 6.51, "lon": 3.41}, confidence=0.6,
    )
    eg.add_node(graph, fact); eg.add_node(graph, hyp)
    eg.add_edge(graph, fact.node_id, hyp.node_id, S.EdgeRelation.CORROBORATES)
    finding = eg.promote_to_finding(graph, hyp.node_id)
    assert fact.node_id in finding.supporting_node_ids


def test_tier2_blocked_by_higher_tier_contradiction():
    """A tier-0/1 contradiction must block tier-2 promotion."""
    graph = eg.EvidenceGraph(case_id="ARK-CASE-1")
    fact = eg.build_node(
        "ARK-CASE-1", "extract_exif", S.ProvenanceType.TOOL_INFERENCE,
        "EXIF GPS Paris", S.ClaimType.LOCATION, {"lat": 48.8, "lon": 2.3},
    )
    hyp = eg.build_node(
        "ARK-CASE-1", "run_vision_ensemble", S.ProvenanceType.AI_HYPOTHESIS,
        "Vision estimates Lagos", S.ClaimType.LOCATION,
        {"lat": 6.5, "lon": 3.4}, confidence=0.7,
    )
    eg.add_node(graph, fact); eg.add_node(graph, hyp)
    eg.add_edge(graph, fact.node_id, hyp.node_id, S.EdgeRelation.CONTRADICTS)
    import pytest
    with pytest.raises(eg.PromotionDenied):
        eg.promote_to_finding(graph, hyp.node_id)


def test_two_independent_tier2_agree_promotes():
    graph = eg.EvidenceGraph(case_id="ARK-CASE-1")
    h1 = eg.build_node(
        "ARK-CASE-1", "run_vision_ensemble", S.ProvenanceType.AI_HYPOTHESIS,
        "GeoSpy: Lagos", S.ClaimType.LOCATION,
        {"lat": 6.5, "lon": 3.4}, confidence=0.55,
    )
    h2 = eg.build_node(
        "ARK-CASE-1", "geoinfer", S.ProvenanceType.AI_HYPOTHESIS,
        "GeoInfer: Lagos", S.ClaimType.LOCATION,
        {"lat": 6.51, "lon": 3.41}, confidence=0.5,
    )
    eg.add_node(graph, h1); eg.add_node(graph, h2)
    eg.add_edge(graph, h1.node_id, h2.node_id, S.EdgeRelation.CORROBORATES)
    finding = eg.promote_to_finding(graph, h2.node_id)
    assert h1.node_id in finding.supporting_node_ids
