"""Brain orchestrator – runs the full failover-cascade pipeline on an image.

This is the single entry point the API endpoints call.  It follows a strict
deterministic-first cascade:

  Tier 1  Cryptographic hash + EXIF metadata extraction
  Tier 2  Reverse geocode (if GPS found) → direct pin
  Tier 3  Cell / Wi-Fi telemetry fallback
  Tier 4  AI vision ensemble (only if API keys are configured)
  Tier 5  Graceful low-context degradation
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from app.brain.clue_extractors.architectural import ArchitecturalExtractor
from app.brain.clue_extractors.botanical import BotanicalExtractor
from app.brain.clue_extractors.indoor import IndoorExtractor
from app.brain.clue_extractors.infrastructure import InfrastructureExtractor
from app.brain.clue_extractors.ocr_text import OcrTextExtractor
from app.brain.consensus_engine import ConsensusEngine
from app.brain.metadata_extractor import MetadataExtractor, reverse_geocode
from app.brain.vision_ensemble import VisionEnsemble
from app.brain.consistency_engine import consistency_engine
from app.brain.contradiction_engine import contradiction_engine
from app.brain.geolocation_fusion import geolocation_fusion
from app.core.security import custody_certificate, custody_hash
from app.models import (
    AddressInfo,
    ConsensusResult,
    Coordinates,
    CustodyCertificate,
    DeviceTelemetry,
)
from app.services.c2pa_service import c2pa_service
from app.services.exiftool_service import exiftool_service
from app.services.source_discovery import source_discovery
from app.services.state_cache import state_cache
from app.services.telemetry_service import TelemetryService

logger = logging.getLogger(__name__)

import re as _re  # noqa: E402

_STREET_SUFFIX_RE = _re.compile(
    r"\b(?:street|st|road|rd|avenue|ave|lane|ln|drive|dr|boulevard|blvd|"
    r"highway|hwy|way|court|ct|crescent|cres|square|plaza|pl)\b",
    _re.IGNORECASE,
)


def _is_location_like(text: str) -> bool:
    """True when an OCR string is a plausible geocodable location token.

    Matches street/road-suffixed names (e.g. "Victoria Island Road") and
    proper-case place names ("Lagos", "Mumbai"), while rejecting noise like
    phone numbers, URLs and single-character labels.
    """
    if len(text) < 3:
        return False
    if _STREET_SUFFIX_RE.search(text):
        return True
    words = [w for w in text.split() if w]
    if not (1 <= len(words) <= 4 and all(w[:1].isupper() for w in words)):
        return False
    if any(ch.isdigit() for ch in text):
        return False
    return True


class CascadeResult:
    """Enriched result from the cascade — carries everything the API needs."""

    def __init__(self) -> None:
        self.status: str = "SUCCESS"
        self.source: str = "NATIVE_EXIF_HARDWARE"
        self.custody_certificate: Optional[dict] = None
        self.custody_hash: str = ""
        self.image_sha256: str = ""
        self.consensus: Optional[ConsensusResult] = None
        self.coordinates: Optional[Coordinates] = None
        self.address: Optional[AddressInfo] = None
        self.camera: dict = {}
        self.altitude: Optional[float] = None
        self.datetime_original: Optional[str] = None
        self.exif_raw: dict = {}
        self.telemetry_resolve: Optional[Coordinates] = None
        self.message: Optional[str] = None
        self.steganography_detected: bool = False
        self.trailing_bytes_count: int = 0
        self.exif_missing: bool = False
        self.file_format: Optional[str] = None
        self.ela_heatmap: Optional[str] = None
        # IMINT — 4-pillar unified Image Data Extraction payload
        self.image_intelligence: Optional[dict] = None
        self.gps_spoofing_detected: bool = False
        self.anomaly_score: float = 0.0
        self.sanity_mismatches: list = []
        self.gps_climate_zone: Optional[str] = None
        self.visual_climate_zone: Optional[str] = None
        # Workbench forensic extensions
        self.deep_metadata: Optional[dict] = None
        self.consistency_findings: list = []
        self.provenance: Optional[dict] = None
        self.geolocation_fusion: Optional[dict] = None
        self.source_discovery: Optional[dict] = None
        self.contradictions: list = []
        self.evidence_summary: Optional[dict] = None
        self.analysis_log: list[str] = []
        # Universal Image Intelligence suite (Phase F)
        self.streetview: Optional[dict] = None
        self.ai_evidence: Optional[dict] = None
        self.evidence_graph: Optional[dict] = None
        self.search_radius_meters: Optional[float] = None
        # Image Intelligence integration layer
        self.observations: list = []
        self.image_classification: Optional[str] = None
        # Stripped-metadata fallback routing (Feature 1)
        self.metadata_status: Optional[str] = None
        # OCR → geocoding candidates (Feature 2)
        self.geo_candidates: list = []
        # Terrain IMINT — ranked candidate regions (Feature 4)
        self.candidate_regions: list = []
        # Step 1 — Original rehydration (GPS recovered from stripped share)
        self.recovered_original: Optional[dict] = None
        # Step 3 — Monte-Carlo / satellite cross-reference surfaced on result
        self.probability_surface: Optional[dict] = None
        self.credible_interval_radius: Optional[float] = None
        self.satellite_crossref: Optional[dict] = None
        # AI Intelligence Layer — structured assessment from the global model
        self.ai_intelligence: Optional[dict] = None


class BrainPipeline:
    """Orchestrates the multi-tier geolocation pipeline."""

    def __init__(self) -> None:
        self.metadata = MetadataExtractor()
        self.vision = VisionEnsemble()
        self.consensus = ConsensusEngine()
        self.telemetry = TelemetryService()
        self.extractors = [
            ArchitecturalExtractor(),
            BotanicalExtractor(),
            OcrTextExtractor(),
            InfrastructureExtractor(),
        ]
        self.indoor_extractor = IndoorExtractor()

    @property
    def ai_keys_configured(self) -> bool:
        """True if any AI/vision path is available.

        Counts a cloud AI key (dynamic settings store), a local Ollama
        runtime (via the unified AI gateway), and the dedicated geo-vision
        providers (GeoSpy / GeoInfer) which resolve independently.
        """
        from app.brain.clue_extractors.base import llm_client
        from app.services.settings_store import settings_store
        return bool(
            settings_store.get_key("geospy_api_key")
            or settings_store.get_key("geoinfer_api_key")
            or settings_store.get_key("llm_api_key")
            or llm_client.is_configured()
        )

    @staticmethod
    def _no_vision_message() -> str:
        """Honest degradation message describing why vision produced nothing."""
        from app.services.ai_gateway import ai_gateway
        base = "EXIF metadata missing or stripped. "
        if ai_gateway.has_vision_llm():
            return (
                base + "An AI provider is reachable, but no vision-capable model "
                "returned usable coordinates for this image."
            )
        if ai_gateway.is_configured():
            return (
                base + "AI provider reachable, but no vision-capable model is "
                "installed on the server. Install one (e.g. `ollama pull llava` "
                "or `ollama pull llama3.2-vision`) to enable local image analysis."
            )
        return (
            base + "No AI provider is configured on the server: add a cloud "
            "vision key in the Admin Console or start the local Ollama runtime."
        )

    async def analyze(
        self,
        image_bytes: bytes,
        device_telemetry: Optional[DeviceTelemetry] = None,
        user_id: Optional[str] = None,
        run_indoor: bool = True,
        request_id: Optional[str] = None,
    ) -> CascadeResult:
        """Run the full failover cascade.  Returns a :class:`CascadeResult`."""
        result = CascadeResult()

        # ---- Tier 1: Cryptographic hashes (always runs) ----------------
        result.custody_certificate = custody_certificate(image_bytes)
        result.custody_hash = custody_hash(
            image_bytes, {"request_id": request_id} if request_id else {}
        )
        result.image_sha256 = result.custody_certificate["sha256"]

        # ---- Tier 1b: EXIF metadata extraction -------------------------
        meta = self.metadata.extract(image_bytes)
        result.exif_raw = meta.get("raw", {})
        result.camera = meta.get("camera", {})
        result.altitude = meta.get("altitude")
        result.datetime_original = meta.get("datetime_original")
        metadata_coords = meta.get("gps")

        # ELA heatmap + steganography + exif_missing flags
        result.ela_heatmap = meta.get("ela_heatmap")
        stego = meta.get("steganography", {})
        result.steganography_detected = stego.get("steganography_detected", False)
        result.trailing_bytes_count = stego.get("trailing_bytes_count", 0)
        result.exif_missing = meta.get("exif_missing", False)
        result.file_format = meta.get("file_format")
        result.image_intelligence = meta.get("image_intelligence")

        # Stripped-metadata fallback routing (Feature 1): an image that is
        # fully stripped (no EXIF at all) OR partially stripped (EXIF block
        # survived but GPS removed by an intermediary) is routed to the
        # secondary visual fallback pipeline and flagged explicitly.
        result.metadata_status = (
            "STRIPPED_BY_INTERMEDIARY"
            if result.exif_missing or metadata_coords is None
            else "EXIF_PRESENT"
        )

        # ---- Tier 2: Direct GPS pin + reverse geocode ------------------
        if metadata_coords:
            result.coordinates = metadata_coords
            result.address = reverse_geocode(metadata_coords.lat, metadata_coords.lon)
            await self._maybe_fetch_streetview(
                result, metadata_coords.lat, metadata_coords.lon
            )
            consensus = self.consensus.aggregate(
                metadata_coords, None, [], []
            )
            result.consensus = consensus
            result.source = "NATIVE_EXIF_HARDWARE"
            result.status = "SUCCESS"
            # Enrich consensus with country from reverse geocode
            if result.address and result.address.country:
                consensus.primary_country = result.address.country
                consensus.region = result.address.state or consensus.region
            await self._run_deep_analysis(result, image_bytes, [])
            return result

        # ---- Tier 3: Cell / Wi-Fi telemetry ----------------------------
        telemetry_coords: Optional[Coordinates] = None
        if device_telemetry:
            last_known = device_telemetry.last_known_outdoor_gps
            if not last_known and user_id:
                cached = state_cache.get_outdoor_gps(user_id)
                if cached:
                    from app.models import GpsFix
                    import time as _time
                    last_known = GpsFix(
                        lat=cached.lat, lon=cached.lon, timestamp=int(_time.time())
                    )
            telemetry_coords = self.telemetry.resolve(
                last_known_gps=last_known if last_known else None,
                cell_tower=device_telemetry.connected_cell_tower,
                wifi_bssids=device_telemetry.nearby_wifi_bssids,
            )
            if telemetry_coords and user_id:
                from app.models import GpsFix
                import time as _time
                state_cache.set_outdoor_gps(
                    user_id,
                    GpsFix(lat=telemetry_coords.lat, lon=telemetry_coords.lon,
                           timestamp=int(_time.time())),
                )
            result.telemetry_resolve = telemetry_coords

        if telemetry_coords:
            result.coordinates = telemetry_coords
            result.address = reverse_geocode(
                telemetry_coords.lat, telemetry_coords.lon
            )
            consensus = self.consensus.aggregate(
                None, telemetry_coords, [], []
            )
            result.consensus = consensus
            result.source = "TELEMETRY"
            result.status = "SUCCESS"
            if result.address and result.address.country:
                consensus.primary_country = result.address.country
            await self._run_deep_analysis(result, image_bytes, [])
            return result

        # ---- Tier 4: AI vision ensemble (only if keys configured) -----
        vision_results = await self.vision.locate(image_bytes)

        # Terrain IMINT — ranked candidate regions from vision-LLM reasoning.
        seen_regions: set[str] = set()
        for vr in vision_results:
            for r in (vr.candidate_regions or []):
                region = (r.get("region") or "").strip()
                if region and region.lower() not in seen_regions:
                    seen_regions.add(region.lower())
                    result.candidate_regions.append(r)
        result.candidate_regions.sort(
            key=lambda r: float(r.get("confidence", 0.0)), reverse=True,
        )

        extractor_results = []
        # Run clue extractors concurrently with a per-extractor timeout.
        # Each extractor calls the LLM (ai_gateway) — wrapping in to_thread
        # with a hard cap prevents any single slow model from stalling the
        # entire cascade.  Extractors that fail or timeout degrade to None.
        _ext_timeout = 30.0
        _ext_tasks = [
            asyncio.wait_for(
                asyncio.to_thread(ext.extract, image_bytes),
                timeout=_ext_timeout,
            )
            for ext in self.extractors
        ]
        if run_indoor:
            _ext_tasks.append(
                asyncio.wait_for(
                    asyncio.to_thread(self.indoor_extractor.extract, image_bytes),
                    timeout=_ext_timeout,
                )
            )
        _ext_results = await asyncio.gather(*_ext_tasks, return_exceptions=True)
        for r in _ext_results:
            if isinstance(r, Exception):
                logger.warning("Clue extractor failed/timed out: %s", r)
            elif r is not None:
                extractor_results.append(r)

        # OCR → geocoding candidates (Feature 2): geocode street/place text
        # extracted from the image so the spatial canvas can plot candidate pins.
        result.geo_candidates = await self._geocode_ocr_candidates(extractor_results)

        # ---- Tier 4b: Universal Image Intelligence suite (parallel) ----
        # Discrete providers for the stripped-metadata path: GeoSpy prediction,
        # vision scene analysis, and reverse source search (TinEye/Serper).
        # Each tool is honest-by-design — None / UNAVAILABLE when unkeyed.
        # Hard timeout prevents any slow provider from stalling the cascade.
        from ..agent.tool_registry import registry as _tool_registry
        _tier4b_timeout = 45.0
        ai_results = await asyncio.gather(
            asyncio.wait_for(
                _tool_registry.acall(
                    "predict_geospy_coordinates", image_bytes=image_bytes),
                timeout=_tier4b_timeout,
            ),
            asyncio.wait_for(
                _tool_registry.acall(
                    "analyze_vision_scene", image_bytes=image_bytes),
                timeout=_tier4b_timeout,
            ),
            asyncio.wait_for(
                _tool_registry.acall(
                    "search_reverse_source", image_bytes=image_bytes),
                timeout=_tier4b_timeout,
            ),
            return_exceptions=True,
        )
        geospy_predict, scene_analysis, reverse_source = ai_results
        ai_evidence: dict = {}
        if isinstance(geospy_predict, dict) and geospy_predict:
            ai_evidence["geospy"] = geospy_predict
        if isinstance(scene_analysis, dict) and scene_analysis:
            ai_evidence["scene"] = scene_analysis
        if isinstance(reverse_source, dict):
            ai_evidence["source_discovery"] = reverse_source
        result.ai_evidence = ai_evidence or None

        # ---- Original rehydration upgrade (Step 1) -----------------------
        # If reverse source recovered GPS from the stripped share's earliest
        # web copy, treat it as authoritative hardware metadata so the
        # cascade promotes it to a hard pin.
        _sd = ai_evidence.get("source_discovery") or {}
        if _sd.get("recovered_gps") and metadata_coords is None:
            metadata_coords = Coordinates(
                lat=_sd["recovered_gps"]["lat"], lon=_sd["recovered_gps"]["lon"]
            )
            result.recovered_original = _sd

        consensus = self.consensus.aggregate(
            metadata_coords, telemetry_coords, vision_results, extractor_results
        )
        result.consensus = consensus

        has_metadata = metadata_coords is not None
        has_telemetry = telemetry_coords is not None
        has_vision = bool(vision_results) or any(
            r.estimated_latitude is not None for r in extractor_results
        )
        if has_metadata or has_telemetry or has_vision:
            result.coordinates = Coordinates(
                lat=consensus.estimated_latitude, lon=consensus.estimated_longitude
            )
            result.search_radius_meters = consensus.search_radius_meters
            if has_metadata:
                result.source = (
                    "RECOVERED_ORIGINAL" if result.recovered_original
                    else "NATIVE_EXIF_HARDWARE"
                )
            elif has_telemetry:
                result.source = "TELEMETRY"
            else:
                result.source = "AI_VISION"
            result.status = "SUCCESS"
            # Reverse-geocode the resolved candidate (probabilistic pin).
            if result.coordinates:
                result.address = reverse_geocode(
                    result.coordinates.lat, result.coordinates.lon
                )
                if result.address and result.address.country:
                    consensus.primary_country = result.address.country
                    consensus.region = result.address.state or consensus.region
        else:
            # ---- Tier 5: Graceful low-context degradation ---------------
            result.source = "EXIF_MISSING_NO_AI_KEY"
            result.status = "PARTIAL_SUCCESS"
            result.coordinates = None
            result.message = self._no_vision_message()

        # ---- Step 3: Monte-Carlo surface + satellite cross-reference ----
        result.credible_interval_radius = consensus.credible_interval_radius
        result.probability_surface = consensus.probability_surface
        if result.coordinates and result.satellite_crossref is None:
            try:
                result.satellite_crossref = geolocation_fusion.cross_reference(
                    result.coordinates, result.address
                )
            except Exception as exc:
                logger.warning("Satellite cross-reference failed: %s", exc)

        # ---- GPS Spoofing Sanity Matrix -------------------------------
        # Cross-reference visual tags with GPS coordinates to detect
        # context mismatches (e.g. tropical foliage tags vs Arctic GPS).
        from app.brain.metadata_extractor import check_gps_spoofing
        all_tags = (result.consensus.visual_evidence_tags if result.consensus else [])
        spoof_result = check_gps_spoofing(result.coordinates, all_tags)
        result.gps_spoofing_detected = spoof_result.get("gps_spoofing_detected", False)
        result.anomaly_score = spoof_result.get("anomaly_score", 0.0)
        result.sanity_mismatches = spoof_result.get("mismatches", [])
        result.gps_climate_zone = spoof_result.get("gps_climate_zone")
        result.visual_climate_zone = spoof_result.get("visual_climate_zone")
        if result.gps_spoofing_detected:
            result.tamper_flags = getattr(result, "tamper_flags", [])
            result.tamper_flags.append("gps_spoofing_suspected")

        # ---- Deep forensic analysis layer (Workbench) -------------------
        all_tags = (result.consensus.visual_evidence_tags if result.consensus else [])
        await self._run_deep_analysis(result, image_bytes, all_tags)

        # ---- AI Intelligence Layer ----------------------------------------
        # Like phone_analysis: build a fact sheet from deterministic results,
        # send it to the global ARK-CAI model, get a structured assessment
        # back.  The AI provides its own observations, contradictions, and
        # recommendations — not just a summary of what the pipeline found.
        await self._run_ai_intelligence(result)

        return result

    # ------------------------------------------------------------------ #
    async def _maybe_fetch_streetview(self, result, lat: float, lon: float) -> None:
        """Fetch a Street View panorama when the camera recorded a heading."""
        imint = result.image_intelligence or {}
        heading = imint.get("geospatial", {}).get("gps_img_direction")
        if heading is None:
            return
        from ..services.geo_providers import fetch_streetview
        try:
            result.streetview = await fetch_streetview(lat, lon, heading)
        except Exception as exc:
            logger.warning("Street View fetch failed: %s", exc)

    # ------------------------------------------------------------------ #
    async def _geocode_ocr_candidates(self, extractor_results: list) -> list:
        """Geocode location-relevant OCR text into candidate pins (Feature 2).

        Collects OCR evidence tags from the clue extractors and selects the
        street / place-like strings (street-suffix tokens, proper-case place
        names) then resolves them to coordinates via the geocoding service.
        Any miss degrades to an empty list — candidates are never fabricated.
        """
        from ..services.geocoding_service import geocode_batch

        texts: list[str] = []
        for ext in extractor_results:
            for t in (ext.evidence_tags or []):
                if getattr(t, "category", "") != "ocr":
                    continue
                label = getattr(t, "label", "") or ""
                label = label.strip()
                if not label:
                    continue
                if _is_location_like(label):
                    texts.append(label)

        if not texts:
            return []
        try:
            return await geocode_batch(texts[:8])
        except Exception as exc:  # noqa: BLE001 — geocode must degrade, not crash
            logger.warning("OCR geocoding failed: %s", exc)
            return []

    # ------------------------------------------------------------------ #
    def _build_evidence_graph(self, result) -> Optional[dict]:
        """Auditable evidence graph with provenance-tagged nodes.

        Direct GPS/telemetry coordinates are TOOL_INFERENCE; all AI-provider
        contributions (GeoSpy / scene / reverse source) are tagged
        ``ai_hypothesis`` so the promotion rule can never elevate them to
        findings without corroboration.
        """
        from ..agent import evidence_graph as eg
        from ..agent.schemas import ClaimType, EdgeRelation, ProvenanceType
        case_id = "CASCADE-" + result.image_sha256[:8].upper()
        graph = eg.EvidenceGraph(case_id=case_id)
        try:
            custody = eg.build_node(
                case_id, "compute_custody_hash", ProvenanceType.CRYPTOGRAPHIC,
                "SHA-256 custody certificate", ClaimType.INTEGRITY,
                {"sha256": result.image_sha256}, 1.0,
            )
            eg.add_node(graph, custody)

            coord_node = None
            if result.coordinates:
                is_ai = result.source == "AI_VISION"
                prov = (ProvenanceType.AI_HYPOTHESIS if is_ai
                        else ProvenanceType.TOOL_INFERENCE)
                coord_node = eg.build_node(
                    case_id, "fuse_geolocation", prov,
                    "Resolved location hypothesis" if is_ai else "Resolved location",
                    ClaimType.LOCATION,
                    {"lat": result.coordinates.lat, "lon": result.coordinates.lon},
                    result.consensus.confidence_score if result.consensus else 0.5,
                    model_id="vision_ensemble" if is_ai else None,
                )
                eg.add_node(graph, coord_node)
                eg.add_edge(graph, custody.node_id, coord_node.node_id,
                            EdgeRelation.DERIVED_FROM, note="custody -> location")

            ai = result.ai_evidence or {}
            if ai.get("geospy") and coord_node:
                g = ai["geospy"]
                gnode = eg.build_node(
                    case_id, "predict_geospy_coordinates", ProvenanceType.AI_HYPOTHESIS,
                    "GeoSpy location hypothesis", ClaimType.LOCATION,
                    {"lat": g.get("estimated_latitude"),
                     "lon": g.get("estimated_longitude")},
                    g.get("confidence_score", 0.5), model_id="geospy",
                )
                eg.add_node(graph, gnode)
                eg.add_edge(graph, gnode.node_id, coord_node.node_id,
                            EdgeRelation.CORROBORATES, note="geospy -> consensus")

            if ai.get("scene") and coord_node:
                s = ai["scene"]
                snode = eg.build_node(
                    case_id, "analyze_vision_scene", ProvenanceType.AI_HYPOTHESIS,
                    "Vision scene analysis", ClaimType.METADATA,
                    (s.get("evidence_tags") or s.get("ocr_texts") or []),
                    s.get("confidence_score", 0.5), model_id="llm_vision",
                )
                eg.add_node(graph, snode)
                eg.add_edge(graph, snode.node_id, coord_node.node_id,
                            EdgeRelation.CORROBORATES, note="scene -> location")

            if ai.get("source_discovery"):
                sd = ai["source_discovery"]
                src_node = eg.build_node(
                    case_id, "search_reverse_source", ProvenanceType.AI_HYPOTHESIS,
                    "Reverse source discovery", ClaimType.SOURCE,
                    {"exact": len(sd.get("exact_matches", [])),
                     "similar": len(sd.get("similar_matches", []))},
                    0.6,
                )
                eg.add_node(graph, src_node)
                if coord_node:
                    eg.add_edge(graph, src_node.node_id, coord_node.node_id,
                                EdgeRelation.CORROBORATES, note="source -> location")
            return eg.to_dict(graph)
        except Exception as exc:
            logger.warning("Evidence graph build failed: %s", exc)
            return None

    # ------------------------------------------------------------------ #
    async def _run_deep_analysis(self, result, image_bytes: bytes, all_tags: list) -> None:
        """Run ExifTool, consistency, C2PA, source discovery, fusion, contradictions."""
        result.analysis_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Evidence acquired")
        result.analysis_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] SHA-256 calculated")

        # ExifTool deep metadata extraction
        deep = exiftool_service.extract_deep(image_bytes)
        result.deep_metadata = deep
        if deep.get("available"):
            n_fields = sum(len(g) for g in deep.get("groups", {}).values())
            result.analysis_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] ExifTool: {n_fields} metadata fields discovered")

        # Metadata consistency engine
        if deep.get("groups"):
            result.consistency_findings = consistency_engine.analyze(
                deep["groups"], deep.get("file_info", {})
            )
            for f in result.consistency_findings:
                result.analysis_log.append(
                    f"[{datetime.now().strftime('%H:%M:%S')}] {f.get('status','WARNING')}: {f.get('type','')} — {f['message'][:60]}"
                )

        # C2PA / provenance analysis
        result.provenance = c2pa_service.analyze(image_bytes, deep.get("groups", {}))
        result.analysis_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] C2PA provenance: {result.provenance['state']}")

        # Source discovery: reuse Tier 4b result when available (no-GPS path),
        # otherwise compute it now (GPS-found path skipped Tier 4b).
        # This is the SINGLE source_discovery call — no duplicates.
        ai_sd = (result.ai_evidence or {}).get("source_discovery")
        if ai_sd:
            result.source_discovery = ai_sd
            result.analysis_log.append(
                f"[{datetime.now().strftime('%H:%M:%S')}] Source discovery: {ai_sd.get('state', 'unknown')} "
                f"(pHash={ai_sd.get('phash', 'none')[:16]}...)"
            )
        else:
            from app.agent.unified_registry import unified_registry as _tool_registry
            try:
                result.source_discovery = await asyncio.wait_for(
                    _tool_registry.acall(
                        "search_reverse_source",
                        image_bytes=image_bytes,
                        exiftool_groups=deep.get("groups", {}),
                    ),
                    timeout=45.0,
                )
                result.analysis_log.append(
                    f"[{datetime.now().strftime('%H:%M:%S')}] Source discovery: {result.source_discovery.get('state', 'unknown')} "
                    f"(pHash={result.source_discovery.get('phash', 'none')[:16]}...)"
                )
            except (asyncio.TimeoutError, Exception) as exc:
                logger.warning("Source discovery failed: %s", exc)
                from app.services.source_discovery import compute_phash
                result.source_discovery = {
                    "state": "UNAVAILABLE",
                    "phash": compute_phash(image_bytes),
                    "embedded_urls": [],
                    "exact_matches": [],
                    "similar_matches": [],
                    "timeline": [],
                    "provider": "none",
                    "detail": f"Source discovery failed: {exc}",
                    "recovered_gps": None,
                    "recovered_metadata": None,
                    "recovered_source_url": None,
                }

        # Multi-layer geolocation fusion with explainability
        result.geolocation_fusion = geolocation_fusion.fuse(
            result.consensus,
            result.coordinates,
            (result.address.model_dump() if result.address else None),
            all_tags,
            result.consistency_findings,
            result.exif_raw or {},
            satellite=result.satellite_crossref,
            recovered_gps=result.recovered_original,
        )
        result.analysis_log.append(
            f"[{datetime.now().strftime('%H:%M:%S')}] Geolocation fusion: "
            f"{result.geolocation_fusion['independent_evidence_classes']} evidence classes"
        )

        # Contradiction engine
        result.contradictions = contradiction_engine.detect(
            result.consistency_findings,
            result.geolocation_fusion,
            result.exif_raw or {},
            result.gps_spoofing_detected,
            result.anomaly_score,
            result.sanity_mismatches,
        )
        if result.contradictions:
            result.analysis_log.append(
                f"[{datetime.now().strftime('%H:%M:%S')}] {len(result.contradictions)} contradiction(s) detected"
            )

        # Evidence summary (investigation overview)
        result.evidence_summary = self._build_summary(result)

        # Provenance-tagged evidence graph (AI providers tagged ai_hypothesis)
        result.evidence_graph = self._build_evidence_graph(result)
        if result.evidence_graph:
            result.analysis_log.append(
                f"[{datetime.now().strftime('%H:%M:%S')}] Evidence graph: "
                f"{len(result.evidence_graph['nodes'])} nodes, "
                f"{len(result.evidence_graph['edges'])} edges"
            )
        result.analysis_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Analysis complete")

        return result

    # ------------------------------------------------------------------ #
    async def _run_ai_intelligence(self, result) -> None:
        """AI Intelligence Layer — the ARK-CAI model reasons about the image.

        Mirrors the phone_analysis pattern: build a fact sheet from
        deterministic results, send it to the global ARK-CAI model
        (ai_gateway → cloud/Ollama cascade), get a structured assessment
        back.  The AI provides its own observations, contradictions, and
        recommendations — not just a summary of what the pipeline found.

        This is honest-by-design: if no AI provider is configured, the
        pipeline degrades to deterministic-only analysis.  The AI layer
        is additive — it never replaces or overrides the deterministic
        cascade, it enriches it.
        """
        from app.brain.clue_extractors.base import llm_client

        if not llm_client.is_configured():
            result.analysis_log.append(
                f"[{datetime.now().strftime('%H:%M:%S')}] AI intelligence: skipped (no provider configured)"
            )
            return

        # Build the fact sheet — everything the deterministic cascade found
        fact_sheet = {
            "image_sha256": result.image_sha256,
            "status": result.status,
            "source": result.source,
            "metadata_status": result.metadata_status,
            "coordinates": {"lat": result.coordinates.lat, "lon": result.coordinates.lon} if result.coordinates else None,
            "address": result.address.model_dump() if result.address else None,
            "camera": result.camera,
            "altitude": result.altitude,
            "datetime_original": result.datetime_original,
            "exif_missing": result.exif_missing,
            "exif_raw_keys": list((result.exif_raw or {}).keys())[:10],
            "ela_heatmap": result.ela_heatmap is not None,
            "steganography_detected": result.steganography_detected,
            "gps_spoofing_detected": result.gps_spoofing_detected,
            "anomaly_score": result.anomaly_score,
            "consensus": {
                "confidence_score": result.consensus.confidence_score if result.consensus else 0,
                "tier": result.consensus.tier if result.consensus else "none",
                "visual_evidence_tags": (result.consensus.visual_evidence_tags if result.consensus else [])[:10],
            },
            "consistency_findings": result.consistency_findings[:5],
            "contradictions": result.contradictions[:5],
            "deep_metadata_available": bool(result.deep_metadata and result.deep_metadata.get("available")),
            "deep_metadata_fields": sum(len(g) for g in (result.deep_metadata or {}).get("groups", {}).values()),
            "provenance_state": result.provenance.get("state") if result.provenance else "unknown",
            "source_discovery_state": result.source_discovery.get("state") if result.source_discovery else "unknown",
            "source_discovery_phash": (result.source_discovery.get("phash", "")[:16] + "...") if result.source_discovery else "none",
            "exact_matches": len((result.source_discovery or {}).get("exact_matches", [])),
            "similar_matches": len((result.source_discovery or {}).get("similar_matches", [])),
            "recovered_gps": result.recovered_original.get("recovered_gps") if result.recovered_original else None,
            "geolocation_fusion_classes": (result.geolocation_fusion or {}).get("independent_evidence_classes", 0),
        }

        system_prompt = (
            "You are ARK-CAI, the AI intelligence layer for image forensics. "
            "You receive a fact sheet from the deterministic BrainPipeline. "
            "Your job is to REASON about the evidence — not just summarize it.\n\n"
            "Provide:\n"
            "1. **ai_assessment**: Your overall assessment of the image location and integrity\n"
            "2. **key_observations**: 3-5 specific observations the operator should know\n"
            "3. **contradictions_analysis**: What contradictions or anomalies concern you and why\n"
            "4. **confidence_adjustment**: Do you agree with the pipeline's confidence? Why or why not?\n"
            "5. **recommended_actions**: What should the operator do next (be specific)\n"
            "6. **risk_flags**: Any red flags or areas of concern\n\n"
            "Be specific, evidence-based, and concise. Never fabricate data — "
            "only reason about what the fact sheet provides."
        )
        user_prompt = f"Image analysis fact sheet:\n{json.dumps(fact_sheet, indent=2, default=str)}"

        try:
            import json as _json
            ai_result = await asyncio.wait_for(
                asyncio.to_thread(llm_client.chat_json, system_prompt, user_prompt),
                timeout=30.0,
            )
            if isinstance(ai_result, dict):
                result.ai_intelligence = ai_result
                result.analysis_log.append(
                    f"[{datetime.now().strftime('%H:%M:%S')}] AI intelligence: assessment complete"
                )
            else:
                result.ai_intelligence = None
                result.analysis_log.append(
                    f"[{datetime.now().strftime('%H:%M:%S')}] AI intelligence: no structured response"
                )
        except asyncio.TimeoutError:
            result.ai_intelligence = None
            result.analysis_log.append(
                f"[{datetime.now().strftime('%H:%M:%S')}] AI intelligence: timed out"
            )
        except Exception as exc:
            result.ai_intelligence = None
            result.analysis_log.append(
                f"[{datetime.now().strftime('%H:%M:%S')}] AI intelligence: {exc}"
            )

    # ------------------------------------------------------------------ #
    def _build_summary(self, result) -> dict:
        """Build the investigation overview (what we know / don't know).

        Uses the canonical observation builder so every forensic layer is
        represented and the evidence count reflects real observations — never
        a silent zero when AI keys are absent.
        """
        from .observations import (
            build_location_hypothesis,
            build_next_steps,
            build_observations,
            classify_image,
            ladder_state,
        )

        fusion = result.geolocation_fusion or {}
        prov = result.provenance or {}
        disc = result.source_discovery or {}
        known: list[str] = []
        unknown: list[str] = []
        suspicious: list[str] = []

        observations = build_observations(result)
        result.observations = observations
        result.image_classification = classify_image(result)

        if result.coordinates:
            if result.source == "AI_VISION":
                suspicious.append(
                    "Location: AI vision hypothesis — requires corroboration"
                )
            known.append(f"Location: {fusion.get('primary_location') or 'resolved'}")
        else:
            unknown.append("Location: no coordinates established")
        if result.exif_raw:
            known.append("Metadata: EXIF present")
        else:
            unknown.append("Metadata: EXIF stripped/missing")
        if result.deep_metadata and result.deep_metadata.get("available"):
            known.append(f"Deep metadata: {sum(len(g) for g in result.deep_metadata.get('groups',{}).values())} fields")
        if result.ela_heatmap:
            known.append("Pixel forensics: ELA available")
        if observations:
            known.append(f"Evidence: {len(observations)} observations recorded")

        if prov.get("state") == "UNAVAILABLE":
            unknown.append(f"Provenance: {prov.get('state')}")
        elif prov.get("state") in ("INVALID", "INCOMPLETE"):
            suspicious.append(f"Provenance: {prov.get('state')}")

        for c in result.contradictions:
            suspicious.append(f"Contradiction: {c.get('type','')}")

        if disc.get("state") == "UNAVAILABLE":
            unknown.append("Source discovery: not configured")

        if result.gps_spoofing_detected:
            suspicious.append(f"GPS spoofing: anomaly {result.anomaly_score*100:.0f}%")

        return {
            "location": fusion.get("primary_location", "Unknown"),
            "confidence": (result.consensus.confidence_score if result.consensus else 0.0),
            "integrity": "REVIEW REQUIRED" if (result.exif_missing or result.steganography_detected) else "VERIFIED",
            "provenance": prov.get("state", "UNAVAILABLE"),
            "contradictions": len(result.contradictions),
            "evidence_count": len(observations),
            "sources_discovered": len(disc.get("exact_matches", [])) + len(disc.get("similar_matches", [])),
            "analysis_status": result.status,
            "observations": observations,
            "image_classification": result.image_classification,
            "ladder": ladder_state(result),
            "location_hypothesis": build_location_hypothesis(result),
            "known": known,
            "unknown": unknown,
            "suspicious": suspicious,
            "next_steps": build_next_steps(result, unknown, suspicious),
        }


# Module-level singleton
brain = BrainPipeline()
