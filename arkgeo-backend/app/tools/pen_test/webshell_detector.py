"""Webshell detector — defensive DFIR scan of a web root.

The ARK task list called this module ``web_shell_injector`` (an anonymous
FTP/HTTP payload uploader with command-execution hooks). That capability is
**not implemented** — deploying a webshell is a persistent-backdoor implant and
falls outside what this investigation platform ships. In its place this module
provides the defensive counterpart the RE-ACT chain's Exploit phase can
actually use on authorized engagements: a static scanner that hunts an owned
web root for known webshell signatures and risky eval/exec patterns.

The scan is entirely local file inspection:

* known shell families (c99 / r57 / b374k / wso / x86 / China Chopper / Godzilla)
* classic dropper / launcher strings (``eval($_POST``, ``assert($_REQUEST``,
  ``gzinflate(base64_decode``, ``@system``, ``passthru``, ``popen``)
* opaque high-entropy payload blobs (base64) inside otherwise plain scripts

Degrades honestly: a missing/invalid path returns ``UNAVAILABLE``; unreadable
files are skipped and reported, never fatal.
"""
from __future__ import annotations

import base64
import logging
import math
import os
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Name markers that flag a file before content inspection (family shells often
# ship under their own name).
_SHELL_NAME_RE = re.compile(
    r"^(c99|r57|b374k|wso|wso2|safe0ver|php-backdoor|webshell|shell|x86|"
    r"china|ch0|godzilla|behinder|jspy|webshellx)"
    r".*\.(php|jsp|jspx|asp|aspx|cgi|py|pl)$",
    re.IGNORECASE,
)

# Dangerous function / launcher patterns found inside scripts.
_LAUNCHER_PATTERNS: list[tuple[str, str]] = [
    ("eval-post", r"eval\s*\(\s*\$_?(?:POST|REQUEST|GET|COOKIE)\s*\["),
    ("assert-request", r"assert\s*\(\s*\$_?(?:POST|REQUEST|GET)\s*\["),
    ("gzinflate-blob", r"gzinflate\s*\(\s*base64_decode\s*\("),
    ("str-rot13-blob", r"str_rot13\s*\(\s*base64_decode\s*\("),
    ("base64-blob", r"base64_decode\s*\(\s*['\"][A-Za-z0-9+/=]{80,}['\"]\s*\)"),
    ("system-exec", r"(?:system|passthru|shell_exec|popen|proc_open)\s*\("),
    ("eval-string", r"eval\s*\(\s*['\"][^'\"]{40,}['\"]\s*\)"),
    ("php-superglobal-get", r"\$_(?:POST|GET|REQUEST)\[.{1,80}\]\s*\)"),
    ("create-function", r"create_function\s*\("),
    ("gzinflate-rot13", r"gzinflate\s*\(\s*str_rot13\s*\("),
]

# File extensions treated as script-bearing web content.
_WEB_EXTS = {".php", ".php3", ".php4", ".phtml", ".asp", ".aspx", ".ashx",
             ".jsp", ".jspx", ".cgi", ".pl", ".py", ".rb"}

_MAX_FILE_BYTES = 2 * 1024 * 1024   # skip files larger than 2 MB
_MAX_FILES = 5000                   # bounded scan — never walks forever
_BASE64_BLOB_RE = re.compile(r"[A-Za-z0-9+/]{80,}={0,2}")


def _shannon_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    freq: dict[int, int] = {}
    for byte in data:
        freq[byte] = freq.get(byte, 0) + 1
    length = len(data)
    return -sum((count / length) * math.log2(count / length)
                for count in freq.values())


def _is_base64_blob(text: str) -> bool:
    """Heuristic: a long base64 string with high entropy inside a script."""
    blob = _BASE64_BLOB_RE.search(text)
    if not blob:
        return False
    try:
        raw = base64.b64decode(blob.group(0), validate=True)
    except Exception:  # noqa: BLE001 — not valid base64, skip
        return False
    return bool(raw) and _shannon_entropy(raw) >= 5.0


def _scan_file(path: str, max_file_bytes: int = _MAX_FILE_BYTES) -> Optional[dict[str, Any]]:
    """Return a detection record for ``path``, or None if clean/unreadable."""
    try:
        with open(path, "rb") as fh:
            data = fh.read(max_file_bytes + 1)
    except (OSError, PermissionError):
        return None
    if len(data) > max_file_bytes:
        return None
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return None

    name = os.path.basename(path)
    flags: list[str] = []
    if _SHELL_NAME_RE.match(name):
        flags.append("shell-family-name")
    for label, pattern in _LAUNCHER_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            flags.append(label)
    if _is_base64_blob(text):
        flags.append("high-entropy-base64-blob")
    if not flags:
        return None
    risk = "HIGH" if len(flags) >= 2 or "eval-post" in flags or \
        "assert-request" in flags or "gzinflate-blob" in flags else "MEDIUM"
    return {
        "file": path,
        "flags": flags,
        "risk": risk,
        "bytes": len(data),
    }


def _scan_tree(target_path: str, max_file_bytes: int = _MAX_FILE_BYTES) -> list[dict[str, Any]]:
    """Walk the web root (bounded) collecting detection records."""
    detections: list[dict[str, Any]] = []
    skipped: list[str] = []
    visited = 0
    for root, dirs, files in os.walk(target_path):
        dirs.sort()
        for fname in files:
            visited += 1
            if visited > _MAX_FILES:
                return detections + [{"truncated": True,
                                      "detail": "file-count cap reached"}]
            ext = os.path.splitext(fname)[1].lower()
            if ext not in _WEB_EXTS:
                continue
            full = os.path.join(root, fname)
            record = _scan_file(full, max_file_bytes)
            if record:
                detections.append(record)
            elif not os.access(full, os.R_OK):
                skipped.append(full)
        if len(skipped) > 200:
            break
    if skipped:
        detections.insert(0, {
            "unreadable_files": len(skipped),
            "samples": skipped[:10],
        })
    return detections


async def scan_webshells(
    target_path: str = "",
    max_file_bytes: int = _MAX_FILE_BYTES,
) -> dict[str, Any]:
    """Scan an owned web root for webshell indicators (read-only).

    Args:
        target_path: absolute path to the web root to scan (e.g. the server's
            ``/var/www/html`` or a workspace copy).
        max_file_bytes: per-file content cap for inspection.
    """
    target_path = (target_path or "").strip()
    if max_file_bytes > 0:
        max_file_bytes = max(1024, min(int(max_file_bytes), 8 * 1024 * 1024))

    if not target_path:
        return {
            "state": "UNAVAILABLE", "tool": "webshell_detector",
            "detail": "No target web root supplied.", "detections": [],
            "total": 0,
        }
    if not os.path.isdir(target_path):
        return {
            "state": "UNAVAILABLE", "tool": "webshell_detector",
            "detail": f"target_path is not a readable directory: {target_path}",
            "detections": [], "total": 0,
        }
    try:
        detections = _scan_tree(target_path, max_file_bytes)
    except Exception as exc:  # noqa: BLE001
        logger.warning("webshell scan failed for %r: %s", target_path, exc)
        return {
            "state": "ERROR", "tool": "webshell_detector",
            "detail": f"Scan failed: {type(exc).__name__}",
            "detections": [], "total": 0,
        }
    real = [d for d in detections if "file" in d]
    return {
        "state": "AVAILABLE", "tool": "webshell_detector",
        "detail": (f"Webshell scan complete — {len(real)} indicator(s) across "
                   f"{len(detections)} record(s)."),
        "target_path": target_path,
        "detections": detections,
        "total": len(real),
    }
