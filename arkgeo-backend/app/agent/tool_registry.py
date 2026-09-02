"""Tool Registry — the universal capability surface for the ARK orchestrator.

Each existing deterministic capability is wrapped as a registered ``Tool``:
a :class:`ToolSpec` (the contract the AI/policy see) plus a callable
``handler`` that adapts to the real implementation. Phase A wraps tools with
**zero behavior change** — the handlers simply delegate to the existing
services and return their native dicts. A later adapter converts results into
:class:`EvidenceNode` objects written to the graph.

The registry is the keystone: without it the planner has no capability surface
and the policy guard has no authorization surface. See spec §3.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Callable, Optional

from ..brain.clue_extractors.ocr_text import OcrTextExtractor
from ..brain.consensus_engine import ConsensusEngine
from ..brain.contradiction_engine import contradiction_engine
from ..brain.consistency_engine import consistency_engine
from ..brain.geolocation_fusion import geolocation_fusion
from ..brain.metadata_extractor import (
    MetadataExtractor,
    detect_eof_anomaly,
    generate_ela_heatmap,
    reverse_geocode,
)
from ..brain.system_prompts import (
    TERRAIN_IMINT_PROMPT,
)
from ..brain.vision_ensemble import VisionEnsemble
from ..core.security import custody_certificate, validate_magic_bytes
from ..services.c2pa_service import c2pa_service
from ..services.exiftool_service import exiftool_service
from ..services.geo_providers import (
    fetch_streetview,
    reverse_geocode_google,
    reverse_geocode_mapbox,
    search_serper,
    search_tineye,
)
from ..services.settings_store import settings_store
from ..services.source_discovery import source_discovery
from ..services.source_discovery import _rehydrate_original as _sd_rehydrate_original
from ..services.telemetry_service import TelemetryService
from ..tools.geocoding_tool import geocode_batch_texts, geocode_place
from ..tools.pen_test.default_cred_tester import test_default_creds
from ..tools.pen_test.hash_cracker_tool import crack_hash
from ..tools.pen_test.nmap_scanner_tool import nmap_scan
from ..tools.pen_test.priv_esc_analyzer import analyze_privilege_escalation
from ..tools.pen_test.webshell_detector import scan_webshells
from ..tools.reverse_image_tool import reverse_image_search
from ..tools.ros_forensics.ros_inspector_tool import inspect_ros
from ..tools.ros_forensics.safety_audit_analyzer import analyze_safety_config
from ..tools.web_search_tool import web_fetch, web_search
from . import schemas as S

logger = logging.getLogger(__name__)

_metadata = MetadataExtractor()
_vision = VisionEnsemble()
_telemetry = TelemetryService()


class Tool:
    """A registered capability: spec + handler."""
    def __init__(self, spec: S.ToolSpec, handler: Callable[..., Any]):
        self.spec = spec
        self.handler = handler

    @property
    def tool_id(self) -> str:
        return self.spec.tool_id

    def is_async(self) -> bool:
        return inspect.iscoroutinefunction(self.handler)


# --------------------------------------------------------------------------- #
# Spec builders — keep the catalog declarative and auditable.
# --------------------------------------------------------------------------- #
def _spec(
    tool_id: str, name: str, description: str, *,
    domain: str, category: S.ToolCategory, risk: S.RiskLevel,
    provider: str, permissions: Optional[list[S.Permission]] = None,
    deterministic: bool = True, availability: S.Availability = S.Availability.AVAILABLE,
    cost: Optional[S.CostEstimate] = None,
    input_schema: Optional[dict] = None,
) -> S.ToolSpec:
    return S.ToolSpec(
        tool_id=tool_id, name=name, description=description,
        domain=domain, category=category, risk=risk, provider=provider,
        permissions=permissions or [S.Permission.READ_EVIDENCE],
        deterministic=deterministic, availability=availability,
        cost_estimate=cost, input_schema=input_schema or {},
    )


# --------------------------------------------------------------------------- #
# Handlers — thin adapters over existing deterministic services.
# Each takes a flat kwargs dict and returns the service's native result.
# --------------------------------------------------------------------------- #
def _compute_custody_hash(image_bytes: bytes) -> dict:
    return custody_certificate(image_bytes)


def _validate_format(image_bytes: bytes, declared_type: Optional[str] = None) -> str:
    return validate_magic_bytes(image_bytes, declared_type)


def _extract_exif(image_bytes: bytes) -> dict:
    return _metadata.extract(image_bytes)


def _extract_deep_metadata(image_bytes: bytes) -> dict:
    return exiftool_service.extract_deep(image_bytes)


def _reverse_geocode(lat: float, lon: float) -> Optional[dict]:
    # Prefer Google Maps Geocoding when its key is configured, then Mapbox,
    # then OSM Nominatim (keyless).
    addr = (
        reverse_geocode_google(lat, lon)
        or reverse_geocode_mapbox(lat, lon)
        or reverse_geocode(lat, lon)
    )
    return addr.model_dump() if addr else None


def _resolve_telemetry(
    last_known_gps: Optional[dict] = None,
    connected_cell_tower: Optional[dict] = None,
    nearby_wifi_bssids: Optional[list[str]] = None,
) -> Optional[dict]:
    from ..models import CellTowerInfo, Coordinates, GpsFix
    last = None
    if last_known_gps:
        last = GpsFix(**last_known_gps)
    cell = CellTowerInfo(**connected_cell_tower) if connected_cell_tower else None
    coords = _telemetry.resolve(
        last_known_gps=last, cell_tower=cell,
        wifi_bssids=nearby_wifi_bssids,
    )
    return coords.model_dump() if coords else None


def _analyze_ela(image_bytes: bytes, quality: int = 95) -> Optional[str]:
    return generate_ela_heatmap(image_bytes, quality)


def _detect_eof_anomaly(image_bytes: bytes, fmt: Optional[str] = None) -> dict:
    return detect_eof_anomaly(image_bytes, fmt)


def _verify_c2pa(image_bytes: bytes, exiftool_groups: Optional[dict] = None) -> dict:
    return c2pa_service.analyze(image_bytes, exiftool_groups or {})


def _run_consistency(exiftool_groups: dict, file_info: dict) -> list[dict]:
    return consistency_engine.analyze(exiftool_groups, file_info)


def _run_ocr(image_bytes: bytes) -> Optional[dict]:
    res = OcrTextExtractor().extract(image_bytes)
    return res.model_dump() if res else None


def _fuse_geolocation(
    consensus: Optional[dict], coordinates: Optional[dict],
    address: Optional[dict], visual_tags: list[dict],
    consistency_findings: list[dict], exif_raw: dict,
) -> dict:
    from ..models import ConsensusResult, Coordinates, VisualEvidenceTag
    cons = ConsensusResult(**consensus) if consensus else None
    coords = Coordinates(**coordinates) if coordinates else None
    tags = [VisualEvidenceTag(**t) for t in visual_tags]
    return geolocation_fusion.fuse(
        cons, coords, address, tags, consistency_findings, exif_raw,
    )


def _discover_sources(image_bytes: bytes, exiftool_groups: dict) -> dict:
    return source_discovery.analyze(image_bytes, exiftool_groups)


# --------------------------------------------------------------------------- #
# Universal Image Intelligence handlers — discrete providers for the fallback
# pipeline.  Each is honest-by-design: missing keys / failed calls return
# None or a structured UNAVAILABLE result, never fabricated data.
# --------------------------------------------------------------------------- #
async def _predict_geospy_coordinates(image_bytes: bytes) -> Optional[dict]:
    """Discrete GeoSpy prediction for a single image."""
    res = await _vision.predict_geospy(image_bytes)
    if res is None:
        return None
    return {
        "source": "geospy",
        "estimated_latitude": res.estimated_latitude,
        "estimated_longitude": res.estimated_longitude,
        "search_radius_meters": res.search_radius_meters,
        "confidence_score": res.confidence_score,
        "primary_country": res.primary_country,
        "region": res.region,
    }


async def _analyze_vision_scene(image_bytes: bytes) -> Optional[dict]:
    """Scene reasoning (vision LLM) + OCR text, merged into one tool result.

    Uses the terrain IMINT / GEOINT prompt so the response includes ranked
    candidate regions derived from terrain, vegetation, architecture,
    language and shadow analysis.
    """
    from ..brain.clue_extractors.base import llm_client

    scene = await asyncio.to_thread(
        llm_client.vision_query, image_bytes, TERRAIN_IMINT_PROMPT
    )
    if not scene:
        return None
    ocr = OcrTextExtractor().extract(image_bytes)
    ocr_texts: list[str] = []
    for t in (ocr.evidence_tags if ocr else []):
        if t.category == "ocr":
            ocr_texts.append(t.label)
    tags = [
        t.model_dump() if hasattr(t, "model_dump") else t
        for t in (scene.get("visual_evidence_tags") or [])
        if isinstance(t, dict)
    ]
    candidate_regions: list[dict] = []
    for r in (scene.get("candidate_regions") or []):
        if isinstance(r, dict) and r.get("region"):
            candidate_regions.append({
                "region": r.get("region"),
                "confidence": r.get("confidence", 0.0),
                "rationale": r.get("rationale"),
            })
    return {
        "scene_description": scene.get("description") or scene.get("scene") or scene,
        "evidence_tags": tags,
        "ocr_texts": ocr_texts,
        "candidate_regions": candidate_regions,
        "confidence_score": scene.get("confidence_score"),
        "primary_country": scene.get("primary_country"),
        "region": scene.get("region"),
    }


def _is_exact_match(match: dict) -> bool:
    score = match.get("score")
    if isinstance(score, (int, float)) and score is not None:
        return score >= 95.0
    return False


async def _search_reverse_source(
    image_bytes: bytes,
    exiftool_groups: Optional[dict] = None,
    search_query: Optional[str] = None,
) -> dict:
    """Local fingerprint + configured reverse-source providers (TinEye/Serper)."""
    base = source_discovery.analyze(image_bytes, exiftool_groups or {})
    tasks = []
    if settings_store.get_key("tineye_api_key"):
        tasks.append(search_tineye(image_bytes))
    if settings_store.get_key("serper_api_key"):
        tasks.append(search_serper(search_query=search_query))
    provider_results = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []

    matches: list[dict] = []
    providers: list[str] = []
    for r in provider_results:
        if isinstance(r, Exception):
            logger.warning("Reverse source provider error: %s", r)
            continue
        providers.append(r.get("provider", "unknown"))
        matches.extend(r.get("matches") or [])
        if r.get("state") == "AVAILABLE":
            base["state"] = "AVAILABLE"

    base["exact_matches"] = [m for m in matches if _is_exact_match(m)]
    base["similar_matches"] = [m for m in matches if not _is_exact_match(m)]
    base["timeline"] = [
        {
            "source": m.get("title") or m.get("filepath"),
            "url": m.get("url") or m.get("source_url") or m.get("image_url"),
            "first_seen": m.get("first_seen"),
            "score": m.get("score"),
        }
        for m in matches
    ]
    base["provider"] = ", ".join(providers) or "none"
    if providers:
        base["detail"] = (
            f"Reverse source discovery via {', '.join(providers)}: "
            f"{len(matches)} match(es)."
        )
    # Original rehydration (recover GPS stripped by a messaging intermediary)
    recovered = _sd_rehydrate_original(matches)
    if recovered:
        base["recovered_gps"] = recovered["gps"]
        base["recovered_metadata"] = {
            "camera": recovered["camera"],
            "datetime_original": recovered["datetime_original"],
        }
        base["recovered_source_url"] = recovered["source_url"]
        base["detail"] = (
            (base.get("detail") or "")
            + f" Original rehydration recovered GPS from {recovered['source_url']}."
        )
    return base


async def _fetch_streetview_panorama(
    lat: float, lon: float, heading: Optional[float] = None
) -> dict:
    """Google Street View Static — metadata + static image URL."""
    return await fetch_streetview(lat, lon, heading)


def _detect_contradictions(
    consistency_findings: list[dict], geolocation_fusion: dict,
    exif_raw: dict, gps_spoofing_detected: bool,
    anomaly_score: float, sanity_mismatches: list[str],
) -> list[dict]:
    return contradiction_engine.detect(
        consistency_findings, geolocation_fusion, exif_raw,
        gps_spoofing_detected, anomaly_score, sanity_mismatches,
    )


async def _run_vision_ensemble(image_bytes: bytes) -> list[dict]:
    results = await _vision.locate(image_bytes)
    return [r.model_dump() for r in results]


def _aggregate_consensus(
    metadata_coords: Optional[dict], telemetry_coords: Optional[dict],
    vision_results: list[dict], extractor_results: list[dict],
) -> dict:
    from ..models import Coordinates, VisionResult
    mc = Coordinates(**metadata_coords) if metadata_coords else None
    tc = Coordinates(**telemetry_coords) if telemetry_coords else None
    vr = [VisionResult(**r) for r in vision_results]
    er = [VisionResult(**r) for r in extractor_results]
    return ConsensusEngine().aggregate(mc, tc, vr, er).model_dump()


async def _brain_analyze(image_bytes: bytes) -> Any:
    """Full ARK Brain 4-tier image-intelligence cascade (metadata → vision →
    fusion → contradictions), followed by a bounded agentic refinement loop.

    The IMAGE workspace routes its upload analysis through the unified engine
    via this tool.  When the deterministic cascade resolves only a low-confidence
    hypothesis (e.g. a metadata-stripped, heavily-compressed share), the engine
    iterates: it enhances the image through the unified dispatcher and
    re-runs the vision ensemble / GeoSpy on the enhanced copy, folding any
    improved estimate back into the consensus.  This is the agentic
    crop→enhance→re-analyze loop, driven entirely through the single
    ``registry`` dispatcher.
    """
    from ..brain.pipeline import BrainPipeline

    cascade = await BrainPipeline().analyze(image_bytes)
    if cascade.source in ("AI_VISION", "EXIF_MISSING_NO_AI_KEY"):
        try:
            cascade = await asyncio.wait_for(
                _refine_image_analysis(cascade, image_bytes),
                timeout=60.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Agentic image refinement timed out after 60s")
        except Exception as exc:
            logger.warning("Agentic image refinement failed: %s", exc)
    return cascade


def _enhance_image(image_bytes: bytes, scale: int = 2) -> bytes:
    """Classical detail-recovery for compressed / re-shared images.

    Upscales with a high-quality Lanczos filter and applies an unsharp mask to
    recover edge detail lost to WhatsApp / Telegram re-encoding.  This is an
    honest, dependency-free enhancement (not ML super-resolution) that improves
    downstream OCR and vision-ensemble performance on degraded shares.
    """
    try:
        from io import BytesIO
        from PIL import Image, ImageFilter

        img = Image.open(BytesIO(image_bytes)).convert("RGB")
        scale = max(1, min(4, int(scale)))
        up = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
        up = up.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))
        out = BytesIO()
        up.save(out, format="JPEG", quality=95)
        return out.getvalue()
    except Exception as exc:
        logger.warning("Image enhancement failed: %s", exc)
        return image_bytes


async def _refine_image_analysis(cascade, image_bytes: bytes):
    """Bounded agentic loop: enhance → re-analyze → fold in improvements."""
    from app.brain.consensus_engine import ConsensusEngine
    from app.models import Coordinates, VisionResult

    cur_conf = cascade.consensus.confidence_score if cascade.consensus else 0.0

    enhanced = await registry.acall("enhance_image", image_bytes=image_bytes)
    if not enhanced:
        return cascade

    results: list[VisionResult] = []
    try:
        results.extend(await _vision.locate(enhanced))
    except Exception as exc:
        logger.debug("Enhanced vision ensemble failed: %s", exc)
    try:
        gs = await _vision.predict_geospy(enhanced)
        if gs is not None:
            results.append(gs)
    except Exception as exc:
        logger.debug("Enhanced GeoSpy failed: %s", exc)

    coord_results = [
        r for r in results
        if getattr(r, "estimated_latitude", None) is not None
        and getattr(r, "confidence_score", None) is not None
    ]
    if not coord_results:
        return cascade

    best = max(coord_results, key=lambda r: r.confidence_score)
    if best.confidence_score > cur_conf + 0.02:
        consensus = ConsensusEngine().aggregate(None, None, coord_results, [])
        cascade.coordinates = Coordinates(
            lat=consensus.estimated_latitude, lon=consensus.estimated_longitude
        )
        cascade.consensus = consensus
        cascade.search_radius_meters = consensus.search_radius_meters
        cascade.status = "SUCCESS"
        cascade.source = "AI_VISION_REFINED"
        cascade.analysis_log.append(
            f"Agentic refinement (enhance + re-analyze) improved confidence "
            f"to {consensus.confidence_score:.2f}"
        )
    return cascade


# --------------------------------------------------------------------------- #
# Phase F handlers — NETWORK + SECOPS domains.
#
# These are deterministic, offline adapters: they normalize/analyze the
# structured inputs the executor resolves from graph state (scope, prior
# tool output). No real network scanning or SIEM calls happen here — a
# production deployment swaps each handler body for the real client. The
# orchestrator, graph, console and guard never change.
# --------------------------------------------------------------------------- #
def _discover_hosts(network_range: str = "", hosts: Optional[list] = None) -> dict:
    """Normalize a scope (CIDR/host) + any supplied host records."""
    try:
        from ipaddress import ip_network
        net = ip_network(network_range or "", strict=False)
        scope = {"cidr": str(net), "netmask": str(net.netmask),
                 "num_addresses": net.num_addresses, "version": net.version}
    except Exception:
        scope = {"cidr": network_range or None, "netmask": None,
                 "num_addresses": None, "version": None}
    records = []
    for h in (hosts or []):
        if isinstance(h, dict) and h.get("host"):
            records.append({
                "host": str(h["host"]),
                "status": str(h.get("status", "unknown")),
                "service": h.get("service"),
            })
    return {"scope": scope, "hosts": records, "total": len(records),
            "complete": True}


def _fingerprint_service(host: str = "", port: int = 0,
                         service: Optional[str] = None) -> dict:
    return {"host": host, "port": int(port), "service": service or "unknown",
            "fingerprint": {"status": "not_enumerated", "banner": None}}


def _port_scan(host: str = "", ports: Optional[list] = None) -> dict:
    valid = sorted({int(p) for p in (ports or []) if 1 <= int(p) <= 65535})
    return {"host": host, "scanned_ports": valid, "count": len(valid),
            "open_ports": [], "complete": True}


def _tls_inspect(host: str = "", port: int = 443,
                 certificates: Optional[list] = None) -> dict:
    certs = [c for c in (certificates or []) if isinstance(c, dict)]
    return {"host": host, "port": int(port), "certificates": certs,
            "certificate_count": len(certs), "valid": None}


def _siem_query(query: str = "", events: Optional[list] = None) -> dict:
    evs = [e for e in (events or []) if isinstance(e, dict)]
    return {"query": query, "events": evs, "count": len(evs), "window": None}


def _threat_hunt(indicator: str = "", telemetry: Optional[list] = None) -> dict:
    tl = [t for t in (telemetry or []) if isinstance(t, dict)]
    return {"indicator": indicator, "telemetry": tl, "matches": 0,
            "ioas": [], "window": None}


def _detect_correlation(events: Optional[list] = None) -> dict:
    evs = [e for e in (events or []) if isinstance(e, dict)]
    return {"events": evs, "patterns": [], "correlations": [], "count": 0}


def _incident_annotate(incident_id: str = "", note: str = "",
                       severity: str = "medium") -> dict:
    return {"incident_id": incident_id, "note": note, "severity": severity,
            "recorded": True}


# --------------------------------------------------------------------------- #
# OSINT / LOCAL-FILESYSTEM domain — sandboxed directory inspection.
# Real I/O is done by :mod:`local_inspector` against a single authorized root
# (~/Documents/ARK_Investigations); the handler is a thin adapter.
# --------------------------------------------------------------------------- #
def _inspect_local_path(target_path: str = "") -> dict:
    from .local_inspector import inspect_path
    return inspect_path(target_path)


# --------------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------------- #
def _catalog() -> list[Tool]:
    return [
        Tool(_spec(
            "compute_custody_hash", "Custody Hash",
            "Compute SHA-256/SHA-1/MD5 custody certificate for an image.",
            domain="image", category=S.ToolCategory.READ, risk=S.RiskLevel.LOW,
            provider="ark_module",
        ), _compute_custody_hash),

        Tool(_spec(
            "validate_format", "Validate Format",
            "Validate file magic bytes (anti-spoofing). Returns detected format.",
            domain="image", category=S.ToolCategory.READ, risk=S.RiskLevel.LOW,
            provider="ark_module",
        ), _validate_format),

        Tool(_spec(
            "extract_exif", "Extract EXIF",
            "Extract GPS, camera, timestamps and tamper flags via Pillow/piexif.",
            domain="image", category=S.ToolCategory.READ, risk=S.RiskLevel.LOW,
            provider="ark_module",
        ), _extract_exif),

        Tool(_spec(
            "extract_deep_metadata", "Deep Metadata",
            "Run ExifTool for a grouped metadata tree (EXIF/XMP/IPTC/MakerNotes).",
            domain="image", category=S.ToolCategory.READ, risk=S.RiskLevel.LOW,
            provider="exiftool",
            availability=(S.Availability.AVAILABLE if exiftool_service.available
                          else S.Availability.REQUIRES_KEY),
        ), _extract_deep_metadata),

        Tool(_spec(
            "reverse_geocode", "Reverse Geocode",
            "Reverse-geocode lat/lon to an address (country/state/city/road). "
            "Prefers Mapbox Geocoding when a token is set, else OSM Nominatim.",
            domain="image", category=S.ToolCategory.READ, risk=S.RiskLevel.LOW,
            provider="mapbox",
            permissions=[S.Permission.QUERY_EXTERNAL],
        ), _reverse_geocode),

        Tool(_spec(
            "fetch_streetview_panorama", "Street View Panorama",
            "Fetch a Google Street View panorama + static image for coordinates.",
            domain="image", category=S.ToolCategory.READ, risk=S.RiskLevel.LOW,
            provider="google_streetview",
            permissions=[S.Permission.QUERY_EXTERNAL],
            availability=S.Availability.REQUIRES_KEY,
            cost=S.CostEstimate(api_calls=1, est_ms=2000),
        ), _fetch_streetview_panorama),

        Tool(_spec(
            "predict_geospy_coordinates", "GeoSpy Coordinates",
            "Predict geolocation coordinates from visual content via GeoSpy.",
            domain="image", category=S.ToolCategory.ANALYSIS,
            risk=S.RiskLevel.ELEVATED, provider="geospy",
            deterministic=False,
            availability=S.Availability.REQUIRES_KEY,
            permissions=[S.Permission.CALL_PROVIDER],
            cost=S.CostEstimate(model_tokens=400, api_calls=1, est_ms=3000),
        ), _predict_geospy_coordinates),

        Tool(_spec(
            "analyze_vision_scene", "Vision Scene Analysis",
            "Scene reasoning + OCR text extraction via a vision-capable LLM.",
            domain="image", category=S.ToolCategory.ANALYSIS,
            risk=S.RiskLevel.ELEVATED, provider="vision_llm",
            deterministic=False,
            availability=S.Availability.REQUIRES_KEY,
            permissions=[S.Permission.CALL_PROVIDER],
            cost=S.CostEstimate(model_tokens=1500, api_calls=2, est_ms=6000),
        ), _analyze_vision_scene),

        Tool(_spec(
            "resolve_telemetry", "Resolve Telemetry",
            "Resolve location from last-known GPS / cell tower / Wi-Fi BSSIDs.",
            domain="image", category=S.ToolCategory.READ, risk=S.RiskLevel.LOW,
            provider="ark_module",
        ), _resolve_telemetry),

        Tool(_spec(
            "analyze_ela", "Error Level Analysis",
            "Generate an ELA heatmap revealing edited/spliced regions.",
            domain="image", category=S.ToolCategory.ANALYSIS, risk=S.RiskLevel.LOW,
            provider="ark_module",
        ), _analyze_ela),

        Tool(_spec(
            "detect_eof_anomaly", "EOF Anomaly Detection",
            "Detect trailing bytes after the legitimate EOF marker (stego/smuggling).",
            domain="image", category=S.ToolCategory.ANALYSIS, risk=S.RiskLevel.LOW,
            provider="ark_module",
        ), _detect_eof_anomaly),

        Tool(_spec(
            "verify_c2pa", "Verify C2PA",
            "Inspect Content Credentials (C2PA) provenance manifest and signature.",
            domain="image", category=S.ToolCategory.ANALYSIS, risk=S.RiskLevel.LOW,
            provider="ark_module",
        ), _verify_c2pa),

        Tool(_spec(
            "run_consistency", "Consistency Analysis",
            "Cross-reference metadata fields for timeline/software/thumbnail anomalies.",
            domain="image", category=S.ToolCategory.ANALYSIS, risk=S.RiskLevel.LOW,
            provider="ark_module",
        ), _run_consistency),

        Tool(_spec(
            "run_ocr", "OCR & Infrastructure",
            "Extract text/infrastructure indicators (signs, plates) via vision LLM.",
            domain="image", category=S.ToolCategory.ANALYSIS,
            risk=S.RiskLevel.ELEVATED, provider="vision_llm",
            deterministic=False,
            availability=S.Availability.REQUIRES_KEY,
            permissions=[S.Permission.CALL_PROVIDER],
            cost=S.CostEstimate(model_tokens=800, api_calls=1, est_ms=4000),
        ), _run_ocr),

        Tool(_spec(
            "fuse_geolocation", "Geolocation Fusion",
            "Fuse multi-layer evidence into a defensible location hypothesis.",
            domain="image", category=S.ToolCategory.ANALYSIS,
            risk=S.RiskLevel.MEDIUM, provider="ark_module",
        ), _fuse_geolocation),

        Tool(_spec(
            "discover_sources", "Source Discovery",
            "Compute perceptual hash, extract embedded URLs, query reverse-search.",
            domain="image", category=S.ToolCategory.ANALYSIS,
            risk=S.RiskLevel.ELEVATED, provider="reverse_search",
            permissions=[S.Permission.QUERY_EXTERNAL],
            availability=S.Availability.REQUIRES_KEY,
            cost=S.CostEstimate(api_calls=1, est_ms=3000),
        ), _discover_sources),

        Tool(_spec(
            "search_reverse_source", "Reverse Source Search",
            "Reverse-source discovery via TinEye/Serper: phash + web image matches.",
            domain="image", category=S.ToolCategory.ANALYSIS,
            risk=S.RiskLevel.ELEVATED, provider="reverse_search",
            permissions=[S.Permission.QUERY_EXTERNAL],
            availability=S.Availability.REQUIRES_KEY,
            cost=S.CostEstimate(api_calls=2, est_ms=6000),
        ), _search_reverse_source),

        Tool(_spec(
            "detect_contradictions", "Contradiction Detection",
            "Cross-reference all evidence layers for structured contradictions.",
            domain="image", category=S.ToolCategory.ANALYSIS, risk=S.RiskLevel.LOW,
            provider="ark_module",
        ), _detect_contradictions),

        Tool(_spec(
            "run_vision_ensemble", "Vision Ensemble",
            "Query configured vision providers (GeoSpy/GeoInfer/LLM) for location.",
            domain="image", category=S.ToolCategory.ANALYSIS,
            risk=S.RiskLevel.ELEVATED, provider="vision_ensemble",
            deterministic=False,
            availability=S.Availability.REQUIRES_KEY,
            permissions=[S.Permission.CALL_PROVIDER],
            cost=S.CostEstimate(model_tokens=1200, api_calls=2, est_ms=6000),
        ), _run_vision_ensemble),

        Tool(_spec(
            "aggregate_consensus", "Aggregate Consensus",
            "Bayesian-flavoured aggregation of location estimates into a pin.",
            domain="image", category=S.ToolCategory.ANALYSIS,
            risk=S.RiskLevel.MEDIUM, provider="ark_module",
        ), _aggregate_consensus),

        Tool(_spec(
            "brain_analyze", "Image Intelligence Analysis",
            "Full forensic image analysis: metadata, provenance, geolocation, "
            "vision, source discovery and contradictions (4-tier Brain cascade).",
            domain="image", category=S.ToolCategory.ANALYSIS,
            risk=S.RiskLevel.LOW, provider="ark_module",
        ), _brain_analyze),

        Tool(_spec(
            "enhance_image", "Enhance / Decompress Image",
            "Recover detail from a compressed or re-shared image (Lanczos upscale "
            "+ unsharp mask) to improve downstream OCR and vision analysis.",
            domain="image", category=S.ToolCategory.ANALYSIS,
            risk=S.RiskLevel.LOW, provider="ark_module",
            deterministic=True,
            input_schema={
                "type": "object",
                "properties": {
                    "image_bytes": {"type": "string", "description": "Base64 image."},
                    "scale": {"type": "integer", "default": 2, "minimum": 1, "maximum": 4},
                },
                "required": ["image_bytes"],
            },
        ), _enhance_image),

        # ---- Phase F — NETWORK domain ------------------------------------- #
        Tool(_spec(
            "discover_hosts", "Discover Hosts",
            "Enumerate hosts/services within the authorized network scope.",
            domain="network", category=S.ToolCategory.READ, risk=S.RiskLevel.LOW,
            provider="ark_module",
            input_schema={
                "type": "object",
                "properties": {
                    "network_range": {
                        "type": "string",
                        "description": "CIDR range or hostname to enumerate (e.g. '192.168.1.0/24' or 'example.com').",
                    },
                    "hosts": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Optional pre-discovered host records to normalize.",
                    },
                },
                "required": ["network_range"],
            },
        ), _discover_hosts),

        Tool(_spec(
            "fingerprint_service", "Fingerprint Service",
            "Identify a service and its version on a discovered host/port.",
            domain="network", category=S.ToolCategory.READ,
            risk=S.RiskLevel.ELEVATED, provider="ark_module",
            input_schema={
                "type": "object",
                "properties": {
                    "host": {
                        "type": "string",
                        "description": "IP or hostname to fingerprint.",
                    },
                    "port": {
                        "type": "integer",
                        "description": "Port number to fingerprint.",
                    },
                    "service": {
                        "type": "string",
                        "description": "Optional known service hint.",
                    },
                },
                "required": ["host", "port"],
            },
        ), _fingerprint_service),

        Tool(_spec(
            "port_scan", "Port Scan",
            "Probe exposed ports on a host (high risk — step confirmation).",
            domain="network", category=S.ToolCategory.HIGH_RISK,
            risk=S.RiskLevel.HIGH, provider="ark_module",
            input_schema={
                "type": "object",
                "properties": {
                    "host": {
                        "type": "string",
                        "description": "Target IP or hostname.",
                    },
                    "ports": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Specific ports to scan (e.g. [80, 443, 8080]).",
                    },
                },
                "required": ["host"],
            },
        ), _port_scan),

        Tool(_spec(
            "tls_inspect", "TLS Inspect",
            "Inspect TLS certificate state on an exposed service.",
            domain="network", category=S.ToolCategory.READ,
            risk=S.RiskLevel.ELEVATED, provider="ark_module",
            input_schema={
                "type": "object",
                "properties": {
                    "host": {
                        "type": "string",
                        "description": "Target IP or hostname.",
                    },
                    "port": {
                        "type": "integer",
                        "description": "TLS port (default 443).",
                    },
                    "certificates": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Optional pre-fetched certificate data.",
                    },
                },
                "required": ["host"],
            },
        ), _tls_inspect),

        # ---- Phase F — SECOPS domain -------------------------------------- #
        Tool(_spec(
            "siem_query", "SIEM Query",
            "Query the security-event timeline for the case window.",
            domain="secops", category=S.ToolCategory.READ, risk=S.RiskLevel.LOW,
            provider="ark_module",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "SIEM query string (e.g. 'src_ip=10.0.0.1 AND action=failed').",
                    },
                    "events": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Optional pre-loaded event records to query.",
                    },
                },
                "required": ["query"],
            },
        ), _siem_query),

        Tool(_spec(
            "threat_hunt", "Threat Hunt",
            "Search telemetry for indicators of compromise.",
            domain="secops", category=S.ToolCategory.READ,
            risk=S.RiskLevel.ELEVATED, provider="ark_module",
            input_schema={
                "type": "object",
                "properties": {
                    "indicator": {
                        "type": "string",
                        "description": "IOC to hunt (IP, domain, hash, filename, regex).",
                    },
                    "telemetry": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Optional telemetry records to search.",
                    },
                },
                "required": ["indicator"],
            },
        ), _threat_hunt),

        Tool(_spec(
            "detect_correlation", "Detect Correlation",
            "Correlate security events into detection patterns.",
            domain="secops", category=S.ToolCategory.ANALYSIS,
            risk=S.RiskLevel.MEDIUM, provider="ark_module",
            input_schema={
                "type": "object",
                "properties": {
                    "events": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Security events to correlate.",
                    },
                },
            },
        ), _detect_correlation),

        Tool(_spec(
            "incident_annotate", "Incident Annotate",
            "Annotate the case incident record (action — step confirmation).",
            domain="secops", category=S.ToolCategory.ACTION,
            risk=S.RiskLevel.MEDIUM, provider="ark_module",
            input_schema={
                "type": "object",
                "properties": {
                    "incident_id": {
                        "type": "string",
                        "description": "Incident identifier to annotate.",
                    },
                    "note": {
                        "type": "string",
                        "description": "Analyst note to attach.",
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                        "description": "Severity level.",
                    },
                },
                "required": ["incident_id", "note"],
            },
        ), _incident_annotate),

        # ---- OSINT / LOCAL-FILESYSTEM domain ----------------------------- #
        Tool(_spec(
            "inspect_local_path", "Local Path Inspector",
            "Inspect a sandboxed local directory under "
            "~/Documents/ARK_Investigations. Auto-creates the path, then "
            "builds a recursive index: MIME type, size, SHA-256, Shannon "
            "entropy (high-entropy = packed/encrypted/embedded payload) and "
            "image EXIF capture date/camera/GPS.",
            domain="osint", category=S.ToolCategory.READ, risk=S.RiskLevel.LOW,
            provider="ark_module",
            permissions=[S.Permission.READ_EVIDENCE],
            input_schema={
                "target_path": {
                    "type": "string",
                    "description": "Relative path under the sandbox root "
                                   "(e.g. case-001 or evidence-drop). "
                                   "~/… and absolute paths are also accepted "
                                   "when inside the sandbox.",
                },
            },
        ), _inspect_local_path),

        Tool(_spec(
            "web_search", "Web Search",
            "Headless web search via Tavily when keyed, else the keyless "
            "DuckDuckGo HTML page. Iterative loop: web_search → web_fetch → "
            "parse HTML → verified location. Never fabricates results.",
            domain="osint", category=S.ToolCategory.READ, risk=S.RiskLevel.LOW,
            provider="tavily",
            permissions=[S.Permission.QUERY_EXTERNAL],
            cost=S.CostEstimate(api_calls=1, est_ms=1500),
            input_schema={
                "query": {
                    "type": "string",
                    "description": "Search query text.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max results (1-10, default 5).",
                },
                "search_depth": {
                    "type": "string",
                    "description": "Tavily depth: basic | advanced.",
                },
            },
        ), web_search),

        Tool(_spec(
            "web_fetch", "Web Fetch",
            "Fetch a public HTTP(S) page and return its title + trimmed "
            "visible text for verification/parse-HTML steps.",
            domain="osint", category=S.ToolCategory.READ, risk=S.RiskLevel.LOW,
            provider="web",
            permissions=[S.Permission.QUERY_EXTERNAL],
            cost=S.CostEstimate(api_calls=1, est_ms=1500),
            input_schema={
                "url": {
                    "type": "string",
                    "description": "Absolute http(s) URL to fetch.",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Max chars of visible text to return (default 8000).",
                },
            },
        ), web_fetch),

        Tool(_spec(
            "geocode_place", "Geocode Place",
            "Forward-geocode a place-name/OCR string to candidate coordinates "
            "(Google Geocoding when keyed, else keyless OSM Nominatim).",
            domain="osint", category=S.ToolCategory.READ, risk=S.RiskLevel.LOW,
            provider="google_maps",
            permissions=[S.Permission.QUERY_EXTERNAL],
            cost=S.CostEstimate(api_calls=1, est_ms=1500),
            input_schema={
                "place": {
                    "type": "string",
                    "description": "Place name / OCR-derived location string.",
                },
            },
        ), geocode_place),

        Tool(_spec(
            "geocode_batch_texts", "Geocode Batch Texts",
            "Geocode many OCR strings concurrently; unmatched queries dropped.",
            domain="osint", category=S.ToolCategory.READ, risk=S.RiskLevel.LOW,
            provider="google_maps",
            permissions=[S.Permission.QUERY_EXTERNAL],
            cost=S.CostEstimate(api_calls=1, est_ms=2000),
            input_schema={
                "places": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of place-name / OCR strings to geocode.",
                },
            },
        ), geocode_batch_texts),

        Tool(_spec(
            "reverse_image_search", "Reverse Image Search",
            "Reverse-image search an image asset via configured providers "
            "(TinEye upload; Serper image search by URL or keyword).",
            domain="osint", category=S.ToolCategory.ANALYSIS,
            risk=S.RiskLevel.ELEVATED, provider="reverse_search",
            permissions=[S.Permission.QUERY_EXTERNAL],
            availability=S.Availability.REQUIRES_KEY,
            cost=S.CostEstimate(api_calls=2, est_ms=6000),
            input_schema={
                "search_query": {
                    "type": "string",
                    "description": "Optional keyword search (Serper).",
                },
                "image_url": {
                    "type": "string",
                    "description": "Optional reachable image URL (Serper reverse-image).",
                },
            },
        ), reverse_image_search),

        # ---- Level-4 — PENTEST domain (authorized engagements only). -------- #
        # Active capabilities require EXEC_SHELL, granted only to the RE-ACT
        # chain guard and explicit admin grants — the standard investigator
        # surface keeps them denied (skipped honestly) by default.
        Tool(_spec(
            "nmap_scan", "Nmap Scan",
            "Active network scan (nmap) of an authorized host/CIDR: open ports, "
            "service/version detection. EXEC_SHELL grant required.",
            domain="pentest", category=S.ToolCategory.READ,
            risk=S.RiskLevel.ELEVATED, provider="nmap",
            permissions=[S.Permission.READ_EVIDENCE, S.Permission.EXEC_SHELL],
            cost=S.CostEstimate(est_ms=30000),
            input_schema={
                "host": {"type": "string",
                         "description": "IP / hostname / CIDR (authorized scope)."},
                "ports": {"type": "string",
                          "description": "Optional port list, e.g. '22,80,443'."},
                "scan_type": {"type": "string",
                              "description": "tcp_connect | syn | udp."},
                "dry_run": {"type": "boolean",
                            "description": "Simulate without sending traffic."},
            },
        ), nmap_scan),

        Tool(_spec(
            "default_cred_tester", "Default Credential Tester",
            "Test a small fixed set of factory-default credentials against an "
            "authorized web target (Basic auth or login form). Refuses to run "
            "without authorized=True.",
            domain="pentest", category=S.ToolCategory.HIGH_RISK,
            risk=S.RiskLevel.HIGH, provider="ark_module",
            permissions=[S.Permission.QUERY_EXTERNAL],
            cost=S.CostEstimate(api_calls=12, est_ms=20000),
            input_schema={
                "target_url": {"type": "string",
                               "description": "Authorized http(s) target URL."},
                "profile": {"type": "string",
                            "description": "generic | web | router | cctv | iot."},
                "authorized": {"type": "boolean",
                               "description": "MUST be true for any request."},
            },
        ), test_default_creds),

        Tool(_spec(
            "scan_webshells", "Webshell Detection",
            "Scan an owned web root for known webshell signatures and risky "
            "eval/exec patterns (defensive DFIR counterpart to shell implants).",
            domain="pentest", category=S.ToolCategory.ANALYSIS,
            risk=S.RiskLevel.ELEVATED, provider="ark_module",
            permissions=[S.Permission.READ_EVIDENCE],
            cost=S.CostEstimate(est_ms=10000),
            input_schema={
                "target_path": {"type": "string",
                                "description": "Absolute web-root path to scan."},
            },
        ), scan_webshells),

        Tool(_spec(
            "crack_hash", "Hash Cracker",
            "Offline hash-format recovery (hashcat/john) of a single hash "
            "against an explicit wordlist. No remote target. EXEC_SHELL grant "
            "required.",
            domain="pentest", category=S.ToolCategory.ANALYSIS,
            risk=S.RiskLevel.ELEVATED, provider="hashcat",
            permissions=[S.Permission.READ_EVIDENCE, S.Permission.EXEC_SHELL],
            cost=S.CostEstimate(est_ms=30000),
            input_schema={
                "hash_value": {"type": "string",
                               "description": "Offline hash to recover."},
                "wordlist": {"type": "string",
                             "description": "Path to a wordlist file."},
                "hash_type": {"type": "string",
                              "description": "auto | md5 | sha1 | sha256 | sha512 | bcrypt | ..."},
            },
        ), crack_hash),

        Tool(_spec(
            "analyze_privilege_escalation", "Priv-Esc Analyzer",
            "Local host enumeration on an authorized box: sudo policy, SUID, "
            "world-writable files, CTF flag files. EXEC_SHELL grant required.",
            domain="pentest", category=S.ToolCategory.HIGH_RISK,
            risk=S.RiskLevel.HIGH, provider="ark_module",
            permissions=[S.Permission.READ_EVIDENCE, S.Permission.EXEC_SHELL],
            cost=S.CostEstimate(est_ms=30000),
            input_schema={
                "target_root": {"type": "string",
                                "description": "Filesystem root for the search (default /)."},
                "dry_run": {"type": "boolean",
                            "description": "Simulate without executing commands."},
            },
        ), analyze_privilege_escalation),

        # ---- Level-4 — ROS / OT forensics domain. -------------------------- #
        Tool(_spec(
            "inspect_ros", "ROS Inspector",
            "Introspect a live ROS 1 / ROS 2 node graph, topics and parameter "
            "surface; optionally parse a safety_config.yaml alongside.",
            domain="ros", category=S.ToolCategory.READ,
            risk=S.RiskLevel.MEDIUM, provider="ros",
            permissions=[S.Permission.READ_EVIDENCE, S.Permission.EXEC_SHELL],
            cost=S.CostEstimate(est_ms=10000),
            input_schema={
                "ros2": {"type": "boolean",
                         "description": "Introspect a ROS 2 system (default ROS 1)."},
                "safety_config_path": {"type": "string",
                                       "description": "Optional safety_config.yaml."},
            },
        ), inspect_ros),

        Tool(_spec(
            "analyze_safety_config", "Safety Audit",
            "Static safety-config drift & tamper analysis (velocity limits, "
            "protective-stop / E-stop state, joint limits) vs a reference "
            "baseline. Pure static parsing — no live system contact.",
            domain="ros", category=S.ToolCategory.ANALYSIS,
            risk=S.RiskLevel.LOW, provider="ark_module",
            permissions=[S.Permission.READ_EVIDENCE],
            cost=S.CostEstimate(est_ms=2000),
            input_schema={
                "config_path": {"type": "string",
                                "description": "Observed safety_config.yaml path."},
                "reference_path": {"type": "string",
                                   "description": "Authoritative baseline YAML."},
            },
        ), analyze_safety_config),
    ]


class ToolRegistry:
    """Lookup table of registered tools."""
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {t.tool_id: t for t in _catalog()}

    def get(self, tool_id: str) -> Optional[Tool]:
        return self._tools.get(tool_id)

    def list(self, domain: Optional[str] = None) -> list[Tool]:
        if domain:
            return [t for t in self._tools.values() if t.spec.domain == domain]
        return list(self._tools.values())

    def specs(self, domain: Optional[str] = None) -> list[S.ToolSpec]:
        return [t.spec for t in self.list(domain)]

    def call(self, tool_id: str, **kwargs) -> Any:
        """Invoke a sync tool by id. Async tools must be awaited via `acall`."""
        tool = self.get(tool_id)
        if not tool:
            raise KeyError(f"Tool not registered: {tool_id}")
        if tool.is_async():
            raise TypeError(
                f"{tool_id} is async — await registry.acall(...) instead"
            )
        return tool.handler(**kwargs)

    async def acall(self, tool_id: str, **kwargs) -> Any:
        """Invoke a tool by id, awaiting if async."""
        tool = self.get(tool_id)
        if not tool:
            raise KeyError(f"Tool not registered: {tool_id}")
        if tool.is_async():
            return await tool.handler(**kwargs)
        return tool.handler(**kwargs)


registry = ToolRegistry()
