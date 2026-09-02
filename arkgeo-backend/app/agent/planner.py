"""Investigation Planner — cognitive unit 02. Objective → structured plan.

Two paths, one invariant:

* **Deterministic template** — always available. ``verify_location_credibility``
  maps to the canonical 12-step investigation (integrity → metadata →
  timestamps → structure → OCR → visual → location → provenance → sources →
  contradictions → assessment), mirroring the approved example plan.
* **Model proposal** — the Model Gateway (unit 09) may propose an ordering.
  Every proposed ``tool_id`` is validated against the specialist's registered
  tools; the template is the fallback on *any* model or parse failure.

The model is never a hard dependency. Its output is *input*, not authority —
exactly the "ARK Core decides, AI proposes" separation.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from . import schemas as S
from .model_gateway import gateway
from .specialists import SpecialistRegistry
from .tool_registry import registry

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Plan templates — tool_id → human rationale, in investigation order.
# Mirrors the approved 12-step plan in the master plan (Phase C).
# --------------------------------------------------------------------------- #
_VERIFY_LOCATION_STEPS: list[tuple[str, str]] = [
    ("compute_custody_hash", "Verify evidence integrity (SHA-256/SHA-1/MD5)"),
    ("validate_format", "Validate file magic bytes (anti-spoofing)"),
    ("extract_exif", "Extract EXIF/XMP/IPTC: GPS, camera, timestamps"),
    ("extract_deep_metadata", "Extract deep metadata via ExifTool (MakerNotes, ICC)"),
    ("run_consistency", "Compare capture vs file timestamps; check consistency"),
    ("analyze_ela", "Inspect JPEG/compression characteristics (edited regions)"),
    ("detect_eof_anomaly", "Detect trailing bytes after EOF (stego/smuggling)"),
    ("run_ocr", "Extract visible text: signs, plates, roads"),
    ("run_vision_ensemble", "Analyze visual geographic clues (requires vision key)"),
    ("reverse_geocode", "Resolve extracted GPS coordinates to a place name"),
    ("resolve_telemetry", "Resolve location from telemetry (GPS/cell/Wi-Fi)"),
    ("verify_c2pa", "Check provenance/C2PA signature state"),
    ("discover_sources", "Search configured reverse-source-discovery providers"),
    ("detect_contradictions", "Cross-reference evidence layers for contradictions"),
    ("aggregate_consensus", "Bayesian consensus over all location estimates"),
    ("fuse_geolocation", "Fuse multi-layer evidence into a defensible hypothesis"),
]

_NETWORK_STEPS: list[tuple[str, str]] = [
    ("discover_hosts", "Enumerate hosts/services within the authorized scope"),
    ("fingerprint_service", "Identify service versions on discovered hosts"),
    ("port_scan", "Probe exposure on discovered hosts (step-confirm)"),
    ("tls_inspect", "Inspect TLS certificates on exposed services"),
]

_SECOPS_STEPS: list[tuple[str, str]] = [
    ("siem_query", "Query the security-event timeline for the case window"),
    ("threat_hunt", "Search telemetry for indicators of compromise"),
    ("detect_correlation", "Correlate security events into detection patterns"),
    ("incident_annotate", "Annotate the case incident record (action)"),
]

_TEMPLATES: dict[str, list[tuple[str, str]]] = {
    "image_verify_location": _VERIFY_LOCATION_STEPS,
    "network_full": _NETWORK_STEPS,
    "secops_full": _SECOPS_STEPS,
}


def _generic_steps(tool_ids: list[str]) -> list[tuple[str, str]]:
    """Fallback template for goals without a curated mapping."""
    return [(tid, "Run registered domain tool") for tid in tool_ids]


def plan_hash(revision: S.PlanRevision) -> str:
    """Tamper-evident SHA-256 over the revision payload (plan lineage §7)."""
    import hashlib
    import json

    blob = json.dumps(
        {
            "revision_id": revision.revision_id,
            "parent_revision_id": revision.parent_revision_id,
            "objective_id": revision.objective_id,
            "steps": [
                {"step_id": s.step_id, "tool_id": s.tool_id,
                 "rationale": s.rationale}
                for s in revision.steps
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode()).hexdigest()


class PlanBuilder:
    """Builds :class:`PlanRevision` objects from typed objectives."""

    def __init__(self, specialists: Optional[SpecialistRegistry] = None) -> None:
        self._specialists = specialists or SpecialistRegistry()

    # ------------------------------------------------------------------ #
    async def build(
        self,
        objective: S.InvestigationObjective,
        case_id: str,
        *,
        use_model: bool = True,
    ) -> tuple[S.PlanRevision, str]:
        """Produce a proposed plan revision.

        Returns ``(revision, planner_source)`` where ``planner_source`` is
        ``"model"`` or ``"template"`` — recorded on the session so the PLAN
        console shows how the plan was produced (unit 10/audit).
        """
        specialist = self._specialists.get(objective.domain)
        template_id = self._specialists.plan_template_id(
            specialist.domain, objective.goal
        ) if specialist else None

        steps: list[S.PlanStep] | None = None
        source = "template"

        if use_model and specialist:
            tool_specs = self._specialists.registered_tools(specialist.domain)
            proposed = await gateway.plan_steps(
                objective, tool_specs, specialist.domain,
            )
            if proposed:
                allowed = {spec.tool_id for spec in tool_specs}
                valid = [p for p in proposed if p["tool_id"] in allowed]
                if valid:
                    steps = [
                        S.PlanStep(
                            step_id=_step_id(i),
                            tool_id=p["tool_id"],
                            rationale=p.get("rationale") or "Model-proposed step",
                        )
                        for i, p in enumerate(valid)
                    ]
                    source = "model"

        if steps is None:
            raw = _TEMPLATES.get(template_id or "", None)
            if raw is None and specialist:
                raw = _generic_steps(
                    [spec.tool_id for spec in
                     self._specialists.registered_tools(specialist.domain)]
                )
            steps = [
                S.PlanStep(step_id=_step_id(i), tool_id=tid, rationale=rat)
                for i, (tid, rat) in enumerate(raw or [])
            ]

        revision = S.PlanRevision(
            revision_id=f"REV-{uuid.uuid4().hex[:8].upper()}",
            parent_revision_id=None,
            objective_id=objective.objective_id,
            steps=steps,
            delta_reason="initial proposal",
        )
        revision.budget_estimate = _budget_estimate(objective, steps)
        revision.hash = plan_hash(revision)
        return revision, source


def _budget_estimate(
    objective: S.InvestigationObjective,
    steps: list[S.PlanStep],
) -> S.BudgetEstimate:
    """Sum registered tools' cost estimates over the plan steps.

    Rendered on the plan BEFORE approval so the analyst sees expected burn
    against the objective's budget limits.
    """
    estimate = S.BudgetEstimate(
        budget=objective.constraints.budget,
        estimated_steps=len(steps),
    )
    for step in steps:
        tool = registry.get(step.tool_id)
        if not tool or not tool.spec.cost_estimate:
            continue
        estimate.estimated_tokens += tool.spec.cost_estimate.model_tokens or 0
        estimate.estimated_ms += tool.spec.cost_estimate.est_ms or 0
        estimate.estimated_api_calls += tool.spec.cost_estimate.api_calls or 0
    return estimate


def _step_id(index: int) -> str:
    return f"STEP-{index + 1:02d}"


plan_builder = PlanBuilder()
