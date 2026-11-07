"""Phase G — case engine unification.

One case collects evidence from ≥2 domains; findings span domains; cross-domain
contradiction edges link location claims produced by different domains; the case
carries one findings list and one audit trail. Exercised at the engine level
(derived merged graph) and end-to-end through the API.
"""
import io
import json
import uuid

import piexif
import pytest
from PIL import Image
from fastapi.testclient import TestClient

from app.agent import case_engine as ce
from app.agent import evidence_graph as eg
from app.agent import schemas as S
from app.agent.orchestrator import orchestrator
from app.agent.tool_registry import registry

from main import app


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


def _objective(domain: str, subject: str) -> S.InvestigationObjective:
    return S.InvestigationObjective(
        objective_id=f"OBJ-{uuid.uuid4().hex[:8].upper()}",
        goal=S.InvestigationGoal.FULL_FORENSIC_PROFILE,
        subject=subject, domain=domain,
    )


def _force_template_planner(monkeypatch):
    async def _template_only(objective, tool_specs, desc):
        return None
    async def _terminate(objective, gap, specs, budget_summary):
        return None
    monkeypatch.setattr("app.agent.model_gateway.gateway.plan_steps", _template_only)
    monkeypatch.setattr("app.agent.model_gateway.gateway.propose_next", _terminate)


def _session_with(case_id: str, tool_id: str, value: dict,
                  claim_type: S.ClaimType, domain: str):
    """A minimal session whose graph holds one typed evidence node."""
    obj = _objective(domain, "x")
    graph = S.EvidenceGraph(case_id=case_id)
    eg.add_node(graph, eg.build_node(
        case_id=case_id, tool_id=tool_id, provenance_type=S.ProvenanceType.TOOL_INFERENCE,
        claim=f"{tool_id} claim", claim_type=claim_type, value=value, confidence=1.0,
    ))
    from app.agent.orchestrator import InvestigationSession

    return InvestigationSession(
        investigation_id=f"ARK-INV-{uuid.uuid4().hex[:8].upper()}",
        case_id=case_id, objective=obj, plan=S.PlanRevision(
            revision_id="REV-TEST", parent_revision_id=None,
            objective_id=obj.objective_id, steps=[], hash="x"), graph=graph,
    )


class TestMergeCaseGraph:
    def test_unions_nodes_edges_findings(self):
        case = "ARK-CASE-MERGE1"
        a = _session_with(case, "extract_exif", {"make": "X"},
                          S.ClaimType.METADATA, "image")
        b = _session_with(case, "web_search", {"total": 1},
                          S.ClaimType.SOURCE, "osint")
        merged = ce.merge_case_graph([a, b])
        assert len(merged.nodes) == 2
        assert merged.case_id == case

    def test_domains_in_case_sorted_distinct(self):
        case = "ARK-CASE-MERGE2"
        merged = ce.merge_case_graph([
            _session_with(case, "extract_exif", {}, S.ClaimType.METADATA, "image"),
            _session_with(case, "web_search", {}, S.ClaimType.SOURCE, "osint"),
            _session_with(case, "extract_deep_metadata", {}, S.ClaimType.METADATA, "image"),
        ])
        assert ce.domains_in_case(merged) == ["image", "osint"]

    def test_audit_tool_is_not_a_domain(self):
        case = "ARK-CASE-MERGE3"
        graph = S.EvidenceGraph(case_id=case)
        eg.audit_tool_call(graph, "extract_exif", {"status": "ran", "arguments": {}})
        session = _session_with(case, "extract_exif", {}, S.ClaimType.METADATA, "image")
        session.graph = graph
        merged = ce.merge_case_graph([session])
        assert "audit" not in ce.domains_in_case(merged)
        assert len(ce._audit_trail(merged)) == 1


class TestCrossDomainContradiction:
    def test_location_conflict_across_domains_is_reported(self):
        case = "ARK-CASE-XDOM1"
        image = _session_with(case, "resolve_telemetry",
                              {"lat": 48.85, "lon": 2.35},
                              S.ClaimType.LOCATION, "image")
        osint = _session_with(case, "geocode_place",
                              {"lat": 40.71, "lon": -74.00},
                              S.ClaimType.LOCATION, "osint")
        merged = ce.merge_case_graph([image, osint])
        conflicts = ce.cross_domain_contradictions(merged)
        assert len(conflicts) == 1
        pair = {conflicts[0]["src_domain"], conflicts[0]["dst_domain"]}
        assert pair == {"image", "osint"}

    def test_same_domain_conflict_is_not_cross_domain(self):
        case = "ARK-CASE-XDOM2"
        a = _session_with(case, "resolve_telemetry", {"lat": 48.85, "lon": 2.35},
                          S.ClaimType.LOCATION, "image")
        b = _session_with(case, "fuse_geolocation", {"lat": 40.71, "lon": -74.00},
                          S.ClaimType.LOCATION, "image")
        merged = ce.merge_case_graph([a, b])
        assert ce.cross_domain_contradictions(merged) == []

    def test_agreeing_locations_corroborate_not_contradict(self):
        case = "ARK-CASE-XDOM3"
        a = _session_with(case, "resolve_telemetry", {"lat": 48.85, "lon": 2.35},
                          S.ClaimType.LOCATION, "image")
        b = _session_with(case, "geocode_place", {"lat": 48.8501, "lon": 2.3501},
                          S.ClaimType.LOCATION, "osint")
        merged = ce.merge_case_graph([a, b])
        assert ce.cross_domain_contradictions(merged) == []
        assert any(e.relation == S.EdgeRelation.CORROBORATES for e in merged.edges)


class TestCaseView:
    def test_cross_domain_view_shape(self):
        case = "ARK-CASE-VIEW1"
        image = _session_with(case, "extract_exif", {"make": "X"},
                              S.ClaimType.METADATA, "image")
        osint = _session_with(case, "web_search", {"total": 2},
                              S.ClaimType.SOURCE, "osint")
        view = ce.case_view(case, [image, osint])
        assert view["case_id"] == case
        assert view["domain"] == "cross"
        assert view["domains"] == ["image", "osint"]
        assert view["evidence_count"] == 2
        assert view["finding_count"] == 0
        assert view["investigation_ids"] == [image.investigation_id, osint.investigation_id]

    def test_single_domain_view_is_not_cross(self):
        case = "ARK-CASE-VIEW2"
        view = ce.case_view(case, [
            _session_with(case, "extract_exif", {}, S.ClaimType.METADATA, "image"),
        ])
        assert view["domain"] == "image"

    def test_audit_trail_is_time_ordered(self):
        case = "ARK-CASE-VIEW3"
        graph = S.EvidenceGraph(case_id=case)
        eg.audit_tool_call(graph, "extract_exif", {"status": "ran", "arguments": {}})
        eg.audit_tool_call(graph, "compute_custody_hash",
                           {"status": "ran", "arguments": {}})
        session = _session_with(case, "extract_exif", {}, S.ClaimType.METADATA, "image")
        session.graph = graph
        trail = ce.case_view(case, [session])["audit_trail"]
        assert [t["at_ms"] for t in trail] == sorted(t["at_ms"] for t in trail)
        assert {t["tool_id"] for t in trail} == {"extract_exif", "compute_custody_hash"}


class TestListCases:
    def test_groups_by_case_newest_first(self):
        a = _session_with("ARK-CASE-L1", "extract_exif", {}, S.ClaimType.METADATA, "image")
        b = _session_with("ARK-CASE-L1", "web_search", {}, S.ClaimType.SOURCE, "osint")
        c = _session_with("ARK-CASE-L2", "discover_hosts", {}, S.ClaimType.DEVICE, "network")
        a.updated_at_ms, b.updated_at_ms, c.updated_at_ms = 100, 200, 150
        rows = ce.list_cases([a, b, c])
        assert [r["case_id"] for r in rows] == ["ARK-CASE-L1", "ARK-CASE-L2"]
        l1 = rows[0]
        assert l1["domain"] == "cross"
        assert l1["investigation_count"] == 2
        assert l1["domains"] == ["image", "osint"]

    def test_rollup_status_is_least_advanced(self):
        a = _session_with("C", "extract_exif", {}, S.ClaimType.METADATA, "image")
        b = _session_with("C", "web_search", {}, S.ClaimType.SOURCE, "osint")
        a.status, b.status = "done", "paused"
        assert ce._rollup_status([a, b]) == "paused"
        b.status = "done"
        assert ce._rollup_status([a, b]) == "done"


class TestCaseApi:
    def setup_method(self):
        self.client = TestClient(app)

    def test_unknown_case_is_404(self):
        assert self.client.get("/api/v1/cases/ARK-CASE-NOPE").status_code == 404

    def test_list_cases_shape(self):
        r = self.client.get("/api/v1/cases")
        assert r.status_code == 200
        assert "cases" in r.json()

    def test_case_end_to_end_two_domains(self, monkeypatch):
        _force_template_planner(monkeypatch)

        async def _fake_geocode(place):
            return {"state": "AVAILABLE", "query": place, "lat": 40.71, "lon": -74.0}

        monkeypatch.setitem(registry._tools["geocode_place"].__dict__,
                            "handler", _fake_geocode)

        img = self.client.post(
            "/api/v1/investigate",
            files={"file": ("x.jpg", _image_with_gps(48.8566, 2.3522), "image/jpeg")},
            data={"objective": json.dumps(
                {"goal": "full_forensic_profile", "subject": "x", "domain": "image"})},
        )
        assert img.status_code == 200
        case_id = img.json()["case_id"]
        self.client.post(f"/api/v1/investigate/{img.json()['investigation_id']}/approve",
                         json={})

        osint = self.client.post(
            "/api/v1/investigate",
            files={"file": ("y.jpg", _image_with_gps(), "image/jpeg")},
            data={"objective": json.dumps(
                {"goal": "full_forensic_profile", "subject": "Paris",
                 "domain": "osint"})},
        )
        assert osint.status_code == 200
        # Force the OSINT investigation onto the image case (same case id).
        from app.agent.orchestrator import orchestrator as _orch
        _orch.get(osint.json()["investigation_id"]).case_id = case_id
        self.client.post(f"/api/v1/investigate/{osint.json()['investigation_id']}/approve",
                         json={})

        case = self.client.get(f"/api/v1/cases/{case_id}")
        assert case.status_code == 200
        body = case.json()
        assert body["case_id"] == case_id
        assert {"image", "osint"} <= set(body["domains"])
        assert body["domain"] == "cross"
        assert len(body["investigation_ids"]) == 2
        # One findings list and one audit trail for the whole case.
        assert isinstance(body["findings"], list)
        assert len(body["audit_trail"]) >= 1

        listed = self.client.get("/api/v1/cases").json()["cases"]
        assert case_id in {c["case_id"] for c in listed}
