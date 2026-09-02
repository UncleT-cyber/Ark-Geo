"""Local Directory Inspector — sandboxed filesystem evidence gathering.

The ARK agent surface reads the analyst's local case folders through one
narrow, sandboxed entry point: everything under ``~/Documents/ARK_Investigations``.
The inspector never reads outside that root — ``target_path`` is resolved and
validated against the sandbox before any I/O (see :func:`safe_resolve`).

For a target it builds a recursive index:

* MIME type + size + SHA-256 (partial, flagged, for very large files)
* Shannon entropy over the first bytes — a high-entropy flag marks packed /
  encrypted / payload binaries (the stego/smuggling heuristic from the image
  pipeline, applied to whole folders)
* embedded image metadata (capture date / camera / GPS) via the existing
  ExifTool service when present

The target directory is auto-created (``mkdir -p``) so the analyst can point
ARK at a case folder that does not exist yet — the tool reports that it was
created rather than erroring.

The output is pure data; the agent loop turns it into observations/findings.
"""
from __future__ import annotations

import hashlib
import logging
import math
import mimetypes
import os
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Default sandbox: the analyst's case-drop directory. Nothing is ever read
# above this root, no matter what path is requested.
_DEFAULT_SANDBOX_NAME = "ARK_Investigations"

# Directories skipped during the recursive index (repo/noise artifacts).
_SKIP_DIRS = {".git", ".hg", ".svn", "__pycache__", "node_modules", ".DS_Store"}

# Entropy / size guards — keep the index bounded and cheap.
_ENTROPY_WINDOW = 4096                 # first 4 KiB for the entropy flag
_HIGH_ENTROPY_THRESHOLD = 7.5          # bits/byte over the window
_FULL_HASH_LIMIT = 512 * 1024 * 1024   # hash whole files up to 512 MiB
_HASH_WINDOW = 64 * 1024 * 1024        # beyond that, hash the first 64 MiB
_MAX_ENTRIES = 400                     # output cap (deepest/first wins)

_IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".heif",
    ".gif", ".webp", ".bmp",
}


# --------------------------------------------------------------------------- #
# Sandbox root + path resolution
# --------------------------------------------------------------------------- #
def sandbox_root() -> Path:
    """The one directory the inspector may read: ``~/Documents/ARK_Investigations``."""
    return Path.home() / "Documents" / _DEFAULT_SANDBOX_NAME


def ensure_sandbox() -> Path:
    """Create the sandbox root if missing and return it."""
    root = sandbox_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _within(path: Path, root: Path) -> bool:
    try:
        return path == root or path.is_relative_to(root)
    except ValueError:
        return False


def safe_resolve(target_path: str, *, create: bool = True) -> Path:
    """Resolve a target path inside the sandbox root (validated, escaped-safe).

    * ``~/...`` and relative paths resolve against the sandbox root.
    * An absolute path is honoured only when it already lives under the root.
    * When ``create`` the resolved target directory is auto-created
      (``mkdir -p``), matching the "point ARK at a not-yet-existing case
      folder" flow.

    Raises ``ValueError`` for empty input or any path escaping the sandbox —
    that is the entire authorization surface of this tool.
    """
    root = ensure_sandbox().resolve()
    raw = os.path.expanduser(str(target_path or "").strip())
    if not raw:
        raise ValueError("target path is empty")

    candidate = Path(raw)
    if candidate.is_absolute():
        resolved = candidate.resolve()
        if not _within(resolved, root):
            raise ValueError(f"path outside sandbox: {resolved}")
    else:
        resolved = (root / candidate).resolve()
        if not _within(resolved, root):
            raise ValueError(f"path outside sandbox: {resolved}")

    if create:
        resolved.mkdir(parents=True, exist_ok=True)
    return resolved


# --------------------------------------------------------------------------- #
# Per-file probes
# --------------------------------------------------------------------------- #
def _shannon_entropy(data: bytes) -> float:
    """Bits per byte over ``data`` (8.0 = fully random)."""
    if not data:
        return 0.0
    counts = [0] * 256
    for b in data:
        counts[b] += 1
    n = len(data)
    return -sum(c / n * math.log2(c / n) for c in counts if c)


def _sha256(path: Path) -> tuple[str, bool]:
    """Streamed SHA-256. ``partial`` is True for files over the hash window."""
    h = hashlib.sha256()
    partial = False
    try:
        size = path.stat().st_size
        window = _FULL_HASH_LIMIT if size <= _FULL_HASH_LIMIT else _HASH_WINDOW
        partial = size > _FULL_HASH_LIMIT
        remaining = window
        with open(path, "rb") as fh:
            while remaining > 0:
                chunk = fh.read(min(1 << 20, remaining))
                if not chunk:
                    break
                h.update(chunk)
                remaining -= len(chunk)
    except OSError:
        return "", False
    return h.hexdigest(), partial


def _mime(path: Path) -> str:
    guess, _ = mimetypes.guess_type(str(path))
    if guess:
        return guess
    ext = path.suffix.lower()
    return {"bin": "application/octet-stream", "dat": "application/octet-stream"}.get(
        ext.lstrip("."), "application/octet-stream"
    )


def _image_metadata(path: Path) -> dict:
    """Best-effort EXIF capture date / camera / GPS for image files.

    Uses the existing ExifTool service on a read-only basis; any failure
    degrades to an empty dict (the file is still indexed).
    """
    if path.suffix.lower() not in _IMAGE_EXTS:
        return {}
    try:
        if path.stat().st_size > 8 * 1024 * 1024:
            return {}
        from ..services.exiftool_service import exiftool_service
        if not exiftool_service.available:
            return {}
        with open(path, "rb") as fh:
            data = fh.read()
        if not data:
            return {}
        deep = exiftool_service.extract_deep(data)
        if not deep or not deep.get("available"):
            return {}

        file_info = deep.get("file_info") or {}
        groups: dict[str, list[dict]] = deep.get("groups") or {}
        exif = {t["tag"]: t["value"] for t in groups.get("EXIF", [])}
        gps = {t["tag"]: t["value"] for t in groups.get("GPS", [])}

        camera = " ".join(str(v) for v in (exif.get("Make"), exif.get("Model"))
                          if v).strip() or None
        date = (
            exif.get("DateTimeOriginal")
            or exif.get("CreateDate")
            or file_info.get("file_modify_date")
        )
        lat = gps.get("GPSLatitude") or gps.get("Latitude")
        lon = gps.get("GPSLongitude") or gps.get("Longitude")
        return {
            "capture_date": date,
            "camera": camera,
            "gps": f"{lat}, {lon}" if lat and lon else None,
            "dimensions": f"{file_info.get('image_width', '?')}x"
                          f"{file_info.get('image_height', '?')}"
                          if file_info.get("image_width") else None,
        }
    except Exception as exc:  # noqa: BLE001 — metadata is best-effort
        logger.warning("Image metadata probe failed for %s: %s", path, exc)
        return {}


def _index_file(path: Path, rel: Path, out: list[dict]) -> None:
    if len(out) >= _MAX_ENTRIES:
        return
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    digest, partial_hash = _sha256(path)
    high_entropy = False
    try:
        with open(path, "rb") as fh:
            head = fh.read(_ENTROPY_WINDOW)
        high_entropy = _shannon_entropy(head) >= _HIGH_ENTROPY_THRESHOLD
    except OSError:
        pass
    entry: dict[str, Any] = {
        "name": path.name,
        "relpath": rel.as_posix(),
        "kind": "file",
        "size": size,
        "mime": _mime(path),
        "sha256": digest or None,
        "partial_hash": partial_hash or None,
        "high_entropy": high_entropy or None,
    }
    meta = _image_metadata(path)
    if meta:
        entry["image_metadata"] = meta
    out.append(entry)


def inspect_path(target_path: str, *, max_entries: int = _MAX_ENTRIES) -> dict:
    """Recursively index a sandboxed local path.

    Auto-creates the sandbox root and the target directory. Returns a
    structured result: the resolved path, sandbox root, whether the target
    was created, and a flat recursive index (directories + files, with MIME,
    size, SHA-256, entropy flags and image EXIF metadata).
    """
    from datetime import datetime, timezone

    target = safe_resolve(target_path, create=False)
    created = not target.exists()
    target.mkdir(parents=True, exist_ok=True)  # auto-create (mkdir -p)
    entries: list[dict] = []
    walked = 0
    start = datetime.now(timezone.utc)

    for dirpath, dirnames, filenames in os.walk(target):
        dirnames[:] = sorted(
            d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")
        )
        rel_dir = Path(dirpath).relative_to(target)
        if len(entries) >= max_entries:
            break
        if rel_dir.as_posix() != ".":
            entries.append({
                "name": Path(dirpath).name,
                "relpath": rel_dir.as_posix(),
                "kind": "dir",
                "size": None,
                "mime": "inode/directory",
                "sha256": None,
                "partial_hash": None,
                "high_entropy": None,
            })
        for fname in sorted(filenames):
            if fname.startswith(".") and fname != ".DS_Store":
                continue
            fpath = Path(dirpath) / fname
            if fpath.is_symlink() and not fpath.is_file():
                continue
            _index_file(fpath, Path(dirpath).relative_to(target) / fname, entries)
            if len(entries) >= max_entries:
                break
        walked += 1

    return {
        "target_path": str(target),
        "sandbox_root": str(target.parent),
        "created": created,
        "walked_dirs": walked,
        "entries": entries,
        "file_count": sum(1 for e in entries if e["kind"] == "file"),
        "dir_count": sum(1 for e in entries if e["kind"] == "dir"),
        "total_bytes": sum(e["size"] or 0 for e in entries),
        "high_entropy_files": [e["relpath"] for e in entries
                               if e["kind"] == "file" and e["high_entropy"]],
        "scanned_at": start.isoformat(),
        "max_entries": max_entries,
        "truncated": len(entries) >= max_entries,
    }


def observations_from_result(result: dict) -> list[dict]:
    """Fold an ``inspect_path`` result into CaseObservation-shaped dicts.

    Matches the frontend ``CaseObservation`` contract
    (``type/status/layer/label/detail/confidence``) so the terminal can fold
    them into the active case unchanged.
    """
    obs: list[dict] = []
    target = result.get("target_path") or "?"
    obs.append({
        "type": "FILESYSTEM",
        "status": "OBSERVED",
        "layer": "local",
        "label": f"Sandboxed directory inspected: {target}",
        "detail": (
            f"{result.get('file_count', 0)} file(s), "
            f"{result.get('dir_count', 0)} subdirectories, "
            f"{result.get('total_bytes', 0)} bytes"
        ),
        "confidence": 1.0,
    })
    if result.get("created"):
        obs.append({
            "type": "FILESYSTEM",
            "status": "UNAVAILABLE",
            "layer": "local",
            "label": f"Directory auto-created: {target}",
            "detail": "The folder did not exist — ARK created it. Drop evidence "
                      "files here and re-inspect.",
            "confidence": 1.0,
        })
    for rel in result.get("high_entropy_files", [])[:20]:
        obs.append({
            "type": "STEGO",
            "status": "ANOMALY",
            "layer": "local",
            "label": f"High-entropy binary: {rel}",
            "detail": "High Shannon entropy — packed, encrypted or embedded "
                      "payload likely. Inspect with forensic tools.",
            "confidence": 0.7,
        })
    return obs
