"""Phase F tests — cross-domain reuse of the orchestrator/graph/guard/console.

The NETWORK + SECOPS specialists register their first-wave tools in the same
Tool Registry. No core module (orchestrator, executor, correlator, guard,
console) changes for a new domain — each objective runs through the identical
adaptive loop and writes evidence onto its case graph.

Also covers the merged plan lineage (revision chain → one ordered step list)
that the PLAN console renders.
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
from app.agent.orchestrator import orchestrator
from app.agent.specialists import specialists
from app.agent.tool_registry import registry

from main import app

_NETWORK_TOOLS = {"discover_hosts", "fingerprint_service", "port_scan", "tls_inspect"}
_SECOPS_TOOLS = {"siem_query", "threat_hunt", "detect_correlation", "incident_annotate"}


def _image_with_gps(lat=48.8566, lon=2.3522) -> bytes:
    img = Image.new("RGB", (64, 64), color=(60, 60, 60))

    def _dms(v):
        v = abs(v)
        d = int(v); m = int((v - d) * 60)
        s = (v - d - m / 60) * 3600
        return ((d, 1), (m, 1), (int(s * 10000), 10000))

    gps = {
        piexif.GPSIFD.GPSLatitude: _dms(lat),
        piexif.GPSIFD.GPSLatitudeRef: b"N",
        piexif.GPSIFD.GPSLongitude: _dms(lon),
        piexif.GPSIFD.GPSLongitudeRef: b"E",
    }
    buf = io.BytesIO()
    img.save(buf, format="jpeg", exif=piexif.dump({"GPS": gps}))
    return buf.getvalue()


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


class TestRegistryCrossDomain:
    def test_phase_f_tools_registered(self):
        assert _NETWORK_TOOLS <= set(registry._tools)
        assert _SECOPS_TOOLS <= set(registry._tools)

    def test_network_tool_risk_categories(self):
        assert registry.get("discover_hosts").spec.risk == S.RiskLevel.LOW
        assert registry.get("fingerprint_service").spec.risk == S.RiskLevel.ELEVATED
        assert registry.get("port_scan").spec.risk == S.RiskLevel.HIGH
        assert registry.get("port_scan").spec.category == S.ToolCategory.HIGH_RISK
        assert registry.get("tls_inspect").spec.risk == S.RiskLevel.ELEVATED

    def test_secops_tool_risk_categories(self):
        assert registry.get("siem_query").spec.risk == S.RiskLevel.LOW
        assert registry.get("threat_hunt").spec.risk == S.RiskLevel.ELEVATED
        assert registry.get("detect_correlation").spec.risk == S.RiskLevel.MEDIUM
        assert registry.get("incident_annotate").spec.category == S.ToolCategory.ACTION

    def test_specialists_route_phase_f_tools(self):
        assert {t.tool_id for t in specialists.registered_tools("network")} == _NETWORK_TOOLS
        assert {t.tool_id for t in specialists.registered_tools("secops")} == _SECOPS_TOOLS


class TestNetworkEndToEnd:
    @pytest.mark.asyncio
    async def test_network_objective_runs_through_same_loop(self, monkeypatch):
        _force_template_planner(monkeypatch)
        session = await orchestrator.start(
            _objective("network", "192.168.1.0/24"))
        planned = {s.tool_id for s in session.plan.steps}
        assert planned == _NETWORK_TOOLS

        done = await orchestrator.approve(session.investigation_id)
        assert done.status == "done"

        node_tools = {n.tool_id for n in done.graph.nodes.values()
                      if n.tool_id != "audit"}
        assert "discover_hosts" in node_tools          # low → auto
        assert "fingerprint_service" in node_tools     # elevated → runs
        assert "tls_inspect" in node_tools             # elevated → runs
        assert "port_scan" not in node_tools           # step-confirm → gated
        # The gated tool is audited, not silently dropped.
        assert any("step_confirm_unapproved" in str(a.value)
                   for a in done.graph.nodes.values()
                   if a.tool_id == "audit")

    @pytest.mark.asyncio
    async def test_discover_hosts_records_cidr_scope(self, monkeypatch):
        _force_template_planner(monkeypatch)
        session = await orchestrator.start(
            _objective("network", "192.168.1.0/24"))
        await orchestrator.approve(session.investigation_id)
        host_node = next(n for n in session.graph.nodes.values()
                         if n.tool_id == "discover_hosts")
        assert host_node.claim_type == S.ClaimType.DEVICE
        assert host_node.value["scope"]["num_addresses"] > 0

    @pytest.mark.asyncio
    async def test_network_without_scope_skips_cleanly(self, monkeypatch):
        _force_template_planner(monkeypatch)
        session = await orchestrator.start(_objective("network", ""))
        done = await orchestrator.approve(session.investigation_id)
        assert done.status == "done"
        assert all("skipped" in e["status"] or "skipped" in e["message"]
                   for e in done.activity_log)


class TestSecopsEndToEnd:
    @pytest.mark.asyncio
    async def test_secops_objective_same_case_evidence(self, monkeypatch):
        _force_template_planner(monkeypatch)
        net = await orchestrator.start(_objective("network", "10.0.0.0/24"))
        sec = await orchestrator.start(
            _objective("secops", "suspicious-auth"), case_id=net.case_id)
        assert sec.case_id == net.case_id  # cross-domain reuse of the case

        done = await orchestrator.approve(sec.investigation_id)
        assert done.status == "done"

        node_tools = {n.tool_id for n in done.graph.nodes.values()
                      if n.tool_id != "audit"}
        assert {"siem_query", "threat_hunt", "detect_correlation"} <= node_tools
        assert "incident_annotate" not in node_tools  # action → step-confirm
        # Evidence lands on the same case namespace as the NETWORK session.
        assert all(n.case_id == net.case_id
                   for n in done.graph.nodes.values())

    @pytest.mark.asyncio
    async def test_secops_tools_chain_on_graph_state(self, monkeypatch):
        _force_template_planner(monkeypatch)
        session = await orchestrator.start(_objective("secops", "auth-failures"))
        await orchestrator.approve(session.investigation_id)
        # detect_correlation consumes siem_query's event list from the graph.
        corr = next(n for n in session.graph.nodes.values()
                    if n.tool_id == "detect_correlation")
        assert corr.value["events"] == []
        assert corr.value["count"] == 0


class TestMergedPlanLineage:
    @pytest.mark.asyncio
    async def test_revision_chain_grows_and_merges(self, monkeypatch):
        _force_template_planner(monkeypatch)
        session = await orchestrator.start(_objective("network", "10.0.0.0/24"))
        await orchestrator.approve(session.investigation_id)

        assert len(session.revisions) == 1  # no gaps → no delta
        payload = session.to_dict()
        assert payload["merged_plan"]["count"] == len(_NETWORK_TOOLS)
        merged_tools = [m["tool_id"] for m in payload["merged_plan"]["steps"]]
        assert merged_tools == sorted(merged_tools) or set(merged_tools) == _NETWORK_TOOLS

    @pytest.mark.asyncio
    async def test_amendment_appends_revision(self, monkeypatch):
        _force_template_planner(monkeypatch)
        session = await orchestrator.start(_objective("network", "10.0.0.0/24"))
        done = await orchestrator.approve(
            session.investigation_id,
            amend_steps=[{"tool_id": "discover_hosts", "rationale": "first"},
                         {"tool_id": "tls_inspect", "rationale": "second"}])
        assert len(done.revisions) == 2
        assert done.revisions[1].parent_revision_id == done.revisions[0].revision_id
        # Merged plan dedupes the re-planned tool but keeps ordering.
        merged_tools = [m["tool_id"] for m in done.to_dict()["merged_plan"]["steps"]]
        assert merged_tools.count("discover_hosts") == 1
        assert merged_tools[0] == "discover_hosts"
        assert merged_tools[-1] == "tls_inspect"

    @pytest.mark.asyncio
    async def test_adaptive_delta_in_merged_plan(self, monkeypatch):
        """A contradiction mid-run appends a delta; the merged plan shows the
        whole investigation as one ordered step list."""
        from tests.test_phase_e_adaptive import (
            _force_template_planner as _ft, _patch_geocoder,
        )
        _patch_geocoder(monkeypatch)
        _ft(monkeypatch)
        async def _resolve(objective, gap, specs, budget_summary):
            assert gap["gap_type"] == S.GapType.OPEN_CONTRADICTION.value
            return [{"tool_id": "reverse_geocode", "rationale": "settle"}]
        monkeypatch.setattr(
            "app.agent.model_gateway.gateway.propose_next", _resolve)

        obj = S.InvestigationObjective(
            objective_id="OBJ-M", goal=S.InvestigationGoal.VERIFY_LOCATION_CREDIBILITY,
            subject="fixture.jpg", domain="image",
            claims_to_verify=[S.ClaimToVerify(field="gps.latitude", value="1")])
        session = await orchestrator.start(obj, image_bytes=_image_with_gps())
        eg.add_node(
            session.graph,
            eg.build_node(
                session.case_id, "fixture_telemetry",
                S.ProvenanceType.TOOL_INFERENCE,
                "Tokyo", S.ClaimType.LOCATION,
                {"lat": 35.6762, "lon": 139.6503}, confidence=0.9,
            ),
        )
        eg.add_node(
            session.graph,
            eg.build_node(
                session.case_id, "fixture_telemetry",
                S.ProvenanceType.TOOL_INFERENCE,
                "Lagos", S.ClaimType.LOCATION,
                {"lat": 6.5244, "lon": 3.3792}, confidence=0.9,
            ),
        )
        done = await orchestrator.approve(session.investigation_id)
        assert done.status == "done"
        assert len(done.revisions) >= 2
        payload = done.to_dict()
        merged = payload["merged_plan"]["steps"]
        # The delta's tool appears once; every step is tagged with its origin.
        assert len(merged) == len({m["tool_id"] for m in merged})
        assert any(m["tool_id"] == "reverse_geocode" for m in merged)
        assert all(m.get("revision_id") for m in merged)
        assert all(m.get("delta_reason") for m in merged)
        # Delta revision is hash-chained to its parent.
        assert (done.revisions[-1].parent_revision_id
                == done.revisions[-2].revision_id)


class TestCrossDomainApi:
    def setup_method(self):
        self.client = TestClient(app)

    def test_network_objective_via_api(self, monkeypatch):
        _force_template_planner(monkeypatch)
        obj = {
            "goal": "full_forensic_profile",
            "subject": "192.168.1.0/24",
            "domain": "network",
        }
        resp = self.client.post(
            "/api/v1/investigate",
            files={"file": ("net.bin", _image_with_gps(), "image/jpeg")},
            data={"objective": json.dumps(obj)},
        )
        assert resp.status_code == 200
        inv_id = resp.json()["investigation_id"]
        assert {"discover_hosts", "tls_inspect"} <= {
            s["tool_id"] for s in resp.json()["plan"]["steps"]}

        done = self.client.post(f"/api/v1/investigate/{inv_id}/approve", json={})
        body = done.json()
        assert body["status"] == "done"
        assert body["merged_plan"]["count"] >= 1
        assert "revisions" in body
        # NETWORK evidence on the case graph via the identical console payload.
        node_tools = {
            n["tool_id"] for n in body["graph"]["nodes"].values()
            if n["tool_id"] != "audit"
        }
        assert "discover_hosts" in node_tools
