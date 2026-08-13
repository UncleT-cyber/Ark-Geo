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

import logging
from typing import Optional

from app.brain.clue_extractors.architectural import ArchitecturalExtractor
from app.brain.clue_extractors.botanical import BotanicalExtractor
from app.brain.clue_extractors.indoor import IndoorExtractor
from app.brain.clue_extractors.infrastructure import InfrastructureExtractor
from app.brain.clue_extractors.ocr_text import OcrTextExtractor
from app.brain.consensus_engine import ConsensusEngine
from app.brain.metadata_extractor import MetadataExtractor, reverse_geocode
from app.brain.vision_ensemble import VisionEnsemble
from app.core.security import custody_certificate, custody_hash
from app.models import (
    AddressInfo,
    ConsensusResult,
    Coordinates,
    CustodyCertificate,
    DeviceTelemetry,
)
from app.services.state_cache import state_cache
from app.services.telemetry_service import TelemetryService

logger = logging.getLogger(__name__)


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
        self.gps_spoofing_detected: bool = False
        self.anomaly_score: float = 0.0
        self.sanity_mismatches: list = []
        self.gps_climate_zone: Optional[str] = None
        self.visual_climate_zone: Optional[str] = None


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
        """True if any AI/vision API key is set (checks dynamic settings store)."""
        from app.brain.clue_extractors.base import llm_client
        from app.services.settings_store import settings_store
        return bool(
            settings_store.get_key("geospy_api_key")
            or settings_store.get_key("geoinfer_api_key")
            or settings_store.get_key("llm_api_key")
            or llm_client.is_configured()
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

        # ---- Tier 2: Direct GPS pin + reverse geocode ------------------
        if metadata_coords:
            result.coordinates = metadata_coords
            result.address = reverse_geocode(metadata_coords.lat, metadata_coords.lon)
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
            return result

        # ---- Tier 4: AI vision ensemble (only if keys configured) -----
        vision_results = await self.vision.locate(image_bytes)

        extractor_results = []
        for ext in self.extractors:
            ext_result = ext.extract(image_bytes)
            if ext_result:
                extractor_results.append(ext_result)
        if run_indoor:
            indoor = self.indoor_extractor.extract(image_bytes)
            if indoor:
                extractor_results.append(indoor)

        consensus = self.consensus.aggregate(
            metadata_coords, telemetry_coords, vision_results, extractor_results
        )
        result.consensus = consensus

        if vision_results or any(
            r.estimated_latitude is not None for r in extractor_results
        ):
            result.source = "AI_VISION"
            result.status = "SUCCESS"
            result.coordinates = Coordinates(
                lat=consensus.estimated_latitude, lon=consensus.estimated_longitude
            )
        else:
            # ---- Tier 5: Graceful low-context degradation ---------------
            result.source = "EXIF_MISSING_NO_AI_KEY"
            result.status = "PARTIAL_SUCCESS"
            result.coordinates = None
            result.message = (
                "EXIF metadata missing or stripped. "
                "No AI vision API keys configured on server. "
                "Cannot determine geolocation."
            )

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

        return result


# Module-level singleton
brain = BrainPipeline()
