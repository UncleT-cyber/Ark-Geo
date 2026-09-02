"""Correlator / Adaptive Reasoner — cognitive unit 04.

Reads the evidence graph and derives **gaps**: the difference between what the
objective demands and what the graph currently supports. Gaps are the only
things the adaptive loop may act on — the model proposes an ordering among a
gap's ``addressable_by`` tools, or termination. It never free-form picks.

Gap types (see :class:`schemas.GraphGap`):

* ``unverified_claim`` — an objective ``claims_to_verify`` entry with no
  finding of the matching claim type.
* ``open_contradiction`` — a ``CONTRADICTS`` edge no finding adjudicates
  (both endpoints listed as ``contradicting_node_ids``).
* ``low_corroboration`` — a finding resting on a single supporting node.
* ``missing_layer`` — an expected evidence layer (integrity / timestamp /
  source / location) absent from the graph for the objective's domain.

This is deterministic machinery. No model call lives here.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from . import schemas as S
from . import evidence_graph as eg

# Claim field hints → claim type, for light unverified-claim detection.
_CLAIM_HINTS: list[tuple[tuple[str, ...], S.ClaimType]] = [
    (("gps", "lat", "long", "location", "coordinate", "geo", "place"), S.ClaimType.LOCATION),
    (("timestamp", "date", "time", "capture"), S.ClaimType.TIMESTAMP),
    (("integrity", "hash", "tamper", "eof", "ela"), S.ClaimType.INTEGRITY),
    (("camera", "make", "model", "device", "serial"), S.ClaimType.DEVICE),
    (("c2pa", "source", "provenance", "signature", "copyright"), S.ClaimType.SOURCE),
]

# claim_type → tools that could corroborate it (image domain priority order).
_CORROBORATE_TOOLS: dict[S.ClaimType, list[str]] = {
    S.ClaimType.LOCATION: ["reverse_geocode", "resolve_telemetry",
                           "aggregate_consensus", "fuse_geolocation"],
    S.ClaimType.TIMESTAMP: ["extract_exif", "run_consistency", "detect_contradictions"],
    S.ClaimType.INTEGRITY: ["compute_custody_hash", "analyze_ela",
                            "detect_eof_anomaly"],
    S.ClaimType.DEVICE: ["extract_exif", "extract_deep_metadata"],
    S.ClaimType.SOURCE: ["verify_c2pa", "discover_sources"],
    S.ClaimType.METADATA: ["extract_exif", "extract_deep_metadata"],
    S.ClaimType.OTHER: ["detect_contradictions"],
}

# Expected evidence layers per objective domain. Each is a
# (claim_type, missing_marker, rationale, addressable tools) tuple.
_MISSING_LAYERS: dict[str, list[tuple[S.ClaimType, str, str, list[str]]]] = {
    "image": [
        (S.ClaimType.INTEGRITY, "no integrity claim recorded",
         "Objective requires integrity proof (hash / format / ELA).",
         ["compute_custody_hash", "validate_format", "analyze_ela"]),
        (S.ClaimType.METADATA, "no metadata claim recorded",
         "No EXIF/deep metadata extracted — camera, timestamps, GPS unknown.",
         ["extract_exif", "extract_deep_metadata"]),
        (S.ClaimType.SOURCE, "no provenance claim recorded",
         "C2PA/provenance state not established.",
         ["verify_c2pa"]),
    ],
    "network": [
        (S.ClaimType.DEVICE, "no device inventory recorded",
         "No hosts/services inventoried for the authorized network scope.",
         ["discover_hosts", "fingerprint_service"]),
        (S.ClaimType.SOURCE, "no tls provenance recorded",
         "TLS certificate state not established for exposed services.",
         ["tls_inspect"]),
    ],
    "secops": [
        (S.ClaimType.TIMESTAMP, "no security-event timeline recorded",
         "No SIEM/security-event timeline exists for the case window.",
         ["siem_query", "detect_correlation"]),
        (S.ClaimType.INTEGRITY, "no threat indicator assessed",
         "No indicators of compromise assessed against telemetry.",
         ["threat_hunt"]),
    ],
}


def _new_gap_id(gap_type: S.GapType, rationale: str,
                related: list[str] | None = None) -> str:
    """Deterministic gap id — stable across recomputes so the adaptive loop
    can dedup gaps it already acted on (bounded re-planning)."""
    import hashlib
    import json

    blob = json.dumps(
        [gap_type.value, rationale, sorted(related or [])],
        sort_keys=True, separators=(",", ":"),
    )
    return f"GAP-{hashlib.sha256(blob.encode()).hexdigest()[:8].upper()}"


def claim_type_for_field(field: str) -> S.ClaimType:
    """Map a claim field string (e.g. ``gps.latitude``) to a claim type."""
    f = field.lower()
    for hints, claim_type in _CLAIM_HINTS:
        if any(h in f for h in hints):
            return claim_type
    return S.ClaimType.OTHER


def open_contradictions(graph: eg.EvidenceGraph) -> list[S.EvidenceEdge]:
    """CONTRADICTS edges no finding adjudicates."""
    resolved_pairs = set()
    for finding in graph.findings:
        for cid in finding.contradicting_node_ids:
            resolved_pairs.add(cid)
    open_edges: list[S.EvidenceEdge] = []
    for edge in graph.edges:
        if edge.relation != S.EdgeRelation.CONTRADICTS:
            continue
        if edge.src not in resolved_pairs or edge.dst not in resolved_pairs:
            open_edges.append(edge)
    return open_edges


def _node_value_has_key(value: Any, field: str) -> bool:
    """Best-effort: does a node value address a dotted claim field?"""
    if value is None:
        return False
    if isinstance(value, dict):
        parts = field.split(".")
        cur: Any = value
        for i, part in enumerate(parts):
            if not isinstance(cur, dict):
                return False
            # Tolerate singular/plural and common renames at leaf level.
            if part in cur:
                cur = cur[part]
                continue
            if i == len(parts) - 1:
                for alt in (part.rstrip("s"), part + "s",
                            "lat" if part == "latitude" else part,
                            "lon" if part == "longitude" else part):
                    if alt in cur:
                        return True
                return False
            return False
        return True
    if isinstance(value, (list, tuple)):
        return any(_node_value_has_key(v, field) for v in value)
    return False


def graph_gaps(
    graph: eg.EvidenceGraph,
    objective: S.InvestigationObjective,
) -> list[S.GraphGap]:
    """Derive actionable gaps from the graph against the objective."""
    gaps: list[S.GraphGap] = []
    findings_by_claim = {
        ct: [f for f in graph.findings if f.claim_type == ct]
        for ct in S.ClaimType
    }

    # 1. Unverified claims.
    for claim in objective.claims_to_verify:
        ct = claim_type_for_field(claim.field)
        if findings_by_claim[ct]:
            continue
        addressed = any(
            _node_value_has_key(n.value, claim.field)
            for n in graph.nodes.values()
            if n.claim_type == ct
        )
        if addressed:
            continue
        gaps.append(S.GraphGap(
            gap_id=_new_gap_id(S.GapType.UNVERIFIED_CLAIM,
                               f"Claim '{claim.field}' is not verified"),
            gap_type=S.GapType.UNVERIFIED_CLAIM,
            severity=S.RiskLevel.MEDIUM,
            rationale=f"Claim '{claim.field}' is not verified by any evidence.",
            addressable_by=_CORROBORATE_TOOLS.get(ct, []),
        ))

    # 2. Open contradictions — the exit gate for adaptive re-planning.
    for edge in open_contradictions(graph):
        gaps.append(S.GraphGap(
            gap_id=_new_gap_id(S.GapType.OPEN_CONTRADICTION,
                               f"Contradiction between {edge.src} and {edge.dst}",
                               [edge.src, edge.dst]),
            gap_type=S.GapType.OPEN_CONTRADICTION,
            severity=S.RiskLevel.HIGH,
            rationale=(f"Contradiction between {edge.src} and {edge.dst} "
                       f"is unresolved: {edge.note or 'conflicting claims'}."),
            addressable_by=_CORROBORATE_TOOLS.get(
                _node_claim_type(graph, edge.src), []),
            related_node_ids=[edge.src, edge.dst],
        ))

    # 3. Low corroboration — single-source findings.
    # Deterministic tool facts (confidence >= 0.9) are self-sufficient; only
    # softer evidence needs an independent corroborating pass.
    for finding in graph.findings:
        if finding.confidence >= 0.9:
            continue
        if len(finding.supporting_node_ids) >= 2:
            continue
        gaps.append(S.GraphGap(
            gap_id=_new_gap_id(S.GapType.LOW_CORROBORATION,
                               f"Finding {finding.finding_id}",
                               list(finding.supporting_node_ids)),
            gap_type=S.GapType.LOW_CORROBORATION,
            severity=S.RiskLevel.MEDIUM,
            rationale=(f"Finding {finding.finding_id} rests on a single "
                       f"evidence source (confidence {finding.confidence:.2f})."),
            addressable_by=_CORROBORATE_TOOLS.get(finding.claim_type, []),
            related_node_ids=list(finding.supporting_node_ids),
        ))

    # 4. Missing evidence layers for the domain.
    for claim_type, marker, rationale, tools in \
            _MISSING_LAYERS.get(objective.domain, []):
        if findings_by_claim[claim_type]:
            continue
        exists = any(n.claim_type == claim_type for n in graph.nodes.values())
        if exists:
            continue
        gaps.append(S.GraphGap(
            gap_id=_new_gap_id(S.GapType.MISSING_LAYER, rationale),
            gap_type=S.GapType.MISSING_LAYER,
            severity=S.RiskLevel.LOW,
            rationale=rationale,
            addressable_by=tools,
        ))

    return gaps


def actionable_gaps(gaps: list[S.GraphGap]) -> list[S.GraphGap]:
    """Gaps that still have addressable (executable) options."""
    return [g for g in gaps if not g.resolved and g.addressable_by]


def _node_claim_type(graph: eg.EvidenceGraph, node_id: str) -> S.ClaimType:
    node = graph.nodes.get(node_id)
    return node.claim_type if node else S.ClaimType.OTHER


def _coords(value: Any) -> Optional[dict[str, float]]:
    if isinstance(value, dict):
        if "gps" in value:
            return _coords(value["gps"])
        for k in ("lat", "latitude"):
            if k in value and ("lon" in value or "longitude" in value):
                lon = value.get("lon") if "lon" in value else value.get("longitude")
                try:
                    return {"lat": float(value[k]), "lon": float(lon)}
                except (TypeError, ValueError):
                    return None
    return None


def correlate_location_nodes(graph: eg.EvidenceGraph, tolerance: float = 0.02) -> None:
    """Link agreeing location claims (CORROBORATES) and disagreeing ones
    (CONTRADICTS). The contradiction edges feed the adaptive re-plan loop."""
    loc_nodes = [
        n for n in graph.nodes.values()
        if n.claim_type == S.ClaimType.LOCATION
    ]
    for i, a in enumerate(loc_nodes):
        for b in loc_nodes[i + 1:]:
            if any(
                (e.src == a.node_id and e.dst == b.node_id)
                or (e.src == b.node_id and e.dst == a.node_id)
                for e in graph.edges
            ):
                continue
            av, bv = _coords(a.value), _coords(b.value)
            if not av or not bv:
                continue
            if eg._agree_within_tolerance(av, bv, tolerance):
                eg.add_edge(graph, a.node_id, b.node_id,
                            S.EdgeRelation.CORROBORATES,
                            note="location agreement within tolerance")
            else:
                eg.add_edge(graph, a.node_id, b.node_id,
                            S.EdgeRelation.CONTRADICTS,
                            note="conflicting location claims")


correlator = None  # stateless — module functions only
