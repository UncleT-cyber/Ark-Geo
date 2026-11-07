"""Case Engine — cognitive unit 07/12 adjacent: cross-domain case unification.

Phase G. Until now a *case* was an implicit grouping: several investigations
(one per domain) could share a ``case_id``, but nothing assembled them into a
single case view. This engine does exactly that, deterministically and
read-only:

* **One case, many domains** — a case's evidence, findings, and audit trail
  are the union across every investigation that shares the ``case_id``.
* **Cross-domain contradiction edges** — location claims that disagree are
  linked ``CONTRADICTS`` on the merged case graph even when the two claims
  were produced by different domains (e.g. EXIF GPS from IMAGE vs a geocoded
  OCR string from OSINT).
* **One audit trail** — every audited tool invocation across the case, in
  time order.

The engine never mutates a session graph: the merged graph is derived on read.
It is the backend source of truth the frontend CASES domain (CaseExplorer)
binds to.
"""
from __future__ import annotations

from typing import Any, Optional

from . import evidence_graph as eg
from . import schemas as S
from .correlator import correlate_location_nodes
from .tool_registry import registry

# Domains that count as "a domain" for the ≥2-domain exit gate. The synthetic
# audit tool is not a domain.
_NON_DOMAIN_TOOL_IDS = {"audit"}


def tool_domain(tool_id: str) -> Optional[str]:
    """Registered domain for a tool id, or ``None`` if unknown/synthetic."""
    if tool_id in _NON_DOMAIN_TOOL_IDS:
        return None
    tool = registry.get(tool_id)
    return tool.spec.domain if tool else None


def merge_case_graph(sessions: list[Any]) -> S.EvidenceGraph:
    """Union every session graph for one case into a derived case graph.

    Node ids are unique across sessions, so the union is lossless. Cross-domain
    location correlation runs on the merged graph so agreement/contradiction
    edges span domains.
    """
    case_id = sessions[0].case_id if sessions else ""
    merged = S.EvidenceGraph(case_id=case_id)
    seen_nodes: set[str] = set()
    for session in sessions:
        for node_id, node in session.graph.nodes.items():
            if node_id not in seen_nodes:
                merged.nodes[node_id] = node
                seen_nodes.add(node_id)
    # Edges are (src, dst, relation) unique; session graphs never share edge ids.
    seen_edges: set[tuple[str, str, str]] = set()
    for session in sessions:
        for edge in session.graph.edges:
            key = (edge.src, edge.dst, edge.relation.value)
            if key not in seen_edges:
                merged.edges.append(edge)
                seen_edges.add(key)
    for session in sessions:
        merged.findings.extend(session.graph.findings)
    correlate_location_nodes(merged)
    return merged


def cross_domain_contradictions(merged: S.EvidenceGraph) -> list[dict]:
    """Contradiction edges whose two endpoints belong to different domains."""
    out: list[dict] = []
    for edge in merged.edges:
        if edge.relation != S.EdgeRelation.CONTRADICTS:
            continue
        src = merged.nodes.get(edge.src)
        dst = merged.nodes.get(edge.dst)
        if not src or not dst:
            continue
        src_domain, dst_domain = tool_domain(src.tool_id), tool_domain(dst.tool_id)
        if not src_domain or not dst_domain or src_domain == dst_domain:
            continue
        out.append({
            "edge_id": edge.edge_id,
            "src_domain": src_domain,
            "dst_domain": dst_domain,
            "src_tool": src.tool_id,
            "dst_tool": dst.tool_id,
            "src_claim": src.claim,
            "dst_claim": dst.claim,
            "note": edge.note,
        })
    return out


def _audit_trail(merged: S.EvidenceGraph) -> list[dict]:
    """Every audited tool invocation across the case, in time order."""
    audits = [
        n for n in merged.nodes.values()
        if n.tool_id in _NON_DOMAIN_TOOL_IDS
    ]
    audits.sort(key=lambda n: n.produced_at_ms)
    return [
        {
            "node_id": n.node_id,
            "invocation_id": (n.value or {}).get("invocation_id"),
            "tool_id": (n.value or {}).get("tool_id"),
            "status": (n.value or {}).get("status"),
            "arguments_hash": (n.value or {}).get("arguments_hash"),
            "at_ms": n.produced_at_ms,
            "hash": n.hash,
        }
        for n in audits
    ]


def domains_in_case(merged: S.EvidenceGraph) -> list[str]:
    """Distinct investigation domains represented on the case graph."""
    found: set[str] = set()
    for node in merged.nodes.values():
        domain = tool_domain(node.tool_id)
        if domain:
            found.add(domain)
    return sorted(found)


def case_view(case_id: str, sessions: list[Any]) -> dict:
    """Unified, court-relevant view of one cross-domain case."""
    merged = merge_case_graph(sessions)
    domains = domains_in_case(merged)
    findings = [f.model_dump() for f in merged.findings]
    return {
        "case_id": case_id,
        "domain": "cross" if len(domains) >= 2 else (domains[0] if domains else "unknown"),
        "domains": domains,
        "investigation_ids": [s.investigation_id for s in sessions],
        "objectives": [s.objective.model_dump() for s in sessions],
        "status": _rollup_status(sessions),
        "evidence_count": len([
            n for n in merged.nodes.values() if n.tool_id not in _NON_DOMAIN_TOOL_IDS
        ]),
        "finding_count": len(findings),
        "findings": findings,
        "domains_by_finding": [
            {"finding_id": f["finding_id"], "domain": f.get("domain")}
            for f in findings
        ],
        "cross_domain_contradictions": cross_domain_contradictions(merged),
        "audit_trail": _audit_trail(merged),
        "graph": eg.to_dict(merged),
    }


def list_cases(sessions: list[Any]) -> list[dict]:
    """One summary row per case, newest first, across every domain."""
    by_case: dict[str, list[Any]] = {}
    for session in sessions:
        by_case.setdefault(session.case_id, []).append(session)

    rows: list[dict] = []
    for case_id, group in by_case.items():
        merged = merge_case_graph(group)
        domains = domains_in_case(merged)
        rows.append({
            "case_id": case_id,
            "domain": "cross" if len(domains) >= 2 else (domains[0] if domains else "unknown"),
            "domains": domains,
            "investigation_count": len(group),
            "evidence_count": len([
                n for n in merged.nodes.values() if n.tool_id not in _NON_DOMAIN_TOOL_IDS
            ]),
            "finding_count": len(merged.findings),
            "cross_domain_contradictions": len(cross_domain_contradictions(merged)),
            "status": _rollup_status(group),
            "updated_at_ms": max(s.updated_at_ms for s in group),
        })
    rows.sort(key=lambda r: r["updated_at_ms"], reverse=True)
    return rows


def _rollup_status(sessions: list[Any]) -> str:
    """Case status is the least-advanced session status, so a case is only
    'done' when every investigation on it is done."""
    order = ["failed", "rejected", "paused", "running", "approved", "proposed", "done"]
    statuses = {s.status for s in sessions}
    for status in order:
        if status in statuses:
            return status
    return "unknown"
