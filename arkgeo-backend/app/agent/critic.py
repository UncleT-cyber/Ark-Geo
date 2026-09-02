"""Critique Engine — cognitive unit 06.

Challenges high-confidence conclusions with falsifiability questions,
single-source risks, and alternative explanations. A Critique is **not a
verdict** — it asks what could make the target conclusion wrong and which
independent evidence check would settle it.

The critic records each critique as a tier-2 (``ai_hypothesis``) evidence
node on the graph so the challenge is auditable, and never promotes itself —
that stays with the graph's promotion rule.
"""
from __future__ import annotations

import uuid
from typing import Optional

from . import schemas as S
from . import evidence_graph as eg

# claim_type → challenge templates (question, risk, alternative).
_CRITIQUES: dict[S.ClaimType, tuple[str, str, str]] = {
    S.ClaimType.LOCATION: (
        "Could spoofed or edited GPS metadata (exif editing, GPS re-write) "
        "explain the location claim?",
        "Location relies on metadata that an attacker could forge; no "
        "independent (vision/telemetry) confirmation.",
        "The photo was taken elsewhere and GPS was written or edited after "
        "capture.",
    ),
    S.ClaimType.INTEGRITY: (
        "Could recompression, software processing, or re-encoding have "
        "changed the file without malicious intent?",
        "Integrity evidence only proves bytes are unchanged since hashing, "
        "not that the file is authentic at origin.",
        "The file was edited in benign software (Photoshop/GIMP) before "
        "submission, invalidating 'untouched' interpretations.",
    ),
    S.ClaimType.TIMESTAMP: (
        "Could a clock skew or EXIF rewrite explain the capture time?",
        "Timestamps depend on the capturing device's clock, which may be "
        "wrong or altered.",
        "The timestamp was written by a different device or timezone than "
        "claimed.",
    ),
    S.ClaimType.SOURCE: (
        "Could a partial or stripped C2PA/provenance chain mislead the "
        "source assessment?",
        "Provenance signature presence does not prove authentic origin; "
        "signatures can be absent for valid reasons.",
        "The provenance block was added by tooling, not the camera.",
    ),
    S.ClaimType.DEVICE: (
        "Could camera model strings be spoofed or copied from another file?",
        "Device attribution relies on metadata that is trivially editable.",
        "The EXIF device strings were copied from a different photograph.",
    ),
}


def _new_id() -> str:
    return f"CRT-{uuid.uuid4().hex[:8].upper()}"


def critique(
    graph: eg.EvidenceGraph,
    hypotheses: list[S.Hypothesis],
    model_id: Optional[str] = None,
) -> list[S.Critique]:
    """Build one critique per high-confidence hypothesis and record each as
    a tier-2 node on the graph (auditable challenge)."""
    critiques: list[S.Critique] = []
    for hypothesis in hypotheses:
        if hypothesis.confidence < 0.5:
            continue
        ct = S.ClaimType.LOCATION
        # Map hypothesis back to a claim type via the strongest supporting
        # node so the right challenge template applies.
        for node in graph.nodes.values():
            if node.node_id in hypothesis.supporting_node_ids:
                ct = node.claim_type
                break
        question, risk, alternative = _CRITIQUES.get(
            ct, _CRITIQUES[S.ClaimType.INTEGRITY])
        target_id = hypothesis.supporting_node_ids[0] \
            if hypothesis.supporting_node_ids else hypothesis.hypothesis_id
        critique = S.Critique(
            critique_id=_new_id(),
            case_id=graph.case_id,
            target_id=target_id,
            questions=[question],
            risks=[risk],
            alternative_explanations=[alternative],
            challenges_conclusion=True,
            model_id=model_id,
        )
        critiques.append(critique)

        # Record the challenge on the graph (tier-2, never promoted).
        eg.add_node(
            graph,
            eg.build_node(
                case_id=graph.case_id,
                tool_id="critic",
                provenance_type=S.ProvenanceType.AI_HYPOTHESIS,
                claim=f"Critique of {target_id}",
                claim_type=S.ClaimType.OTHER,
                value={"critique_id": critique.critique_id,
                       "questions": critique.questions,
                       "risks": critique.risks,
                       "alternative_explanations": critique.alternative_explanations},
                confidence=0.5,
                model_id=model_id,
            ),
        )
    return critiques


critic = None  # stateless — module functions only
