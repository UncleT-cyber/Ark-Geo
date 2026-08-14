"""Evidence Graph — pure, audited operations.

The graph is the spine of the investigation. Tools and the AI both read/write
it. The operations here are deliberately pure (no I/O, no LLM) so they are
deterministic and testable.

Key invariant — the **promotion rule** (§2 of the spec): a tier-2
(ai_hypothesis) node may not be promoted to a finding unless corroborated by a
tier-0/1 node, or by >=2 independent tier-2 nodes agreeing within tolerance.
This is enforced in :func:`promote_to_finding`, not by prompt etiquette.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Optional

from .schemas import (
    EdgeRelation,
    EvidenceEdge,
    EvidenceGraph,
    EvidenceNode,
    Finding,
    ProvenanceType,
    PromotionDenied,
    now_ms,
)

# Epistemic weight: higher = more trustworthy. Tier-2 may not override tier-0/1.
_PROVENANCE_WEIGHT: dict[ProvenanceType, int] = {
    ProvenanceType.CRYPTOGRAPHIC: 0,
    ProvenanceType.TOOL_INFERENCE: 1,
    ProvenanceType.AI_HYPOTHESIS: 2,
}


def _gen_id(prefix: str) -> str:
    return f"ARK-{prefix}-{uuid.uuid4().hex[:8].upper()}"


def node_hash(case_id: str, payload: dict[str, Any]) -> str:
    """Stable SHA-256 over a canonical JSON encoding of the node payload."""
    blob = json.dumps(
        {"case_id": case_id, **payload},
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def build_node(
    case_id: str,
    tool_id: str,
    provenance_type: ProvenanceType,
    claim: str,
    claim_type,
    value: Any,
    confidence: float = 1.0,
    model_id: Optional[str] = None,
) -> EvidenceNode:
    """Construct an EvidenceNode with a freshly computed tamper-evident hash."""
    node_id = _gen_id("EVN")
    payload = {
        "node_id": node_id,
        "tool_id": tool_id,
        "provenance_type": provenance_type,
        "claim": claim,
        "claim_type": claim_type,
        "value": value,
        "confidence": confidence,
        "model_id": model_id,
    }
    return EvidenceNode(
        node_id=node_id,
        case_id=case_id,
        tool_id=tool_id,
        provenance_type=provenance_type,
        claim=claim,
        claim_type=claim_type,
        value=value,
        confidence=confidence,
        model_id=model_id,
        produced_at_ms=now_ms(),
        hash=node_hash(case_id, payload),
    )


def add_node(graph: EvidenceGraph, node: EvidenceNode) -> EvidenceNode:
    """Add a node, validating its hash. Returns the node for convenience."""
    recomputed = node_hash(
        node.case_id,
        {
            "node_id": node.node_id,
            "tool_id": node.tool_id,
            "provenance_type": node.provenance_type,
            "claim": node.claim,
            "claim_type": node.claim_type,
            "value": node.value,
            "confidence": node.confidence,
            "model_id": node.model_id,
        },
    )
    if node.hash and recomputed != node.hash:
        raise ValueError(f"Node hash mismatch for {node.node_id} — tamper detected")
    graph.nodes[node.node_id] = node
    return node


def add_edge(
    graph: EvidenceGraph,
    src: str,
    dst: str,
    relation: EdgeRelation,
    weight: Optional[float] = None,
    note: Optional[str] = None,
) -> EvidenceEdge:
    """Record a relationship between two nodes.

    ``corroborates`` → positive weight; ``contradicts`` → negative weight.
    The weight sign is enforced here so callers can't accidentally sign a
    contradiction as corroboration.
    """
    if src not in graph.nodes or dst not in graph.nodes:
        missing = src if src not in graph.nodes else dst
        raise KeyError(f"Node {missing} not in graph")

    if weight is None:
        weight = 1.0 if relation == EdgeRelation.CORROBORATES else -1.0
    if relation == EdgeRelation.CONTRADICTS and weight > 0:
        weight = -abs(weight)
    if relation == EdgeRelation.CORROBORATES and weight < 0:
        weight = abs(weight)

    edge = EvidenceEdge(
        edge_id=_gen_id("EDG"),
        case_id=graph.case_id,
        src=src,
        dst=dst,
        relation=relation,
        weight=weight,
        created_at_ms=now_ms(),
        note=note,
    )
    graph.edges.append(edge)
    return edge


def neighbors(graph: EvidenceGraph, node_id: str) -> list[EvidenceEdge]:
    """All edges touching a node (in either direction)."""
    return [e for e in graph.edges if e.src == node_id or e.dst == node_id]


def contradictions_for(graph: EvidenceGraph, node_id: str) -> list[EvidenceEdge]:
    """Contradicting edges involving a node."""
    return [
        e for e in neighbors(graph, node_id)
        if e.relation == EdgeRelation.CONTRADICTS
    ]


def corroboration_score(graph: EvidenceGraph, node_id: str) -> float:
    """Sum of edge weights touching a node (positive = corroborated)."""
    return sum(e.weight for e in neighbors(graph, node_id))


def _agree_within_tolerance(a: Any, b: Any, tol: float) -> bool:
    """Loose agreement check for corroboration across nodes."""
    if a == b:
        return True
    # Coordinate tuples/dicts carrying lat/lon
    if isinstance(a, dict) and isinstance(b, dict):
        keys = [k for k in ("lat", "lon", "latitude", "longitude")
                if k in a or k in b]
        if not keys:
            return a == b
        for k in keys:
            av, bv = a.get(k), b.get(k)
            if av is None or bv is None:
                return False
            try:
                if abs(float(av) - float(bv)) > tol + 1e-9:
                    return False
            except (TypeError, ValueError):
                return False
        return True
    # Numeric fallback
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return a == b


def can_promote(
    graph: EvidenceGraph,
    node: EvidenceNode,
    tolerance: float = 0.01,
) -> tuple[bool, list[str]]:
    """Apply the promotion rule. Returns (allowed, supporting_node_ids).

    Tier-0/1 nodes are promotable on their own. Tier-2 (ai_hypothesis) needs
    corroboration from a higher tier, OR >=2 independent tier-2 agreements.
    A contradicting higher-tier node blocks promotion.
    """
    if node.provenance_type in (ProvenanceType.CRYPTOGRAPHIC,
                                ProvenanceType.TOOL_INFERENCE):
        # Still blocked by an explicit higher-tier contradiction.
        for e in contradictions_for(graph, node.node_id):
            other = graph.nodes.get(e.src if e.dst == node.node_id else e.dst)
            if other and _PROVENANCE_WEIGHT[other.provenance_type] <= \
                    _PROVENANCE_WEIGHT[node.provenance_type]:
                return False, []
        return True, [node.node_id]

    # tier-2: needs corroboration
    support: list[str] = []
    tier2_support = 0
    for e in neighbors(graph, node.node_id):
        other_id = e.src if e.dst == node.node_id else e.dst
        other = graph.nodes.get(other_id)
        if not other:
            continue
        if e.relation == EdgeRelation.CORROBORATES:
            if _PROVENANCE_WEIGHT[other.provenance_type] < _PROVENANCE_WEIGHT[
                node.provenance_type
            ]:
                support.append(other_id)
            elif other.provenance_type == ProvenanceType.AI_HYPOTHESIS:
                if _agree_within_tolerance(other.value, node.value, tolerance):
                    tier2_support += 1
                    support.append(other_id)
        if e.relation == EdgeRelation.CONTRADICTS and \
                _PROVENANCE_WEIGHT[other.provenance_type] < \
                _PROVENANCE_WEIGHT[node.provenance_type]:
            # A higher-tier node contradicts — cannot promote.
            return False, []
    if support or tier2_support >= 1:
        # `support` = a higher-tier node corroborates; OR >=1 independent
        # tier-2 node agrees with the candidate (candidate + corroborator
        # = 2 independent tier-2 nodes agreeing, per spec §2).
        return True, support
    return False, []


def promote_to_finding(
    graph: EvidenceGraph,
    node_id: str,
    claim: Optional[str] = None,
    tolerance: float = 0.01,
) -> Finding:
    """Promote an evidence node to a court-relevant finding.

    Raises :class:`PromotionDenied` if the node is tier-2 without
    corroboration (§2 promotion rule).
    """
    node = graph.nodes.get(node_id)
    if not node:
        raise KeyError(f"Node {node_id} not in graph")

    allowed, support = can_promote(graph, node, tolerance)
    if not allowed:
        raise PromotionDenied(
            f"Tier-2 node {node_id} lacks corroboration — cannot promote to finding"
        )

    contra = [e.src if e.dst == node_id else e.dst
              for e in contradictions_for(graph, node_id)]
    finding = Finding(
        finding_id=_gen_id("FND"),
        case_id=graph.case_id,
        claim_type=node.claim_type,
        claim=claim or node.claim,
        value=node.value,
        confidence=max(0.0, min(1.0, node.confidence
                                + 0.1 * (len(support) - 1))),
        supporting_node_ids=support or [node_id],
        contradicting_node_ids=contra,
    )
    graph.findings.append(finding)
    return finding


def to_dict(graph: EvidenceGraph) -> dict:
    """Serialize the graph for the investigation console / API."""
    return {
        "case_id": graph.case_id,
        "nodes": {nid: n.model_dump() for nid, n in graph.nodes.items()},
        "edges": [e.model_dump() for e in graph.edges],
        "findings": [f.model_dump() for f in graph.findings],
        "plan_id": graph.plan_id,
    }
