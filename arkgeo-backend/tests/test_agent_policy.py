"""Tests for the ARK Policy Guard (Phase B).

Covers the authorization surface the Phase C orchestrator will sit behind:
  * allow/deny paths for low / medium / elevated / (would-be) high-risk tools
  * capability/permission checks incl. parameterized call:provider
  * approval tiers (auto / confirm_once / step_confirm) from default ruleset
  * availability gating (requires_key / disabled)
  * budget enforcement (steps / tokens / ms / api_calls)
  * audit-node emission onto the evidence graph

All deterministic — no AI, no network.
"""
import pytest

from app.agent import evidence_graph as eg
from app.agent import schemas as S
from app.agent.policy_guard import (
    BudgetExceeded,
    BudgetUsage,
    PermissionDenied,
    PolicyGuard,
    ToolUnavailable,
    default_rules,
    guard,
)
from app.agent.tool_registry import registry


# A permissive key resolver for tests: returns a key for any provider.
def _keyed(name: str) -> str | None:
    return f"test-key-for-{name}"


def _guard(**kw) -> PolicyGuard:
    kw.setdefault("granted_permissions",
                 ["read:evidence", "call:provider", "query:external"])
    kw.setdefault("key_resolver", _keyed)
    return PolicyGuard(**kw)


# --------------------------------------------------------------------------- #
# Allow / deny and approval tiers
# --------------------------------------------------------------------------- #
def test_low_risk_tool_allowed_auto():
    g = _guard()
    d = g.evaluate("compute_custody_hash")
    assert d.allowed
    assert d.approval_tier == S.ApprovalTier.AUTO


def test_medium_tool_confirm_once():
    g = _guard()
    d = g.evaluate("aggregate_consensus")
    assert d.allowed
    assert d.approval_tier == S.ApprovalTier.CONFIRM_ONCE


def test_elevated_tool_confirm_once_when_keyed():
    g = _guard()
    d = g.evaluate("run_vision_ensemble")
    assert d.allowed
    assert d.approval_tier == S.ApprovalTier.CONFIRM_ONCE


def test_unknown_tool_denied():
    g = _guard()
    d = g.evaluate("does_not_exist")
    assert not d.allowed
    assert d.rule_id == "registry"


# --------------------------------------------------------------------------- #
# Availability gating
# --------------------------------------------------------------------------- #
def test_requires_key_denied_without_key():
    g = _guard(key_resolver=lambda _n: None)
    d = g.evaluate("run_vision_ensemble")
    assert not d.allowed
    assert d.rule_id == "availability"
    assert "requires provider key" in d.reason


def test_requires_key_allowed_with_key():
    g = _guard(key_resolver=lambda n: "k" if n == "llm_api_key" else None)
    d = g.evaluate("run_vision_ensemble")
    assert d.allowed


# --------------------------------------------------------------------------- #
# Capability / permission checks
# --------------------------------------------------------------------------- #
def test_missing_permission_denied():
    # Only read:evidence granted — vision needs call:provider.
    g = PolicyGuard(granted_permissions=["read:evidence"],
                    key_resolver=_keyed)
    d = g.evaluate("run_vision_ensemble")
    assert not d.allowed
    assert d.rule_id == "permissions"
    assert "call:provider" in d.reason


def test_bare_call_provider_satisfies_specific_provider():
    # A bare call:provider grant should satisfy a tool requiring call:provider.
    g = PolicyGuard(
        granted_permissions=["read:evidence", "call:provider"],
        key_resolver=_keyed,
    )
    d = g.evaluate("run_vision_ensemble")
    assert d.allowed


def test_query_external_required_for_geocode():
    g = PolicyGuard(granted_permissions=["read:evidence"],
                    key_resolver=_keyed)
    d = g.evaluate("reverse_geocode")
    assert not d.allowed
    assert d.rule_id == "permissions"


# --------------------------------------------------------------------------- #
# Budget enforcement
# --------------------------------------------------------------------------- #
def test_budget_steps_denial():
    g = _guard(budget=S.Budget(max_steps=1))
    g.record_run("compute_custody_hash")
    d = g.evaluate("extract_exif")
    assert not d.allowed
    assert d.rule_id == "budget"
    assert "step budget exhausted" in d.reason


def test_budget_tokens_denial():
    g = _guard(budget=S.Budget(max_tokens=100))
    g.record_run("run_vision_ensemble", tokens=120)
    d = g.evaluate("extract_exif")
    assert not d.allowed
    assert d.rule_id == "budget"
    assert "token budget exhausted" in d.reason


def test_budget_api_calls_denial():
    g = _guard(budget=S.Budget(max_api_calls=1))
    g.record_run("run_vision_ensemble", api_calls=1)
    d = g.evaluate("extract_exif")
    assert not d.allowed
    assert d.rule_id == "budget"


def test_budget_usage_exhausted_reason():
    usage = BudgetUsage(budget=S.Budget(max_ms=10))
    usage.ms = 10
    assert usage.exhausted() is not None
    usage2 = BudgetUsage(budget=S.Budget(max_steps=5))
    assert usage2.exhausted() is None


def test_record_run_accounts_all_counters():
    g = _guard()
    g.record_run("run_vision_ensemble", tokens=500, api_calls=2, elapsed_ms=300)
    assert g.usage.steps == 1
    assert g.usage.tokens == 500
    assert g.usage.api_calls == 2
    assert g.usage.ms == 300


# --------------------------------------------------------------------------- #
# authorize() raises typed exceptions
# --------------------------------------------------------------------------- #
def test_authorize_raises_permission_denied():
    g = PolicyGuard(granted_permissions=["read:evidence"],
                    key_resolver=_keyed)
    with pytest.raises(PermissionDenied):
        g.authorize("run_vision_ensemble")


def test_authorize_raises_budget_exceeded():
    g = _guard(budget=S.Budget(max_steps=0))
    with pytest.raises(BudgetExceeded):
        g.authorize("compute_custody_hash")


def test_authorize_raises_tool_unavailable():
    g = _guard(key_resolver=lambda _n: None)
    with pytest.raises(ToolUnavailable):
        g.authorize("run_vision_ensemble")


def test_authorize_returns_decision_when_allowed():
    g = _guard()
    d = g.authorize("compute_custody_hash")
    assert d.allowed


# --------------------------------------------------------------------------- #
# Default ruleset + custom rule override
# --------------------------------------------------------------------------- #
def test_default_rules_present():
    rules = default_rules()
    assert any(r.rule_id == "default.action-step-confirm" for r in rules)
    assert any(r.rule_id == "default.high-risk-step-confirm" for r in rules)


def test_custom_rule_tightens_low_tool_to_confirm():
    g = _guard()
    g.add_rule(S.PolicyRule(
        rule_id="custodial.confirm",
        match=S.PolicyMatch(tool_id_glob="compute_custody_hash"),
        approval_tier=S.ApprovalTier.CONFIRM_ONCE,
    ))
    d = g.evaluate("compute_custody_hash")
    assert d.allowed
    assert d.approval_tier == S.ApprovalTier.CONFIRM_ONCE


def test_custom_rule_does_not_downgrade_below_default():
    # An explicit AUTO rule on a medium tool should not lower it below the
    # risk default of confirm_once (medium).
    g = _guard()
    g.add_rule(S.PolicyRule(
        rule_id="relax.consensus",
        match=S.PolicyMatch(tool_id_glob="aggregate_consensus"),
        approval_tier=S.ApprovalTier.AUTO,
    ))
    d = g.evaluate("aggregate_consensus")
    # Medium risk default is confirm_once; auto rule cannot downgrade.
    assert d.approval_tier == S.ApprovalTier.CONFIRM_ONCE


# --------------------------------------------------------------------------- #
# Audit-node emission onto the evidence graph
# --------------------------------------------------------------------------- #
def test_audit_node_records_invocation():
    graph = eg.EvidenceGraph(case_id="ARK-CASE-1")
    invocation = {
        "invocation_id": "INV-1",
        "arguments": {"image_bytes": b"..."},
        "status": "done",
        "started_at_ms": 1000,
        "completed_at_ms": 1200,
    }
    decision = {"allowed": True, "approval_tier": "auto", "rule_id": "default"}
    audit = eg.audit_tool_call(graph, "compute_custody_hash",
                               invocation, decision)
    assert audit.provenance_type == S.ProvenanceType.CRYPTOGRAPHIC
    assert audit.tool_id == "audit"
    assert audit.node_id in graph.nodes
    # arguments are hashed, not stored raw
    assert "arguments_hash" in audit.value
    assert "image_bytes" not in str(audit.value)
    assert audit.value["policy"]["rule_id"] == "default"


def test_audit_links_to_produced_evidence():
    graph = eg.EvidenceGraph(case_id="ARK-CASE-1")
    produced = eg.build_node(
        "ARK-CASE-1", "extract_exif", S.ProvenanceType.TOOL_INFERENCE,
        "EXIF GPS", S.ClaimType.LOCATION, {"lat": 6.5, "lon": 3.4},
    )
    eg.add_node(graph, produced)
    invocation = {"invocation_id": "INV-2", "status": "done"}
    audit = eg.audit_tool_call(graph, "extract_exif", invocation,
                               produced_node_id=produced.node_id)
    # A derived_from edge links audit -> produced evidence.
    linked = [e for e in graph.edges
              if e.src == audit.node_id and e.dst == produced.node_id]
    assert linked and linked[0].relation == S.EdgeRelation.DERIVED_FROM


def test_audit_node_is_tamper_evident():
    graph = eg.EvidenceGraph(case_id="ARK-CASE-1")
    audit = eg.audit_tool_call(graph, "compute_custody_hash",
                               {"invocation_id": "INV-3", "status": "done"})
    # Tamper with the recorded value after insertion.
    audit.value["status"] = "tampered"
    # Re-adding a tampered node (recomputed hash != stored) must raise.
    with pytest.raises(ValueError):
        eg.add_node(graph, audit)
