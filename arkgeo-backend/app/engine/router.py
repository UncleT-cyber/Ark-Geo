"""THE ARK — Hybrid Intent Router.

Classifies a user utterance into one of two execution modes and selects the
appropriate CAI specialist role. This is the single decision point that lets THE
ARK's Terminal behave as both a conversational Cyber Security thought-partner and an
autonomous multi-agent task executor.

Modes
-----
* ``ADVISORY``  — strategic guidance, target analysis, vulnerability explanation,
  risk advice, brainstorming. CAI answers as an elite Cyber Security Specialist and
  does **not** execute CLI tools.
* ``AUTONOMOUS`` — actionable operational commands (pentest, enumerate, geolocate,
  scan, ...). Routes to CAI's ``Agent.run()`` multi-agent loop spawning worker roles.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class IntentMode(str, Enum):
    ADVISORY = "advisory"
    AUTONOMOUS = "autonomous"


class SpecialistRole(str, Enum):
    """CAI specialist roles THE ARK can bind to a workspace."""

    GENERALIST = "generalist"
    RECON = "recon_agent"
    WEB_PENTESTER = "web_app_pentester"
    NETWORK_PENTESTER = "network_pentester"
    IMINT = "imint_agent"
    SIEM = "siem_agent"
    RED_TEAMER = "red_teamer"


# Imperative operational verbs that signal an actionable task.
_AUTONOMOUS_VERBS = (
    r"\b(perform|run|execute|launch|start|begin|conduct|do|carry out|use)\b",
    r"\b(enumerate|scan|recon|reconnoitre|reconnoiter|discover|probe|sweep|map)\b",
    r"\b(geolocate|geolocalize|geolocat\w*|find location|locate)\b",
    r"\b(pentest|pen[- ]?test|penetration test|exploit|attack|breach|pivot|lateral)\b",
    r"\b(capture|fetch|download|exfil|dump|harvest|brute|bruteforce|brute-?force)\b",
    r"\b(assess|audit|harden|investigate|hunt|query|search|list|show|get|resolve|lookup)\b",
    # Hands-on verification / session establishment (A.2 operational prompts:
    # "inspect the service", "establish an authenticated session", "verify the
    # account identity" must route to execution, not advisory prose).
    r"\b(inspect|verify|establish|authenticate|access the|connect to)\b",
    r"\b(bypass|override|force)\b",
)

# Explicit THE ARK tool / capability references force an autonomous (executing) route.
_TOOL_RE = re.compile(
    r"\b("
    # Core recon / OSINT
    r"dns|dig|whois|reverse[- ]?image|nmap|gobuster|exiftool|geocode|custody|"
    r"sha[- ]?256|hash|subdomain|enum|dirbust|probe|curl|fetch url|web search|"
    r"imint\.|net\.|recon\.|siem\.|case\.|"
    # Subdomain / DNS enumeration
    r"sublist3r|amass|dnsenum|subfinder|assetfinder|findomain|crtsh|anubis|"
    # Web scanning / fuzzing
    r"whatweb|nikto|dirb|ffuf|wfuzz|httpx|nuclei|katana|gau|gospider|"
    # Network scanning
    r"masscan|rustscan|zmap|tcpdump|wireshark|tshark|ngrep|"
    # exploitation / post-exploitation
    r"sqlmap|metasploit|msfconsole|hydra|john|hashcat|medusa|"
    r"bloodhound|ldapsearch|enum4linux|crackmapexec|impacket|"
    # Reverse shells / payload
    r"reverse[- ]shell|bind[- ]shell|meterpreter|payload|shellcode|"
    # Privilege escalation
    r"privilege[- ]escalation|privesc|sudo|suid|"
    # Persistence / lateral movement
    r"lateral[- ]movement|persistence|exfiltration|"
    # Evasion / defense
    r"av[- ]evasion|defender|bypass|jailbreak|"
    # C2 / malware
    r"c2|command[- ]and[- ]control|beacon|webshell|backdoor|"
    # Threat intel / detection
    r"ioc|yara|sigma|mitre|att&ck|attack[- ]matrix|"
    # Cloud / containers
    r"docker|kubernetes|kubectl|terraform|ansible|"
    r"aws|gcp|azure|s3|"
    # Languages / runtimes
    r"python|python3|bash|ssh|wget|git|"
    # Steganography / forensics
    r"steganography|stego|binwalk|steghide|stegseek|"
    # TOR / anon
    r"tor|onion|dark[- ]web|"
    # Common attack types
    r"xss|sqli|ssrf|xxe|csrf|idor|"
    r"phishing|spearphish|"
    r"ransomware|wiper|"
    # Hacking / pentesting
    r"hack|hacking|pentesting|pwn|ctf"
    r")",
    re.IGNORECASE,
)
_USE_TOOLS_RE = re.compile(r"using (the |ark['' ]*|these )?(ark |security )?tools?", re.IGNORECASE)
_AUTONOMOUS_RE = re.compile("|".join(_AUTONOMOUS_VERBS), re.IGNORECASE)

# Phrasings that signal a conversational / advisory exchange.
_ADVISORY_CUES = (
    r"\b(how should we|how do we|how would you|what should we|what's our|what is our)\b",
    r"\b(what are the risks|what is the risk|risk of|risks of)\b",
    r"\b(brainstorm|strategi\w*|advice|advise|recommend|suggest|thoughts on|think about|opinion)\b",
    r"\b(explain|why (would|is|are|do)|tell me (about|how)|describe|walk me through)\b",
    r"\b(analy[sz]e|assessment strategy|approach (to|for)|plan (our|the|an))\b",
)
_ADVISORY_RE = re.compile("|".join(_ADVISORY_CUES), re.IGNORECASE)

# Target entity hints used to detect an operational instruction.
_TARGET_RE = re.compile(
    r"(?:\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"  # IPv4(+port)
    r"|https?://[^\s]+"  # URL
    r"|\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b"  # domain
    r"|\B/[\w./-]+\b"  # unix path
    r"|\b(?:[A-Z]:[\\/][\w.\\/ -]+)\b)"  # windows path
    r"|\bCIDR\b|\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}/[0-9]{1,2}\b",
    re.IGNORECASE,
)

_QUESTION_RE = re.compile(r"\?$|^(what|how|why|when|who|where|which|can you|could you)\b", re.IGNORECASE)


@dataclass
class RouteDecision:
    mode: IntentMode
    confidence: float
    suggested_role: SpecialistRole = SpecialistRole.GENERALIST
    detected_target: str | None = None
    rationale: str = ""
    raw: str = ""
    # B.4 — when the utterance is investigation-shaped (verify a location,
    # investigate an image/case, correlate evidence), surface a proposed
    # objective so a caller can route into the existing /investigate flow
    # instead of a bare ReAct loop. Purely advisory metadata: nothing executes.
    investigation: bool = False
    objective: dict | None = None

    def to_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "confidence": round(self.confidence, 3),
            "suggested_role": self.suggested_role.value,
            "detected_target": self.detected_target,
            "rationale": self.rationale,
            "raw": self.raw,
            "investigation": self.investigation,
            "objective": self.objective,
        }


def _detect_role(text: str, mode: IntentMode) -> SpecialistRole:
    t = text.lower()
    if mode is IntentMode.ADVISORY:
        # Advisory still benefits from a domain-aligned specialist persona.
        if any(k in t for k in ("image", "photo", "geolocat", "exif", "satellite", "imint")):
            return SpecialistRole.IMINT
        if any(k in t for k in ("log", "siem", "threat", "alert", "detect", "hunt")):
            return SpecialistRole.SIEM
        if any(k in t for k in ("network", "port", "host", "subnet", "scan", "rce", "exploit")):
            return SpecialistRole.NETWORK_PENTESTER
        if any(k in t for k in ("web", "http", "sql", "xss", "endpoint", "api")):
            return SpecialistRole.WEB_PENTESTER
        return SpecialistRole.GENERALIST

    # AUTONOMOUS — pick the worker best suited to the task.
    if any(k in t for k in ("image", "photo", "geolocat", "exif", "satellite", "imint", "spatial")):
        return SpecialistRole.IMINT
    if any(k in t for k in ("log", "siem", "threat", "alert", "detect", "hunt", "forensic")):
        return SpecialistRole.SIEM
    if any(k in t for k in ("web", "http", "website", "sql", "xss", "owasp", "endpoint")):
        return SpecialistRole.WEB_PENTESTER
    if any(k in t for k in ("network", "port", "host", "subnet", "service", "lateral", "pivot", "scan")):
        return SpecialistRole.NETWORK_PENTESTER
    if any(k in t for k in ("recon", "enumerate", "discover", "osint", "fingerprint")):
        return SpecialistRole.RECON
    return SpecialistRole.RED_TEAMER


# --------------------------------------------------------------------------- #
# B.4 — Investigation intent detection
# --------------------------------------------------------------------------- #
# An utterance is investigation-shaped when it asks to verify/establish a
# claim about a subject (location, device, provenance) or to investigate an
# image/case, and carries a forensic signal. Order matters: the most specific
# goal is tested first so "verify this image is authentic" maps to tamper
# detection, not location.
_INVESTIGATION_GOAL_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("tamper_detection", (
        r"\btamper", r"\bmanipulat", r"\bauthentic", r"\bforg(?:e|ed|ery)",
        r"\bphotoshop", r"\bdeepfake", r"\bela\b", r"\bedit(?:ed)?\b",
    )),
    ("device_attribution", (
        r"\bdevice\b", r"\bcamera\b", r"\battribut", r"\bsame (?:phone|camera)\b",
        r"\bwhich (?:device|camera|phone)\b",
    )),
    ("source_discovery", (
        r"\breverse[- ]?image", r"\bsource\b", r"\boriginal(?:ly)?\b",
        r"\bfirst (?:post|upload|appear)", r"\bprovenance\b", r"\bc2pa\b",
        r"\bwhere (?:did|was) (?:this|it) (?:come|originate|appear|first)\b",
    )),
    ("verify_location_credibility", (
        r"\bverif\w*\b.*\b(location|coordinate|gps|place|where)\b",
        r"\b(location|coordinate|gps)\b.*\b(verif|credib|claim|true|accurate)\b",
        r"\bgeolocat", r"\bwhere (?:was|is) (?:this|it|the photo|the image)\b",
        r"\bexif\b.*\b(gps|location)\b",
    )),
)
_INVESTIGATION_GOAL_RE: list[tuple[str, re.Pattern]] = [
    (goal, re.compile("|".join(cues), re.IGNORECASE))
    for goal, cues in _INVESTIGATION_GOAL_CUES
]
_INVESTIGATION_SUBJECT_RE = re.compile(
    r"\b(image|photo|picture|jpeg|jpg|png|evidence|artifact|file|screenshot|"
    r"case|investigation|sample)\b",
    re.IGNORECASE,
)
_INVESTIGATION_VERB_RE = re.compile(
    r"\b(investigat\w*|verif\w*|establish|corroborat\w*|forensic\w*|"
    r"analyse|analyze|authenticat\w*|provenance|determine|find out)\b",
    re.IGNORECASE,
)


def detect_investigation(text: str, detected_target: str | None = None) -> dict | None:
    """Return a proposed objective dict if ``text`` is investigation-shaped.

    Purely heuristic and side-effect free: it proposes, it never executes and
    never invokes a model. The caller decides whether to route into the
    existing ``/investigate`` flow (which still requires human approval).
    """
    raw = (text or "").strip()
    if not raw:
        return None
    # Require a forensic signal (subject or explicit verb) so a bare
    # "verify the account identity" (a general task) does not become a case.
    if not (_INVESTIGATION_SUBJECT_RE.search(raw) or _INVESTIGATION_VERB_RE.search(raw)):
        return None

    goal = None
    for candidate, pattern in _INVESTIGATION_GOAL_RE:
        if pattern.search(raw):
            goal = candidate
            break
    if goal is None:
        # Investigation-shaped subject/verb but no specific goal → full profile.
        if _INVESTIGATION_SUBJECT_RE.search(raw):
            goal = "full_forensic_profile"
        else:
            return None

    return {
        "goal": goal,
        "subject": detected_target or "uploaded-evidence",
        "domain": "image",
        "natural_language": raw,
    }


def classify_intent(text: str) -> RouteDecision:
    """Classify ``text`` into ADVISORY or AUTONOMOUS and pick a specialist role."""
    raw = (text or "").strip()
    if not raw:
        return RouteDecision(
            mode=IntentMode.ADVISORY,
            confidence=1.0,
            suggested_role=SpecialistRole.GENERALIST,
            rationale="Empty input defaults to advisory idle state.",
            raw=raw,
        )

    advisory_hits = len(_ADVISORY_RE.findall(raw))
    autonomous_hits = len(_AUTONOMOUS_RE.findall(raw))
    if _TOOL_RE.search(raw) or _USE_TOOLS_RE.search(raw):
        autonomous_hits += 1  # explicit tool/exec capability reference
    is_question = bool(_QUESTION_RE.search(raw))
    target = _TARGET_RE.search(raw)
    detected_target = target.group(0) if target else None

    # A question with no operational verb is advisory.
    if is_question and autonomous_hits == 0:
        advisory_hits += 1

    # An explicit operational verb with a target strongly implies execution.
    if autonomous_hits and detected_target:
        autonomous_hits += 1

    if autonomous_hits > advisory_hits:
        mode = IntentMode.AUTONOMOUS
        # Confidence scales with how operational the phrasing is.
        confidence = min(0.99, 0.6 + 0.1 * autonomous_hits)
        rationale = (
            f"Detected {autonomous_hits} operational cue(s) and "
            f"{'a target' if detected_target else 'no explicit target'}."
        )
    else:
        mode = IntentMode.ADVISORY
        confidence = min(0.99, 0.6 + 0.1 * advisory_hits)
        rationale = (
            f"Detected {advisory_hits} advisory cue(s) vs "
            f"{autonomous_hits} operational cue(s)."
        )

    role = _detect_role(raw, mode)
    objective = detect_investigation(raw, detected_target)
    return RouteDecision(
        mode=mode,
        confidence=confidence,
        suggested_role=role,
        detected_target=detected_target,
        rationale=rationale,
        raw=raw,
        investigation=objective is not None,
        objective=objective,
    )


__all__ = [
    "IntentMode",
    "SpecialistRole",
    "RouteDecision",
    "classify_intent",
    "detect_investigation",
]
