"""Phase H — model routing & authority.

The model policy decides *which* registered model serves a capability; the
tool policy guard decides *whether a tool may run*. Phase H adds the model
half: a registry of routable models, a policy that is local-first and forces
the local arm on zero-retention cases, and provenance wiring so the chosen
model id lands on findings and the session record.

Exercised at the unit level (registry, policy) and end-to-end through the
``/investigate`` API.
"""
from __future__ import annotations

import io
import json
import uuid

import piexif
import pytest
from PIL import Image
from fastapi.testclient import TestClient

from app.agent import model_policy as mp
from app.agent import model_registry as mr
from app.agent import schemas as S
from app.agent.orchestrator import orchestrator
from app.agent.model_registry import Model, ModelRegistry

from main import app


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
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


def _objective(domain="image", zero_retention=False) -> S.InvestigationObjective:
    return S.InvestigationObjective(
        objective_id=f"OBJ-{uuid.uuid4().hex[:8].upper()}",
        goal=S.InvestigationGoal.VERIFY_LOCATION_CREDIBILITY,
        subject="fixture.jpg",
        domain=domain,
        constraints=S.ObjectiveConstraints(zero_retention=zero_retention),
    )


def _force_template_planner(monkeypatch):
    async def _template_only(objective, tool_specs, desc, **kwargs):
        return None

    async def _terminate(objective, gap, specs, budget_summary, **kwargs):
        return None

    monkeypatch.setattr("app.agent.model_gateway.gateway.plan_steps", _template_only)
    monkeypatch.setattr("app.agent.model_gateway.gateway.propose_next", _terminate)


def _patch_geocoder(monkeypatch):
    monkeypatch.setattr(
        "app.agent.tool_registry.reverse_geocode",
        lambda lat, lon: type("Addr", (), {
            "model_dump": lambda s: {"display_name": "Paris, France",
                                     "lat": 48.8566, "lon": 2.3522}})(),
    )


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
class TestModelRegistry:
    def test_local_planner_registered_and_offline_safe(self):
        m = mr.registry.get(mr.DEFAULT_LOCAL_MODEL)
        assert m is not None
        assert m.spec.local is True
        assert m.spec.offline_ok is True
        assert m.spec.zero_retention_safe is True
        assert S.ModelCapability.PLANNING in m.spec.capabilities

    def test_cloud_arm_is_nonlocal_and_not_zero_retention_safe(self):
        m = mr.registry.get(mr.CLOUD_PLANNER_MODEL)
        assert m is not None
        assert m.spec.local is False
        assert m.spec.offline_ok is False
        assert m.spec.zero_retention_safe is False

    def test_local_for_prefers_zero_retention_safe_local(self):
        m = mr.registry.local_for(S.ModelCapability.VISION)
        assert m is not None and m.spec.local and m.spec.zero_retention_safe

    def test_default_for_is_local_first(self):
        m = mr.registry.default_for(S.ModelCapability.PLANNING)
        assert m.spec.local is True

    def test_specs_filtered_by_capability(self):
        ids = {s.model_id for s in mr.registry.specs(S.ModelCapability.VISION)}
        assert mr.DEFAULT_LOCAL_VISION_MODEL in ids
        assert mr.CLOUD_VISION_MODEL in ids
        assert mr.DEFAULT_LOCAL_MODEL not in ids

    def test_register_adds_model(self):
        reg = ModelRegistry(models=[])
        reg.register(Model(S.ModelSpec(
            model_id="x/y", name="Y", provider=S.ModelProvider.LOCAL,
            capabilities=[S.ModelCapability.REASONING], local=True,
        )))
        assert reg.get("x/y") is not None
        assert reg.default_for(S.ModelCapability.REASONING).model_id == "x/y"

    def test_gateway_factory_failure_returns_none(self):
        m = Model(lambda: (_ for _ in ()).throw(RuntimeError("no key")))
        assert m.gateway() is None


# --------------------------------------------------------------------------- #
# Policy — routing precedence
# --------------------------------------------------------------------------- #
class TestModelPolicy:
    def test_default_is_local_first(self):
        d = mp.route(S.ModelCapability.PLANNING, domain="image")
        assert d.allowed and d.spec.local
        assert d.rule_id == "default"

    def test_zero_retention_forces_local(self):
        d = mp.route(S.ModelCapability.PLANNING, domain="image",
                     zero_retention=True)
        assert d.allowed and d.forced_local
        assert d.spec.local and d.spec.zero_retention_safe
        assert d.rule_id == "constraint.local-only"

    def test_local_only_forces_local(self):
        d = mp.route(S.ModelCapability.VISION, local_only=True)
        assert d.allowed and d.forced_local and d.spec.local

    def test_rule_pins_capability_to_cloud_model(self):
        # A rule can only route to a cloud arm that is actually provisioned;
        # inject an available cloud model to exercise the happy path.
        reg = ModelRegistry(models=[
            mr.registry.get(mr.DEFAULT_LOCAL_MODEL),
            Model(mr.registry.get(mr.CLOUD_PLANNER_MODEL).spec,
                  factory=lambda: object()),
        ])
        p = mp.ModelPolicy(registry=reg, rules=[S.ModelPolicyRule(
            rule_id="r.cloud-plan",
            match=S.ModelPolicyMatch(capability=S.ModelCapability.PLANNING),
            prefer=mr.CLOUD_PLANNER_MODEL,
        )])
        d = p.decide(mp.ModelRequest(capability=S.ModelCapability.PLANNING))
        assert d.allowed and d.spec.model_id == mr.CLOUD_PLANNER_MODEL
        assert d.rule_id == "r.cloud-plan" and d.fallback_used is False

    def test_rule_cannot_leak_sensitive_data_to_cloud(self):
        """The structural guarantee: a cloud-pinning rule is ignored when the
        request is zero-retention — even when that cloud arm is available."""
        reg = ModelRegistry(models=[
            mr.registry.get(mr.DEFAULT_LOCAL_MODEL),
            Model(mr.registry.get(mr.CLOUD_PLANNER_MODEL).spec,
                  factory=lambda: object()),
        ])
        p = mp.ModelPolicy(registry=reg, rules=[S.ModelPolicyRule(
            rule_id="r.cloud-plan",
            match=S.ModelPolicyMatch(capability=S.ModelCapability.PLANNING),
            prefer=mr.CLOUD_PLANNER_MODEL,
        )])
        d = p.decide(mp.ModelRequest(
            capability=S.ModelCapability.PLANNING, zero_retention=True))
        assert d.allowed and d.spec.local
        assert d.spec.model_id != mr.CLOUD_PLANNER_MODEL

    def test_require_local_narrows_to_local_arm(self):
        p = mp.ModelPolicy(rules=[S.ModelPolicyRule(
            rule_id="r.local-vision",
            match=S.ModelPolicyMatch(capability=S.ModelCapability.VISION),
            prefer=mr.CLOUD_VISION_MODEL,
            require_local=True,
        )])
        d = p.decide(mp.ModelRequest(capability=S.ModelCapability.VISION))
        assert d.allowed and d.spec.local
        assert d.spec.model_id == mr.DEFAULT_LOCAL_VISION_MODEL

    def test_rule_preferring_unregistered_model_falls_through(self):
        p = mp.ModelPolicy(rules=[S.ModelPolicyRule(
            rule_id="r.bogus",
            match=S.ModelPolicyMatch(capability=S.ModelCapability.PLANNING),
            prefer="does/not-exist",
        )])
        d = p.decide(mp.ModelRequest(capability=S.ModelCapability.PLANNING))
        assert d.allowed and d.spec.local  # default fallback, not a hard fail
        assert d.fallback_used is True
        assert "r.bogus" in d.rule_id

    def test_rule_pinning_unprovisioned_cloud_model_falls_back_to_local(self):
        """A cloud-pinning rule whose credential is absent must not take the
        investigation down — it degrades to the local arm and says so."""
        p = mp.ModelPolicy(rules=[S.ModelPolicyRule(
            rule_id="r.cloud-plan",
            match=S.ModelPolicyMatch(capability=S.ModelCapability.PLANNING),
            prefer=mr.CLOUD_PLANNER_MODEL,
        )])
        d = p.decide(mp.ModelRequest(capability=S.ModelCapability.PLANNING))
        # The HF cloud factory returns None when unconfigured (the default
        # state in tests), so the rule cannot be satisfied.
        assert d.allowed is True
        assert d.spec.local is True
        assert d.fallback_used is True
        assert d.spec.model_id != mr.CLOUD_PLANNER_MODEL

    def test_disabled_rule_ignored(self):
        p = mp.ModelPolicy(rules=[S.ModelPolicyRule(
            rule_id="r.off", enabled=False,
            match=S.ModelPolicyMatch(capability=S.ModelCapability.PLANNING),
            prefer=mr.CLOUD_PLANNER_MODEL,
        )])
        d = p.decide(mp.ModelRequest(capability=S.ModelCapability.PLANNING))
        assert d.spec.model_id == mr.DEFAULT_LOCAL_MODEL

    def test_no_local_model_for_sensitive_capability_denies(self):
        reg = ModelRegistry(models=[Model(S.ModelSpec(
            model_id="cloud/only", name="C", provider=S.ModelProvider.OTHER,
            capabilities=[S.ModelCapability.PLANNING], local=False,
            zero_retention_safe=False,
        ))])
        p = mp.ModelPolicy(registry=reg)
        d = p.decide(mp.ModelRequest(
            capability=S.ModelCapability.PLANNING, zero_retention=True))
        assert d.allowed is False and d.forced_local

    def test_no_model_registered_denies(self):
        p = mp.ModelPolicy(registry=ModelRegistry(models=[]))
        d = p.decide(mp.ModelRequest(capability=S.ModelCapability.PLANNING))
        assert d.allowed is False and d.spec is None


# --------------------------------------------------------------------------- #
# Orchestrator integration — routing recorded on the session
# --------------------------------------------------------------------------- #
class TestOrchestratorRouting:
    @pytest.mark.asyncio
    async def test_session_records_model_decision(self, monkeypatch):
        _force_template_planner(monkeypatch)
        session = await orchestrator.start(_objective())
        assert session.model_decision is not None
        assert session.model_decision["allowed"] is True
        assert session.model_decision["spec"]["local"] is True

    @pytest.mark.asyncio
    async def test_zero_retention_session_routes_local(self, monkeypatch):
        _force_template_planner(monkeypatch)
        session = await orchestrator.start(_objective(zero_retention=True))
        assert session.model_decision["forced_local"] is True
        assert session.model_decision["spec"]["local"] is True

    @pytest.mark.asyncio
    async def test_findings_carry_model_id(self, monkeypatch):
        _force_template_planner(monkeypatch)
        _patch_geocoder(monkeypatch)
        session = await orchestrator.start(
            _objective(), image_bytes=_image_with_gps(),
        )
        session = await orchestrator.approve(session.investigation_id)
        assert session.status == "done"
        findings = session.graph.findings
        assert findings
        assert all(f.model_id for f in findings)

    @pytest.mark.asyncio
    async def test_model_id_flows_to_planner(self, monkeypatch):
        captured = {}

        async def _capture(objective, tool_specs, desc, model_id=None):
            captured["model_id"] = model_id
            return None

        monkeypatch.setattr("app.agent.model_gateway.gateway.plan_steps", _capture)
        await orchestrator.start(_objective())
        assert captured["model_id"] == mr.DEFAULT_LOCAL_MODEL


# --------------------------------------------------------------------------- #
# API — the routed decision is part of the session payload
# --------------------------------------------------------------------------- #
class TestModelRoutingAPI:
    def setup_method(self):
        self.client = TestClient(app)

    def test_investigate_payload_exposes_model_decision(self, monkeypatch):
        _force_template_planner(monkeypatch)
        resp = self.client.post(
            "/api/v1/investigate",
            files={"file": ("f.jpg", _image_with_gps(), "image/jpeg")},
            data={"objective": json.dumps({
                "goal": "verify_location_credibility",
                "subject": "fixture.jpg",
                "domain": "image",
            })},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["model_decision"]["allowed"] is True
        assert body["model_decision"]["spec"]["local"] is True

    def test_zero_retention_objective_forces_local_via_api(self, monkeypatch):
        _force_template_planner(monkeypatch)
        resp = self.client.post(
            "/api/v1/investigate",
            files={"file": ("f.jpg", _image_with_gps(), "image/jpeg")},
            data={"objective": json.dumps({
                "goal": "verify_location_credibility",
                "subject": "sensitive.jpg",
                "domain": "image",
                "constraints": {"zero_retention": True},
            })},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["model_decision"]["forced_local"] is True
        assert body["model_decision"]["spec"]["local"] is True
