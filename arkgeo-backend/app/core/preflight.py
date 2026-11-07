"""Startup preflight — report optional external-binary availability honestly.

THE ARK degrades gracefully when an optional binary is missing: ExifTool-backed
deep metadata, the managed Chromium runtime, and the CAI network binaries simply
report UNAVAILABLE rather than failing the run. That silence is correct at
runtime but unhelpful at onboarding — a fresh checkout can look healthy while
several capabilities are dark.

This module makes the state visible once, at startup, in one log line per
capability, without ever blocking boot.
"""
from __future__ import annotations

import logging
import shutil

logger = logging.getLogger("arkgeo.preflight")

# External binaries the CAI network/recon tool adapters shell out to. Absent
# ones make their tool report an error result instead of a real answer.
_CAI_BINARIES = ("dig", "nmap", "whois", "gobuster", "curl")

_BINARY_HINTS = {
    "exiftool": "brew install exiftool  (deep metadata will report UNAVAILABLE)",
    "browser": "playwright install chromium  (browser.* tools will report UNAVAILABLE)",
    "dig": "apt install dnsutils  (net.dns_lookup will error)",
    "nmap": "apt install nmap  (net.nmap_scan will error)",
    "whois": "apt install whois  (net.whois will error)",
    "gobuster": "apt install gobuster  (web content discovery will error)",
    "curl": "apt install curl  (web probes will error)",
}


def _exiftool_path() -> str | None:
    return shutil.which("exiftool")


def _browser_available() -> bool:
    try:
        from app.tools.web_intel import browser as browser_runtime
        return bool(browser_runtime.availability().get("available"))
    except Exception:  # noqa: BLE001 — a missing runtime is not fatal
        return False


def check_binaries() -> dict[str, dict]:
    """Return per-capability availability without raising."""
    status: dict[str, dict] = {
        "exiftool": {"available": (path := _exiftool_path()) is not None,
                     "path": path},
        "browser": {"available": _browser_available()},
    }
    for name in _CAI_BINARIES:
        path = shutil.which(name)
        status[name] = {"available": path is not None, "path": path}
    return status


def report() -> dict[str, dict]:
    """Log one line per capability and return the availability map."""
    status = check_binaries()
    for name, info in status.items():
        if info["available"]:
            detail = info.get("path") or "ready"
            logger.info("preflight: %s available (%s)", name, detail)
        else:
            hint = _BINARY_HINTS.get(name, "optional capability disabled")
            logger.warning("preflight: %s NOT available — %s", name, hint)
    return status
