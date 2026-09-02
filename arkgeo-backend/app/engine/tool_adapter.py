"""THE ARK — Real ARK → CAI Tool Registry.

Every tool here is *functional*: it invokes a real THE ARK backend service or a
real local/network binary (nmap, gobuster, dig, whois, exiftool). There are no
simulated placeholders — if a backend or binary is unavailable the tool returns
a structured *error*, never fabricated success data.

Tool schemas are generated with CAI's own ``function_schema`` utility (the CAI
original), so the tool surface THE ARK exposes to the model is produced by CAI's
schema engine. The orchestrator feeds these schemas to the model and dispatches
execution through :func:`call_tool`.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field

# Register the CAI ORIGINAL on sys.path so ``import cai`` resolves to the real
# runtime (the path-shim in app.engine.cai). Imported for its side effect.
import app.engine.cai  # noqa: F401

# Risk tiers gate Human-In-The-Loop (HITL) approval in the orchestrator.
RISK_NONE = "none"
RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"


@dataclass
class ArkTool:
    id: str
    name: str
    description: str
    domain: str
    func: callable
    risk: str = RISK_NONE
    schema: dict | None = None
    simulated: bool = False  # all ARK tools are real; flag kept for compat


# --------------------------------------------------------------------------- #
# Real tool implementations
# --------------------------------------------------------------------------- #
def _run(coro):
    if inspect.iscoroutine(coro):
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        if loop.is_running():
            # We are already inside a running loop (e.g. the orchestrator's
            # async dispatch). Running run_until_complete would raise
            # "This event loop is already running", so execute the coroutine
            # on a brand new loop in a worker thread.
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                return ex.submit(
                    lambda: asyncio.new_event_loop().run_until_complete(coro)
                ).result()
        return loop.run_until_complete(coro)
    return coro


def _req_file(path: str) -> str:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"File not found: {path}")
    return path


def _imint_exiftool(image_path: str) -> str:
    """Extract deep EXIF/metadata from an image using ExifTool."""
    _req_file(image_path)
    from app.services.exiftool_service import ExifToolService

    with open(image_path, "rb") as fh:
        data = fh.read()
    return json.dumps(ExifToolService().extract_deep(data), default=str)


def _imint_reverse_image(image_path: str) -> str:
    """Run provider-agnostic reverse image search (pHash) on an image."""
    _req_file(image_path)
    from app.tools.reverse_image_tool import reverse_image_search

    with open(image_path, "rb") as fh:
        data = fh.read()
    return json.dumps(_run(reverse_image_search(image_data=data)), default=str)


def _imint_geocode(place: str) -> str:
    """Geocode a place name to coordinates via THE ARK geocoding service."""
    from app.tools.geocoding_tool import geocode_place

    return json.dumps(_run(geocode_place(place)), default=str)


def _recon_web_search(query: str, max_results: int = 5) -> str:
    """Search the web (Tavily primary, DuckDuckGo fallback) for OSINT."""
    from app.tools.web_search_tool import web_search

    return json.dumps(_run(web_search(query=query, max_results=max_results)), default=str)


def _recon_web_fetch(url: str, max_chars: int = 8000) -> str:
    """Fetch a URL and extract readable text."""
    from app.tools.web_search_tool import web_fetch

    return json.dumps(_run(web_fetch(url=url, max_chars=max_chars)), default=str)


def _net_dns_lookup(host: str) -> str:
    """Resolve DNS records for a host using dig."""
    r = subprocess.run(["dig", "+short", host], capture_output=True, text=True, timeout=30)
    return json.dumps({"host": host, "stdout": r.stdout.strip(), "stderr": r.stderr.strip(), "rc": r.returncode})


def _net_whois(target: str) -> str:
    """WHOIS lookup for a domain/network using the whois binary."""
    r = subprocess.run(["whois", target], capture_output=True, text=True, timeout=30)
    return json.dumps({"target": target, "stdout": r.stdout[:4000], "rc": r.returncode})


def _net_nmap_scan(target: str, ports: str = "") -> str:
    """Port/service scan of a host or subnet using nmap (robust, auto-degrading).

    Delegates to :func:`app.tools.pen_test.nmap_scanner_tool.nmap_scan` so the
    network tool inherits the same graceful behaviour: structured XML parsing,
    partial-output capture on timeout, and automatic degradation to a fast
    top-100 scan instead of failing outright.  Defaults to the 100 most common
    ports so a standard scan completes comfortably within the timeout.
    """
    from app.tools.pen_test.nmap_scanner_tool import nmap_scan

    result = _run(nmap_scan(
        host=target, ports=ports, top_ports=100, no_ping=True,
        scan_type="tcp_connect", timing="T4", service_version=True,
        timeout=60,
    ))
    return json.dumps(result, default=str)


def _net_dir_enum(target: str, wordlist: str = "common") -> str:
    """Directory/endpoint enumeration on a web target using gobuster."""
    # Use a small built-in wordlist so the tool is self-contained and real.
    wl = os.path.join(os.path.dirname(__file__), "wordlists", "dirs.txt")
    if not os.path.isfile(wl):
        return json.dumps({"error": "wordlist missing", "target": target})
    r = subprocess.run(
        ["gobuster", "dir", "-u", target, "-w", wl, "-q", "-t", "20"],
        capture_output=True, text=True, timeout=240,
    )
    return json.dumps({"target": target, "stdout": r.stdout[:6000], "stderr": r.stderr[:500], "rc": r.returncode})


def _net_subdomain_enum(domain: str) -> str:
    """Enumerate subdomains via the crt.sh certificate transparency log."""
    import urllib.request

    url = f"https://crt.sh/?q=%.{domain}&output=json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ARK-CAI"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        subs = sorted({e["name_value"] for e in data})
        return json.dumps({"domain": domain, "subdomains": subs[:200], "count": len(subs)})
    except Exception as exc:
        return json.dumps({"domain": domain, "error": str(exc)})


def _net_curl_probe(url: str) -> str:
    """Probe a URL and capture status line + headers."""
    r = subprocess.run(
        ["curl", "-sS", "-I", "-m", "20", url],
        capture_output=True, text=True, timeout=30,
    )
    return json.dumps({"url": url, "headers": r.stdout.strip(), "rc": r.returncode})


def _siem_query(query: str, index: str = "*") -> str:
    """Query a configured SIEM endpoint (Elasticsearch _search compatible).

    Requires ARKGEO_SIEM_URL (e.g. http://localhost:9200). Without it the tool
    returns a real configuration error rather than fabricated results.
    """
    base = os.environ.get("ARKGEO_SIEM_URL")
    if not base:
        return json.dumps({"error": "SIEM endpoint not configured (set ARKGEO_SIEM_URL)"})
    import urllib.request

    try:
        body = json.dumps({"query": {"query_string": {"query": query}}, "size": 50}).encode()
        req = urllib.request.Request(
            f"{base.rstrip('/')}/{index}/_search",
            data=body, headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.dumps({"index": index, "query": query, "result": json.loads(resp.read().decode())}, default=str)
    except Exception as exc:
        return json.dumps({"index": index, "query": query, "error": str(exc)})


def _siem_ingest(path: str) -> str:
    """Read and summarise a log file for ingestion into the SIEM."""
    _req_file(path)
    with open(path, "r", errors="ignore") as fh:
        lines = fh.read().splitlines()[:500]
    return json.dumps({"path": path, "lines": len(lines), "preview": lines[:20]})


def _case_custody_hash(path: str) -> str:
    """Compute a SHA-256 chain-of-custody hash for an evidence file."""
    _req_file(path)
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return json.dumps({"path": path, "sha256": h.hexdigest(), "bytes": os.path.getsize(path)})


def _case_attach(case_id: str) -> str:
    """Attach (create) a case vault folder under the evidence store."""
    root = os.path.join("arkgeo_data", "cases")
    os.makedirs(root, exist_ok=True)
    case_dir = os.path.join(root, case_id)
    os.makedirs(case_dir, exist_ok=True)
    return json.dumps({"case_id": case_id, "vault": os.path.abspath(case_dir), "created": os.path.isdir(case_dir)})


def _case_evidence(evidence_id: str) -> str:
    """Inspect chain-of-custody metadata for an evidence id (JSON store)."""
    store = os.path.join("arkgeo_data", "cases", "evidence_index.json")
    if not os.path.isfile(store):
        return json.dumps({"evidence_id": evidence_id, "error": "no evidence index"})
    with open(store) as fh:
        idx = json.load(fh)
    return json.dumps({"evidence_id": evidence_id, "record": idx.get(evidence_id)})


# --------------------------------------------------------------------------- #
# Expanded ARK forensic / security suite wrappers (real backends)
# --------------------------------------------------------------------------- #
def _read_bytes(path: str) -> bytes:
    _req_file(path)
    with open(path, "rb") as fh:
        return fh.read()


def _imint_c2pa(image_path: str) -> str:
    """Inspect C2PA Content Credentials / provenance of an image."""
    data = _read_bytes(image_path)
    from app.services.exiftool_service import ExifToolService
    from app.services.c2pa_service import C2PAService

    groups = ExifToolService().extract_deep(data).get("groups", {})
    return json.dumps(C2PAService().analyze(data, groups), default=str)


def _imint_source_discovery(image_path: str) -> str:
    """Provider-agnostic reverse-image-source discovery (pHash + providers)."""
    data = _read_bytes(image_path)
    from app.services.exiftool_service import ExifToolService
    from app.services.source_discovery import SourceDiscoveryService

    groups = ExifToolService().extract_deep(data).get("groups", {})
    return json.dumps(SourceDiscoveryService().analyze(data, groups), default=str)


def _imint_phash(image_path: str) -> str:
    """Compute a local perceptual hash (pHash) fingerprint of an image."""
    from app.services.source_discovery import compute_phash

    return json.dumps({"phash": compute_phash(_read_bytes(image_path))})


def _imint_extract_urls(image_path: str) -> str:
    """Extract embedded URLs from image metadata (XMP/IPTC/EXIF)."""
    data = _read_bytes(image_path)
    from app.services.exiftool_service import ExifToolService
    from app.services.source_discovery import extract_embedded_urls

    groups = ExifToolService().extract_deep(data).get("groups", {})
    return json.dumps({"urls": extract_embedded_urls(groups)})


def _imint_reverse_geocode(lat: float, lon: float) -> str:
    """Reverse-geocode coordinates to a human address (Mapbox→Google)."""
    from app.services.geo_providers import reverse_geocode_mapbox, reverse_geocode_google

    r = reverse_geocode_mapbox(lat, lon) or reverse_geocode_google(lat, lon)
    return json.dumps(r, default=str) if r else json.dumps({"error": "no geocoder configured"})


def _imint_geocode_batch(queries: str) -> str:
    """Geocode a batch of place names (comma/newline separated)."""
    qlist = [q.strip() for q in queries.replace("\n", ",").split(",") if q.strip()]
    from app.services.geocoding_service import geocode_batch

    return json.dumps(_run(geocode_batch(qlist)), default=str)


def _imint_streetview(lat: float, lon: float) -> str:
    """Fetch Street View metadata + static image URL for coordinates."""
    from app.services.geo_providers import fetch_streetview

    return json.dumps(_run(fetch_streetview(lat, lon)), default=str)


def _imint_tineye(image_path: str) -> str:
    """Reverse image search via TinEye (requires API key)."""
    from app.services.geo_providers import search_tineye

    return json.dumps(_run(search_tineye(_read_bytes(image_path))), default=str)


def _imint_serper(query: str) -> str:
    """Web reverse-source search via Serper (requires API key)."""
    from app.services.geo_providers import search_serper

    return json.dumps(_run(search_serper(query)), default=str)


def _evidence_override(image_sha256: str, finding_key: str, decision: str, note: str = "") -> str:
    """Record an analyst override (confirm|reject|needs_review) with audit."""
    from app.services.analyst_overrides import AnalystOverrides

    return json.dumps(AnalystOverrides().record(image_sha256, finding_key, decision, note), default=str)


def _evidence_overrides(image_sha256: str) -> str:
    """List analyst overrides recorded for an evidence image."""
    from app.services.analyst_overrides import AnalystOverrides

    return json.dumps(AnalystOverrides().list_for_image(image_sha256), default=str)


def _telecom_fact_sheet(phone: str, context: str = "{}") -> str:
    """Build an OSINT fact sheet for a phone number."""
    import json as _json
    from app.services.phone_analysis import build_fact_sheet

    try:
        ctx = _json.loads(context) if context else {}
    except Exception:
        ctx = {}
    return json.dumps(build_fact_sheet(phone, ctx), default=str)


def _telecom_analyze(phone: str, context: str = "{}") -> str:
    """Run a full phone-number OSINT analysis (async)."""
    import json as _json
    from app.services.phone_analysis import run_phone_analysis

    try:
        ctx = _json.loads(context) if context else {}
    except Exception:
        ctx = {}
    return json.dumps(_run(run_phone_analysis(phone, ctx)), default=str)


def _telecom_telemetry(cell_json: str = "{}") -> str:
    """Resolve coordinates from cell-tower / Wi-Fi telemetry (JSON)."""
    import json as _json
    from app.services.telemetry_service import CellularResolver, CellTowerInfo

    spec = _json.loads(cell_json) if cell_json else {}
    tower = None
    if spec.get("cell"):
        c = spec["cell"]
        tower = CellTowerInfo(**{k: c.get(k) for k in ("mcc", "mnc", "lac", "cid") if k in c})
    bssids = spec.get("wifi_bssids")
    r = CellularResolver().resolve(cell_tower=tower, wifi_bssids=bssids)
    return json.dumps({"coordinates": r, "input": spec}, default=str)


def _telecom_imei(identifier: str) -> str:
    """Passive IMEI / IMEI-SV / MEID / serial intelligence (no network lookup)."""
    from app.services.imei_analysis import analyze_identifier

    return json.dumps(analyze_identifier(identifier), default=str)


def _pentest_nmap_scan(host: str, ports: str = "", top_ports: int = 100) -> str:
    """Authorized nmap scan of a host/CIDR (real nmap binary, auto-degrading).

    Defaults to the 100 most common ports so routine scans complete quickly;
    delegates to the robust :func:`nmap_scan` which captures partial output on
    timeout and degrades to a fast scan instead of failing outright.
    """
    from app.tools.pen_test.nmap_scanner_tool import nmap_scan

    return json.dumps(
        _run(nmap_scan(host=host, ports=ports, top_ports=top_ports, no_ping=True)),
        default=str,
    )


def _pentest_priv_esc(target_root: str = "/") -> str:
    """Enumerate local privilege-escalation primitives (authorized host)."""
    from app.tools.pen_test.priv_esc_analyzer import analyze_privilege_escalation

    return json.dumps(_run(analyze_privilege_escalation(target_root=target_root)), default=str)


def _pentest_webshell_scan(target_path: str) -> str:
    """Scan an owned web root for webshell indicators (read-only)."""
    from app.tools.pen_test.webshell_detector import scan_webshells

    return json.dumps(_run(scan_webshells(target_path=target_path)), default=str)


def _pentest_hash_crack(hash_value: str, hash_type: str = "auto", wordlist: str = "") -> str:
    """Crack an offline hash against an explicit wordlist (hashcat)."""
    from app.tools.pen_test.hash_cracker_tool import crack_hash

    return json.dumps(_run(crack_hash(hash_value=hash_value, hash_type=hash_type, wordlist=wordlist)), default=str)


def _pentest_default_creds(target_url: str, profile: str = "generic") -> str:
    """Test factory-default credentials on an authorized web target."""
    from app.tools.pen_test.default_cred_tester import test_default_creds

    return json.dumps(_run(test_default_creds(target_url=target_url, profile=profile, authorized=True)), default=str)


def _ot_ros_inspect(ros2: bool = False) -> str:
    """Introspect a live ROS node graph + parameter surface."""
    from app.tools.ros_forensics.ros_inspector_tool import inspect_ros

    return json.dumps(_run(inspect_ros(ros2=ros2)), default=str)


def _ot_safety_audit(config_path: str) -> str:
    """Analyze a ROS/OT safety configuration for tampering / drift."""
    from app.tools.ros_forensics.safety_audit_analyzer import analyze_safety_config

    return json.dumps(_run(analyze_safety_config(config_path=config_path)), default=str)


def _case_list() -> str:
    """List case vaults in the evidence store."""
    root = os.path.join("arkgeo_data", "cases")
    if not os.path.isdir(root):
        return json.dumps({"cases": []})
    cases = [d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]
    return json.dumps({"cases": cases, "count": len(cases)})


def _net_ssl_check(host: str, port: int = 443) -> str:
    """Probe a TLS endpoint and capture certificate subject/SAN (openssl)."""
    r = subprocess.run(
        ["openssl", "s_client", "-connect", f"{host}:{port}", "-servername", host],
        input="", capture_output=True, text=True, timeout=30,
    )
    subject = ""
    for line in r.stdout.splitlines():
        if "subject=" in line:
            subject = line.strip()
    return json.dumps({"host": host, "port": port, "subject": subject, "rc": r.returncode})


# --------------------------------------------------------------------------- #
# Tool catalogue
# --------------------------------------------------------------------------- #
def _specs() -> list[ArkTool]:
    return [
        ArkTool("imint.exiftool", "ExifToolDeep", "Extract deep EXIF/metadata from an image.", "imint", _imint_exiftool, RISK_LOW),
        ArkTool("imint.reverse_image", "ReverseImageSearch", "Provider-agnostic reverse image search (pHash).", "imint", _imint_reverse_image, RISK_LOW),
        ArkTool("imint.geocode", "GeocodePlace", "Reverse/forward geocode a place name to coordinates.", "imint", _imint_geocode, RISK_LOW),
        ArkTool("recon.web_search", "WebSearch", "Search the web for open-source intelligence.", "recon", _recon_web_search, RISK_LOW),
        ArkTool("recon.web_fetch", "WebFetch", "Fetch and extract readable text from a URL.", "recon", _recon_web_fetch, RISK_LOW),
        ArkTool("net.dns_lookup", "DnsLookup", "Resolve DNS records for a host using dig.", "network", _net_dns_lookup, RISK_LOW),
        ArkTool("net.whois", "WhoisLookup", "WHOIS lookup for a domain/network.", "network", _net_whois, RISK_LOW),
        ArkTool("net.nmap_scan", "NmapScan", "Port/service scan of a host or subnet using nmap.", "network", _net_nmap_scan, RISK_HIGH),
        ArkTool("net.dir_enum", "DirEnum", "Directory/endpoint enumeration using gobuster.", "network", _net_dir_enum, RISK_HIGH),
        ArkTool("net.subdomain_enum", "SubdomainEnum", "Enumerate subdomains via crt.sh certificate transparency.", "network", _net_subdomain_enum, RISK_MEDIUM),
        ArkTool("net.curl_probe", "CurlProbe", "Probe a URL and capture response headers.", "network", _net_curl_probe, RISK_LOW),
        ArkTool("siem.query", "SiemQuery", "Query a configured SIEM endpoint (Elasticsearch).", "siem", _siem_query, RISK_MEDIUM),
        ArkTool("siem.ingest", "SiemIngest", "Read and summarise a log file for SIEM ingestion.", "siem", _siem_ingest, RISK_LOW),
        ArkTool("case.custody_hash", "CustodyHash", "Compute SHA-256 chain-of-custody hash for a file.", "case", _case_custody_hash, RISK_LOW),
        ArkTool("case.attach", "AttachCase", "Attach (create) a case vault folder.", "case", _case_attach, RISK_LOW),
        ArkTool("case.evidence", "EvidenceChain", "Inspect chain-of-custody for an evidence id.", "case", _case_evidence, RISK_LOW),
        ArkTool("case.list", "ListCases", "List case vaults in the evidence store.", "case", _case_list, RISK_LOW),
        # Expanded IMINT / geolocation suite
        ArkTool("imint.c2pa", "C2PAProvenance", "Inspect C2PA Content Credentials / provenance of an image.", "imint", _imint_c2pa, RISK_LOW),
        ArkTool("imint.source_discovery", "SourceDiscovery", "Reverse-image-source discovery (pHash + providers).", "imint", _imint_source_discovery, RISK_LOW),
        ArkTool("imint.phash", "PerceptualHash", "Compute a local perceptual hash fingerprint of an image.", "imint", _imint_phash, RISK_LOW),
        ArkTool("imint.extract_urls", "ExtractEmbeddedUrls", "Extract embedded URLs from image metadata.", "imint", _imint_extract_urls, RISK_LOW),
        ArkTool("imint.reverse_geocode", "ReverseGeocode", "Reverse-geocode coordinates to a human address.", "imint", _imint_reverse_geocode, RISK_LOW),
        ArkTool("imint.geocode_batch", "GeocodeBatch", "Geocode a batch of place names.", "imint", _imint_geocode_batch, RISK_LOW),
        ArkTool("imint.streetview", "StreetView", "Fetch Street View metadata + image URL for coordinates.", "imint", _imint_streetview, RISK_LOW),
        ArkTool("imint.tineye", "TinEyeSearch", "Reverse image search via TinEye.", "imint", _imint_tineye, RISK_LOW),
        ArkTool("imint.serper", "SerperSearch", "Web reverse-source search via Serper.", "imint", _imint_serper, RISK_LOW),
        # Evidence / analyst overrides
        ArkTool("evidence.analyst_override", "AnalystOverride", "Record an analyst override (confirm|reject|needs_review).", "case", _evidence_override, RISK_LOW),
        ArkTool("evidence.analyst_overrides", "ListOverrides", "List analyst overrides for an evidence image.", "case", _evidence_overrides, RISK_LOW),
        # Telecom / OSINT (surfaced under the Network Intelligence workspace)
        ArkTool("telecom.fact_sheet", "PhoneFactSheet", "Build an OSINT fact sheet for a phone number.", "network", _telecom_fact_sheet, RISK_LOW),
        ArkTool("telecom.analyze", "PhoneAnalysis", "Run a full phone-number OSINT analysis.", "network", _telecom_analyze, RISK_LOW),
        ArkTool("telecom.telemetry", "TelemetryResolve", "Resolve coordinates from cell-tower / Wi-Fi telemetry.", "network", _telecom_telemetry, RISK_MEDIUM),
        ArkTool("telecom.imei_decode", "ImeiDecode", "Passive IMEI/IMEI-SV/MEID/serial intelligence: validation, TAC/RBI, manufacturer/model.", "network", _telecom_imei, RISK_LOW),
        # Pentest / exploitation
        ArkTool("pentest.nmap_scan", "PentestNmap", "Authorized nmap scan of a host/CIDR.", "pentest", _pentest_nmap_scan, RISK_HIGH),
        ArkTool("pentest.priv_esc", "PrivEscAnalyzer", "Enumerate local privilege-escalation primitives.", "pentest", _pentest_priv_esc, RISK_HIGH),
        ArkTool("pentest.webshell_scan", "WebshellScanner", "Scan an owned web root for webshell indicators.", "pentest", _pentest_webshell_scan, RISK_MEDIUM),
        ArkTool("pentest.hash_crack", "HashCracker", "Crack an offline hash against a wordlist.", "pentest", _pentest_hash_crack, RISK_MEDIUM),
        ArkTool("pentest.default_creds", "DefaultCredTester", "Test factory-default credentials on an authorized target.", "pentest", _pentest_default_creds, RISK_HIGH),
        # OT / ROS forensics
        ArkTool("ot.ros_inspect", "RosInspector", "Introspect a live ROS node graph + parameters.", "ot", _ot_ros_inspect, RISK_MEDIUM),
        ArkTool("ot.safety_audit", "SafetyAudit", "Analyze a ROS/OT safety config for tampering.", "ot", _ot_safety_audit, RISK_MEDIUM),
        # Network extended
        ArkTool("net.ssl_check", "SslCheck", "Probe a TLS endpoint and capture certificate subject.", "network", _net_ssl_check, RISK_LOW),
    ]


_CATALOGUE: list[ArkTool] = _specs()
_BY_ID = {t.id: t for t in _CATALOGUE}


def _norm(s: str) -> str:
    """Normalize a tool token for tolerant matching (lowercase, alnum only)."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


# Tolerant lookup index built from each tool's own id/name — no per-tool
# hardcoding. Lets models emit variants (e.g. "nmap" for "nmap_scan").
_BY_NORM: dict[str, ArkTool] = {}
for _t in _CATALOGUE:
    for _k in (_t.id, _t.name):
        if _k:
            _BY_NORM.setdefault(_norm(_k), _t)


def _resolve_tool(tool_id: str, domain: str | None = None) -> "ArkTool | None":
    """Resolve a model-emitted tool token to a registered tool.

    Order: exact id → normalized id/name → unambiguous prefix/leaf match
    scoped to ``domain`` when supplied (so "nmap" → "net.nmap_scan" inside the
    network workspace, not the pentest variant). Prefix matching only fires
    when exactly one catalogue entry could match, so an ambiguous abbreviation
    safely falls through to the unknown-tool error.
    """
    t = _BY_ID.get(tool_id)
    if t:
        return t
    t = _BY_NORM.get(_norm(tool_id))
    if t:
        return t
    tok = _norm(tool_id)
    if tok:
        pool = [t for t in _CATALOGUE if domain is None or t.domain == domain]
        cands = [
            t for t in pool
            if any(
                _norm(part).startswith(tok) or tok.startswith(_norm(part))
                for part in (t.id, t.id.split(".")[-1])
            )
        ]
        if len(cands) == 1:
            return cands[0]
    return None


def _schema_for(tool: ArkTool) -> dict:
    from cai.sdk.agents.function_schema import function_schema

    fs = function_schema(tool.func)
    return {
        "type": "function",
        "function": {
            "name": tool.id,
            "description": tool.description,
            "parameters": fs.params_json_schema,
        },
    }


def get_tool_specs(include_schema: bool = False) -> list[dict]:
    out = []
    for t in _CATALOGUE:
        d = {
            "id": t.id,
            "name": t.name,
            "domain": t.domain,
            "description": t.description,
            "risk": t.risk,
        }
        if include_schema:
            d["schema"] = _schema_for(t)
        out.append(d)
    return out


def get_openai_tools(domain: str | None = None) -> list[dict]:
    """Return CAI-generated OpenAI tool schemas for the model.

    If ``domain`` is given, only tools in that domain are returned (used by
    workspace-scoped agents such as IMINT / Recon / BlueTeam).
    """
    cats = _CATALOGUE
    if domain:
        cats = [t for t in cats if t.domain == domain]
    return [_schema_for(t) for t in cats]


def call_tool(tool_id: str, domain: str | None = None, **kwargs) -> dict:
    """Execute a real ARK tool by id and return a structured result."""
    tool = _resolve_tool(tool_id, domain)
    if not tool:
        return {"status": "error", "tool": tool_id, "error": f"unknown tool: {tool_id}"}
    try:
        raw = tool.func(**kwargs)
        if inspect.iscoroutine(raw):
            raw = _run(raw)
        return {"status": "ok", "tool": tool.id, "result": raw}
    except Exception as exc:
        return {"status": "error", "tool": tool.id, "error": str(exc)}


# Backward-compatibility shims (used by agent_bridge.py and tests).
ARK_TOOL_CATALOGUE = _CATALOGUE
def call_ark_tool(tool_id: str, **kwargs) -> dict:
    return call_tool(tool_id, **kwargs)
def get_spec(tool_id: str, domain: str | None = None):
    return _resolve_tool(tool_id, domain)
def catalogue_dicts() -> list[dict]:
    return get_tool_specs()
def build_cai_tools(factory) -> list:
    return []

__all__ = [
    "RISK_NONE", "RISK_LOW", "RISK_MEDIUM", "RISK_HIGH",
    "get_tool_specs", "get_openai_tools", "call_tool",
    "ARK_TOOL_CATALOGUE", "call_ark_tool", "get_spec", "catalogue_dicts", "build_cai_tools",
]
