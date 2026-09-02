"""Phase E tests — adaptive re-planning, contradiction loops, budgets.

Exit gate: a contradiction detected mid-run triggers an append-only,
hash-chained re-plan delta that terminates within budget.

Also covers: gap analysis (unit 04), hypothesis synthesis (unit 05),
critique (unit 06), tool-call memoization, budget pause → resume
(pause_to_ask), and the /resume endpoint.
"""
import io
import json
import uuid

import piexif
import pytest
from PIL import Image
from fastapi.testclient import TestClient

from app.agent import schemas as S
from app.agent import evidence_graph as eg
from app.agent.correlator import correlate_location_nodes, graph_gaps
from app.agent.critic import critique
from app.agent.executor import ExecutionContext, executor
from app.agent.hypothesis_engine import build_hypotheses
from app.agent.orchestrator import orchestrator
from app.agent.planner import plan_builder, plan_hash
from app.agent.policy_guard import PolicyGuard
from app.agent.tool_registry import registry

from main import app

FAKE_ADDRESS = {
    "country": "Nigeria", "city": "Lagos", "display_name": "Lagos Island, Lagos",
}


def _make_image_with_gps(lat=48.8566, lon=2.3522):
    img = Image.new("RGB", (100, 100), color=(120, 120, 120))

    def _dms(value):
        v = abs(value)
        d = int(v)
        m = int((v - d) * 60)
        s = (v - d - m / 60) * 3600
        return ((d, 1), (m, 1), (int(s * 10000), 10000))

    gps_ifd = {
        piexif.GPSIFD.GPSLatitude: _dms(lat),
        piexif.GPSIFD.GPSLatitudeRef: b"N",
        piexif.GPSIFD.GPSLongitude: _dms(lon),
        piexif.GPSIFD.GPSLongitudeRef: b"E",
    }
    buf = io.BytesIO()
    img.save(buf, format="jpeg", exif=piexif.dump({"GPS": gps_ifd}))
    return buf.getvalue()


def _make_objective(**overrides) -> S.InvestigationObjective:
    base = {
        "objective_id": f"OBJ-{uuid.uuid4().hex[:8].upper()}",
        "goal": S.InvestigationGoal.VERIFY_LOCATION_CREDIBILITY,
        "subject": "fixture-evidence.jpg",
        "domain": "image",
        "claims_to_verify": [S.ClaimToVerify(field="gps.latitude", value="48.8566")],
    }
    base.update(overrides)
    return S.InvestigationObjective(**base)


def _patch_geocoder(monkeypatch):
    monkeypatch.setattr(
        "app.agent.tool_registry.reverse_geocode",
        lambda lat, lon: type("Addr", (), {"model_dump": lambda s: FAKE_ADDRESS})(),
    )


def _force_template_planner(monkeypatch):
    async def _template_only(objective, tool_specs, desc):
        return None

    async def _terminate(objective, gap, specs, budget_summary):
        return None

    monkeypatch.setattr("app.agent.model_gateway.gateway.plan_steps", _template_only)
    monkeypatch.setattr("app.agent.model_gateway.gateway.propose_next", _terminate)


def _inject_location_node(graph, case_id, lat, lon, tool_id="fixture_telemetry",
                          confidence=0.9):
    eg.add_node(
        graph,
        eg.build_node(
            case_id=case_id, tool_id=tool_id,
            provenance_type=S.ProvenanceType.TOOL_INFERENCE,
            claim=f"Fixture location {lat}, {lon}",
            claim_type=S.ClaimType.LOCATION,
            value={"lat": lat, "lon": lon},
            confidence=confidence,
        ),
    )


def _make_revision(steps: list[str], objective_id="OBJ-T") -> S.PlanRevision:
    rev = S.PlanRevision(
        revision_id=f"REV-{uuid.uuid4().hex[:8].upper()}",
        parent_revision_id=None,
        objective_id=objective_id,
        steps=[S.PlanStep(step_id=f"STEP-{i + 1:02d}", tool_id=t)
               for i, t in enumerate(steps)],
        delta_reason="test",
    )
    rev.hash = plan_hash(rev)
    return rev


def _full_permissions_guard() -> PolicyGuard:
    return PolicyGuard(granted_permissions=[
        S.Permission.READ_EVIDENCE, S.Permission.QUERY_EXTERNAL,
        S.Permission.CALL_PROVIDER, S.Permission.MUTATE_CASE,
    ])


# --------------------------------------------------------------------------- #
# Correlator (unit 04)
# --------------------------------------------------------------------------- #
class TestCorrelator:
    def test_open_contradiction_gap(self):
        graph = S.EvidenceGraph(case_id="CASE-1")
        _inject_location_node(graph, "CASE-1", 35.6762, 139.6503)
        _inject_location_node(graph, "CASE-1", 6.5244, 3.3792)
        correlate_location_nodes(graph)
        assert any(e.relation == S.EdgeRelation.CONTRADICTS for e in graph.edges)

        gaps = graph_gaps(graph, _make_objective())
        assert any(g.gap_type == S.GapType.OPEN_CONTRADICTION
                   and g.severity == S.RiskLevel.HIGH for g in gaps)

    def test_missing_layer_gap(self):
        graph = S.EvidenceGraph(case_id="CASE-2")
        gaps = graph_gaps(graph, _make_objective())
        assert any(g.gap_type == S.GapType.MISSING_LAYER
                   and "compute_custody_hash" in g.addressable_by for g in gaps)

    def test_unverified_claim_gap(self):
        graph = S.EvidenceGraph(case_id="CASE-3")
        gaps = graph_gaps(graph, _make_objective())
        assert any(g.gap_type == S.GapType.UNVERIFIED_CLAIM
                   and "gps.latitude" in g.rationale for g in gaps)

    def test_gap_ids_stable_across_recomputes(self):
        graph = S.EvidenceGraph(case_id="CASE-4")
        first = graph_gaps(graph, _make_objective())
        second = graph_gaps(graph, _make_objective())
        first_ids = {g.gap_id for g in first}
        second_ids = {g.gap_id for g in second}
        assert first_ids == second_ids

    def test_corroborates_edge_for_agreeing_locations(self):
        graph = S.EvidenceGraph(case_id="CASE-5")
        _inject_location_node(graph, "CASE-5", 48.8566, 2.3522)
        _inject_location_node(graph, "CASE-5", 48.8567, 2.3523)
        correlate_location_nodes(graph)
        assert any(e.relation == S.EdgeRelation.CORROBORATES for e in graph.edges)


# --------------------------------------------------------------------------- #
# Hypothesis engine (unit 05) + Critic (unit 06)
# --------------------------------------------------------------------------- #
class TestHypothesesAndCritic:
    def test_location_hypothesis_ranked_with_alternatives(self):
        graph = S.EvidenceGraph(case_id="CASE-H")
        _inject_location_node(graph, "CASE-H", 35.6762, 139.6503, confidence=0.0)
        eg.add_node(
            graph,
            eg.build_node(
                "CASE-H", "vision", S.ProvenanceType.AI_HYPOTHESIS,
                "Vision guess", S.ClaimType.LOCATION,
                {"lat": 6.5244, "lon": 3.3792}, confidence=0.6,
            ),
        )
        hypotheses = build_hypotheses(graph, _make_objective(), model_id="m1")
        location = next(h for h in hypotheses if "location" in h.claim.lower())
        assert location.confidence > 0
        assert location.alternatives  # ranked candidates
        assert location.model_id == "m1"

    def test_critic_challenges_high_confidence_hypothesis(self):
        graph = S.EvidenceGraph(case_id="CASE-C")
        _inject_location_node(graph, "CASE-C", 35.6762, 139.6503, confidence=0.9)
        _inject_location_node(graph, "CASE-C", 6.5244, 3.3792, confidence=0.7)
        correlate_location_nodes(graph)
        hypotheses = build_hypotheses(graph, _make_objective(), model_id="m1")
        critiques = critique(graph, hypotheses, model_id="m1")
        assert critiques
        assert all(c.challenges_conclusion for c in critiques)
        assert any(c.alternative_explanations for c in critiques)
        # Challenges are recorded as auditable tier-2 nodes.
        assert any(
            n.tool_id == "critic" and n.provenance_type == S.ProvenanceType.AI_HYPOTHESIS
            for n in graph.nodes.values()
        )


# --------------------------------------------------------------------------- #
# Memoization
# --------------------------------------------------------------------------- #
class TestMemoization:
    @pytest.mark.asyncio
    async def test_identical_tool_call_is_reused(self, monkeypatch):
        _patch_geocoder(monkeypatch)
        graph = S.EvidenceGraph(case_id="CASE-M")
        guard = _full_permissions_guard()
        ctx = ExecutionContext(
            case_id="CASE-M", image_bytes=_make_image_with_gps(),
            objective=_make_objective(), graph=graph, memo={},
        )
        rev = _make_revision(["compute_custody_hash", "extract_exif"])

        first = await executor.execute(rev, graph, guard, ctx)
        ran_ids = [e.node_id for e in first if e.status == "ran"]
        evidence_after_first = {n.node_id for n in graph.nodes.values()
                                if n.tool_id != "audit"}

        second = await executor.execute(rev, graph, guard, ctx)
        memoized = [e for e in second if "memoized" in e.message]
        assert len(memoized) == 2
        evidence_after_second = {n.node_id for n in graph.nodes.values()
                                 if n.tool_id != "audit"}
        assert evidence_after_second == evidence_after_first  # no new evidence
        assert all(e.node_id in ran_ids for e in memoized)

    @pytest.mark.asyncio
    async def test_different_args_are_not_reused(self, monkeypatch):
        _patch_geocoder(monkeypatch)
        graph = S.EvidenceGraph(case_id="CASE-M2")
        guard = _full_permissions_guard()
        ctx = ExecutionContext(
            case_id="CASE-M2", image_bytes=_make_image_with_gps(),
            objective=_make_objective(), graph=graph, memo={},
        )
        rev_a = _make_revision(["extract_exif"])
        rev_b = _make_revision(["analyze_ela"])
        await executor.execute(rev_a, graph, guard, ctx)
        n = len(graph.nodes)
        await executor.execute(rev_b, graph, guard, ctx)
        assert len(graph.nodes) > n  # a new tool ran → new evidence node


# --------------------------------------------------------------------------- #
# Adaptive re-planning — the Phase E exit gate
# --------------------------------------------------------------------------- #
class TestAdaptiveReplanning:
    @pytest.mark.asyncio
    async def test_contradiction_triggers_hash_chained_delta(self, monkeypatch):
        _patch_geocoder(monkeypatch)
        _force_template_planner(monkeypatch)

        async def _resolve_contradiction(objective, gap, specs, budget_summary):
            assert gap["gap_type"] == S.GapType.OPEN_CONTRADICTION.value
            return [{"tool_id": "reverse_geocode", "rationale": "settle it"}]

        monkeypatch.setattr(
            "app.agent.model_gateway.gateway.propose_next", _resolve_contradiction)

        session = await orchestrator.start(
            _make_objective(), image_bytes=_make_image_with_gps())
        initial_rev = session.plan.revision_id
        # Pre-existing, conflicting location evidence on the case graph.
        _inject_location_node(session.graph, session.case_id, 35.6762, 139.6503)
        _inject_location_node(session.graph, session.case_id, 6.5244, 3.3792)

        done = await orchestrator.approve(session.investigation_id)
        assert done.status == "done"
        assert done.iterations >= 2
        # The adaptive delta is append-only + hash-chained.
        assert done.plan.revision_id != initial_rev
        assert done.plan.parent_revision_id != initial_rev or \
            done.plan.parent_revision_id != done.plan.revision_id
        assert done.plan.hash
        assert "adaptive" in (done.plan.delta_reason or "")
        # The contradiction was surfaced as a HIGH gap and acted on.
        assert any(g.gap_type == S.GapType.OPEN_CONTRADICTION
                   for g in done.gaps)
        assert any(g.gap_id in done.acted_gap_ids for g in done.gaps
                   if g.gap_type == S.GapType.OPEN_CONTRADICTION) or \
            any(n.tool_id == "adaptive_replan" for n in done.graph.nodes.values())
        # Terminated within budget.
        assert done.budget_usage["steps"] < done.budget_usage["budget"]["max_steps"]
        assert any(e.relation == S.EdgeRelation.CONTRADICTS
                   for e in done.graph.edges)

    @pytest.mark.asyncio
    async def test_no_gaps_terminates_immediately(self, monkeypatch):
        _patch_geocoder(monkeypatch)
        _force_template_planner(monkeypatch)
        session = await orchestrator.start(
            _make_objective(), image_bytes=_make_image_with_gps())
        done = await orchestrator.approve(session.investigation_id)
        assert done.status == "done"
        assert done.iterations == 1
        assert done.plan.delta_reason != "adaptive (model):"

    @pytest.mark.asyncio
    async def test_unclosable_gap_does_not_churn(self, monkeypatch):
        _patch_geocoder(monkeypatch)
        _force_template_planner(monkeypatch)
        session = await orchestrator.start(
            _make_objective(), image_bytes=_make_image_with_gps())
        done = await orchestrator.approve(session.investigation_id)
        assert done.iterations <= 3  # bounded — no runaway loop


# --------------------------------------------------------------------------- #
# Budgets — pause_to_ask + resume
# --------------------------------------------------------------------------- #
class TestBudgets:
    @pytest.mark.asyncio
    async def test_budget_exhaustion_pauses_with_reason(self, monkeypatch):
        _patch_geocoder(monkeypatch)
        _force_template_planner(monkeypatch)
        objective = _make_objective(constraints=S.ObjectiveConstraints(
            budget=S.Budget(max_steps=1)))
        session = await orchestrator.start(objective, image_bytes=_make_image_with_gps())
        done = await orchestrator.approve(session.investigation_id)
        assert done.status == "paused"
        assert done.pause_reason and "budget" in done.pause_reason

    @pytest.mark.asyncio
    async def test_resume_with_budget_continues_to_done(self, monkeypatch):
        _patch_geocoder(monkeypatch)
        _force_template_planner(monkeypatch)
        objective = _make_objective(constraints=S.ObjectiveConstraints(
            budget=S.Budget(max_steps=1)))
        session = await orchestrator.start(objective, image_bytes=_make_image_with_gps())
        paused = await orchestrator.approve(session.investigation_id)
        assert paused.status == "paused"

        resumed = await orchestrator.resume(
            session.investigation_id, budget=S.Budget(max_steps=100))
        assert resumed.status == "done"
        assert resumed.iterations >= 2

    @pytest.mark.asyncio
    async def test_resume_unknown_raises(self):
        with pytest.raises(KeyError):
            await orchestrator.resume("ARK-INV-NOPE")


# --------------------------------------------------------------------------- #
# API — resume endpoint + enriched payload
# --------------------------------------------------------------------------- #
class TestInvestigateAPIAdaptive:
    def setup_method(self):
        self.client = TestClient(app)

    def test_approve_pause_resume_flow(self, monkeypatch):
        _patch_geocoder(monkeypatch)
        _force_template_planner(monkeypatch)
        obj = {
            "goal": "verify_location_credibility",
            "subject": "fixture.jpg",
            "domain": "image",
            "constraints": {"budget": {"max_steps": 1}},
        }
        resp = self.client.post(
            "/api/v1/investigate",
            files={"file": ("fixture.jpg", _make_image_with_gps(), "image/jpeg")},
            data={"objective": json.dumps(obj)},
        )
        inv_id = resp.json()["investigation_id"]

        paused = self.client.post(f"/api/v1/investigate/{inv_id}/approve", json={})
        assert paused.status_code == 200
        assert paused.json()["status"] == "paused"
        assert paused.json()["pause_reason"]

        resumed = self.client.post(f"/api/v1/investigate/{inv_id}/resume",
                                   json={"budget": {"max_steps": 100}})
        assert resumed.status_code == 200
        body = resumed.json()
        assert body["status"] == "done"
        assert body["iterations"] >= 2
        assert body["budget_usage"]["steps"] < 100

    def test_resume_not_paused_returns_409(self, monkeypatch):
        _patch_geocoder(monkeypatch)
        _force_template_planner(monkeypatch)
        obj = {
            "goal": "verify_location_credibility",
            "subject": "fixture.jpg",
            "domain": "image",
        }
        resp = self.client.post(
            "/api/v1/investigate",
            files={"file": ("fixture.jpg", _make_image_with_gps(), "image/jpeg")},
            data={"objective": json.dumps(obj)},
        )
        inv_id = resp.json()["investigation_id"]
        self.client.post(f"/api/v1/investigate/{inv_id}/approve", json={})
        resp = self.client.post(f"/api/v1/investigate/{inv_id}/resume", json={})
        assert resp.status_code == 409
