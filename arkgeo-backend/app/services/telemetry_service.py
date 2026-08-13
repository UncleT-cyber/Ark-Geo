"""Telemetry service – resolve coordinates from non-GPS hardware signals.

When an image lacks usable EXIF GPS, ArkGeo falls back to:
1. Last-known outdoor GPS (from :mod:`app.services.state_cache`)
2. Cell-tower triangulation via OpenCellID
3. Wi-Fi BSSID lookups (Mozilla Location Services / OpenCellID ICHNAEA)

All external calls use ``httpx`` with a short timeout and degrade gracefully
(returning ``None``) rather than raising, so the Brain pipeline can continue.
"""
from __future__ import annotations

import logging
from typing import List, Optional

import httpx

from app.core.config import settings
from app.models import CellTowerInfo, Coordinates

logger = logging.getLogger(__name__)


class TelemetryService:
    """Aggregate non-GPS positioning signals into a best-effort coordinate."""

    def __init__(self) -> None:
        self._client = httpx.Client(timeout=settings.vision_request_timeout)

    # ------------------------------------------------------------------ #
    def resolve(
        self,
        last_known_gps: Optional[Coordinates] = None,
        cell_tower: Optional[CellTowerInfo] = None,
        wifi_bssids: Optional[List[str]] = None,
    ) -> Optional[Coordinates]:
        """Return the most trustworthy coordinate available, or ``None``."""
        if last_known_gps:
            logger.info("Telemetry: using last-known GPS %s", last_known_gps)
            return last_known_gps

        if cell_tower:
            coords = self._resolve_cell(cell_tower)
            if coords:
                return coords

        if wifi_bssids:
            coords = self._resolve_wifi(wifi_bssids)
            if coords:
                return coords

        return None

    # ------------------------------------------------------------------ #
    def _resolve_cell(self, tower: CellTowerInfo) -> Optional[Coordinates]:
        if not settings.opencellid_api_key:
            logger.debug("OpenCellID key not configured; skipping cell lookup")
            return None
        params = {
            "key": settings.opencellid_api_key,
            "mcc": tower.mcc,
            "mnc": tower.mnc,
            "lac": tower.lac,
            "cellid": tower.cell_id,
            "format": "json",
        }
        try:
            resp = self._client.get(settings.opencellid_api_url, params=params)
            resp.raise_for_status()
            data = resp.json()
            if "lat" in data and "lon" in data:
                logger.info("Telemetry: cell lookup -> %s,%s", data["lat"], data["lon"])
                return Coordinates(lat=float(data["lat"]), lon=float(data["lon"]))
        except Exception as exc:  # pragma: no cover - network path
            logger.warning("Cell tower lookup failed: %s", exc)
        return None

    def _resolve_wifi(self, bssids: List[str]) -> Optional[Coordinates]:
        if not settings.opencellid_api_key:
            logger.debug("OpenCellID key not configured; skipping Wi-Fi lookup")
            return None
        # ICHNAEA geolocate endpoint
        url = "https://location.services.mozilla.com/v1/geolocate"
        body = {"wifiAccessPoints": [{"macAddress": b} for b in bssids[:20]]}
        try:
            resp = self._client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()
            loc = data.get("location", {})
            if "lat" in loc and "lng" in loc:
                logger.info("Telemetry: Wi-Fi lookup -> %s,%s", loc["lat"], loc["lng"])
                return Coordinates(lat=float(loc["lat"]), lon=float(loc["lng"]))
        except Exception as exc:  # pragma: no cover - network path
            logger.warning("Wi-Fi BSSID lookup failed: %s", exc)
        return None

    def close(self) -> None:
        self._client.close()
