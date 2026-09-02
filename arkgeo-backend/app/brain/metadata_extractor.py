"""Tier 1 – EXIF / TIFF / XMP metadata extraction & GPS sanity verification.

Uses Pillow + piexif to pull embedded GPS coordinates and other forensic
metadata from an image.  Includes tamper / sanity checks so zeroed or
impossible coordinates are rejected rather than trusted blindly.

A free OpenStreetMap Nominatim reverse-geocoder (via ``geopy``) converts
parsed decimal coordinates into a human-readable address.
"""
from __future__ import annotations

import base64
import hashlib
import io
import logging
import math
from datetime import datetime, timezone
from typing import Optional

import piexif
from PIL import Image, UnidentifiedImageError
from geopy.exc import GeocoderServiceError, GeocoderTimedOut
from geopy.geocoders import Nominatim

from app.models import Coordinates, AddressInfo

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# EXIF tag ids missing from piexif's constant tables (numeric, from the EXIF
# 2.32 / TIFF spec) so the IMINT engine can address every forensic tag it needs.
# --------------------------------------------------------------------------- #
_TAG_SUBSEC_TIME_ORIGINAL = 37521
_TAG_SUBSEC_TIME_DIGITIZED = 37522
_TAG_BODY_SERIAL_NUMBER = 42033  # ExifIFD SerialNumber
_TAG_OWNER_NAME = 42032  # ExifIFD CameraOwnerName
_TAG_IMAGE_UNIQUE_ID = 42016  # ExifIFD ImageUniqueID

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


def _rational_val(val) -> Optional[float]:
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


def _dms_to_decimal(dms, ref: str = "") -> Optional[float]:
    """Convert a DMS coordinate to signed decimal degrees.

    Handles both standard and non-standard device formats:

    * EXIF rational triple ``[(d,1), (m,1), (s,10000)]`` (standard)
    * plain numeric triples / tuples ``[d, m, s]`` or ``[d, m]``
    * a single rational or float (already decimal)
    * strings ``"48 51 23.76"``, ``"48 51.3958"``, or ``"48.8566"``
    * bytes (decoded first)

    ``ref`` may be ``"N"/"S"/"E"/"W"`` (or bytes) — southern/western
    coordinates are negated. Returns ``None`` on any malformed input rather
    than raising (a stripped or corrupt tag must never crash the parser).
    """
    if dms is None:
        return None

    # Bytes → string (some cameras/tools write ASCII DMS).
    if isinstance(dms, bytes):
        try:
            dms = dms.decode("utf-8", errors="replace").strip()
        except Exception:
            return None

    # String forms: "48.8566" | "48 51 23.76" | "48 51.3958"
    if isinstance(dms, str):
        parts = dms.split()
        nums: list[float] = []
        for p in parts:
            try:
                nums.append(float(p))
            except ValueError:
                return None
        if not nums:
            return None
        if len(nums) == 1:
            decimal = nums[0]
        elif len(nums) == 2:
            decimal = nums[0] + nums[1] / 60.0
        else:
            decimal = nums[0] + nums[1] / 60.0 + nums[2] / 3600.0
        return decimal * (-1.0 if str(ref).upper() in ("S", "W") else 1.0)

    # Tuple/list forms: (d, m, s) or single rational.
    if isinstance(dms, (tuple, list)):
        nums = []
        for item in dms:
            if isinstance(item, (tuple, list)):
                num = _rational_val(item)
            elif isinstance(item, bytes):
                try:
                    num = float(item.decode("utf-8", errors="replace"))
                except ValueError:
                    num = None
            else:
                try:
                    num = float(item)
                except (TypeError, ValueError):
                    num = None
            if num is None:
                return None
            nums.append(num)
        if not nums:
            return None
        if len(nums) == 1:
            decimal = nums[0]
        elif len(nums) == 2:
            decimal = nums[0] + nums[1] / 60.0
        else:
            decimal = nums[0] + nums[1] / 60.0 + nums[2] / 3600.0
        return decimal * (-1.0 if str(ref).upper() in ("S", "W") else 1.0)

    try:
        return float(dms) * (-1.0 if str(ref).upper() in ("S", "W") else 1.0)
    except (TypeError, ValueError):
        return None


def _ifd_text(ifd: dict, tag: int) -> Optional[str]:
    """Read a textual IFD tag, decoding bytes and stripping NUL padding."""
    val = ifd.get(tag)
    if val is None:
        return None
    if isinstance(val, bytes):
        try:
            text = val.decode("utf-8", errors="replace").rstrip("\x00").strip()
        except Exception:
            return None
        return text or None
    if isinstance(val, (tuple, list)):
        return None  # rationals are read via _rational_val by callers
    text = str(val).strip()
    return text or None


def _ifd_int(ifd: dict, tag: int) -> Optional[int]:
    val = ifd.get(tag)
    if val is None:
        return None
    if isinstance(val, (tuple, list)):
        if not val:
            return None
        val = val[0]
    try:
        if isinstance(val, bytes):
            return int.from_bytes(val, "little")
        return int(val)
    except (TypeError, ValueError, OverflowError):
        return None


def _flash_fired(flash_code: Optional[int]) -> Optional[bool]:
    """EXIF Flash value bit 0 = flash fired (Boolean)."""
    if flash_code is None:
        return None
    return bool(flash_code & 0x01)


def _dop_quality(dop: Optional[float]) -> Optional[str]:
    """Classify GPS Dilution of Precision into a confidence label."""
    if dop is None:
        return None
    if dop < 1.0:
        return "excellent"
    if dop <= 2.0:
        return "good"
    if dop <= 5.0:
        return "moderate"
    return "poor"


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points, in metres."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _parse_exif_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse ``YYYY:MM:DD HH:MM:SS[.ffffff]`` (or dash-separated) to a naive
    :class:`datetime`, tolerating trailing sub-seconds."""
    if not value:
        return None
    s = value.strip().replace("-", ":")
    if "." in s:
        base, frac = s.split(".", 1)
        s = f"{base}.{frac[:6]}"
    try:
        if "." in s:
            return datetime.strptime(s, "%Y:%m:%d %H:%M:%S.%f")
        return datetime.strptime(s, "%Y:%m:%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def _apply_offset(naive: Optional[datetime], offset: Optional[str]) -> Optional[datetime]:
    """Attach an EXIF ``+HH:MM``/``-HH:MM`` offset and return UTC, or None.

    The naive datetime is device-local wall time; UTC is wall time minus the
    local offset. Computed without touching the host machine's timezone.
    """
    if naive is None or not offset:
        return None
    try:
        sign = 1 if offset[0] == "+" else -1
        digits = offset[1:].replace(":", "")
        hh, mm = int(digits[0:2]), int(digits[2:4])
        total_s = sign * (hh * 3600 + mm * 60)
        epoch = (naive - datetime(1970, 1, 1)).total_seconds()
        return datetime.fromtimestamp(epoch - total_s, tz=timezone.utc)
    except (ValueError, IndexError, TypeError, OSError):
        return None


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
            # IMINT — 4-pillar unified Image Data Extraction payload.
            # Every key below is always present; missing/stripped fields are
            # structural None (contract: never drop the key, never crash).
            "image_intelligence": None,
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

        # IMINT — 4-pillar unified Image Data Extraction payload
        result["image_intelligence"] = self._extract_imint(
            exif_dict, result,
            img_w=getattr(img, "width", None),
            img_h=getattr(img, "height", None),
        )

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
        lat_ref = gps_ifd.get(piexif.GPSIFD.GPSLatitudeRef)
        lon_ref = gps_ifd.get(piexif.GPSIFD.GPSLongitudeRef)
        if isinstance(lat_ref, bytes):
            lat_ref = lat_ref.decode("ascii", errors="replace")
        if isinstance(lon_ref, bytes):
            lon_ref = lon_ref.decode("ascii", errors="replace")
        lat = _dms_to_decimal(
            gps_ifd.get(piexif.GPSIFD.GPSLatitude), lat_ref or "")
        lon = _dms_to_decimal(
            gps_ifd.get(piexif.GPSIFD.GPSLongitude), lon_ref or "")
        if lat is None or lon is None:
            return None
        try:
            return Coordinates(lat=lat, lon=lon)
        except Exception:  # noqa: BLE001 — malformed GPS must degrade, not crash
            return None

    # ------------------------------------------------------------------ #
    # IMINT — 4-pillar unified Image Data Extraction payload
    #
    # Every sub-object below carries a FIXED key set. A tag that is missing
    # or stripped by an adversary yields a structural ``None`` for that
    # explicit field — the key is never dropped and the parser never crashes
    # (compliance contract #2).
    # ------------------------------------------------------------------ #
    def _extract_imint(
        self, exif_dict: dict, result: dict,
        img_w: Optional[int] = None, img_h: Optional[int] = None,
    ) -> dict:
        zeroth = exif_dict.get("0th") or {}
        exif = exif_dict.get("Exif") or {}
        gps = exif_dict.get("GPS") or {}

        geospatial = self._pillar_geospatial(gps, result)
        temporal = self._pillar_temporal(exif, gps)
        device = self._pillar_device(zeroth, exif)
        capture = self._pillar_capture(exif)
        analysis = self._pillar_analysis(geospatial, temporal, device, capture)

        # Asset-type intelligence — screenshot detection (messenger/app
        # transfers strip metadata, but dimensions + container survive).
        screenshot = self._screenshot_signal(
            img_w, img_h, device, result.get("exif_missing"),
            result.get("file_format"),
        )
        analysis["is_screenshot_likely"] = screenshot["is_screenshot_likely"]
        analysis["screenshot_aspect_ratio"] = screenshot["aspect_ratio"]
        analysis["screenshot_reasons"] = screenshot["reasons"]

        return {
            "geospatial": geospatial,
            "temporal": temporal,
            "device": device,
            "capture": capture,
            "analysis": analysis,
        }

    # -- Asset-type intelligence ------------------------------------------ #
    @staticmethod
    def _screenshot_signal(
        img_w: Optional[int], img_h: Optional[int],
        device: dict, exif_missing: Optional[bool], file_format: Optional[str],
    ) -> dict:
        """Heuristic for 'this is probably a screen capture, not a photo'.

        Screenshots survive messenger / app re-encoding with their pixel
        dimensions intact, so aspect ratio + container + missing camera
        provenance combine into a high-signal, low-false-positive indicator.
        """
        if not img_w or not img_h or min(img_w, img_h) <= 0:
            return {"is_screenshot_likely": False, "aspect_ratio": None, "reasons": []}

        aspect = round(img_w / img_h, 4)
        ratio = round(max(img_w, img_h) / min(img_w, img_h), 3)
        reasons: list[str] = []

        if 1.9 <= ratio <= 2.5:
            reasons.append("phone_aspect_ratio")
        elif 1.5 <= ratio < 1.9:
            reasons.append("desktop_aspect_ratio")
        if (file_format or "").lower() == "png":
            reasons.append("png_container")
        if not device.get("make") and not device.get("model"):
            reasons.append("no_camera_provenance")
        if exif_missing:
            reasons.append("metadata_stripped")

        distinctive_aspect = any(
            r in ("phone_aspect_ratio", "desktop_aspect_ratio") for r in reasons
        )
        corroborating = any(
            r in ("png_container", "no_camera_provenance", "metadata_stripped")
            for r in reasons
        )
        verdict = bool(distinctive_aspect and corroborating)
        return {
            "is_screenshot_likely": verdict,
            "aspect_ratio": aspect,
            "reasons": reasons,
        }

    # -- Pillar 1: Geospatial Intelligence (Where) ----------------------- #
    def _pillar_geospatial(self, gps: dict, result: dict) -> dict:
        lat_ref = _ifd_text(gps, piexif.GPSIFD.GPSLatitudeRef)
        lon_ref = _ifd_text(gps, piexif.GPSIFD.GPSLongitudeRef)
        lat = _dms_to_decimal(gps.get(piexif.GPSIFD.GPSLatitude), lat_ref or "")
        lon = _dms_to_decimal(gps.get(piexif.GPSIFD.GPSLongitude), lon_ref or "")

        alt_raw = _rational_val(gps.get(piexif.GPSIFD.GPSAltitude))
        alt_ref_raw = gps.get(piexif.GPSIFD.GPSAltitudeRef)
        below_sea = isinstance(alt_ref_raw, bytes) and alt_ref_raw == b"\x01"
        alt_m = (-alt_raw if below_sea else alt_raw) if alt_raw is not None else None

        dest_lat_ref = _ifd_text(gps, piexif.GPSIFD.GPSDestLatitudeRef)
        dest_lon_ref = _ifd_text(gps, piexif.GPSIFD.GPSDestLongitudeRef)
        dest_lat = _dms_to_decimal(
            gps.get(piexif.GPSIFD.GPSDestLatitude), dest_lat_ref or "")
        dest_lon = _dms_to_decimal(
            gps.get(piexif.GPSIFD.GPSDestLongitude), dest_lon_ref or "")

        dop = _rational_val(gps.get(piexif.GPSIFD.GPSDOP))

        processing = _ifd_text(gps, piexif.GPSIFD.GPSProcessingMethod)
        if processing:
            for prefix in ("ASCII", "UNICODE"):
                if processing.startswith(prefix):
                    processing = processing[len(prefix):].lstrip("\x00").strip()
                    break

        has_coords = lat is not None and lon is not None
        coords_plausible = has_coords and _is_plausible_gps(lat, lon)
        if has_coords and not coords_plausible and result is not None:
            result.setdefault("tamper_flags", []).append(
                f"imint_implausible_gps:{lat},{lon}"
            )

        return {
            "latitude": f"{lat:.6f}" if lat is not None else None,
            "latitude_ref": lat_ref,
            "latitude_decimal": lat,
            "longitude": f"{lon:.6f}" if lon is not None else None,
            "longitude_ref": lon_ref,
            "longitude_decimal": lon,
            "gps_altitude": alt_raw,
            "altitude_meters": alt_m,
            "altitude_ref": ("below_sea_level" if below_sea
                             else "above_sea_level"
                             if alt_ref_raw is not None else None),
            "gps_img_direction": _rational_val(
                gps.get(piexif.GPSIFD.GPSImgDirection)),
            "gps_img_direction_ref": _ifd_text(
                gps, piexif.GPSIFD.GPSImgDirectionRef),
            "gps_speed": _rational_val(gps.get(piexif.GPSIFD.GPSSpeed)),
            "gps_speed_ref": _ifd_text(gps, piexif.GPSIFD.GPSSpeedRef),
            "gps_processing_method": processing,
            "gps_dest_latitude": f"{dest_lat:.6f}" if dest_lat is not None else None,
            "gps_dest_latitude_ref": dest_lat_ref,
            "dest_latitude_decimal": dest_lat,
            "gps_dest_longitude": f"{dest_lon:.6f}" if dest_lon is not None else None,
            "gps_dest_longitude_ref": dest_lon_ref,
            "dest_longitude_decimal": dest_lon,
            "gps_dop": dop,
            "dop_quality": _dop_quality(dop),
            "gps_satellites": _ifd_text(gps, piexif.GPSIFD.GPSSatellites),
            "gps_status": _ifd_text(gps, piexif.GPSIFD.GPSStatus),
            "gps_measure_mode": _ifd_text(gps, piexif.GPSIFD.GPSMeasureMode),
            "has_coordinates": has_coords,
            "coords_plausible": coords_plausible,
        }

    # -- Pillar 2: Chronological & Temporal Integrity (When) ------------- #
    def _pillar_temporal(self, exif: dict, gps: dict) -> dict:
        dto = _ifd_text(exif, piexif.ExifIFD.DateTimeOriginal)
        dtd = _ifd_text(exif, piexif.ExifIFD.DateTimeDigitized)
        offset = _ifd_text(exif, piexif.ExifIFD.OffsetTime)
        offset_orig = _ifd_text(exif, piexif.ExifIFD.OffsetTimeOriginal)
        offset_dig = _ifd_text(exif, piexif.ExifIFD.OffsetTimeDigitized)
        subsec_o = _ifd_text(exif, _TAG_SUBSEC_TIME_ORIGINAL)
        subsec_d = _ifd_text(exif, _TAG_SUBSEC_TIME_DIGITIZED)

        gps_date = _ifd_text(gps, piexif.GPSIFD.GPSDateStamp)
        gps_time = None
        ts = gps.get(piexif.GPSIFD.GPSTimeStamp)
        if ts:
            parts = ([_rational_val(p) for p in ts]
                     if isinstance(ts, (tuple, list)) else [_rational_val(ts)])
            if all(p is not None for p in parts) and len(parts) >= 2:
                gps_time = (
                    f"{int(parts[0]):02d}:{int(parts[1]):02d}:"
                    f"{int(parts[2]):02d}" if len(parts) >= 3
                    else f"{int(parts[0]):02d}:{int(parts[1]):02d}:00"
                )

        # Device local clock → UTC (requires an OffsetTime to be unambiguous).
        device_utc = _apply_offset(
            _parse_exif_datetime(dto), offset_orig or offset)
        # Satellite clock: GPS date+time are UTC by spec.
        sat_utc = None
        if gps_date and gps_time:
            sat_utc = _parse_exif_datetime(f"{gps_date} {gps_time}")

        clock_delta = None
        if device_utc is not None and sat_utc is not None:
            clock_delta = int(
                (device_utc - sat_utc.replace(tzinfo=timezone.utc)).total_seconds())
        drift = clock_delta is not None and abs(clock_delta) > 300

        has_ts = any(
            v is not None for v in (dto, dtd, gps_date, gps_time, subsec_o, subsec_d)
        )
        return {
            "datetime_original": dto,
            "datetime_digitized": dtd,
            "offset_time": offset,
            "offset_time_original": offset_orig,
            "offset_time_digitized": offset_dig,
            "subsec_time_original": subsec_o,
            "subsec_time_digitized": subsec_d,
            "gps_date_stamp": gps_date,
            "gps_time_stamp": gps_time,
            "device_clock_utc": (
                device_utc.isoformat() if device_utc is not None else None),
            "satellite_clock_utc": (
                sat_utc.isoformat() + "Z" if sat_utc is not None else None),
            "clock_delta_seconds": clock_delta,
            "clock_drift_detected": drift,
            "has_timestamps": has_ts,
        }

    # -- Pillar 3: Hardware Provenance & Digital Fingerprinting ---------- #
    def _pillar_device(self, zeroth: dict, exif: dict) -> dict:
        make = _ifd_text(zeroth, piexif.ImageIFD.Make)
        model = _ifd_text(zeroth, piexif.ImageIFD.Model)
        software = _ifd_text(zeroth, piexif.ImageIFD.Software)
        artist = _ifd_text(zeroth, piexif.ImageIFD.Artist)
        copyright_ = _ifd_text(zeroth, piexif.ImageIFD.Copyright)

        lens_make = _ifd_text(exif, piexif.ExifIFD.LensMake)
        lens_model = _ifd_text(exif, piexif.ExifIFD.LensModel)
        lens_serial = _ifd_text(exif, piexif.ExifIFD.LensSerialNumber)
        body_serial = _ifd_text(exif, _TAG_BODY_SERIAL_NUMBER)
        owner = _ifd_text(exif, _TAG_OWNER_NAME)
        image_unique_id = _ifd_text(exif, _TAG_IMAGE_UNIQUE_ID)

        profile_strings = {
            k: v for k, v in {
                "owner_name": owner,
                "artist": artist,
                "copyright": copyright_,
            }.items() if v is not None
        } or None
        has_prov = any(
            v is not None for v in (
                make, model, body_serial, lens_model, lens_serial,
                image_unique_id, software, owner, artist, copyright_,
            )
        )
        return {
            "make": make,
            "model": model,
            "lens_make": lens_make,
            "lens_model": lens_model,
            "body_serial_number": body_serial,
            "lens_serial_number": lens_serial,
            "software": software,
            "image_unique_id": image_unique_id,
            "owner_name": owner,
            "artist": artist,
            "copyright": copyright_,
            "profile_strings": profile_strings,
            "has_provenance": has_prov,
        }

    # -- Pillar 4: Photographic Capture Diagnostics (How) ---------------- #
    def _pillar_capture(self, exif: dict) -> dict:
        exposure = _rational_val(exif.get(piexif.ExifIFD.ExposureTime))
        fnum = _rational_val(exif.get(piexif.ExifIFD.FNumber))
        aper = _rational_val(exif.get(piexif.ExifIFD.ApertureValue))
        shutter = _rational_val(exif.get(piexif.ExifIFD.ShutterSpeedValue))
        iso = _ifd_int(exif, piexif.ExifIFD.ISOSpeedRatings)
        flash = _ifd_int(exif, piexif.ExifIFD.Flash)
        focal = _rational_val(exif.get(piexif.ExifIFD.FocalLength))
        focal35 = _ifd_int(exif, piexif.ExifIFD.FocalLengthIn35mmFilm)
        metering = _ifd_int(exif, piexif.ExifIFD.MeteringMode)
        light = _ifd_int(exif, piexif.ExifIFD.LightSource)
        sensing = _ifd_int(exif, piexif.ExifIFD.SensingMethod)
        program = _ifd_int(exif, piexif.ExifIFD.ExposureProgram)

        exposure_str = None
        if exposure:
            try:
                n = round(1.0 / exposure)
                exposure_str = (
                    f"1/{n}" if abs(1.0 / exposure - n) < 0.05
                    else f"{exposure:.6f}s")
            except (ZeroDivisionError, ValueError):
                exposure_str = None

        has_cap = any(
            v is not None for v in (
                exposure, fnum, aper, shutter, iso, flash, focal, focal35,
                metering, light, sensing, program,
            )
        )
        return {
            "exposure_time": exposure,
            "exposure_time_str": exposure_str,
            "f_number": fnum,
            "aperture_value": aper,
            "shutter_speed_value": shutter,
            "iso": iso,
            "flash": flash,
            "flash_fired": _flash_fired(flash),
            "focal_length": focal,
            "focal_length_35mm": focal35,
            "metering_mode": metering,
            "light_source": light,
            "sensing_method": sensing,
            "exposure_program": program,
            "has_capture": has_cap,
        }

    # -- Derived intelligence over the 4 pillars ------------------------- #
    @staticmethod
    def _pillar_analysis(geospatial: dict, temporal: dict,
                         device: dict, capture: dict) -> dict:
        conflicts: list[str] = []
        if (geospatial.get("has_coordinates")
                and geospatial.get("dest_latitude_decimal") is not None
                and geospatial.get("dest_longitude_decimal") is not None
                and geospatial.get("latitude_decimal") is not None
                and geospatial.get("longitude_decimal") is not None):
            d = _haversine_m(
                geospatial["latitude_decimal"], geospatial["longitude_decimal"],
                geospatial["dest_latitude_decimal"],
                geospatial["dest_longitude_decimal"],
            )
            if d > 1000:
                conflicts.append(f"dest_coordinates_differ:{d:.0f}m")
        if geospatial.get("has_coordinates") and not geospatial.get(
                "coords_plausible"):
            conflicts.append("implausible_coordinates")

        subsec_reasons: list[str] = []
        so = temporal.get("subsec_time_original")
        sd = temporal.get("subsec_time_digitized")
        if so is not None and so.strip("0") == "":
            subsec_reasons.append("all_zero_subsec_original")
        if sd is not None and sd.strip("0") == "":
            subsec_reasons.append("all_zero_subsec_digitized")
        if so and sd and so == sd:
            subsec_reasons.append("identical_subsec_both_clocks")

        fingerprint = None
        profile = [str(device.get(k)).lower().strip() for k in (
            "make", "model", "body_serial_number", "lens_model",
            "lens_serial_number", "software", "owner_name",
        ) if device.get(k)]
        if profile:
            fingerprint = hashlib.sha256(
                "|".join(profile).encode()).hexdigest()[:32]

        return {
            "pillars_present": {
                "geospatial": bool(geospatial.get("has_coordinates")),
                "temporal": bool(temporal.get("has_timestamps")),
                "device": bool(device.get("has_provenance")),
                "capture": bool(capture.get("has_capture")),
            },
            "clock_drift_detected": bool(temporal.get("clock_drift_detected")),
            "dop_quality": geospatial.get("dop_quality"),
            "subsec_anomaly_detected": bool(subsec_reasons),
            "subsec_anomaly_reasons": subsec_reasons,
            "geospatial_conflicts": conflicts,
            "unique_fingerprint": fingerprint,
        }

    @staticmethod
    def decode_base64_image(b64: str) -> bytes:
        """Decode a base64 image string (with or without data-URI prefix)."""
        if "," in b64 and b64.startswith("data:"):
            b64 = b64.split(",", 1)[1]
        return base64.b64decode(b64)
