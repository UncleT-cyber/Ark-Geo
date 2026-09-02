"""Hypothesis Engine — cognitive unit 05.

Synthesizes ranked, evidence-tagged :class:`Hypothesis` objects from the
evidence graph. A hypothesis is a **tier-2 reasoning artifact**: it may cite
graph nodes but is never a fact and never auto-promoted. Promotion stays with
the graph's promotion rule (unit 10).

Deterministic synthesis (no model): candidates are ranked by the confidence
of the evidence nodes behind them; supporting / contradicting node ids are
read straight off the graph. The ``unresolved_questions`` come from the gaps
the correlator derived.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from . import schemas as S
from . import evidence_graph as eg
from .correlator import graph_gaps

_HYPOTHESIS_CLAIMS: dict[S.ClaimType, str] = {
    S.ClaimType.LOCATION: "The capture location is most likely around the highest-confidence coordinate estimate.",
    S.ClaimType.TIMESTAMP: "The capture timestamp is consistent with the file metadata.",
    S.ClaimType.INTEGRITY: "The file is authentic (no tampering detected at the integrity layer).",
    S.ClaimType.SOURCE: "The evidence's provenance / source state is as recorded.",
    S.ClaimType.DEVICE: "The capturing device attribution is as recorded.",
}


def _new_id() -> str:
    return f"HYP-{uuid.uuid4().hex[:8].upper()}"


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


def _location_hypothesis(graph: eg.EvidenceGraph) -> Optional[S.Hypothesis]:
    """Rank coordinate candidates from location-claim nodes (and the fusion
    layer's consensus) into one ranked hypothesis."""
    candidates: dict[str, S.HypothesisCandidate] = {}
    support: dict[str, list[str]] = {}
    contradict: dict[str, list[str]] = {}

    def _add_candidate(key: str, claim: str, confidence: float,
                       node_id: str, is_contradict: bool = False) -> None:
        bucket = contradict if is_contradict else support
        bucket.setdefault(key, []).append(node_id)
        if key not in candidates or candidates[key].confidence < confidence:
            candidates[key] = S.HypothesisCandidate(
                claim=claim, confidence=confidence,
            )

    for node in graph.nodes.values():
        coords = _coords(node.value)
        if coords is None:
            continue
        label = f"{coords['lat']:.4f}, {coords['lon']:.4f}"
        # Confirm / refute against every finding's coordinates.
        for finding in graph.findings:
            if _coords(finding.value) is None:
                continue
            disagree = not eg._agree_within_tolerance(
                coords, _coords(finding.value), 0.05)
            _add_candidate(label, f"Coordinates {label}", node.confidence,
                           node.node_id, is_contradict=disagree)
            break
        else:
            _add_candidate(label, f"Coordinates {label}", node.confidence,
                           node.node_id)

    if not candidates:
        return None

    ordered = sorted(candidates.values(), key=lambda c: -c.confidence)
    top = ordered[0]
    for cand in ordered:
        cand.supporting_node_ids = list(support.get(
            cand.claim, []))
        cand.contradicting_node_ids = list(contradict.get(
            cand.claim, []))

    supporting = []
    contradicting = []
    for node_id in support.get(top.claim, []):
        supporting.append(node_id)
    for node_id in contradict.get(top.claim, []):
        contradicting.append(node_id)

    return S.Hypothesis(
        hypothesis_id=_new_id(),
        case_id=graph.case_id,
        domain="image",
        claim=_HYPOTHESIS_CLAIMS[S.ClaimType.LOCATION],
        confidence=top.confidence,
        supporting_node_ids=supporting,
        contradicting_node_ids=contradicting,
        unresolved_questions=[],
        alternatives=ordered[1:4] if len(ordered) > 1 else [],
    )


def _simple_hypothesis(graph: eg.EvidenceGraph, claim_type: S.ClaimType,
                       domain: str) -> Optional[S.Hypothesis]:
    findings = [f for f in graph.findings if f.claim_type == claim_type]
    if not findings:
        return None
    best = max(findings, key=lambda f: f.confidence)
    return S.Hypothesis(
        hypothesis_id=_new_id(),
        case_id=graph.case_id,
        domain=domain,
        claim=_HYPOTHESIS_CLAIMS.get(claim_type, "Claim assessment."),
        confidence=best.confidence,
        supporting_node_ids=list(best.supporting_node_ids),
        contradicting_node_ids=list(best.contradicting_node_ids),
        unresolved_questions=[],
        alternatives=[],
    )


def build_hypotheses(
    graph: eg.EvidenceGraph,
    objective: S.InvestigationObjective,
    model_id: Optional[str] = None,
) -> list[S.Hypothesis]:
    """Synthesize one hypothesis per evidence layer present in the graph."""
    hypotheses: list[S.Hypothesis] = []
    gaps = graph_gaps(graph, objective)

    location = _location_hypothesis(graph)
    if location:
        hypotheses.append(location)

    for ct in (S.ClaimType.INTEGRITY, S.ClaimType.TIMESTAMP,
               S.ClaimType.SOURCE, S.ClaimType.DEVICE):
        h = _simple_hypothesis(graph, ct, objective.domain)
        if h:
            hypotheses.append(h)

    # Surface open questions from unresolved gaps onto the active hypotheses.
    for gap in gaps:
        if gap.resolved:
            continue
        if not hypotheses:
            break
        # Attach to the most relevant hypothesis: the one whose supporting
        # evidence the gap touches, else the newest one.
        target = None
        for hypothesis in hypotheses:
            if any(nid in hypothesis.supporting_node_ids
                   for nid in gap.related_node_ids):
                target = hypothesis
                break
        target = target or hypotheses[0]
        if gap.rationale not in target.unresolved_questions:
            target.unresolved_questions.append(gap.rationale)

    for h in hypotheses:
        h.model_id = model_id
    return hypotheses
