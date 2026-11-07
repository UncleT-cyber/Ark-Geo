"""Phase F follow-up — OSINT + WEB specialists register their real tools.

OSINT and WEB previously declared planned tool ids (source_search,
proxy_collect, …) that were never registered, so ``registered_tools`` returned
almost nothing and the planner could not see either domain. This wires the
tools that already exist (web_search/geocode/reverse-image; hardened web.* and
browser.*) into the same registry/specialist/executor/correlator path NETWORK
and SECOPS use. No core module changes — additive only.
"""
import uuid

import pytest

from app.agent import schemas as S
from app.agent import evidence_graph as eg
from app.agent.orchestrator import orchestrator
from app.agent.planner import _TEMPLATES
from app.agent.specialists import specialists
from app.agent.tool_registry import registry

_OSINT_TOOLS = {"inspect_local_path", "web_search", "web_fetch", "geocode_place",
                "geocode_batch_texts", "reverse_image_search"}
_WEB_TOOLS = {"web.fetch", "web.extract", "web.links", "web.document",
              "browser.open", "browser.navigate", "browser.snapshot",
              "browser.extract", "browser.screenshot"}


def _objective(domain: str, subject: str, **kw) -> S.InvestigationObjective:
    overrides = {
        "objective_id": f"OBJ-{uuid.uuid4().hex[:8].upper()}",
        "goal": S.InvestigationGoal.FULL_FORENSIC_PROFILE,
        "subject": subject,
        "domain": domain,
    }
    overrides.update(kw)
    return S.InvestigationObjective(**overrides)


def _force_template_planner(monkeypatch):
    async def _template_only(objective, tool_specs, desc):
        return None

    async def _terminate(objective, gap, specs, budget_summary):
        return None

    monkeypatch.setattr("app.agent.model_gateway.gateway.plan_steps", _template_only)
    monkeypatch.setattr("app.agent.model_gateway.gateway.propose_next", _terminate)


class TestOsintWebRouting:
    def test_osint_specialist_routes_registered_tools(self):
        routed = {t.tool_id for t in specialists.registered_tools("osint")}
        assert routed == _OSINT_TOOLS
        # Every routed id is actually registered (not a dangling declaration).
        assert routed <= set(registry._tools)

    def test_web_specialist_routes_registered_tools(self):
        routed = {t.tool_id for t in specialists.registered_tools("web")}
        assert routed == _WEB_TOOLS
        assert routed <= set(registry._tools)

    def test_goal_mappings_point_at_real_templates(self):
        for domain, goal in (("osint", S.InvestigationGoal.SOURCE_DISCOVERY),
                             ("osint", S.InvestigationGoal.FULL_FORENSIC_PROFILE),
                             ("web", S.InvestigationGoal.SOURCE_DISCOVERY),
                             ("web", S.InvestigationGoal.FULL_FORENSIC_PROFILE)):
            tid = specialists.plan_template_id(domain, goal)
            assert tid in _TEMPLATES, (domain, goal, tid)

    def test_every_template_tool_is_registered_and_routable(self):
        """A template step that is not registered would silently skip forever."""
        for template_id, steps in _TEMPLATES.items():
            for tool_id, _rationale in steps:
                assert registry.get(tool_id) is not None, (template_id, tool_id)

    def test_templates_only_use_tools_routed_for_their_domain(self):
        by_domain = {
            "image_verify_location": "image", "network_full": "network",
            "secops_full": "secops", "osint_source_discovery": "osint",
            "osint_full": "osint", "web_source_discovery": "web",
            "web_full": "web",
        }
        for template_id, domain in by_domain.items():
            routed = {t.tool_id for t in specialists.registered_tools(domain)}
            for tool_id, _ in _TEMPLATES[template_id]:
                assert tool_id in routed, (template_id, tool_id)


class TestOsintEndToEnd:
    @pytest.mark.asyncio
    async def test_osint_objective_plans_and_skips_without_scope(self, monkeypatch):
        _force_template_planner(monkeypatch)
        # Empty subject → retrieval steps cannot resolve an argument and skip
        # honestly rather than failing the run.
        session = await orchestrator.start(_objective("osint", ""))
        planned = {s.tool_id for s in session.plan.steps}
        assert planned == {t for t, _ in _TEMPLATES["osint_full"]}

        done = await orchestrator.approve(session.investigation_id)
        assert done.status == "done"
        # Retrieval steps with no resolvable subject skip honestly; nothing fails.
        assert not any(e["status"] == "failed" for e in done.activity_log)
        assert any(e["status"] == "skipped" for e in done.activity_log)

    @pytest.mark.asyncio
    async def test_geocode_place_runs_on_graph_with_claim_type(self, monkeypatch):
        _force_template_planner(monkeypatch)

        async def _fake_geocode(place):
            return {"state": "AVAILABLE", "query": place, "lat": 48.85, "lon": 2.35}

        monkeypatch.setattr(registry.get("geocode_place").handler, "__call__",
                            _fake_geocode, raising=False)
        monkeypatch.setitem(registry._tools["geocode_place"].__dict__,
                            "handler", _fake_geocode)

        session = await orchestrator.start(_objective("osint", "Paris"))
        done = await orchestrator.approve(session.investigation_id)
        node = next((n for n in done.graph.nodes.values()
                     if n.tool_id == "geocode_place"), None)
        assert node is not None
        assert node.claim_type == S.ClaimType.LOCATION
        assert node.value["lat"] == 48.85

    @pytest.mark.asyncio
    async def test_web_tools_share_the_case_graph(self, monkeypatch):
        _force_template_planner(monkeypatch)
        net = await orchestrator.start(_objective("network", "10.0.0.0/24"))
        web = await orchestrator.start(
            _objective("web", "https://example.com"), case_id=net.case_id)
        assert web.case_id == net.case_id

        done = await orchestrator.approve(web.investigation_id)
        assert done.status == "done"
        assert all(n.case_id == net.case_id for n in done.graph.nodes.values())

    @pytest.mark.asyncio
    async def test_osint_missing_layer_gap_is_addressable(self, monkeypatch):
        from app.agent.correlator import graph_gaps
        _force_template_planner(monkeypatch)
        session = await orchestrator.start(_objective("osint", ""))
        gaps = graph_gaps(session.graph, session.objective)
        assert any(g.gap_type == S.GapType.MISSING_LAYER for g in gaps)
        # The gap's remedy is a real registered tool, not a dangling id.
        for gap in gaps:
            for tool_id in gap.addressable_by:
                assert registry.get(tool_id) is not None, tool_id
