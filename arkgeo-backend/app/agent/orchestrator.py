"""Investigation Orchestrator — cognitive units 01, 04, 05, 06, 07, 10.

Unit 01 (Orchestrator): conducts an objective end-to-end —
objective → planner → approval → executor → evidence → findings.

Unit 04 (Correlator): after each execution pass, reads the graph for gaps
(open contradictions, single-source findings, missing layers, unverified
claims). The adaptive loop acts on **gaps**, never free-form tool picks.

Unit 05 (Hypothesis Engine) + Unit 06 (Critic): synthesize ranked hypotheses
and challenge them; both recorded as auditable tier-2 artifacts.

Unit 07 (Context & Memory, light): the ``InvestigationSession`` is the
persistent context frame for a case.

Unit 10 (Findings Engine): evidence nodes are promoted to structured Findings
through the graph's promotion rule — tier-2 nodes are refused without
corroboration by structure, not prompt.

Phase E — the **adaptive loop**:

    execute(plan) → correlate → promote → hypotheses/critiques/gaps →
    if no actionable gap: done
    elif budget exhausted / max iterations / step-confirm needed: paused
    else: model proposes ordering among the gap's candidate tools (or
          termination) → build a hash-chained delta revision → execute
          (memoized) → repeat.

Sessions live in an in-memory thread-safe store for Phase C/E (mirrors
``services/state_cache``). Plans are append-only / hash-chained.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from . import evidence_graph as eg
from . import schemas as S
from .correlator import actionable_gaps, correlate_location_nodes, graph_gaps
from .critic import critique
from .evidence_graph import _agree_within_tolerance
from .executor import AgentLogEntry, ExecutionContext, PlanExecutor
from .hypothesis_engine import build_hypotheses
from .model_gateway import gateway
from .planner import _budget_estimate, plan_builder, plan_hash
from .policy_guard import PolicyGuard
from .tool_registry import registry

logger = logging.getLogger(__name__)

# An authorized investigator's capability surface (Phase C/E default grant).
_INVESTIGATOR_PERMISSIONS = [
    S.Permission.READ_EVIDENCE,
    S.Permission.QUERY_EXTERNAL,
    S.Permission.CALL_PROVIDER,
    S.Permission.MUTATE_CASE,
]

# Cap on adaptive iterations per approval/resume — a hard stop on loops.
_MAX_ITERATIONS = 5

_FINDING_TYPES: dict[S.ClaimType, S.FindingType] = {
    S.ClaimType.LOCATION: S.FindingType.LOCATION_CREDIBILITY,
    S.ClaimType.TIMESTAMP: S.FindingType.TIMELINE_ANOMALY,
    S.ClaimType.INTEGRITY: S.FindingType.TAMPER_DETECTION,
    S.ClaimType.SOURCE: S.FindingType.SOURCE_CONFLICT,
    S.ClaimType.DEVICE: S.FindingType.DEVICE_ATTRIBUTION,
    S.ClaimType.METADATA: S.FindingType.PROVENANCE_STATE,
}

_RISK_ORDER: dict[S.RiskLevel, int] = {
    S.RiskLevel.LOW: 0, S.RiskLevel.MEDIUM: 1,
    S.RiskLevel.ELEVATED: 2, S.RiskLevel.HIGH: 3,
}


@dataclass
class InvestigationSession:
    """The context frame (unit 07) for one AI investigation."""
    investigation_id: str
    case_id: str
    objective: S.InvestigationObjective
    plan: S.PlanRevision
    graph: eg.EvidenceGraph
    planner_source: str = "template"
    activity_log: list[dict] = field(default_factory=list)
    status: str = "proposed"     # proposed | approved | running | done | paused | rejected | failed
    pause_reason: Optional[str] = None
    model_id: Optional[str] = None
    image_bytes: Optional[bytes] = field(default=None, repr=False)
    memo: dict[str, str] = field(default_factory=dict)
    iterations: int = 0
    hypotheses: list[S.Hypothesis] = field(default_factory=list)
    critiques: list[S.Critique] = field(default_factory=list)
    gaps: list[S.GraphGap] = field(default_factory=list)
    acted_gap_ids: list[str] = field(default_factory=list)
    budget_usage: dict = field(default_factory=dict)
    revisions: list[S.PlanRevision] = field(default_factory=list)
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    approved_at_ms: Optional[int] = None
    updated_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> dict:
        merged = _merged_steps(self.revisions)
        return {
            "investigation_id": self.investigation_id,
            "case_id": self.case_id,
            "objective": self.objective.model_dump(),
            "plan": self.plan.model_dump(),
            "planner_source": self.planner_source,
            "model_id": self.model_id,
            "status": self.status,
            "pause_reason": self.pause_reason,
            "created_at_ms": self.created_at_ms,
            "approved_at_ms": self.approved_at_ms,
            "updated_at_ms": self.updated_at_ms,
            "activity_log": self.activity_log,
            "iterations": self.iterations,
            "hypotheses": [h.model_dump() for h in self.hypotheses],
            "critiques": [c.model_dump() for c in self.critiques],
            "gaps": [g.model_dump() for g in self.gaps],
            "acted_gap_ids": list(self.acted_gap_ids),
            "budget_usage": self.budget_usage,
            "graph": eg.to_dict(self.graph),
            "findings": [f.model_dump() for f in self.graph.findings],
            "revisions": [r.model_dump() for r in self.revisions],
            "merged_plan": {"steps": merged, "count": len(merged)},
        }


class InvestigationStore:
    """Thread-safe in-memory store of active investigations (Phase C/E)."""

    def __init__(self) -> None:
        self._sessions: dict[str, InvestigationSession] = {}
        self._lock = threading_lock()

    def put(self, session: InvestigationSession) -> None:
        with self._lock:
            self._sessions[session.investigation_id] = session

    def get(self, investigation_id: str) -> Optional[InvestigationSession]:
        with self._lock:
            return self._sessions.get(investigation_id)

    def list(self) -> list[InvestigationSession]:
        with self._lock:
            return list(self._sessions.values())


def threading_lock():
    import threading
    return threading.Lock()


def _gen_investigation_id() -> str:
    return f"ARK-INV-{uuid.uuid4().hex[:8].upper()}"


def _gen_case_id() -> str:
    return f"ARK-CASE-{uuid.uuid4().hex[:8].upper()}"


def _make_guard(objective: S.InvestigationObjective) -> PolicyGuard:
    guard = PolicyGuard(granted_permissions=_INVESTIGATOR_PERMISSIONS)
    if objective.constraints.budget:
        guard.set_budget(objective.constraints.budget)
    return guard


class InvestigationOrchestrator:
    """Unit 01 — the conductor for one objective at a time."""

    def __init__(self) -> None:
        self.store = InvestigationStore()
        self.executor: PlanExecutor = PlanExecutor()

    # ------------------------------------------------------------------ #
    async def start(
        self,
        objective: S.InvestigationObjective,
        image_bytes: Optional[bytes] = None,
        case_id: Optional[str] = None,
    ) -> InvestigationSession:
        """Create a proposed investigation (objective → plan). No execution."""
        case_id = case_id or _gen_case_id()
        plan, source = await plan_builder.build(objective, case_id)
        session = InvestigationSession(
            investigation_id=_gen_investigation_id(),
            case_id=case_id,
            objective=objective,
            plan=plan,
            graph=eg.EvidenceGraph(case_id=case_id),
            planner_source=source,
            status="proposed",
            image_bytes=image_bytes,
            revisions=[plan],
        )
        if source == "model":
            session.model_id = gateway.default_model
        self.store.put(session)
        return session

    # ------------------------------------------------------------------ #
    async def approve(
        self,
        investigation_id: str,
        approved_by: str = "analyst",
        amend_steps: Optional[list[dict[str, str]]] = None,
        image_bytes: Optional[bytes] = None,
    ) -> InvestigationSession:
        """Approve (and optionally amend) the plan, then run the adaptive loop."""
        session = self.store.get(investigation_id)
        if not session:
            raise KeyError(f"No investigation {investigation_id}")
        if session.status != "proposed":
            raise ValueError(
                f"Investigation {investigation_id} is {session.status} — not proposable"
            )

        guard = _make_guard(session.objective)

        # ---- Optional amendment → new hash-chained revision ---------------- #
        if amend_steps:
            session.plan = _build_revision(
                session, amend_steps, delta_reason="analyst amendment",
            )
            session.revisions.append(session.plan)

        _seal_approval(session, approved_by)
        if image_bytes is not None:
            session.image_bytes = image_bytes

        # Human decision recorded on the graph (auditable approval node).
        eg.add_node(
            session.graph,
            eg.build_node(
                session.case_id, "human", S.ProvenanceType.CRYPTOGRAPHIC,
                f"Plan approved by {approved_by}", S.ClaimType.OTHER,
                {"revision_id": session.plan.revision_id,
                 "approved_by": approved_by},
            ),
        )

        ctx = ExecutionContext(
            case_id=session.case_id,
            image_bytes=session.image_bytes,
            objective=session.objective,
            graph=session.graph,
            memo=session.memo,
        )
        await self._run_adaptive(session, guard, ctx)
        session.updated_at_ms = int(time.time() * 1000)
        if session.objective.constraints.zero_retention:
            session.image_bytes = None  # zero-retention: drop evidence post-use
        self.store.put(session)
        return session

    # ------------------------------------------------------------------ #
    async def resume(
        self,
        investigation_id: str,
        budget: Optional[S.Budget] = None,
        approved_by: str = "analyst",
    ) -> InvestigationSession:
        """Continue a paused investigation (pause_to_ask).

        The analyst may raise the budget; the adaptive loop re-enters from
        the current graph state. Memoization keeps re-runs cheap/consistent.
        """
        session = self.store.get(investigation_id)
        if not session:
            raise KeyError(f"No investigation {investigation_id}")
        if session.status != "paused":
            raise ValueError(
                f"Investigation {investigation_id} is {session.status} — not resumable"
            )

        guard = _make_guard(session.objective)
        if budget is not None:
            guard.set_budget(budget)

        session.pause_reason = None
        session.status = "running"
        eg.add_node(
            session.graph,
            eg.build_node(
                session.case_id, "human", S.ProvenanceType.CRYPTOGRAPHIC,
                f"Investigation resumed by {approved_by}", S.ClaimType.OTHER,
                {"revision_id": session.plan.revision_id,
                 "approved_by": approved_by},
            ),
        )

        ctx = ExecutionContext(
            case_id=session.case_id,
            image_bytes=session.image_bytes,
            objective=session.objective,
            graph=session.graph,
            memo=session.memo,
        )
        await self._run_adaptive(session, guard, ctx)
        session.updated_at_ms = int(time.time() * 1000)
        self.store.put(session)
        return session

    def get(self, investigation_id: str) -> Optional[InvestigationSession]:
        return self.store.get(investigation_id)

    def session_dicts(self) -> list[dict]:
        return [s.to_dict() for s in self.store.list()]

    # ------------------------------------------------------------------ #
    async def _run_adaptive(
        self,
        session: InvestigationSession,
        guard: PolicyGuard,
        ctx: ExecutionContext,
    ) -> None:
        """The Phase E adaptive loop. Runs until convergence, budget
        exhaustion, max iterations, or a step-confirmation need."""
        while True:
            session.iterations += 1

            # ---- Execute the current (possibly delta) revision ------------ #
            log = await self.executor.execute(session.plan, session.graph, guard, ctx)
            session.activity_log.extend(e.to_dict() for e in log)

            # ---- Correlate + promote + reason over the new state ---------- #
            correlate_location_nodes(session.graph)
            self._promote_findings(session)
            session.gaps = graph_gaps(session.graph, session.objective)
            session.hypotheses = build_hypotheses(
                session.graph, session.objective, session.model_id)
            session.critiques = critique(
                session.graph, session.hypotheses, session.model_id)
            session.budget_usage = guard.usage.to_dict()

            # ---- Termination / pause conditions --------------------------- #
            if not actionable_gaps(session.gaps):
                session.status = "done"
                break
            exhausted = guard.usage.exhausted()
            if exhausted:
                session.status = "paused"
                session.pause_reason = exhausted
                break
            if session.iterations >= _MAX_ITERATIONS:
                session.status = "paused"
                session.pause_reason = "maximum adaptive iterations reached"
                break

            # ---- Choose the next action among the gaps -------------------- #
            next_tools = await self._select_next_action(session, guard, ctx)
            if next_tools is None:
                if session.pause_reason:
                    session.status = "paused"
                else:
                    session.status = "done"  # model/planner chose termination
                break

            # ---- Build + run a hash-chained delta revision ----------------- #
            steps, gap, source = next_tools
            session.acted_gap_ids.append(gap.gap_id)
            nodes_before = len(session.graph.nodes)
            session.plan = _build_revision(
                session, steps,
                delta_reason=f"adaptive ({source}): close {gap.gap_id} "
                             f"{gap.gap_type.value}",
            )
            session.revisions.append(session.plan)
            _seal_approval(session, "adaptive")
            eg.add_node(
                session.graph,
                eg.build_node(
                    session.case_id, "adaptive_replan",
                    S.ProvenanceType.AI_HYPOTHESIS,
                    f"Adaptive re-plan ({source}) closing {gap.gap_id}",
                    S.ClaimType.OTHER,
                    {"revision_id": session.plan.revision_id,
                     "gap_id": gap.gap_id, "gap_type": gap.gap_type.value,
                     "source": source,
                     "steps": [s.tool_id for s in session.plan.steps]},
                    confidence=0.5,
                    model_id=session.model_id,
                ),
            )
            # If the delta produced no new evidence (all memoized / nothing
            # addressable), the gap is not closable this pass — mark resolved
            # to prevent churn; the loop terminates at the top of next round.
            if len(session.graph.nodes) == nodes_before + 1:
                for g in session.gaps:
                    if g.gap_id == gap.gap_id:
                        g.resolved = True

    # ------------------------------------------------------------------ #
    async def _select_next_action(
        self,
        session: InvestigationSession,
        guard: PolicyGuard,
        ctx: ExecutionContext,
    ) -> Optional[tuple[list[dict[str, str]], S.GraphGap, str]]:
        """Pick the highest-severity actionable gap and its tool ordering.

        The candidate set is closed to the gap's ``addressable_by`` tools
        that policy permits. The model may order them or choose termination;
        the deterministic fallback runs them in declared priority order.
        """
        for gap in sorted(actionable_gaps(session.gaps),
                          key=lambda g: -_RISK_ORDER[g.severity]):
            if gap.gap_id in session.acted_gap_ids:
                continue  # already re-planned for this gap — no churn
            allowed = [
                tid for tid in gap.addressable_by
                if registry.get(tid) and guard.evaluate(tid).allowed
            ]
            if not allowed:
                continue

            # A gap whose only options need step confirmation → pause_to_ask.
            needs_confirm = [
                tid for tid in allowed
                if guard.evaluate(tid).approval_tier == S.ApprovalTier.STEP_CONFIRM
                and not guard.is_confirmed(tid)
            ]
            if needs_confirm and set(allowed) == set(needs_confirm):
                session.pause_reason = (
                    f"closing {gap.gap_id} requires step confirmation: "
                    f"{', '.join(needs_confirm)}")
                return None

            specs = [registry.get(tid).spec for tid in allowed]
            started = time.perf_counter()
            try:
                proposed = await gateway.propose_next(
                    session.objective, gap.model_dump(), specs,
                    str(guard.usage.to_dict()),
                )
            except Exception:  # noqa: BLE001 — model must never break the loop
                logger.warning("propose_next failed; deterministic fallback")
                proposed = None
            elapsed = int((time.perf_counter() - started) * 1000)
            guard.record_run("planner", api_calls=1, elapsed_ms=elapsed)

            if proposed:
                chosen = [p for p in proposed if p.get("tool_id") in allowed]
                if chosen:
                    return chosen, gap, "model"
                return None  # model chose termination (empty/invalid list)

            # Deterministic fallback: run the gap's permitted tools in order.
            return ([{"tool_id": tid, "rationale": "adaptive fallback"}
                     for tid in allowed], gap, "deterministic")

        return None  # no actionable gap → terminate (done)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _promote_findings(session: InvestigationSession) -> None:
        """Unit 10 — promote eligible evidence to structured Findings.

        Tier-0/1 nodes promote alone; tier-2 nodes are refused by the graph's
        promotion rule unless corroborated. PromotionDenied is expected and
        swallowed — the hypothesis stays a hypothesis.
        """
        domain = session.objective.domain
        for node in session.graph.nodes.values():
            if node.provenance_type == S.ProvenanceType.AI_HYPOTHESIS:
                continue
            try:
                finding = eg.promote_to_finding(session.graph, node.node_id)
            except eg.PromotionDenied:
                continue
            finding.finding_type = _FINDING_TYPES.get(
                node.claim_type, S.FindingType.OTHER)
            finding.domain = domain
            finding.severity = _severity_for(node)


def _merged_steps(revisions: list[S.PlanRevision]) -> list[dict]:
    """Accumulate the plan lineage into one ordered step list for the console.

    Steps are merged by ``tool_id`` in first-seen order (initial proposal
    first, then amendments, then adaptive deltas). A tool re-planned by a
    later revision keeps its place but is tagged with the newest status /
    source revision so the PLAN tab reads as one investigation, not N deltas.
    """
    merged: list[dict] = []
    index: dict[str, int] = {}
    for revision in revisions:
        for step in revision.steps:
            if step.tool_id in index:
                entry = merged[index[step.tool_id]]
                entry["status"] = step.status.value
                entry["result_node_id"] = step.result_node_id
                entry["revision_id"] = revision.revision_id
                entry["delta_reason"] = revision.delta_reason
                continue
            index[step.tool_id] = len(merged)
            merged.append({
                "step_id": step.step_id,
                "tool_id": step.tool_id,
                "rationale": step.rationale,
                "status": step.status.value,
                "result_node_id": step.result_node_id,
                "revision_id": revision.revision_id,
                "delta_reason": revision.delta_reason,
            })
    return merged


def _build_revision(
    session: InvestigationSession,
    steps_raw: list[dict[str, str]],
    delta_reason: str,
) -> S.PlanRevision:
    """Construct a new hash-chained revision from tool/step dicts."""
    steps = [
        S.PlanStep(
            step_id=f"STEP-{i + 1:02d}",
            tool_id=step.get("tool_id", ""),
            rationale=step.get("rationale") or "Re-plan step",
        )
        for i, step in enumerate(steps_raw)
        if step.get("tool_id")
    ]
    revision = S.PlanRevision(
        revision_id=f"REV-{uuid.uuid4().hex[:8].upper()}",
        parent_revision_id=session.plan.revision_id,
        objective_id=session.objective.objective_id,
        steps=steps,
        delta_reason=delta_reason,
    )
    revision.budget_estimate = _budget_estimate(session.objective, steps)
    revision.hash = plan_hash(revision)
    return revision


def _seal_approval(session: InvestigationSession, approved_by: str) -> None:
    session.plan.approved_at_ms = int(time.time() * 1000)
    session.plan.approved_by = approved_by
    session.approved_at_ms = session.plan.approved_at_ms
    session.status = "running"


def _severity_for(node: S.EvidenceNode) -> S.FindingSeverity:
    if node.claim_type in (S.ClaimType.INTEGRITY,):
        return S.FindingSeverity.HIGH
    if node.confidence >= 0.8:
        return S.FindingSeverity.HIGH if node.claim_type == S.ClaimType.LOCATION \
            else S.FindingSeverity.MEDIUM
    return S.FindingSeverity.MEDIUM


orchestrator = InvestigationOrchestrator()
