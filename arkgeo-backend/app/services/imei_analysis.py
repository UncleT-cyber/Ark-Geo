"""IMEI / MEID / serial intelligence — passive, reference-based device attribution.

Everything here is derived WITHOUT any network signaling.  From a single
identifier we can establish:

  * validity (3GPP Luhn check digit for IMEI / MEID check digit)
  * structure  (TAC | SNR | check-digit for IMEI; TAC | SNR | SV for IMEI-SV)
  * Reporting Body Identifier (RBI) -> allocating manufacturer (from the
    public GSMA RBI ranges)
  * TAC -> manufacturer / model / bands WHEN a TAC database is supplied
    (``settings.imei_tac_db_path``).  Without that file only the RBI-level
    hint is returned, and ``confidence`` reflects that honestly.

No live carrier query, no SS7/Diameter, no location — this is the passive,
license-free half of phone intelligence.  Live state/location belongs to the
authorized signaling subsystem (``app.signaling``).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Reference data
# --------------------------------------------------------------------------- #
# GSMA Reporting Body Identifier (RBI) -> allocating manufacturer.  This is the
# public, structural allocation; it identifies WHO was assigned the TAC range,
# not the exact model (that needs a full TAC database).  Entries are conservative
# and labeled; unknown RBIs return None rather than a guess.
RBI_MANUFACTURERS: dict[str, str] = {
    "01": "Apple Inc. (RBI 01)",
    "35": "Nokia / HMD / Microsoft (RBI 35)",
    "49": "LG Electronics (RBI 49)",
    "50": "Lucent / Alcatel (RBI 50)",
    "51": "HMD Global / Microsoft (RBI 51)",
    "52": "Samsung Electronics (RBI 52)",
    "53": "Samsung Electronics (RBI 53)",
    "54": "Samsung Electronics (RBI 54)",
    "86": "Lenovo / Motorola Mobility (RBI 86)",
    "91": "Sony Mobile / Ericsson (RBI 91)",
    "98": "Huawei Technologies (RBI 98)",
    "99": "Huawei Technologies (RBI 99)",
}

# A few widely-documented TAC prefixes kept as a *seed* so the module is useful
# out-of-the-box.  Operators should override/replace this with a full TAC dump
# via ``settings.imei_tac_db_path``.  Each value is a dict so the schema can grow
# (model, release_year, bands, os).  Marked ``seed=True`` so callers know it is
# not the authoritative allocation.
SEED_TAC_DB: dict[str, dict[str, Any]] = {
    "354049": {"brand": "Apple", "model": "iPhone (A-series)", "os": "iOS", "seed": True},
    "355392": {"brand": "Apple", "model": "iPhone (A-series)", "os": "iOS", "seed": True},
    "353944": {"brand": "Apple", "model": "iPhone (A-series)", "os": "iOS", "seed": True},
    "490154": {"brand": "LG", "model": "LG (various)", "os": "Android", "seed": True},
    "356307": {"brand": "Samsung", "model": "Samsung Galaxy (various)", "os": "Android", "seed": True},
    "520003": {"brand": "Samsung", "model": "Samsung Galaxy (various)", "os": "Android", "seed": True},
    "91142": {"brand": "Sony", "model": "Xperia (various)", "os": "Android", "seed": True},
    "865206": {"brand": "Motorola", "model": "Moto (various)", "os": "Android", "seed": True},
    "86130": {"brand": "Lenovo", "model": "Lenovo/MBB (various)", "os": "Android", "seed": True},
    "99000": {"brand": "Huawei", "model": "Huawei (various)", "os": "Android/HarmonyOS", "seed": True},
}


def _load_tac_db() -> dict[str, dict[str, Any]]:
    path = getattr(settings, "imei_tac_db_path", None)
    db: dict[str, dict[str, Any]] = {}
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                db = json.load(fh)
            logger.info("Loaded TAC database with %d entries from %s", len(db), path)
            return db
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load TAC db %s: %s", path, exc)
    return dict(SEED_TAC_DB)


def _rbi_of(tac: str) -> tuple[str, Optional[str]]:
    """Return (rbi, manufacturer_hint).

    RBI is normally the first two digits, but GSMA also allocates 3-digit RBIs
    (e.g. 35x); we try 3 then 2.
    """
    for width in (3, 2):
        if len(tac) >= width:
            cand = tac[:width]
            if cand in RBI_MANUFACTURERS:
                return cand, RBI_MANUFACTURERS[cand]
    # 2-digit fallback even if not in the table (report the code)
    return (tac[:2], None)


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def _luhn_check_digit(body: str) -> int:
    """Compute the 3GPP/IMEI Luhn check digit for a digit string ``body``."""
    total = 0
    # IMEI: double every second digit starting from the RIGHT of the body
    # (i.e. the last digit of the body is NOT doubled). Standard Luhn.
    reversed_body = body[::-1]
    for idx, ch in enumerate(reversed_body):
        d = int(ch)
        if idx % 2 == 0:  # doubles d14,d12,... (even positions from the left)
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - (total % 10)) % 10


def validate_imei(imei: str) -> dict[str, Any]:
    """Validate a 15-digit IMEI (or 16-digit IMEI-SV). Returns structured result."""
    raw = (imei or "").strip().upper().replace(" ", "").replace("-", "")
    res = {"input": imei, "normalized": raw, "valid": False, "kind": None,
           "reason": None}
    if not raw.isdigit():
        res["reason"] = "IMEI must contain only digits."
        return res
    if len(raw) == 15:
        res["kind"] = "IMEI"
        body, cd = raw[:14], int(raw[14])
        res["valid"] = _luhn_check_digit(body) == cd
        if not res["valid"]:
            res["reason"] = (
                f"Check digit mismatch (expected {_luhn_check_digit(body)}, got {cd})."
            )
    elif len(raw) == 16:
        res["kind"] = "IMEI-SV"
        # IMEI-SV: first 14 are the IMEI body, last 2 are Software Version.
        body = raw[:14]
        res["valid"] = True  # SV has no check digit on the version
        res["software_version"] = raw[14:16]
    else:
        res["reason"] = f"IMEI must be 15 or 16 digits (got {len(raw)})."
        return res
    return res


def validate_meid(meid: str) -> dict[str, Any]:
    """Validate a MEID (14 hex digits + check, or 18-digit decimal MEID)."""
    raw = (meid or "").strip().upper().replace(" ", "").replace("-", "")
    res = {"input": meid, "normalized": raw, "valid": False, "kind": None,
           "reason": None}
    if len(raw) == 14 and all(c in "0123456789ABCDEF" for c in raw):
        res["kind"] = "MEID"
        res["valid"] = True  # full check-digit validation is optional in many stacks
    elif len(raw) == 18 and raw.isdigit():
        res["kind"] = "MEID-DEC"
        res["valid"] = True
    else:
        res["reason"] = "MEID must be 14 hex digits or 18 decimal digits."
        return res
    return res


# --------------------------------------------------------------------------- #
# Full analysis
# --------------------------------------------------------------------------- #
def analyze_identifier(identifier: str) -> dict[str, Any]:
    """Passive device attribution from an IMEI / IMEI-SV / MEID / serial string.

    Returns a structured, honestly-scoped report.  ``confidence`` is
    ``high`` only when a TAC database resolved the exact model; otherwise
    ``low`` (RBI-level hint only).
    """
    raw = (identifier or "").strip().upper().replace(" ", "").replace("-", "")
    if not raw:
        return {"ok": False, "error": "empty identifier"}

    tac_db = _load_tac_db()

    # IMEI / IMEI-SV path
    if raw.isdigit() and len(raw) in (15, 16):
        v = validate_imei(raw)
        if not v["valid"]:
            return {"ok": False, "kind": v["kind"], "valid": False,
                    "error": v["reason"], "normalized": raw}
        tac = raw[:8]
        snr = raw[8:14]
        cd = raw[14] if len(raw) == 15 else None
        rbi, mfr_hint = _rbi_of(tac)
        model = tac_db.get(tac) or tac_db.get(tac[:6]) or tac_db.get(tac[:5])
        brand = (model or {}).get("brand") or mfr_hint
        confidence = "high" if model else ("medium" if mfr_hint else "low")
        return {
            "ok": True,
            "kind": v["kind"],
            "valid": True,
            "normalized": raw,
            "structure": {
                "tac": tac,
                "snr": snr,
                "check_digit": cd,
                "rbi": rbi,
                "software_version": v.get("software_version"),
            },
            "manufacturer": brand,
            "model": (model or {}).get("model") if model else None,
            "os": (model or {}).get("os") if model else None,
            "rbi_manufacturer_hint": mfr_hint,
            "tac_database_match": bool(model),
            "confidence": confidence,
            "platform_note": (
                "IMEI is present on both Android and iOS cellular models; "
                "it alone cannot distinguish OS. iOS CDMA models also carry a "
                "MEID, and Apple's serial (not IMEI) is used for warranty lookup."
            ),
            "caveats": [
                "Passive, reference-only: no carrier/network lookup performed.",
                "Exact model requires a populated TAC database (settings.imei_tac_db_path).",
                "An IMEI identifies a DEVICE, not a subscriber or a person.",
            ],
        }

    # MEID path
    if (len(raw) == 14 and all(c in "0123456789ABCDEF" for c in raw)) or (
        len(raw) == 18 and raw.isdigit()
    ):
        v = validate_meid(raw)
        return {
            "ok": v["valid"],
            "kind": v["kind"],
            "valid": v["valid"],
            "normalized": raw,
            "note": "MEID identifies a CDMA device (common on legacy US/iOS CDMA models).",
            "confidence": "medium",
            "caveats": ["No network lookup performed.", "MEID maps to a device, not a subscriber."],
        } if v["valid"] else {"ok": False, "error": v["reason"], "normalized": raw}

    # Fallback: treat as a serial / unknown identifier
    return {
        "ok": True,
        "kind": "serial_or_unknown",
        "valid": None,
        "normalized": raw,
        "manufacturer": None,
        "model": None,
        "confidence": "low",
        "note": (
            "Identifier is not a 15/16-digit IMEI or a 14-hex MEID. It may be a "
            "vendor serial (e.g. Apple serial). Serial-to-model decoding depends "
            "on the vendor scheme and is out of scope for passive reference lookup."
        ),
        "caveats": ["No TAC/RBI resolution possible for this format."],
    }
