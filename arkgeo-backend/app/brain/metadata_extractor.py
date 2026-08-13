"""Tier 1 – EXIF / TIFF / XMP metadata extraction & GPS sanity verification.

Uses Pillow + piexif to pull embedded GPS coordinates and other forensic
metadata from an image.  Includes tamper / sanity checks so zeroed or
impossible coordinates are rejected rather than trusted blindly.
"""
from __future__ import annotations

import base64
import io
import logging
from typing import Optional

import piexif
from PIL import Image, UnidentifiedImageError

from app.models import Coordinates

logger = logging.getLogger(__name__)


class MetadataExtractionError(Exception):
    """Raised when an image cannot be parsed at all."""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _decode_image(image_bytes: bytes) -> Image.Image:
    try:
        return Image.open(io.BytesIO(image_bytes))
    except UnidentifiedImageError as exc:  # pragma: no cover - defensive
        raise MetadataExtractionError("Image format not recognised") from exc


def _dms_to_decimal(dms, ref: str) -> float:
    """Convert EXIF rational DMS tuple to a signed decimal degree."""
    d, m, s = dms
    d_val = float(d[0]) / float(d[1]) if isinstance(d, tuple) else float(d)
    m_val = float(m[0]) / float(m[1]) if isinstance(m, tuple) else float(m)
    s_val = float(s[0]) / float(s[1]) if isinstance(s, tuple) else float(s)
    decimal = d_val + m_val / 60.0 + s_val / 3600.0
    if ref in ("S", "W"):
        decimal = -decimal
    return decimal


# --------------------------------------------------------------------------- #
# Sanity checks
# --------------------------------------------------------------------------- #
def _is_plausible_gps(lat: float, lon: float) -> bool:
    """Reject null-island (0,0) and out-of-range values."""
    if lat == 0.0 and lon == 0.0:
        return False
    if not (-90 <= lat <= 90):
        return False
    if not (-180 <= lon <= 180):
        return False
    return True


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
class MetadataExtractor:
    """Extract and validate GPS metadata from image bytes."""

    def extract(self, image_bytes: bytes) -> dict:
        """Return a dict with ``gps`` (Optional[Coordinates]) and ``raw`` metadata."""
        result: dict = {"gps": None, "raw": {}, "tamper_flags": []}
        img = _decode_image(image_bytes)

        # Basic EXIF via Pillow
        exif_data = img.getexif()
        if exif_data:
            result["raw"].update({piexif.TAGS.get(k, {}).get("name", str(k)): str(v)
                                  for k, v in exif_data.items()})

        # Full EXIF (including GPS) via piexif
        exif_raw = img.info.get("exif", b"")
        exif_dict = {}
        if exif_raw:
            try:
                exif_dict = piexif.load(exif_raw)
            except (ValueError, piexif.InvalidImageDataError):
                exif_dict = {}

        gps_ifd = exif_dict.get("GPS") or {}
        coords = self._extract_gps(gps_ifd)
        if coords:
            if _is_plausible_gps(coords.lat, coords.lon):
                result["gps"] = coords
            else:
                result["tamper_flags"].append(
                    f"implausible_gps:{coords.lat},{coords.lon}"
                )
                logger.warning("Rejected implausible GPS: %s,%s", coords.lat, coords.lon)

        # XMP / software tamper hints
        software = str(result["raw"].get("Software", "")).lower()
        if software and any(t in software for t in ("photoshop", "gimp", "snapseed", "lightroom")):
            result["tamper_flags"].append(f"editing_software:{software}")

        return result

    # ------------------------------------------------------------------ #
    def _extract_gps(self, gps_ifd: dict) -> Optional[Coordinates]:
        if not gps_ifd:
            return None
        try:
            lat = _dms_to_decimal(gps_ifd[piexif.GPSIFD.GPSLatitude],
                                  gps_ifd[piexif.GPSIFD.GPSLatitudeRef].decode())
            lon = _dms_to_decimal(gps_ifd[piexif.GPSIFD.GPSLongitude],
                                  gps_ifd[piexif.GPSIFD.GPSLongitudeRef].decode())
            return Coordinates(lat=lat, lon=lon)
        except (KeyError, ValueError, TypeError, AttributeError):
            return None

    @staticmethod
    def decode_base64_image(b64: str) -> bytes:
        """Decode a base64 image string (with or without data-URI prefix)."""
        if "," in b64 and b64.startswith("data:"):
            b64 = b64.split(",", 1)[1]
        return base64.b64decode(b64)
