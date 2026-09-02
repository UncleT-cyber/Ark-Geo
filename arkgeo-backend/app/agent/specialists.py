"""Domain specialists — knowledge/tool-selection layers over the cognitive core.

A specialist is **not** an AI brain. It knows its domain and which tools it
routes to; the orchestrator decides what to do next, the policy governor
decides what *may* execute, the evidence graph records what happened. Adding
a domain = registering one :class:`SpecialistSpec` + its tools; the cognitive
core is unchanged.

See ``docs/ARK_INTEGRATED_SECURITY_ENVIRONMENT.md`` §2 — "the specialist
understands the domain, the Tool Registry knows what can execute, the Policy
Governor decides what may execute."
"""
from __future__ import annotations

from typing import Optional

from . import schemas as S
from .tool_registry import registry


def _image_specialist() -> S.SpecialistSpec:
    return S.SpecialistSpec(
        domain="image",
        name="IMAGE Intelligence",
        description="Digital image forensics: metadata, provenance, geolocation, "
                    "visual clues, OCR, and source history.",
        understands=[
            "EXIF", "XMP", "IPTC", "MakerNotes", "JPEG structure", "provenance",
            "C2PA", "geolocation", "OCR", "visual clues", "ELA", "image similarity",
            "source history",
        ],
        tool_ids=[
            "compute_custody_hash", "validate_format", "extract_exif",
            "extract_deep_metadata", "reverse_geocode", "resolve_telemetry",
            "analyze_ela", "detect_eof_anomaly", "verify_c2pa", "run_consistency",
            "run_ocr", "fuse_geolocation",             "discover_sources",
            "detect_contradictions", "run_vision_ensemble", "aggregate_consensus",
            "brain_analyze", "enhance_image",
        ],
        goal_mappings={
            S.InvestigationGoal.VERIFY_LOCATION_CREDIBILITY: "image_verify_location",
            S.InvestigationGoal.DEVICE_ATTRIBUTION: "image_device_attribution",
            S.InvestigationGoal.TAMPER_DETECTION: "image_tamper_detection",
            S.InvestigationGoal.SOURCE_DISCOVERY: "image_source_discovery",
            S.InvestigationGoal.FULL_FORENSIC_PROFILE: "image_full_profile",
        },
    )


def _network_specialist() -> S.SpecialistSpec:
    return S.SpecialistSpec(
        domain="network",
        name="NETWORK Intelligence",
        description="Authorized network discovery: hosts, services, protocols, "
                    "traffic, topology, and certificates.",
        understands=[
            "hosts", "services", "protocols", "traffic", "topology",
            "certificates", "network relationships", "DNS-as-evidence",
        ],
        tool_ids=[
            "discover_hosts", "fingerprint_service", "port_scan", "tls_inspect",
        ],
        goal_mappings={
            S.InvestigationGoal.VERIFY_LOCATION_CREDIBILITY: "network_full",
            S.InvestigationGoal.DEVICE_ATTRIBUTION: "network_full",
            S.InvestigationGoal.TAMPER_DETECTION: "network_full",
            S.InvestigationGoal.SOURCE_DISCOVERY: "network_full",
            S.InvestigationGoal.FULL_FORENSIC_PROFILE: "network_full",
        },
    )


def _secops_specialist() -> S.SpecialistSpec:
    return S.SpecialistSpec(
        domain="secops",
        name="THREAT & SECOPS",
        description="SIEM, IDS/IPS, security events, correlations, detections, "
                    "incidents, threat hunting, and telemetry.",
        understands=[
            "SIEM", "IDS/IPS", "security events", "alerts", "correlations",
            "detections", "incidents", "threat hunting", "telemetry",
        ],
        tool_ids=[
            "siem_query", "threat_hunt", "detect_correlation", "incident_annotate",
        ],
        goal_mappings={
            S.InvestigationGoal.VERIFY_LOCATION_CREDIBILITY: "secops_full",
            S.InvestigationGoal.DEVICE_ATTRIBUTION: "secops_full",
            S.InvestigationGoal.TAMPER_DETECTION: "secops_full",
            S.InvestigationGoal.SOURCE_DISCOVERY: "secops_full",
            S.InvestigationGoal.FULL_FORENSIC_PROFILE: "secops_full",
        },
    )


def _osint_specialist() -> S.SpecialistSpec:
    return S.SpecialistSpec(
        domain="osint",
        name="OSINT / Intelligence",
        description="Public-source intelligence: entities, relationships, "
                    "timelines, documents, and source credibility.",
        understands=[
            "public sources", "entities", "relationships", "timelines",
            "documents", "online identities", "source credibility",
            "corroboration",
        ],
        tool_ids=[
            "source_search", "entity_extract", "relationship_build", "timeline_build",
            "inspect_local_path",
        ],
        goal_mappings={},
    )


def _web_specialist() -> S.SpecialistSpec:
    return S.SpecialistSpec(
        domain="web",
        name="WEB / App Security",
        description="Authorized testing: HTTP, APIs, sessions, endpoints, "
                    "authentication flows, and application structure.",
        understands=[
            "HTTP", "APIs", "sessions", "applications", "endpoints", "traffic",
            "authentication flows", "web architecture",
        ],
        tool_ids=[
            "proxy_collect", "http_history", "endpoint_map", "app_structure",
        ],
        goal_mappings={},
    )


def _pentest_specialist() -> S.SpecialistSpec:
    return S.SpecialistSpec(
        domain="pentest",
        name="RED TEAM / PENTEST",
        description="Authorized offensive-security capability: active host "
                    "scanning, default-credential checks, offline hash recovery, "
                    "and local privilege-escalation enumeration. Active steps "
                    "require EXEC_SHELL / explicit authorization.",
        understands=[
            "nmap", "port enumeration", "service fingerprints", "default credentials",
            "hash recovery", "hashcat", "john", "privilege escalation", "SUID",
            "webshell indicators", "authorized engagement scope",
        ],
        tool_ids=[
            "nmap_scan", "default_cred_tester", "crack_hash",
            "analyze_privilege_escalation", "scan_webshells",
        ],
        goal_mappings={},
    )


def _ros_specialist() -> S.SpecialistSpec:
    return S.SpecialistSpec(
        domain="ros",
        name="ROS / OT FORENSICS",
        description="Robotic / OT forensics: ROS 1 & 2 node graphs, topic and "
                    "parameter surfaces, and safety-config audit (limits, "
                    "protective-stop / E-stop state).",
        understands=[
            "ROS 1", "ROS 2", "ROS nodes", "ROS topics", "ROS params",
            "safety config", "velocity limits", "E-stop", "protective stop",
            "joint limits", "OT forensics",
        ],
        tool_ids=[
            "inspect_ros", "analyze_safety_config",
        ],
        goal_mappings={},
    )


def _catalog() -> list[S.SpecialistSpec]:
    return [
        _image_specialist(),
        _network_specialist(),
        _secops_specialist(),
        _osint_specialist(),
        _web_specialist(),
        _pentest_specialist(),
        _ros_specialist(),
    ]


class SpecialistRegistry:
    """Lookup table of domain specialists.

    A specialist is the knowledge layer that *routes* an objective to the
    tools registered for its domain. It owns no execution and no AI.
    """

    def __init__(self) -> None:
        self._specs: dict[str, S.SpecialistSpec] = {
            s.domain: s for s in _catalog()
        }

    def get(self, domain: str) -> Optional[S.SpecialistSpec]:
        return self._specs.get(domain)

    def list(self) -> list[S.SpecialistSpec]:
        return list(self._specs.values())

    def domains(self) -> list[str]:
        return list(self._specs)

    def registered_tools(self, domain: str) -> list[S.ToolSpec]:
        """Tool specs actually registered for a specialist's domain.

        Planned tool ids (NETWORK/SECOPS/OSINT/WEB first wave) are declared on
        the specialist but only returned once their ToolSpec is registered in
        :mod:`tool_registry`. This is how Phase F lights up without touching
        the core.
        """
        spec = self.get(domain)
        if not spec:
            return []
        return [t.spec for t in registry.list(domain)
                if t.tool_id in set(spec.tool_ids)]

    def plan_template_id(self, domain: str, goal: S.InvestigationGoal) -> Optional[str]:
        spec = self.get(domain)
        if not spec:
            return None
        return spec.goal_mappings.get(goal)


specialists = SpecialistRegistry()
