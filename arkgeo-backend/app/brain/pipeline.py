"""Brain orchestrator – runs the full 4-tier pipeline on an image.

This is the single entry point the API endpoints call.  It wires together:
  Tier 1  metadata_extractor
  Tier 2  vision_ensemble
  Tier 3  clue_extractors
  Tier 4  consensus_engine
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
from app.brain.metadata_extractor import MetadataExtractor
from app.brain.vision_ensemble import VisionEnsemble
from app.models import ConsensusResult, Coordinates, DeviceTelemetry
from app.services.state_cache import state_cache
from app.services.telemetry_service import TelemetryService

logger = logging.getLogger(__name__)


class BrainPipeline:
    """Orchestrates the 4-tier geolocation pipeline."""

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

    async def analyze(
        self,
        image_bytes: bytes,
        device_telemetry: Optional[DeviceTelemetry] = None,
        user_id: Optional[str] = None,
        run_indoor: bool = True,
    ) -> tuple[ConsensusResult, dict]:
        """Run the pipeline. Returns (consensus, raw_metadata_dict)."""

        # ---- Tier 1: EXIF metadata -----------------------------------
        meta = self.metadata.extract(image_bytes)
        metadata_coords = meta.get("gps")

        # ---- Telemetry fallback (cell / Wi-Fi / last-known) ----------
        telemetry_coords: Optional[Coordinates] = None
        if not metadata_coords and device_telemetry:
            last_known = device_telemetry.last_known_outdoor_gps
            if not last_known and user_id:
                last_known_coord = state_cache.get_outdoor_gps(user_id)
                if last_known_coord:
                    last_known = type("G", (), {
                        "lat": last_known_coord.lat,
                        "lon": last_known_coord.lon,
                        "timestamp": None,
                    })()
            telemetry_coords = self.telemetry.resolve(
                last_known_gps=last_known if last_known else None,
                cell_tower=device_telemetry.connected_cell_tower,
                wifi_bssids=device_telemetry.nearby_wifi_bssids,
            )
            # Cache a good outdoor GPS for future use.
            if telemetry_coords and user_id:
                from app.models import GpsFix
                import time
                state_cache.set_outdoor_gps(
                    user_id,
                    GpsFix(lat=telemetry_coords.lat, lon=telemetry_coords.lon, timestamp=int(time.time())),
                )

        # Early exit if we have high-confidence deterministic data.
        if metadata_coords:
            consensus = self.consensus.aggregate(
                metadata_coords, telemetry_coords, [], []
            )
            return consensus, meta["raw"]

        # ---- Tier 2: Vision ensemble ---------------------------------
        vision_results = await self.vision.locate(image_bytes)

        # ---- Tier 3: Clue extractors ---------------------------------
        extractor_results = []
        for ext in self.extractors:
            result = ext.extract(image_bytes)
            if result:
                extractor_results.append(result)
        if run_indoor:
            indoor = self.indoor_extractor.extract(image_bytes)
            if indoor:
                extractor_results.append(indoor)

        # ---- Tier 4: Consensus ---------------------------------------
        consensus = self.consensus.aggregate(
            metadata_coords, telemetry_coords, vision_results, extractor_results
        )
        return consensus, meta["raw"]


# Module-level singleton
brain = BrainPipeline()
