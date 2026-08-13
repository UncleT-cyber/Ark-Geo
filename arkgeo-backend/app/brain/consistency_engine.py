"""Metadata consistency engine — structured forensic findings.

Compares related metadata values and returns structured findings that
describe anomalies (not judgements).  Each finding follows the schema:

    {
      "status":   "OK" | "WARNING" | "ERROR",
      "type":     "TIMELINE_ANOMALY" | "SOFTWARE_EDIT" | ...,
      "severity":  "LOW" | "MEDIUM" | "HIGH",
      "message":  "human-readable description",
      "evidence":  [list of source fields that produced the finding]
    }

The engine never claims an image is "fake" — it reports observable
inconsistencies for the analyst to evaluate.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _parse_exif_date(date_str: str) -> Optional[datetime]:
    """Parse an ExifTool date string into a timezone-naive datetime.

    ExifTool formats: ``YYYY:MM:DD HH:MM:SS`` (with optional timezone).
    Timezone info is stripped to allow comparison between mixed-precision
    dates.  Returns ``None`` if parsing fails.
    """
    if not date_str or not isinstance(date_str, str):
        return None
    # Strip timezone suffixes for consistent naive comparison
    clean = date_str.strip()
    # Remove trailing timezone like "+00:00" or "Z" or "+05:30"
    import re
    clean = re.sub(r"[+-]\d{2}:?\d{2}$|Z$", "", clean)
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M:%SZ"):
        try:
            return datetime.strptime(clean, fmt)
        except ValueError:
            continue
    return None


class ConsistencyEngine:
    """Cross-reference metadata fields to surface structured inconsistencies."""

    def analyze(self, exiftool_groups: dict, file_info: dict) -> list[dict]:
        """Run all consistency checks against ExifTool grouped metadata.

        ``exiftool_groups`` is the grouped tree from :mod:`exiftool_service`.
        Returns a list of structured findings.
        """
        findings: list[dict] = []
        flat = self._flatten(exiftool_groups)

        self._check_timeline(flat, file_info, findings)
        self._check_editing_software(flat, findings)
        self._check_thumbnail(flat, findings)
        self._check_gps_timestamp(flat, findings)
        self._check_make_model(flat, findings)

        return findings

    # ------------------------------------------------------------------ #
    @staticmethod
    def _flatten(groups: dict) -> dict:
        """Flatten the grouped tree into ``Tag → value`` for easy lookup."""
        flat: dict[str, str] = {}
        for entries in groups.values():
            for entry in entries:
                flat[entry["tag"]] = entry["value"]
        return flat

    # ------------------------------------------------------------------ #
    def _check_timeline(self, flat: dict, file_info: dict, out: list) -> None:
        dto = _parse_exif_date(flat.get("DateTimeOriginal"))
        create = _parse_exif_date(flat.get("CreateDate"))
        modify = _parse_exif_date(file_info.get("file_modify_date") or flat.get("FileModifyDate"))

        if dto and create and dto != create:
            delta_hours = abs((dto - create).total_seconds()) / 3600
            out.append({
                "status": "WARNING",
                "type": "TIMELINE_ANOMALY",
                "severity": "MEDIUM" if delta_hours > 24 else "LOW",
                "message": (
                    "DateTimeOriginal and CreateDate differ by "
                    f"{delta_hours:.1f} hours — metadata timestamps are inconsistent."
                ),
                "evidence": [
                    f"DateTimeOriginal={flat.get('DateTimeOriginal')}",
                    f"CreateDate={flat.get('CreateDate')}",
                ],
            })

        if modify and dto and modify > dto:
            out.append({
                "status": "WARNING",
                "type": "TIMELINE_ANOMALY",
                "severity": "MEDIUM",
                "message": (
                    "File modification timestamp occurs after the claimed capture time "
                    "— file was altered after creation."
                ),
                "evidence": [
                    f"DateTimeOriginal={flat.get('DateTimeOriginal')}",
                    f"FileModifyDate={file_info.get('file_modify_date')}",
                ],
            })

    # ------------------------------------------------------------------ #
    def _check_editing_software(self, flat: dict, out: list) -> None:
        software = (flat.get("Software") or "").lower()
        editing_tools = ("photoshop", "gimp", "lightroom", "snapseed",
                         "affinity", "pixlr", "canva")
        if any(t in software for t in editing_tools):
            tool_name = next(t for t in editing_tools if t in software)
            out.append({
                "status": "WARNING",
                "type": "SOFTWARE_EDIT",
                "severity": "MEDIUM",
                "message": (
                    f"Editing software detected in metadata: '{tool_name}'. "
                    "Image may have been processed after capture."
                ),
                "evidence": [f"Software={flat.get('Software')}"],
            })

    # ------------------------------------------------------------------ #
    def _check_thumbnail(self, flat: dict, out: list) -> None:
        thumb_w = flat.get("ThumbnailImageWidth") or flat.get("ExifImageWidth")
        main_w = flat.get("ExifImageWidth") or flat.get("ImageWidth")
        if thumb_w and main_w:
            try:
                if int(thumb_w) > int(main_w):
                    out.append({
                        "status": "WARNING",
                        "type": "THUMBNAIL_MISMATCH",
                        "severity": "LOW",
                        "message": "Embedded thumbnail dimensions exceed the main image — unusual structure.",
                        "evidence": [
                            f"ThumbnailWidth={thumb_w}",
                            f"ImageWidth={main_w}",
                        ],
                    })
            except (ValueError, TypeError):
                pass

    # ------------------------------------------------------------------ #
    def _check_gps_timestamp(self, flat: dict, out: list) -> None:
        gps_date = flat.get("GPSDateStamp") or flat.get("GPSDateTime")
        dto = _parse_exif_date(flat.get("DateTimeOriginal"))
        gps_dt = _parse_exif_date(gps_date) if gps_date else None
        if gps_dt and dto:
            delta_hours = abs((gps_dt - dto).total_seconds()) / 3600
            if delta_hours > 6:
                out.append({
                    "status": "WARNING",
                    "type": "GPS_TIMESTAMP_CONFLICT",
                    "severity": "HIGH",
                    "message": (
                        "GPS timestamp differs from capture timestamp by "
                        f"{delta_hours:.1f} hours — possible timezone spoofing "
                        "or metadata manipulation."
                    ),
                    "evidence": [
                        f"GPSDateTime={gps_date}",
                        f"DateTimeOriginal={flat.get('DateTimeOriginal')}",
                    ],
                })

    # ------------------------------------------------------------------ #
    def _check_make_model(self, flat: dict, out: list) -> None:
        make = flat.get("Make")
        model = flat.get("Model")
        software = (flat.get("Software") or "").lower()
        # If software claims a phone OS but make is a DSLR, flag mismatch
        if make and ("iphone" in model.lower() if model else False) and "android" in software:
            out.append({
                "status": "ERROR",
                "type": "DEVICE_SOFTWARE_MISMATCH",
                "severity": "HIGH",
                "message": (
                    "Device Make/Model indicates iPhone but Software references Android "
                    "— metadata fields are contradictory."
                ),
                "evidence": [
                    f"Make={make}", f"Model={model}", f"Software={flat.get('Software')}",
                ],
            })


# Singleton
consistency_engine = ConsistencyEngine()
