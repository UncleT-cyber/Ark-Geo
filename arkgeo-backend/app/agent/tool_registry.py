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

import inspect
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
from ..brain.vision_ensemble import VisionEnsemble
from ..core.security import custody_certificate, validate_magic_bytes
from ..services.c2pa_service import c2pa_service
from ..services.exiftool_service import exiftool_service
from ..services.source_discovery import source_discovery
from ..services.telemetry_service import TelemetryService
from . import schemas as S

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
) -> S.ToolSpec:
    return S.ToolSpec(
        tool_id=tool_id, name=name, description=description,
        domain=domain, category=category, risk=risk, provider=provider,
        permissions=permissions or [S.Permission.READ_EVIDENCE],
        deterministic=deterministic, availability=availability,
        cost_estimate=cost,
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
    addr = reverse_geocode(lat, lon)
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
            "Reverse-geocode lat/lon to an address (country/state/city/road).",
            domain="image", category=S.ToolCategory.READ, risk=S.RiskLevel.LOW,
            provider="nominatim",
            permissions=[S.Permission.QUERY_EXTERNAL],
        ), _reverse_geocode),

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
