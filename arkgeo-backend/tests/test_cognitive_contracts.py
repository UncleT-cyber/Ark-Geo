"""Cognitive-core contracts (units 05-09 + domain specialists).

These are additive Phase A/B-style contracts for
``docs/ARK_INTEGRATED_SECURITY_ENVIRONMENT.md`` §2: Hypothesis, Critique,
ContextFrame, ModelSpec, structured Finding fields, and the specialist
registry. No behavior change to the deterministic pipeline or the policy
guard — this file only validates that the shapes the cognitive layer will
consume exist and are coherent.
"""
import pytest

from app.agent import schemas as S
from app.agent.specialists import SpecialistRegistry, specialists


# --------------------------------------------------------------------------- #
# Structured Finding (unit 10) — backward-compatible extension
# --------------------------------------------------------------------------- #
class TestStructuredFinding:
    def test_minimal_finding_still_constructs(self):
        f = S.Finding(
            finding_id="ARK-FND-1", case_id="ARK-CASE-1",
            claim_type=S.ClaimType.LOCATION, claim="Lagos",
            value={"lat": 6.5, "lon": 3.4}, confidence=0.9,
            supporting_node_ids=["n1"], contradicting_node_ids=[],
        )
        assert f.status == S.FindingStatus.NEEDS_REVIEW
        assert f.finding_type == S.FindingType.OTHER
        assert f.severity == S.FindingSeverity.MEDIUM

    def test_full_finding_carries_court_fields(self):
        f = S.Finding(
            finding_id="FIND-00921", case_id="ARK-CASE-2047",
            claim_type=S.ClaimType.TIMESTAMP,
            finding_type=S.FindingType.TIMELINE_ANOMALY,
            severity=S.FindingSeverity.HIGH, confidence=0.92,
            claim="File modification occurs after claimed capture time",
            value={"mtime": "2024-08-12T12:00Z", "capture": "2024-08-12T09:00Z"},
            supporting_node_ids=["IMG-0032", "EXIF-004", "FILE-009"],
            contradicting_node_ids=[],
            observation="File modification after claimed capture time.",
            assessment="Post-capture processing likely.",
            status=S.FindingStatus.VALIDATED, domain="image",
        )
        assert f.finding_type == S.FindingType.TIMELINE_ANOMALY
        assert f.status == S.FindingStatus.VALIDATED
        assert f.domain == "image"


# --------------------------------------------------------------------------- #
# Hypothesis (unit 05) — ranked candidates, never promoted wholesale
# --------------------------------------------------------------------------- #
class TestHypothesis:
    def test_hypothesis_with_ranked_candidates(self):
        h = S.Hypothesis(
            hypothesis_id="HYP-1", case_id="C-1", domain="image",
            claim="Location is likely Lagos",
            confidence=0.82,
            supporting_node_ids=["exif-1", "ocr-2"],
            contradicting_node_ids=[],
            unresolved_questions=["Is metadata altered?"],
            model_id="qwen2.5-coder:3b",
            alternatives=[
                S.HypothesisCandidate(claim="Lagos", confidence=0.82),
                S.HypothesisCandidate(claim="Abuja", confidence=0.11),
                S.HypothesisCandidate(claim="Accra", confidence=0.07),
            ],
        )
        assert sum(c.confidence for c in h.alternatives) == pytest.approx(1.0, abs=1e-6)
        assert h.model_id  # pinned — part of provenance

    def test_hypothesis_is_not_a_finding(self):
        h = S.Hypothesis(hypothesis_id="H", case_id="C", domain="image", claim="x")
        assert not hasattr(h, "finding_id")


# --------------------------------------------------------------------------- #
# Critique (unit 06) — challenges, not verdicts
# --------------------------------------------------------------------------- #
class TestCritique:
    def test_critique_enumerates_checks(self):
        c = S.Critique(
            critique_id="CRIT-1", case_id="C-1", target_id="FIND-1",
            questions=["What evidence is independent?"],
            risks=["GPS may conflict with visual evidence"],
            alternative_explanations=["Metadata could have been altered"],
            challenges_conclusion=True,
        )
        assert c.challenges_conclusion is True
        assert c.questions


# --------------------------------------------------------------------------- #
# ContextFrame (unit 07) — layered context
# --------------------------------------------------------------------------- #
class TestContextFrame:
    def test_context_carries_case_without_restating(self):
        ctx = S.ContextFrame(
            case_id="CASE-2047", domain="image",
            recent_evidence_node_ids=["n1", "n2"],
            open_finding_ids=["F1"],
            is_zero_retention=False,
        )
        assert ctx.case_id == "CASE-2047"
        assert ctx.tenant_id is None

    def test_context_defaults(self):
        ctx = S.ContextFrame()
        assert ctx.recent_evidence_node_ids == []
        assert ctx.is_zero_retention is False


# --------------------------------------------------------------------------- #
# ModelSpec (unit 09) — provider-agnostic gateway contract
# --------------------------------------------------------------------------- #
class TestModelSpec:
    def test_local_qwen_planner(self):
        m = S.ModelSpec(
            model_id="qwen2.5-coder:3b",
            name="Qwen 2.5 Coder 3B (local planner)",
            capabilities=[S.ModelCapability.PLANNING, S.ModelCapability.ROUTING],
            provider=S.ModelProvider.OLLAMA,
            local=True,
            version="2.5",
            offline_ok=True,
            zero_retention_safe=True,
            endpoint="qwen2.5-coder:3b",
        )
        assert m.provider == S.ModelProvider.OLLAMA
        assert m.zero_retention_safe  # sensitive cases may route here
        assert m.offline_ok

    def test_cloud_vision_flagged_nonlocal(self):
        m = S.ModelSpec(
            model_id="vision-x", name="V", capabilities=[S.ModelCapability.VISION],
            provider=S.ModelProvider.OPENAI, local=False,
            offline_ok=False, zero_retention_safe=False,
        )
        assert not m.offline_ok


# --------------------------------------------------------------------------- #
# Specialist registry — knowledge layers over one cognitive core
# --------------------------------------------------------------------------- #
class TestSpecialists:
    def test_seven_domains_registered(self):
        assert set(specialists.domains()) == {
            "image", "network", "secops", "osint", "web", "pentest", "ros",
        }

    def test_level4_specialists_route_to_registered_tools(self):
        pentest = specialists.get("pentest")
        assert pentest is not None
        ids = {t.tool_id for t in specialists.registered_tools("pentest")}
        assert ids == {
            "nmap_scan", "default_cred_tester", "crack_hash",
            "analyze_privilege_escalation", "scan_webshells",
        }
        ros = specialists.get("ros")
        assert ros is not None
        assert {t.tool_id for t in specialists.registered_tools("ros")} == {
            "inspect_ros", "analyze_safety_config",
        }

    def test_image_specialist_routes_to_registered_tools(self):
        img = specialists.get("image")
        assert img is not None
        registered = specialists.registered_tools("image")
        ids = {t.tool_id for t in registered}
        # All 16 Phase A tools are registered under the image domain.
        assert ids == set(specialists.get("image").tool_ids)
        assert len(ids) == 16

    def test_planned_domains_declare_but_do_not_route_yet(self):
        # OSINT now routes its first real tool (inspect_local_path); WEB is
        # still declared but unregistered — it routes to nothing until its
        # tools land.
        osint = specialists.get("osint")
        assert osint is not None and osint.tool_ids
        assert {t.tool_id for t in specialists.registered_tools("osint")} == {"inspect_local_path"}
        for domain in ("web",):
            spec = specialists.get(domain)
            assert spec is not None and spec.tool_ids
            assert specialists.registered_tools(domain) == []
        for domain in ("network", "secops"):
            assert specialists.registered_tools(domain) != []

    def test_goal_mapping_for_location_verification(self):
        assert specialists.plan_template_id(
            "image", S.InvestigationGoal.VERIFY_LOCATION_CREDIBILITY
        ) == "image_verify_location"

    def test_registry_built_independently(self):
        r = SpecialistRegistry()
        assert r.get("secops").domain == "secops"
        assert r.get("unknown") is None
