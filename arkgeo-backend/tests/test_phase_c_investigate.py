"""Phase C tests — investigation loop (planner → guard → executor → graph).

Covers the deterministic orchestrator substrate behind Investigation Mode:
  * Planner (unit 02): template plan, model-proposed plan, model fallback.
  * Executor (unit 03 + 08 usage): authorized runs, denied skips, argument
    resolution from graph state, audit lineage.
  * Orchestrator (units 01/07/10): proposed → approved → done lifecycle,
    hash-chained amendment, finding promotion.
  * API: POST /investigate, POST /investigate/{id}/approve, GET /investigate/{id}.

Network/hardware dependency note: the ``reverse_geocode`` tool calls OSM
Nominatim — every test patches it with a fixed address so the suite stays
hermetic and fast.
"""
import io
import json
import uuid

import piexif
import pytest
from PIL import Image
from fastapi.testclient import TestClient

from app.agent import schemas as S
from app.agent.executor import ExecutionContext, executor
from app.agent.orchestrator import orchestrator
from app.agent.planner import plan_builder
from app.agent.policy_guard import PolicyGuard
from app.agent.tool_registry import registry

from main import app

FAKE_ADDRESS = {
    "country": "France", "state": "Ile-de-France", "city": "Paris",
    "road": "Rue de Rivoli", "postcode": "75001",
    "display_name": "Rue de Rivoli, Paris, France",
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
    exif_bytes = piexif.dump({"GPS": gps_ifd})
    buf = io.BytesIO()
    img.save(buf, format="jpeg", exif=exif_bytes)
    return buf.getvalue()


def _make_objective(**overrides) -> S.InvestigationObjective:
    base = {
        "objective_id": f"OBJ-{uuid.uuid4().hex[:8].upper()}",
        "goal": S.InvestigationGoal.VERIFY_LOCATION_CREDIBILITY,
        "subject": "fixture-evidence.jpg",
        "domain": "image",
        "claims_to_verify": [
            S.ClaimToVerify(field="gps.latitude", value="48.8566"),
        ],
    }
    base.update(overrides)
    return S.InvestigationObjective(**base)


def _patch_geocoder(monkeypatch):
    monkeypatch.setattr(
        "app.agent.tool_registry.reverse_geocode",
        lambda lat, lon: type("Addr", (), {"model_dump": lambda s: FAKE_ADDRESS})(),
    )


def _force_template_planner(monkeypatch):
    """Pin the planner + adaptive reasoner to deterministic behavior.

    The live Ollama model is available on dev hosts — the model paths are
    exercised separately (TestPlanner / adaptive tests); everywhere else we
    want a fixed, reproducible 16-step plan and immediate termination.
    """

    async def _template_only(objective, tool_specs, desc):
        return None

    async def _terminate(objective, gap, specs, budget_summary):
        return None  # model chose termination → adaptive loop stops

    monkeypatch.setattr("app.agent.model_gateway.gateway.plan_steps", _template_only)
    monkeypatch.setattr("app.agent.model_gateway.gateway.propose_next", _terminate)


def _new_case_id() -> str:
    return f"ARK-CASE-{uuid.uuid4().hex[:8].upper()}"


# --------------------------------------------------------------------------- #
# Planner (unit 02)
# --------------------------------------------------------------------------- #
class TestPlanner:
    @pytest.mark.asyncio
    async def test_template_plan_is_registered_and_hashed(self):
        obj = _make_objective()
        plan, source = await plan_builder.build(obj, _new_case_id(), use_model=False)
        assert source == "template"
        assert len(plan.steps) == 16
        assert plan.hash
        assert plan.parent_revision_id is None
        for step in plan.steps:
            assert registry.get(step.tool_id) is not None, step.tool_id
        ids = [s.tool_id for s in plan.steps]
        assert "compute_custody_hash" in ids and "fuse_geolocation" in ids

    @pytest.mark.asyncio
    async def test_model_path_used_when_valid(self, monkeypatch):
        async def fake_plan_steps(objective, tool_specs, desc):
            return [
                {"tool_id": "extract_exif", "rationale": "GPS first"},
                {"tool_id": "compute_custody_hash", "rationale": "integrity"},
            ]

        monkeypatch.setattr("app.agent.model_gateway.gateway.plan_steps", fake_plan_steps)
        plan, source = await plan_builder.build(_make_objective(), _new_case_id())
        assert source == "model"
        assert [s.tool_id for s in plan.steps] == ["extract_exif", "compute_custody_hash"]

    @pytest.mark.asyncio
    async def test_model_failure_falls_back_to_template(self, monkeypatch):
        async def broken(objective, tool_specs, desc):
            return None

        monkeypatch.setattr("app.agent.model_gateway.gateway.plan_steps", broken)
        plan, source = await plan_builder.build(_make_objective(), _new_case_id())
        assert source == "template"
        assert len(plan.steps) == 16

    @pytest.mark.asyncio
    async def test_model_invalid_ids_are_dropped(self, monkeypatch):
        async def bad(objective, tool_specs, desc):
            return [
                {"tool_id": "extract_exif", "rationale": "ok"},
                {"tool_id": "totally_not_a_tool", "rationale": "hallucinated"},
            ]

        monkeypatch.setattr("app.agent.model_gateway.gateway.plan_steps", bad)
        plan, source = await plan_builder.build(_make_objective(), _new_case_id())
        assert source == "model"
        assert [s.tool_id for s in plan.steps] == ["extract_exif"]


# --------------------------------------------------------------------------- #
# Executor (unit 03 + policy guard usage)
# --------------------------------------------------------------------------- #
class TestExecutor:
    @pytest.mark.asyncio
    async def test_full_plan_executes_with_skips_not_fatal(self, monkeypatch):
        _patch_geocoder(monkeypatch)
        obj = _make_objective()
        plan, _ = await plan_builder.build(obj, _new_case_id(), use_model=False)
        graph = S.EvidenceGraph(case_id=obj.objective_id)
        guard = PolicyGuard(granted_permissions=[
            S.Permission.READ_EVIDENCE, S.Permission.QUERY_EXTERNAL,
            S.Permission.CALL_PROVIDER, S.Permission.MUTATE_CASE,
        ])
        ctx = ExecutionContext(
            case_id=obj.objective_id,
            image_bytes=_make_image_with_gps(),
            objective=obj,
            graph=graph,
        )
        log = await executor.execute(plan, graph, guard, ctx)
        statuses = {e.tool_id: e.status for e in log}

        assert statuses["compute_custody_hash"] == "ran"
        assert statuses["extract_exif"] == "ran"
        assert statuses["run_consistency"] == "ran"
        assert statuses["aggregate_consensus"] == "ran"
        assert statuses["fuse_geolocation"] == "ran"
        # Provider-key tools skip (availability REQUIRES_KEY), not fatal.
        assert statuses["run_ocr"] == "skipped"
        assert statuses["run_vision_ensemble"] == "skipped"
        assert statuses["discover_sources"] == "skipped"

        assert len(graph.nodes) >= len([e for e in log if e.status == "ran"])
        assert any(e.relation == S.EdgeRelation.DERIVED_FROM for e in graph.edges)

    @pytest.mark.asyncio
    async def test_denied_step_is_skipped_with_audit(self, monkeypatch):
        _patch_geocoder(monkeypatch)
        obj = _make_objective()
        plan, _ = await plan_builder.build(obj, _new_case_id(), use_model=False)
        graph = S.EvidenceGraph(case_id=obj.objective_id)
        # No QUERY_EXTERNAL → reverse_geocode is denied.
        guard = PolicyGuard(granted_permissions=[
            S.Permission.READ_EVIDENCE, S.Permission.MUTATE_CASE,
        ])
        ctx = ExecutionContext(case_id=obj.objective_id, image_bytes=_make_image_with_gps(),
                               objective=obj, graph=graph)
        log = await executor.execute(plan, graph, guard, ctx)
        entry = next(e for e in log if e.tool_id == "reverse_geocode")
        assert entry.status == "skipped"
        assert "denied" in entry.message
        # The denied call is recorded on the graph as an audit node.
        assert any(
            n.tool_id == "audit" and n.value.get("tool_id") == "reverse_geocode"
            for n in graph.nodes.values()
        )

    @pytest.mark.asyncio
    async def test_missing_image_fails_noisily_but_never_crashes(self, monkeypatch):
        _patch_geocoder(monkeypatch)
        obj = _make_objective()
        plan, _ = await plan_builder.build(obj, _new_case_id(), use_model=False)
        graph = S.EvidenceGraph(case_id=obj.objective_id)
        guard = PolicyGuard(granted_permissions=[
            S.Permission.READ_EVIDENCE, S.Permission.QUERY_EXTERNAL,
            S.Permission.CALL_PROVIDER, S.Permission.MUTATE_CASE,
        ])
        ctx = ExecutionContext(case_id=obj.objective_id, image_bytes=None,
                               objective=obj, graph=graph)
        log = await executor.execute(plan, graph, guard, ctx)
        # Tools that need raw image bytes must never "ran" without an image.
        image_tools = {
            "compute_custody_hash", "validate_format", "extract_exif",
            "extract_deep_metadata", "analyze_ela", "detect_eof_anomaly",
            "run_ocr", "run_vision_ensemble", "verify_c2pa", "discover_sources",
        }
        for entry in log:
            if entry.tool_id in image_tools:
                assert entry.status in ("skipped", "failed"), entry
        # No evidence claims from the failed image tools land on the graph.
        assert all(n.tool_id in ("audit", "resolve_telemetry", "run_consistency",
                                 "aggregate_consensus", "fuse_geolocation",
                                 "detect_contradictions")
                   for n in graph.nodes.values())


# --------------------------------------------------------------------------- #
# Orchestrator (units 01 / 07 / 10)
# --------------------------------------------------------------------------- #
class TestOrchestrator:
    @pytest.mark.asyncio
    async def test_lifecycle_proposed_to_done_with_findings(self, monkeypatch):
        _patch_geocoder(monkeypatch)
        _force_template_planner(monkeypatch)
        session = await orchestrator.start(_make_objective(),
                                           image_bytes=_make_image_with_gps())
        assert session.status == "proposed"
        assert session.plan.revision_id

        done = await orchestrator.approve(session.investigation_id,
                                          approved_by="analyst-test")
        assert done.status == "done"
        assert done.activity_log
        assert done.graph.case_id == session.case_id
        assert len(done.graph.nodes) > 0
        assert done.graph.findings  # tier-0/1 evidence nodes promote automatically
        assert any(f.claim_type == S.ClaimType.INTEGRITY for f in done.graph.findings)

    @pytest.mark.asyncio
    async def test_amendment_hash_chains_revisions(self, monkeypatch):
        _patch_geocoder(monkeypatch)
        _force_template_planner(monkeypatch)
        session = await orchestrator.start(_make_objective(),
                                           image_bytes=_make_image_with_gps())
        old_rev = session.plan.revision_id

        done = await orchestrator.approve(
            session.investigation_id,
            amend_steps=[
                {"tool_id": "compute_custody_hash", "rationale": "start here"},
                {"tool_id": "extract_exif", "rationale": "then GPS"},
            ],
        )
        # The amendment is a distinct, hash-chained revision: the audited
        # approval node records its revision_id (≠ the initial proposal) and
        # the final plan descends from that chain (parent ≠ initial).
        assert done.plan.revision_id != old_rev
        assert done.plan.parent_revision_id != old_rev
        assert done.plan.hash
        approved_revs = [
            n.value.get("revision_id")
            for n in done.graph.nodes.values()
            if n.tool_id == "human" and "approved" in n.claim
        ]
        assert approved_revs and approved_revs[0] != old_rev

    @pytest.mark.asyncio
    async def test_approve_unknown_investigation_raises(self, monkeypatch):
        _patch_geocoder(monkeypatch)
        _force_template_planner(monkeypatch)
        with pytest.raises(KeyError):
            await orchestrator.approve("ARK-INV-NOPE")

    @pytest.mark.asyncio
    async def test_double_approve_rejected(self, monkeypatch):
        _patch_geocoder(monkeypatch)
        _force_template_planner(monkeypatch)
        session = await orchestrator.start(_make_objective(),
                                           image_bytes=_make_image_with_gps())
        await orchestrator.approve(session.investigation_id)
        with pytest.raises(ValueError):
            await orchestrator.approve(session.investigation_id)


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
class TestInvestigateAPI:
    def setup_method(self):
        self.client = TestClient(app)

    def test_create_approve_get_flow(self, monkeypatch):
        _patch_geocoder(monkeypatch)
        _force_template_planner(monkeypatch)
        obj = {
            "goal": "verify_location_credibility",
            "subject": "fixture.jpg",
            "domain": "image",
            "natural_language": "Verify this location claim.",
        }
        resp = self.client.post(
            "/api/v1/investigate",
            files={"file": ("fixture.jpg", _make_image_with_gps(), "image/jpeg")},
            data={"objective": json.dumps(obj)},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "proposed"
        assert body["planner_source"] in ("template", "model")
        assert body["plan"]["steps"]
        inv_id = body["investigation_id"]

        approve = self.client.post(f"/api/v1/investigate/{inv_id}/approve",
                                   json={"approved_by": "pytest"})
        assert approve.status_code == 200, approve.text
        done = approve.json()
        assert done["status"] == "done"
        assert done["activity_log"]
        assert done["findings"]
        assert done["graph"]["nodes"]

        fetched = self.client.get(f"/api/v1/investigate/{inv_id}")
        assert fetched.status_code == 200
        assert fetched.json()["investigation_id"] == inv_id

    def test_bad_goal_returns_400(self):
        resp = self.client.post(
            "/api/v1/investigate",
            files={"file": ("x.jpg", _make_image_with_gps(), "image/jpeg")},
            data={"objective": json.dumps({"goal": "not_a_goal"})},
        )
        assert resp.status_code == 400

    def test_empty_file_returns_400(self):
        resp = self.client.post(
            "/api/v1/investigate",
            files={"file": ("empty.jpg", b"", "image/jpeg")},
            data={"objective": json.dumps({"goal": "verify_location_credibility"})},
        )
        assert resp.status_code == 400

    def test_unknown_investigation_404(self):
        assert self.client.get("/api/v1/investigate/ARK-INV-UNKNOWN").status_code == 404

    def test_approve_unknown_investigation_404(self):
        resp = self.client.post("/api/v1/investigate/ARK-INV-UNKNOWN/approve",
                                json={})
        assert resp.status_code == 404
