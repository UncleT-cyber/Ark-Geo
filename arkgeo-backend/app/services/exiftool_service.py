"""Deep metadata extraction via ExifTool.

Wraps the system ``exiftool`` binary to produce a richly grouped metadata
tree (EXIF / XMP / IPTC / ICC / MakerNotes / File / Composite) with raw
field values, plus file properties (MIME, size, dimensions).

All operations run on a temporary working copy — the original evidence
bytes are never modified.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ExifTool group order for the output tree
GROUP_ORDER = ("File", "EXIF", "ExifIFD", "GPS", "XMP", "IPTC", "ICC_Profile",
               "MakerNotes", "Composite", "JFIF", "Photoshop", "ICC")


class ExifToolService:
    """Thin, safe wrapper around the ``exiftool`` CLI."""

    def __init__(self) -> None:
        self._binary = shutil.which("exiftool")

    @property
    def available(self) -> bool:
        return self._binary is not None

    # ------------------------------------------------------------------ #
    def extract_deep(self, image_bytes: bytes) -> dict[str, Any]:
        """Run ExifTool on a working copy and return a structured metadata tree.

        Returns a dict with keys:
            available   – bool (was exiftool present?)
            groups      – dict[group_name, list[{tag, value}]]
            raw         – list of raw ExifTool JSON records
            file_info   – dict with size/mime/dimensions
            error       – str | None
        """
        result: dict[str, Any] = {
            "available": self.available,
            "groups": {},
            "raw": [],
            "file_info": {},
            "error": None,
        }
        if not self.available:
            result["error"] = "ExifTool not installed on server"
            return result

        tmp_path = None
        try:
            # Write a working copy — never touch original evidence
            fd, tmp_path = tempfile.mkstemp(suffix=".bin")
            with os.fdopen(fd, "wb") as f:
                f.write(image_bytes)

            args = [
                self._binary, "-j", "-G1", "-struct", "-a",
                "-api", "LargeFileSupport=1",
                tmp_path,
            ]
            import subprocess
            proc = subprocess.run(
                args, capture_output=True, text=True, timeout=15,
            )
            if proc.returncode != 0:
                result["error"] = proc.stderr.strip() or "ExifTool failed"
                return result

            records = json.loads(proc.stdout)
            if not records:
                return result
            raw = records[0]
            result["raw"] = raw
            result["groups"] = self._group_tags(raw)
            result["file_info"] = self._extract_file_info(raw)
        except json.JSONDecodeError as exc:
            result["error"] = f"ExifTool JSON parse error: {exc}"
        except subprocess.TimeoutExpired:
            result["error"] = "ExifTool timed out"
        except Exception as exc:
            result["error"] = f"ExifTool error: {exc}"
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        return result

    # ------------------------------------------------------------------ #
    @staticmethod
    def _group_tags(raw: dict) -> dict[str, list[dict]]:
        """Convert ExifTool's flat ``Group:Tag`` keys into a grouped tree."""
        groups: dict[str, list[dict]] = {}
        for key, value in raw.items():
            if key == "SourceFile":
                continue
            # Keys look like "EXIF:Make" or "File:FileSize" or "File:System:FileName"
            parts = key.split(":")
            if len(parts) >= 2:
                group = parts[-2]
                tag = parts[-1]
            else:
                group, tag = "Other", key
            groups.setdefault(group, []).append({
                "tag": tag,
                "value": ExifToolService._stringify(value),
            })
        # Sort groups by preferred order, then alphabetical
        ordered = {g: groups[g] for g in GROUP_ORDER if g in groups}
        for g in sorted(groups):
            if g not in ordered:
                ordered[g] = groups[g]
        return ordered

    @staticmethod
    def _extract_file_info(raw: dict) -> dict:
        info = {
            "mime_type": raw.get("File:MIMEType") or raw.get("System:MIMEType"),
            "file_size": raw.get("File:FileSize") or raw.get("System:FileSize"),
            "image_width": raw.get("File:ImageWidth") or raw.get("EXIF:ExifImageWidth"),
            "image_height": raw.get("File:ImageHeight") or raw.get("EXIF:ExifImageHeight"),
            "file_type": raw.get("File:FileType"),
            "file_modify_date": raw.get("System:FileModifyDate") or raw.get("File:FileModifyDate"),
            "encoding": raw.get("File:Encoding"),
        }
        return {k: v for k, v in info.items() if v is not None}

    @staticmethod
    def _stringify(value: Any) -> str:
        """Convert ExifTool values to display strings."""
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)


# Singleton
exiftool_service = ExifToolService()
