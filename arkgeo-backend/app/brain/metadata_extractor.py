"""Tier 1 – EXIF / TIFF / XMP metadata extraction & GPS sanity verification.

Uses Pillow + piexif to pull embedded GPS coordinates and other forensic
metadata from an image.  Includes tamper / sanity checks so zeroed or
impossible coordinates are rejected rather than trusted blindly.

A free OpenStreetMap Nominatim reverse-geocoder (via ``geopy``) converts
parsed decimal coordinates into a human-readable address.
"""
from __future__ import annotations

import base64
import io
import logging
import math
from typing import Optional

import piexif
from PIL import Image, UnidentifiedImageError
from geopy.exc import GeocoderServiceError, GeocoderTimedOut
from geopy.geocoders import Nominatim

from app.models import Coordinates, AddressInfo

logger = logging.getLogger(__name__)

# Single shared geocoder instance (Nominatim usage policy requires a
# persistent User-Agent and 1 req/s max).
_geolocator = Nominatim(user_agent="arkgeo-forensic/1.0", timeout=5)


class MetadataExtractionError(Exception):
    """Raised when an image cannot be parsed at all."""


# --------------------------------------------------------------------------- #
# Steganography / EOF anomaly detection
# --------------------------------------------------------------------------- #
def detect_eof_anomaly(image_bytes: bytes, fmt: str | None = None) -> dict:
    """Scan for trailing bytes appended after the legitimate End-of-File marker.

    JPEG images end with ``0xFFD9``; PNG images end with the IEND chunk
    (``\\x49\\x45\\x4e\\x44\\xae\\x42\\x60\\x82``).  Any data beyond these
    markers may indicate steganographic payload, appended malware, or
    container smuggling.

    Returns a dict with:
        steganography_detected – bool
        trailing_bytes_count    – int (number of anomalous bytes after EOF)
        eof_offset              – int | None (absolute byte offset of EOF marker)
        file_format             – str | None
    """
    result = {
        "steganography_detected": False,
        "trailing_bytes_count": 0,
        "eof_offset": None,
        "file_format": fmt,
    }

    detected_fmt = fmt or detect_format(image_bytes)
    if detected_fmt is None:
        return result
    result["file_format"] = detected_fmt

    eof_offset = None
    if detected_fmt == "jpeg":
        # JPEG EOI marker: 0xFFD9.  Search from the end for the *last* EOI.
        # Some cameras embed thumbnails with their own EOI, so we look for
        # the final one.
        idx = image_bytes.rfind(b"\xff\xd9")
        if idx != -1:
            eof_offset = idx + 2  # marker is 2 bytes
    elif detected_fmt == "png":
        # PNG IEND chunk: 8-byte sequence (length=0 + "IEND" + CRC)
        idx = image_bytes.rfind(b"IEND\xae\x42\x60\x82")
        if idx != -1:
            eof_offset = idx + 8

    if eof_offset is not None and eof_offset < len(image_bytes):
        trailing = len(image_bytes) - eof_offset
        result["eof_offset"] = eof_offset
        result["trailing_bytes_count"] = trailing
        result["steganography_detected"] = trailing > 0

    return result


def detect_format(image_bytes: bytes) -> str | None:
    """Return ``"jpeg"`` or ``"png"`` based on magic bytes, or ``None``."""
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if image_bytes.startswith(b"\x89\x50\x4e\x47"):
        return "png"
    return None


# --------------------------------------------------------------------------- #
# Error Level Analysis (ELA)
# --------------------------------------------------------------------------- #
def generate_ela_heatmap(image_bytes: bytes, quality: int = 95) -> str | None:
    """Generate an Error Level Analysis heatmap as a Base64-encoded PNG.

    ELA works by re-saving the image at a known JPEG compression quality,
    then computing the absolute pixel-by-pixel difference between the
    original and the re-saved version.  Regions that were previously
    compressed (authentic camera output) show small differences, while
    regions that were edited / spliced in show larger differences because
    they lose more data on the second compression pass.

    The result is rescaled to maximise visible contrast and returned as a
    Base64-encoded PNG string suitable for an ``<img src="data:...">`` tag.

    Returns ``None`` if the image cannot be processed (e.g. PNG with no
    JPEG re-save path, or corrupt data).
    """
    try:
        original = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:
        logger.warning("ELA: could not open image: %s", exc)
        return None

    # Re-save at the target quality
    resave_buf = io.BytesIO()
    original.save(resave_buf, format="JPEG", quality=quality)
    resave_buf.seek(0)
    try:
        resaved = Image.open(resave_buf).convert("RGB")
    except Exception as exc:
        logger.warning("ELA: could not re-open resaved image: %s", exc)
        return None

    # Ensure dimensions match (they should for JPEG, but guard anyway)
    if resaved.size != original.size:
        resaved = resaved.resize(original.size)

    # Compute absolute pixel difference
    import numpy as np
    orig_arr = np.asarray(original, dtype=np.int16)
    re_arr = np.asarray(resaved, dtype=np.int16)
    diff = np.abs(orig_arr - re_arr)

    # Rescale to 0-255 for maximum contrast
    max_val = diff.max()
    if max_val == 0:
        # Identical — no compression artefacts at all (suspicious or lossless)
        diff_scaled = np.zeros_like(diff, dtype=np.uint8)
    else:
        diff_scaled = (diff * (255.0 / max_val)).clip(0, 255).astype(np.uint8)

    # Convert to a heatmap-style image: amplify with a cyan-magenta colormap
    # so high-difference regions stand out visually.
    ela_image = Image.fromarray(diff_scaled, mode="RGB")

    # Apply a simple heatmap tint by boosting the red channel where diff is high
    # and boosting blue where diff is low.
    r = diff_scaled[:, :, 0].astype(np.uint8)
    g = (diff_scaled[:, :, 1] * 0.2).astype(np.uint8)
    b = (255 - diff_scaled[:, :, 2]).astype(np.uint8)
    heatmap = np.stack([r, g, b], axis=-1).astype(np.uint8)
    ela_image = Image.fromarray(heatmap, mode="RGB")

    # Resize for frontend payload efficiency (max 400px wide)
    max_width = 400
    if ela_image.width > max_width:
        ratio = max_width / ela_image.width
        ela_image = ela_image.resize(
            (max_width, int(ela_image.height * ratio)), Image.LANCZOS
        )

    out_buf = io.BytesIO()
    ela_image.save(out_buf, format="PNG")
    ela_b64 = base64.b64encode(out_buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{ela_b64}"


# --------------------------------------------------------------------------- #
# GPS Spoofing Sanity Matrix
# --------------------------------------------------------------------------- #
# Climate zone definitions approximated by latitude bands.
# These are used to cross-reference botanical tags with GPS coordinates.

_TROPICAL_LABELS = {
    "palm", "coconut", "banana", "mango", "papaya", "hibiscus", "orchid",
    "fern", "bamboo", "tropical", "jungle", "rainforest", "mangrove",
    "bromeliad", "plumeria", "frangipani", "teak", "mahogany",
}

_ARCTIC_LABELS = {
    "pine", "spruce", "fir", "birch", "willow", "lichen", "moss",
    "tundra", "conifer", "evergreen", "snow", "ice", "glacier",
    "arctic", "subarctic", "taiga",
}

_DESERT_LABELS = {
    "cactus", "succulent", "aloe", "agave", "sage", "sand", "rock",
    "desert", "arid", "drought", "mesquite", "ocotillo", "yucca",
}

# Infrastructure / electrical standards by region
_INFRA_EU_LABELS = {"european", "europe", "eu license", "230v", "50hz", "type c", "type f"}
_INFRA_US_LABELS = {"american", "us license", "120v", "60hz", "type a", "type b"}
_INFRA_UK_LABELS = {"uk license", "230v uk", "type g", "british", "left-hand"}


def _lat_to_climate(lat: float) -> str:
    """Map a latitude to a rough climate zone label."""
    abs_lat = abs(lat)
    if abs_lat >= 66.5:
        return "arctic"
    if abs_lat >= 45:
        return "temperate_cold"
    if abs_lat >= 23.5:
        return "temperate"
    return "tropical"


def _classify_botanical_tag(label: str) -> str:
    """Classify a botanical tag label into a climate expectation."""
    label_lower = label.lower().strip()
    if any(t in label_lower for t in _TROPICAL_LABELS):
        return "tropical"
    if any(t in label_lower for t in _ARCTIC_LABELS):
        return "arctic"
    if any(t in label_lower for t in _DESERT_LABELS):
        return "desert"
    return "unknown"


def check_gps_spoofing(
    gps_coords: Optional[Coordinates],
    visual_tags: list,
) -> dict:
    """Cross-reference visual environment tags with GPS coordinates.

    Consumes the outputs of the botanical and infrastructure clue
    extractors (``VisualEvidenceTag`` objects or dicts with
    ``category``, ``label``, ``confidence``) and compares the implied
    climate / region against the GPS-derived climate zone.

    Returns a dict:
        gps_spoofing_detected – bool
        anomaly_score          – float (0.0 to 1.0)
        mismatches            – list[str] (human-readable mismatch descriptions)
        gps_climate_zone      – str | None
        visual_climate_zone   – str | None
    """
    result = {
        "gps_spoofing_detected": False,
        "anomaly_score": 0.0,
        "mismatches": [],
        "gps_climate_zone": None,
        "visual_climate_zone": None,
    }

    if not gps_coords:
        return result

    gps_climate = _lat_to_climate(gps_coords.lat)
    result["gps_climate_zone"] = gps_climate

    # Collect botanical and infrastructure tags
    botanical_climates: list[tuple[str, float]] = []
    infra_regions: list[str] = []
    for tag in visual_tags:
        category = getattr(tag, "category", "") or (tag.get("category", "") if isinstance(tag, dict) else "")
        label = getattr(tag, "label", "") or (tag.get("label", "") if isinstance(tag, dict) else "")
        confidence = getattr(tag, "confidence", 0.5)
        if isinstance(tag, dict):
            confidence = tag.get("confidence", 0.5)

        if category == "botanical":
            climate = _classify_botanical_tag(label)
            if climate != "unknown":
                botanical_climates.append((climate, float(confidence)))
        elif category == "infrastructure":
            label_lower = label.lower()
            if any(r in label_lower for r in _INFRA_EU_LABELS):
                infra_regions.append("EU")
            elif any(r in label_lower for r in _INFRA_US_LABELS):
                infra_regions.append("US")
            elif any(r in label_lower for r in _INFRA_UK_LABELS):
                infra_regions.append("UK")

    # Determine dominant visual climate zone (weighted by confidence)
    if botanical_climates:
        climate_scores: dict[str, float] = {}
        for climate, conf in botanical_climates:
            climate_scores[climate] = climate_scores.get(climate, 0.0) + conf
        dominant_visual = max(climate_scores, key=climate_scores.get)
        result["visual_climate_zone"] = dominant_visual

        # Check mismatch
        if dominant_visual != gps_climate:
            # Severity based on how extreme the mismatch is
            mismatch_pairs = {
                ("tropical", "arctic"), ("arctic", "tropical"),
                ("tropical", "temperate_cold"), ("arctic", "tropical"),
                ("desert", "arctic"), ("arctic", "desert"),
            }
            is_severe = (dominant_visual, gps_climate) in mismatch_pairs or \
                        (gps_climate, dominant_visual) in mismatch_pairs
            score = min(1.0, climate_scores[dominant_visual] * (1.5 if is_severe else 0.7))
            result["anomaly_score"] = max(result["anomaly_score"], score)
            result["mismatches"].append(
                f"Botanical tags suggest '{dominant_visual}' climate but GPS "
                f"coordinates resolve to '{gps_climate}' zone "
                f"(lat={gps_coords.lat:.4f})"
            )

    # Check infrastructure vs GPS hemisphere
    if infra_regions:
        # Simple check: if GPS is in the southern hemisphere but infra says
        # EU/US/UK (northern), flag as suspicious
        for region in infra_regions:
            if gps_coords.lat < -30 and region in ("EU", "US", "UK"):
                result["anomaly_score"] = max(result["anomaly_score"], 0.8)
                result["mismatches"].append(
                    f"Infrastructure tags indicate '{region}' standards but "
                    f"GPS is in southern hemisphere (lat={gps_coords.lat:.4f})"
                )

    result["gps_spoofing_detected"] = result["anomaly_score"] >= 0.5
    return result


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
# Reverse geocoding
# --------------------------------------------------------------------------- #
def reverse_geocode(lat: float, lon: float) -> Optional[AddressInfo]:
    """Turn decimal coordinates into a human-readable address via OSM Nominatim.

    Returns ``None`` if the network lookup fails or times out — the pipeline
    continues with coordinates-only in that case.
    """
    try:
        location = _geolocator.reverse(f"{lat}, {lon}", language="en", exactly_one=True)
    except (GeocoderTimedOut, GeocoderServiceError, Exception) as exc:
        logger.warning("Reverse geocode failed for %s,%s: %s", lat, lon, exc)
        return None
    if not location or not location.raw:
        return None
    addr = location.raw.get("address", {})
    country = addr.get("country")
    state = addr.get("state") or addr.get("region") or addr.get("state_district")
    city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("hamlet") or addr.get("county")
    road = addr.get("road") or addr.get("pedestrian") or addr.get("footway") or addr.get("suburb")
    postcode = addr.get("postcode")
    return AddressInfo(
        country=country,
        state=state,
        city=city,
        road=road,
        postcode=postcode,
        display_name=location.address,
    )


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
class MetadataExtractor:
    """Extract and validate GPS metadata from image bytes."""

    def extract(self, image_bytes: bytes) -> dict:
        """Return a dict with gps, camera, raw metadata and tamper flags.

        Keys:
            gps           – Optional[Coordinates]  (decimal degrees)
            altitude      – Optional[float]       (metres)
            gps_timestamp – Optional[str]         (ISO-ish from GPSTimeStamp)
            camera        – dict with make/model/lens/software/exposure
            datetime_original – Optional[str]
            raw           – flat dict of all EXIF name→value
            tamper_flags  – list[str]
        """
        result: dict = {
            "gps": None,
            "altitude": None,
            "gps_timestamp": None,
            "camera": {},
            "datetime_original": None,
            "raw": {},
            "tamper_flags": [],
            "steganography": {
                "steganography_detected": False,
                "trailing_bytes_count": 0,
                "eof_offset": None,
                "file_format": None,
            },
            "exif_missing": False,
            "file_format": None,
            "ela_heatmap": None,
        }

        # Steganography / EOF anomaly scan (runs before decode for early flag)
        stego = detect_eof_anomaly(image_bytes)
        result["steganography"] = stego
        result["file_format"] = stego.get("file_format")
        if stego.get("steganography_detected"):
            result["tamper_flags"].append(
                f"trailing_bytes:{stego['trailing_bytes_count']}"
            )

        # Error Level Analysis (ELA) — generates a base64 heatmap
        result["ela_heatmap"] = generate_ela_heatmap(image_bytes)

        img = _decode_image(image_bytes)

        # Basic EXIF via Pillow (0th IFD)
        exif_data = img.getexif()
        if exif_data:
            result["raw"].update({piexif.TAGS.get(k, {}).get("name", str(k)): str(v)
                                  for k, v in exif_data.items()})

        # Full EXIF (including GPS, EXIF, MakerNote IFDs) via piexif
        exif_raw = img.info.get("exif", b"")
        exif_dict = {}
        if exif_raw:
            try:
                exif_dict = piexif.load(exif_raw)
            except (ValueError, piexif.InvalidImageDataError):
                exif_dict = {}

        # Flag EXIF as missing/stripped if no raw EXIF bytes and no Pillow exif
        if not exif_raw and not exif_data:
            result["exif_missing"] = True
            result["tamper_flags"].append("exif_stripped")

        # Camera parameters from 0th + EXIF IFDs
        self._extract_camera(exif_dict, result)

        # GPS data
        gps_ifd = exif_dict.get("GPS") or {}
        self._extract_gps_full(gps_ifd, result)

        # XMP / software tamper hints
        software = str(result["raw"].get("Software", "")).lower()
        if software and any(t in software for t in ("photoshop", "gimp", "snapseed", "lightroom")):
            result["tamper_flags"].append(f"editing_software:{software}")

        return result

    # ------------------------------------------------------------------ #
    def _extract_camera(self, exif_dict: dict, result: dict) -> None:
        """Populate result["camera"] with make / model / lens / software / exposure."""
        zeroth = exif_dict.get("0th") or {}
        exif = exif_dict.get("Exif") or {}

        def _get(ifd, tag):
            val = ifd.get(tag)
            if val is None:
                return None
            if isinstance(val, bytes):
                try:
                    return val.decode("utf-8", errors="replace").rstrip("\x00").strip()
                except Exception:
                    return str(val)
            return str(val)

        camera = {
            "make": _get(zeroth, piexif.ImageIFD.Make),
            "model": _get(zeroth, piexif.ImageIFD.Model),
            "lens_model": _get(exif, piexif.ExifIFD.LensModel),
            "software": _get(zeroth, piexif.ImageIFD.Software),
            "f_number": self._rational(exif.get(piexif.ExifIFD.FNumber)),
            "exposure_time": self._rational(exif.get(piexif.ExifIFD.ExposureTime)),
            "iso": int(self._rational(exif.get(piexif.ExifIFD.ISOSpeedRatings)) or 0) or None,
            "focal_length": self._rational(exif.get(piexif.ExifIFD.FocalLength)),
        }
        # Only keep non-None values
        result["camera"] = {k: v for k, v in camera.items() if v is not None}

        # DateTimeOriginal
        dto = _get(exif, piexif.ExifIFD.DateTimeOriginal)
        if dto:
            result["datetime_original"] = dto

    @staticmethod
    def _rational(val) -> Optional[float]:
        """Convert an EXIF rational ((num, den)) to a float, or None."""
        if val is None:
            return None
        try:
            if isinstance(val, tuple) and len(val) == 2:
                num, den = val
                return float(num) / float(den) if float(den) != 0 else None
            return float(val)
        except (TypeError, ValueError, ZeroDivisionError):
            return None

    # ------------------------------------------------------------------ #
    def _extract_gps_full(self, gps_ifd: dict, result: dict) -> None:
        """Extract lat, lon, altitude, and GPS timestamp from the GPS IFD."""
        if not gps_ifd:
            return
        coords = self._extract_gps(gps_ifd)
        if coords:
            if _is_plausible_gps(coords.lat, coords.lon):
                result["gps"] = coords
            else:
                result["tamper_flags"].append(
                    f"implausible_gps:{coords.lat},{coords.lon}"
                )
                logger.warning("Rejected implausible GPS: %s,%s", coords.lat, coords.lon)

        # Altitude (metres)
        alt = self._rational(gps_ifd.get(piexif.GPSIFD.GPSAltitude))
        if alt is not None:
            alt_ref = gps_ifd.get(piexif.GPSIFD.GPSAltitudeRef, b"\x00")
            if isinstance(alt_ref, bytes) and alt_ref == b"\x01":
                alt = -alt  # below sea level
            result["altitude"] = alt

        # GPS timestamp (HH:MM:SS from rationals)
        ts = gps_ifd.get(piexif.GPSIFD.GPSTimeStamp)
        if ts:
            try:
                parts = [self._rational(p) for p in ts]
                if all(p is not None for p in parts):
                    result["gps_timestamp"] = (
                        f"{int(parts[0]):02d}:{int(parts[1]):02d}:{int(parts[2]):02d}"
                    )
            except (TypeError, ValueError, IndexError):
                pass

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
