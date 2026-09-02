"""ARK Identity Contract (cognitive layer §6) — prompt files + composition.

Validates the runtime architecture the identity contract defines:

* prompt files are data under ``app/agent/cognitive/`` and
  ``app/agent/domains/<domain>/``;
* :mod:`app.agent.context_builder` composes core → domain → tools in a fixed
  order, swaps the domain block without changing who ARK is, and degrades
  gracefully when a file is missing;
* the model gateway (unit 09) routes planner/adaptive calls through the
  composed contract, not ad-hoc inline prompts.

These are contract tests: they pin the *shape* of the identity layer so
later domains (OSINT/WEB engines, cases) add files instead of rewiring.
"""
import pytest

from app.agent import schemas as S
from app.agent.context_builder import (
    ContextBuilder,
    DECLARED_DOMAINS,
    context_builder,
)
from app.agent.domains import __file__ as _domains_pkg
from app.agent.specialists import specialists
from app.agent.cognitive import __file__ as _cognitive_pkg
from pathlib import Path


def _objective(domain="image", **overrides) -> S.InvestigationObjective:
    return S.InvestigationObjective(
        objective_id="OBJ-IDENTITY-TEST",
        goal=S.InvestigationGoal.VERIFY_LOCATION_CREDIBILITY,
        subject="scope-target",
        domain=domain,
        claims_to_verify=[S.ClaimToVerify(field="location", value="test")],
        **overrides,
    )


# --------------------------------------------------------------------------- #
# Prompt files — data, not code
# --------------------------------------------------------------------------- #
class TestPromptFilesExist:
    _CORE = ["00_identity", "01_governance", "02_tool_contract",
             "03_evidence_contract", "04_reasoning_policy",
             "05_reporting_contract"]

    def test_core_prompt_files_present(self):
        cog = Path(_cognitive_pkg).parent
        for stem in self._CORE:
            assert (cog / f"{stem}.prompt").is_file(), f"{stem}.prompt missing"

    def test_every_declared_domain_has_triplet(self):
        dom = Path(_domains_pkg).parent
        for d in DECLARED_DOMAINS:
            for f in ("identity", "reasoning", "tools"):
                p = dom / d / f"{f}.prompt"
                assert p.is_file(), f"{p} missing"

    def test_declared_domains_cover_registered_specialists(self):
        for spec in specialists.list():
            assert spec.domain in DECLARED_DOMAINS


# --------------------------------------------------------------------------- #
# Composition — order, inheritance without prompt inheritance, swap
# --------------------------------------------------------------------------- #
class TestComposition:
    def test_system_prompt_section_order(self):
        sys = context_builder.build_system_prompt("network", [])
        assert "ARK CORE IDENTITY" in sys
        assert "ARK GOVERNANCE" in sys
        assert "ARK TOOL CONTRACT" in sys
        assert "ARK EVIDENCE CONTRACT" in sys
        assert "ARK REASONING POLICY" in sys
        assert "ARK REPORTING CONTRACT" in sys
        order = [sys.index("ARK CORE IDENTITY"), sys.index("ARK GOVERNANCE"),
                 sys.index("ARK TOOL CONTRACT"), sys.index("ARK EVIDENCE CONTRACT"),
                 sys.index("ARK REASONING POLICY"),
                 sys.index("ARK REPORTING CONTRACT"),
                 sys.index("DOMAIN — NETWORK")]
        assert order == sorted(order)

    def test_domain_block_swaps_but_identity_unchanged(self):
        core_for = lambda d: context_builder.build_system_prompt(d, [])
        net, sec, img = core_for("network"), core_for("secops"), core_for("image")
        # Same stable ARK core, different specialist.
        for section in ("ARK CORE IDENTITY", "ARK GOVERNANCE",
                        "ARK EVIDENCE CONTRACT"):
            assert section in net and section in sec
        assert "NETWORK" in net and "NETWORK" not in sec.split("===== DOMAIN —")[1]
        assert "Threat & SecOps" in sec
        assert "Image Intelligence" in img
        assert "THREAT & SECOPS" in sec.upper()

    def test_identity_establishes_role_and_boundaries(self):
        sys = context_builder.build_system_prompt("image", [])
        # The core statements that define ARK's role.
        assert "you are ark" in sys.lower()
        assert "cognitive investigation" in sys.lower()
        assert "never fabricate" in sys.lower()
        assert "the analyst remains the final decision-maker" in sys.lower()
        # Anti-hallucination principle is present verbatim.
        assert "verifiable investigative work" in sys
        assert "absence of evidence" in sys.lower()

    def test_tools_are_injected_dynamically(self):
        tools = specialists.registered_tools("network")
        sys = context_builder.build_system_prompt("network", tools)
        assert "AVAILABLE TOOLS" in sys
        for t in tools:
            assert f"- {t.tool_id}:" in sys
        # A tool from another domain must NOT leak in.
        assert "siem_query" not in sys

    def test_missing_file_degrades_gracefully(self, tmp_path):
        b = ContextBuilder(cognitive_dir=tmp_path, domains_dir=tmp_path)
        # Nothing to load → tools-only prompt, no crash.
        sys = b.build_system_prompt("image", [])
        assert "AVAILABLE TOOLS" in sys
        assert "ARK CORE IDENTITY" not in sys

    def test_user_prompt_carries_case_context(self):
        tools = specialists.registered_tools("network")
        system, user = context_builder.build_plan_prompt(
            _objective("network", natural_language="map the scope"), tools)
        assert "map the scope" in user
        assert "scope-target" in user
        assert "location=test" in user
        assert "network" in user.lower()
        assert system != ""

    def test_next_prompt_carries_gap_and_budget(self):
        tools = specialists.registered_tools("secops")
        system, user = context_builder.build_next_prompt(
            _objective("secops"),
            gap={"gap_type": "integrity", "rationale": "missing telemetry"},
            tool_specs=tools,
            budget_summary="used 3/25",
        )
        assert "missing telemetry" in user
        assert "used 3/25" in user
        assert "integrity" in user


# --------------------------------------------------------------------------- #
# Gateway wiring — planner + adaptive calls go through the identity contract
# --------------------------------------------------------------------------- #
class TestGatewayWiring:
    @pytest.mark.asyncio
    async def test_plan_steps_composes_contract(self, monkeypatch):
        captured = {}

        async def fake_chat(messages, **kwargs):
            captured["system"] = messages[0]["content"]
            captured["user"] = messages[1]["content"]
            return '{"steps": [{"tool_id": "siem_query", "rationale": "start"}]}'

        from app.agent.model_gateway import gateway
        monkeypatch.setattr(gateway, "chat", fake_chat)
        tools = specialists.registered_tools("secops")
        out = await gateway.plan_steps(_objective("secops"), tools, "secops")
        assert out and out[0]["tool_id"] == "siem_query"
        assert "ARK CORE IDENTITY" in captured["system"]
        assert "DOMAIN — SECOPS" in captured["system"].upper()
        assert "siem_query" in captured["system"]
        assert "USER OBJECTIVE" in captured["user"]

    @pytest.mark.asyncio
    async def test_propose_next_composes_contract(self, monkeypatch):
        captured = {}

        async def fake_chat(messages, **kwargs):
            captured["system"] = messages[0]["content"]
            captured["user"] = messages[1]["content"]
            return '{"steps": [{"tool_id": "threat_hunt", "rationale": "close gap"}]}'

        from app.agent.model_gateway import gateway
        monkeypatch.setattr(gateway, "chat", fake_chat)
        tools = specialists.registered_tools("secops")
        out = await gateway.propose_next(
            _objective("secops"),
            gap={"gap_type": "integrity", "rationale": "hunt missing"},
            tool_specs=tools,
            budget_summary="used 1/25",
        )
        assert out and out[0]["tool_id"] == "threat_hunt"
        assert "ARK CORE IDENTITY" in captured["system"]
        assert "hunt missing" in captured["user"]

    @pytest.mark.asyncio
    async def test_plan_steps_keeps_signature_compat(self, monkeypatch):
        # The planner calls (objective, tool_specs, domain_key); a domain key
        # must flow through without breaking the existing call site.
        from app.agent.planner import plan_builder
        _base = _objective("network")

        async def fake_plan_steps(objective, tool_specs, domain_key):
            return [{"tool_id": "discover_hosts", "rationale": "first"}]

        monkeypatch.setattr("app.agent.model_gateway.gateway.plan_steps",
                            fake_plan_steps)
        plan, source = await plan_builder.build(_base, "CASE-IDENT")
        assert source == "model"
        assert plan.steps[0].tool_id == "discover_hosts"
