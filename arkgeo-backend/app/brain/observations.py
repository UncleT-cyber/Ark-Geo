"""Unified image-intelligence observations builder.

Centralizes how every forensic layer (File Forensics, OCR/Vision, Source
Discovery, Provenance/C2PA, AI hypothesis, Street View) becomes a structured
observation record.  These records are the single evidence currency of the
Investigation workspace:

    {
      "id": "OBS-0001",
      "type": "DEVICE_METADATA",
      "status": "OBSERVED",          # OBSERVED | NOT_OBSERVED | UNAVAILABLE | ANOMALY | HYPOTHESIS
      "layer": "File Forensics",
      "label": "Camera device identified",
      "detail": "Apple iPhone 15 Pro",
      "source": "tool_inference",     # cryptographic | tool_inference | ai_hypothesis
      "confidence": 0.99,
    }

This module is deliberately honest-by-design: absence of a signal is reported
as an explicit state (NOT_OBSERVED / UNAVAILABLE) rather than silence, and
never converted into a manipulation claim.
"""
from __future__ import annotations

from typing import Any, Optional


def _tget(tag: Any, key: str, default: Any = None) -> Any:
    """Attribute access for VisualEvidenceTag models or plain dicts."""
    if isinstance(tag, dict):
        return tag.get(key, default)
    return getattr(tag, key, default)

# --------------------------------------------------------------------------- #
# Image classification — Likely Screenshot / Camera / Exported / Unknown
# --------------------------------------------------------------------------- #
IMAGE_CLASS_CAMERA = "Likely Camera Photograph"
IMAGE_CLASS_SCREENSHOT = "Likely Screenshot"
IMAGE_CLASS_EXPORTED = "Likely Exported Image"
IMAGE_CLASS_UNKNOWN = "Unknown"

EXPORTABLE_FORMATS = ("png", "webp", "gif", "bmp", "tif", "tiff")

# Ordered fallback investigation ladder.  When one evidence source is missing
# or unavailable the next reachable path is offered to the analyst (and to the
# AI investigator) instead of dead-ending.
FALLBACK_LADDER: list[dict[str, Any]] = [
    {
        "id": "exif_geolocation",
        "label": "EXIF GPS pin + reverse geocode",
        "tool_id": "reverse_geocode",
        "requires_key": False,
        "resolves": "WHERE",
        "fallback": "streetview_panorama",
    },
    {
        "id": "streetview_panorama",
        "label": "Street View panorama on camera heading",
        "tool_id": "fetch_streetview_panorama",
        "requires_key": True,
        "resolves": "WHERE",
        "fallback": "ai_geolocation",
    },
    {
        "id": "ai_geolocation",
        "label": "AI vision geolocation hypothesis",
        "tool_id": "predict_geospy_coordinates",
        "requires_key": True,
        "resolves": "WHERE",
        "fallback": "vision_scene",
    },
    {
        "id": "vision_scene",
        "label": "Scene / landmark / climate analysis",
        "tool_id": "analyze_vision_scene",
        "requires_key": True,
        "resolves": "WHERE|WHAT",
        "fallback": "ocr_text",
    },
    {
        "id": "ocr_text",
        "label": "OCR text + infrastructure indicators",
        "tool_id": "extract_ocr_text",
        "requires_key": True,
        "resolves": "WHERE|WHAT",
        "fallback": "reverse_source",
    },
    {
        "id": "reverse_source",
        "label": "Reverse image source discovery",
        "tool_id": "search_reverse_source",
        "requires_key": True,
        "resolves": "SOURCE",
        "fallback": "local_fingerprint",
    },
    {
        "id": "local_fingerprint",
        "label": "Local fingerprint (pHash / duplicate detection)",
        "tool_id": "compute_perceptual_hash",
        "requires_key": False,
        "resolves": "SOURCE",
        "fallback": "deep_metadata",
    },
    {
        "id": "deep_metadata",
        "label": "ExifTool deep metadata tree",
        "tool_id": "extract_deep_metadata",
        "requires_key": False,
        "resolves": "WHAT|WHEN|HOW",
        "fallback": "consistency_engine",
    },
    {
        "id": "consistency_engine",
        "label": "Metadata consistency / timeline integrity",
        "tool_id": "run_consistency_engine",
        "requires_key": False,
        "resolves": "WHEN",
        "fallback": "c2pa_provenance",
    },
    {
        "id": "c2pa_provenance",
        "label": "C2PA / Content Credentials provenance",
        "tool_id": "verify_c2pa",
        "requires_key": False,
        "resolves": "PROVENANCE",
        "fallback": "ela_analysis",
    },
    {
        "id": "ela_analysis",
        "label": "Error-level analysis for local edits",
        "tool_id": "run_ela",
        "requires_key": False,
        "resolves": "INTEGRITY",
        "fallback": "geolocation_fusion",
    },
    {
        "id": "geolocation_fusion",
        "label": "Cross-layer geolocation fusion + contradictions",
        "tool_id": "fuse_geolocation",
        "requires_key": False,
        "resolves": "WHERE",
        "fallback": None,
    },
]


def classify_image(result) -> str:
    """Classify the image into one of the four investigation asset types.

    Screenshot heuristics dominate when present; camera provenance wins for
    real photographs; stripped non-camera containers are treated as exported
    images; otherwise the class is Unknown (never fabricated).
    """
    imint = result.image_intelligence or {}
    analysis = imint.get("analysis") or {}
    if analysis.get("is_screenshot_likely"):
        return IMAGE_CLASS_SCREENSHOT

    device = imint.get("device") or {}
    if device.get("has_provenance") or result.camera:
        return IMAGE_CLASS_CAMERA

    fmt = (result.file_format or "").lower()
    if fmt in EXPORTABLE_FORMATS and result.exif_missing:
        return IMAGE_CLASS_EXPORTED

    return IMAGE_CLASS_UNKNOWN


def screenshot_strategy(result) -> list[str]:
    """Investigation strategy switch for screenshot-classified images."""
    imint = result.image_intelligence or {}
    analysis = imint.get("analysis") or {}
    if not analysis.get("is_screenshot_likely"):
        return []
    return [
        "OCR the captured frame for UI text / usernames / app identifiers",
        "Reverse-search the frame for the original post or thread",
        "Extract embedded URLs from metadata",
        "Correlate visible logos / watermarks with known app UIs",
        "Trace source timeline via exact / visually-similar matches",
    ]


# --------------------------------------------------------------------------- #
# Structured observations
# --------------------------------------------------------------------------- #
class ObservationBuilder:
    """Builds the canonical observation list for an analysis result."""

    def __init__(self) -> None:
        self._observations: list[dict[str, Any]] = []
        self._seq = 0

    def _next_id(self) -> str:
        self._seq += 1
        return f"OBS-{self._seq:04d}"

    def add(
        self,
        type_: str,
        status: str,
        layer: str,
        label: str,
        detail: str,
        source: str = "tool_inference",
        confidence: Optional[float] = None,
    ) -> dict[str, Any]:
        obs = {
            "id": self._next_id(),
            "type": type_,
            "status": status,
            "layer": layer,
            "label": label,
            "detail": detail,
            "source": source,
            "confidence": confidence,
        }
        self._observations.append(obs)
        return obs

    def build(self, result) -> list[dict[str, Any]]:
        self._observations = []
        self._seq = 0
        imint = result.image_intelligence or {}
        analysis = imint.get("analysis") or {}
        device = imint.get("device") or {}
        temporal = imint.get("temporal") or {}
        geospatial = imint.get("geospatial") or {}
        capture = imint.get("capture") or {}

        # ---- Custody / cryptographic (WHAT it is) -------------------------- #
        self.add(
            "CUSTODY", "OBSERVED", "File Forensics",
            "Custody certificate computed",
            f"SHA-256 {result.image_sha256[:16]}… · SHA-1 / MD5 triple hash",
            "cryptographic", 1.0,
        )

        # ---- IMINT 4-pillar (WHAT / WHEN / WHERE / HOW) ------------------- #
        if device.get("has_provenance"):
            self.add(
                "DEVICE_METADATA", "OBSERVED", "File Forensics",
                "Camera device identified (WHAT)",
                " ".join(str(v) for v in
                         (device.get("make"), device.get("model")) if v),
                "tool_inference", 0.98,
            )
        else:
            self.add(
                "DEVICE_METADATA", "NOT_OBSERVED", "File Forensics",
                "No camera provenance",
                "No Make / Model / serial recorded — consistent with an exported "
                "or re-encoded asset.",
                "tool_inference", None,
            )

        if temporal.get("has_timestamps"):
            self.add(
                "TEMPORAL_METADATA", "OBSERVED", "File Forensics",
                "Capture time recorded (WHEN)",
                f"DateTimeOriginal: {temporal.get('datetime_original') or 'unknown'}",
                "tool_inference", 0.95,
            )
        else:
            self.add(
                "TEMPORAL_METADATA", "NOT_OBSERVED", "File Forensics",
                "No capture timestamps",
                "DateTime / GPS timestamps absent — timeline cannot be anchored.",
                "tool_inference", None,
            )

        if geospatial.get("has_coordinates"):
            self.add(
                "GEOLOCATION", "OBSERVED", "File Forensics",
                "GPS coordinates present (WHERE)",
                f"{geospatial.get('latitude_decimal')}, {geospatial.get('longitude_decimal')}",
                "tool_inference", 1.0,
            )
        else:
            self.add(
                "GEOLOCATION", "NOT_OBSERVED", "File Forensics",
                "No embedded GPS coordinates",
                "GPS stripped or never recorded — falls back to AI / visual geolocation.",
                "tool_inference", None,
            )

        if capture.get("has_capture"):
            self.add(
                "CAPTURE_METADATA", "OBSERVED", "File Forensics",
                "Capture diagnostics present (HOW)",
                f"ISO {capture.get('iso')} · f/{capture.get('f_number')} · "
                f"{capture.get('exposure_time_str')}s · {capture.get('focal_length_35mm')}mm",
                "tool_inference", 0.9,
            )

        if result.exif_missing or getattr(result, "metadata_status", None) == "STRIPPED_BY_INTERMEDIARY":
            partial = bool(result.exif_raw) and not result.exif_missing
            self.add(
                "METADATA_STATE", "ANOMALY", "File Forensics",
                "EXIF metadata stripped by intermediary"
                if partial else "EXIF metadata stripped or missing",
                (
                    "Camera EXIF block survived but GPS was removed by an "
                    "intermediary — routed to the secondary visual fallback pipeline."
                    if partial else
                    "No usable EXIF block — the dominant reason downstream sources were required."
                ),
                "tool_inference", None,
            )

        # ---- Integrity / structure ---------------------------------------- #
        if result.steganography_detected:
            self.add(
                "INTEGRITY", "ANOMALY", "File Forensics",
                "Trailing bytes after EOF",
                f"{result.trailing_bytes_count} bytes appended beyond the JPEG/PNG end marker.",
                "cryptographic", None,
            )
        else:
            self.add(
                "INTEGRITY", "OBSERVED", "File Forensics",
                "No structural anomalies",
                "EOF markers clean — no trailing steganographic payload detected.",
                "cryptographic", None,
            )

        # ---- Consistency findings ----------------------------------------- #
        for f in (result.consistency_findings or []):
            sev = f.get("status", "WARNING")
            self.add(
                "CONSISTENCY",
                "ANOMALY" if sev != "OK" else "OBSERVED",
                "File Forensics",
                f.get("type", "CONSISTENCY"),
                f.get("message", ""),
                "tool_inference", None,
            )

        # ---- OCR / Vision --------------------------------------------------- #
        tags = (result.consensus.visual_evidence_tags
                if result.consensus else [])
        ocr_tags = [t for t in tags if _tget(t, "category") == "ocr"]
        visual_tags = [t for t in tags if _tget(t, "category") != "ocr"]

        vision_available = result.source not in ("EXIF_MISSING_NO_AI_KEY",)
        if vision_available:
            self.add(
                "OCR", "OBSERVED", "OCR & Vision",
                f"OCR completed — {len(ocr_tags)} text region(s) detected",
                "; ".join(_tget(t, "label", "") for t in ocr_tags[:5]) or "no text regions",
                "tool_inference", 0.6,
            )
        else:
            self.add(
                "OCR", "UNAVAILABLE", "OCR & Vision",
                "OCR provider not configured",
                "OCR and visual extraction require an LLM provider key (Admin).",
                "tool_inference", None,
            )

        for t in visual_tags:
            self.add(
                "VISUAL", "OBSERVED", "OCR & Vision",
                f"{_tget(t, 'category', '').upper()} clue: {_tget(t, 'label')}",
                f"{_tget(t, 'label')} · confidence {float(_tget(t, 'confidence', 0)):.0%}",
                "ai_hypothesis" if _tget(t, "category") in ("architecture", "botanical", "infrastructure") else "tool_inference",
                float(_tget(t, "confidence", 0)),
            )

        # ---- Provenance / C2PA -------------------------------------------- #
        prov = result.provenance or {}
        pstate = prov.get("state", "UNAVAILABLE")
        if pstate == "VERIFIED":
            self.add(
                "PROVENANCE", "OBSERVED", "Provenance / C2PA",
                "Content Credentials verified",
                prov.get("detail", ""),
                "tool_inference", None,
            )
        elif pstate in ("INVALID", "INCOMPLETE"):
            self.add(
                "PROVENANCE", "ANOMALY", "Provenance / C2PA",
                f"C2PA state: {pstate}",
                prov.get("detail", ""),
                "tool_inference", None,
            )
        else:
            self.add(
                "PROVENANCE", "UNAVAILABLE", "Provenance / C2PA",
                "No Content Credentials / C2PA manifest detected",
                prov.get("detail", "C2PA verification unavailable — absence is not "
                                   "proof of manipulation."),
                "tool_inference", None,
            )

        # ---- Source discovery --------------------------------------------- #
        disc = result.source_discovery or {}
        if disc.get("state") == "AVAILABLE":
            self.add(
                "SOURCE_DISCOVERY", "OBSERVED", "Source Discovery",
                f"Reverse search available ({disc.get('provider') or 'provider'})",
                f"{len(disc.get('exact_matches', []))} exact · "
                f"{len(disc.get('similar_matches', []))} similar · pHash {disc.get('phash','')[:16]}…",
                "ai_hypothesis", 0.6,
            )
        else:
            self.add(
                "SOURCE_DISCOVERY", "UNAVAILABLE", "Source Discovery",
                "Reverse source search not configured",
                "Local pHash fingerprint computed; provider key required for web matches.",
                "tool_inference", None,
            )

        # ---- AI hypothesis providers --------------------------------------- #
        ai = result.ai_evidence or {}
        if ai.get("geospy"):
            g = ai["geospy"]
            self.add(
                "AI_HYPOTHESIS", "HYPOTHESIS", "AI Geolocation",
                "GeoSpy location hypothesis",
                f"{g.get('estimated_latitude')}, {g.get('estimated_longitude')} "
                f"· {float(g.get('confidence_score', 0)):.0%}",
                "ai_hypothesis", float(g.get("confidence_score", 0)),
            )
        if ai.get("scene"):
            s = ai["scene"]
            scene_tags = (s.get("evidence_tags") or s.get("ocr_texts") or [])
            self.add(
                "AI_HYPOTHESIS", "HYPOTHESIS", "OCR & Vision",
                "Vision scene hypothesis",
                "; ".join(str(x) for x in scene_tags[:5])
                or "scene analysis produced no tags",
                "ai_hypothesis", float(s.get("confidence_score", 0)),
            )

        # ---- Street View --------------------------------------------------- #
        sv = result.streetview
        if sv:
            status = "OBSERVED" if sv.get("state") == "AVAILABLE" else "UNAVAILABLE"
            self.add(
                "STREETVIEW", status, "Spatial",
                "Street View panorama" if sv.get("state") == "AVAILABLE"
                else "Street View unavailable",
                sv.get("detail", "") or f"pano {sv.get('pano_id')} at heading {sv.get('heading')}",
                "tool_inference", None,
            )

        # ---- Image classification ------------------------------------------ #
        cls = classify_image(result)
        self.add(
            "IMAGE_CLASS", "OBSERVED", "File Forensics",
            f"Asset classified: {cls}",
            screenshot_strategy(result)[0] if cls == IMAGE_CLASS_SCREENSHOT
            else f"Image treated as {cls} for downstream strategy selection.",
            "tool_inference", None,
        )

        return self._observations


def build_observations(result) -> list[dict[str, Any]]:
    """Public entry — build the canonical observation list for a result."""
    return ObservationBuilder().build(result)


# --------------------------------------------------------------------------- #
# Fallback ladder state
# --------------------------------------------------------------------------- #
def ladder_state(result) -> dict[str, Any]:
    """Report the state of every fallback ladder step for the current result.

    Each step is either ``ran`` (produced by this analysis), ``reachable``
    (not yet consumed but its requirements are satisfied), ``blocked``
    (requires a provider key that is not configured), or ``skipped``.
    """
    ran_tools: set[str] = set()
    if result.coordinates:
        ran_tools.add("reverse_geocode")
    if result.streetview:
        ran_tools.add("fetch_streetview_panorama")
    if (result.ai_evidence or {}).get("geospy"):
        ran_tools.add("predict_geospy_coordinates")
    if (result.ai_evidence or {}).get("scene"):
        ran_tools.add("analyze_vision_scene")
    if (result.ai_evidence or {}).get("source_discovery"):
        ran_tools.add("search_reverse_source")

    has_keys = {
        "fetch_streetview_panorama": _key_configured("google_maps_api_key"),
        "predict_geospy_coordinates": _key_configured("geospy_api_key")
        or _key_configured("gemini_api_key"),
        "analyze_vision_scene": _key_configured("gemini_api_key")
        or _key_configured("anthropic_api_key")
        or _key_configured("llm_api_key"),
        "extract_ocr_text": _key_configured("llm_api_key")
        or _key_configured("gemini_api_key"),
        "search_reverse_source": _key_configured("tineye_api_key")
        or _key_configured("serper_api_key")
        or _key_configured("reverse_search_api_key"),
    }

    steps = []
    for step in FALLBACK_LADDER:
        tid = step["tool_id"]
        keyed = tid in has_keys
        ran = tid in ran_tools
        if tid == "compute_perceptual_hash":
            ran = bool((result.source_discovery or {}).get("phash"))
        if tid in ("extract_deep_metadata", "consistency_engine",
                   "c2pa_provenance", "run_ela", "geolocation_fusion"):
            ran = True  # deterministic layers always run in the cascade
        if ran:
            status = "ran"
        elif keyed and has_keys[tid]:
            status = "reachable"
        elif keyed:
            status = "blocked"
        else:
            status = "reachable"
        steps.append({
            "id": step["id"],
            "label": step["label"],
            "tool_id": tid,
            "requires_key": keyed,
            "resolves": step["resolves"],
            "fallback": step["fallback"],
            "status": status,
        })

    run_count = sum(1 for s in steps if s["status"] == "ran")
    blocked_count = sum(1 for s in steps if s["status"] == "blocked")
    reachable = [s["id"] for s in steps if s["status"] == "reachable"]
    return {
        "steps": steps,
        "ran": run_count,
        "total": len(steps),
        "blocked": blocked_count,
        "reachable_next": reachable[0] if reachable else None,
        "complete": run_count == len(steps),
    }


def _key_configured(name: str) -> bool:
    try:
        from app.services.settings_store import settings_store
        return bool(settings_store.get_key(name))
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Context-aware next steps (Investigate Next)
# --------------------------------------------------------------------------- #
NEXT_STEP_GOALS = {
    "verify_location_credibility": "verify_location_credibility",
    "device_attribution": "device_attribution",
    "tamper_detection": "tamper_detection",
    "source_discovery": "source_discovery",
    "full_forensic_profile": "full_forensic_profile",
}


def build_next_steps(result, unknown: list[str], suspicious: list[str]) -> list[dict[str, Any]]:
    """Build structured, context-aware recommendations from the actual
    evidence state.  Each step carries an ARK AI investigation goal so the
    frontend can launch a real investigation with one click."""
    steps: list[dict[str, Any]] = []
    seq = 0

    def _step(action: str, reason: str, goal: str, priority: str,
              claim: Optional[str] = None) -> None:
        nonlocal seq
        seq += 1
        steps.append({
            "id": f"NS-{seq:02d}",
            "action": action,
            "reason": reason,
            "goal": NEXT_STEP_GOALS.get(goal, "full_forensic_profile"),
            "priority": priority,
            "claim": claim,
        })

    no_coords = "Location: no coordinates established" in unknown
    exif_stripped = "Metadata: EXIF stripped/missing" in unknown
    disc_unavailable = "Source discovery: not configured" in unknown
    prov_unavailable = "Provenance: UNAVAILABLE" in unknown
    contradictions = any("Contradiction" in s or "spoofing" in s for s in suspicious)

    if no_coords:
        _step(
            "Run AI geolocation investigation",
            "No GPS embedded — AI vision + scene hypothesis required to establish a location.",
            "verify_location_credibility", "high", "gps.location",
        )
        _step(
            "Reverse-search the image",
            "Exact / visually-similar matches reveal the source and earliest-seen timestamp.",
            "source_discovery", "high",
        )
    elif not contradictions:
        _step(
            "Verify resolved location against independent sources",
            "Location pinned — corroborate with Street View and reverse geocoding.",
            "verify_location_credibility", "medium", "gps.location",
        )

    if exif_stripped:
        _step(
            "Attributing the device and capture timeline",
            "EXIF stripped — infer device / timeline from structural fingerprints and image class.",
            "device_attribution", "medium", "device.make",
        )

    if contradictions or any("spoofing" in s for s in suspicious):
        _step(
            "Investigate detected contradictions",
            "Conflicting evidence layers require a tamper-detection pass.",
            "tamper_detection", "high",
        )

    if disc_unavailable:
        _step(
            "Complete source discovery",
            "Reverse-search provider not configured — local pHash only.",
            "source_discovery", "medium",
        )
    if prov_unavailable:
        _step(
            "Deep-dive provenance state",
            "No C2PA manifest — verify integrity claim via tamper pass.",
            "tamper_detection", "low",
        )

    if not steps:
        _step(
            "Full forensic profile",
            "All primary signals consumed — build the complete investigation profile.",
            "full_forensic_profile", "low",
        )

    return steps


# --------------------------------------------------------------------------- #
# Location hypothesis (GPS-off / location-stripped images)
# --------------------------------------------------------------------------- #
def build_location_hypothesis(result) -> Optional[dict[str, Any]]:
    """When no coordinates were established, surface geographic clues and a
    best-effort hypothesis with supporting / contradicting evidence and
    explicit confidence.  Never fabricates coordinates that were not produced."""
    if result.coordinates:
        return None

    fusion = result.geolocation_fusion or {}
    hypothesis = fusion.get("hypothesis")
    supporting = [
        {"layer": e.get("layer"), "label": e.get("label")}
        for e in fusion.get("supporting", [])
        if e.get("direction") in ("supporting", "neutral")
    ]
    contradicting = [
        {"layer": e.get("layer"), "label": e.get("label")}
        for e in fusion.get("contradicting", [])
        if e.get("direction") == "contradicting"
    ]

    ai = result.ai_evidence or {}
    if hypothesis is None and ai.get("geospy"):
        g = ai["geospy"]
        if g.get("estimated_latitude") is not None:
            hypothesis = {
                "lat": g["estimated_latitude"],
                "lon": g["estimated_longitude"],
            }
            supporting.append({
                "layer": "ai_hypothesis",
                "label": f"GeoSpy: {g.get('location_hint') or 'predicted coordinates'}",
            })

    confidence = float(fusion.get("confidence", 0.0))
    if hypothesis is None and ai.get("geospy"):
        confidence = float((ai["geospy"] or {}).get("confidence_score", 0.0)) or confidence

    clues = _geographic_clues(result)
    alternatives = []
    if hypothesis:
        alternatives = [
            {"claim": "GPS was stripped from the original camera file", "confidence": 0.4},
            {"claim": "Image is a repost of an originally-geotagged capture", "confidence": 0.3},
        ]

    return {
        "hypothesis": hypothesis,
        "confidence": confidence,
        "supporting": supporting,
        "contradicting": contradicting,
        "clues": clues,
        "alternatives": alternatives,
        "note": "No embedded GPS — location is a hypothesis requiring corroboration, not a verified pin." if hypothesis
                else "No GPS and no AI provider produced coordinates — location cannot be established.",
    }


def _geographic_clues(result) -> list[str]:
    """Surface non-coordinate geographic signals for GPS-off images."""
    clues: list[str] = []
    imint = result.image_intelligence or {}
    analysis = imint.get("analysis") or {}
    if result.gps_climate_zone:
        clues.append(f"Climate zone (GPS parity): {result.gps_climate_zone}")
    if result.visual_climate_zone:
        clues.append(f"Climate zone (visual): {result.visual_climate_zone}")
    for tag in (result.consensus.visual_evidence_tags if result.consensus else []):
        clues.append(f"{_tget(tag, 'category', '').upper()}: {_tget(tag, 'label')}")
    urls = (result.source_discovery or {}).get("embedded_urls") or []
    for url in urls[:3]:
        clues.append(f"Embedded URL: {url}")
    if analysis.get("is_screenshot_likely"):
        clues.append("Asset classified as screenshot — frame contents (UI / text) are the primary clues")
    return clues
