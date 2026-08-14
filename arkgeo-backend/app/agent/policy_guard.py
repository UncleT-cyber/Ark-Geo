"""Policy / Permission Guard — Phase B.

Evaluates a :class:`PolicyDecision` for every tool the orchestrator wants to
invoke. It is the *authorization surface* that sits between the planner and the
registry: a tool runs only when the guard returns ``allowed=True`` and the
required approval (if any) has been recorded.

Responsibilities (spec §5):

  * **Capability/permission check** — the caller's granted permissions must
    cover the tool's required permissions. ``call:provider:<name>`` is
    parameterized: a granted ``call:provider`` (bare) allows any provider, while
    ``call:provider:geospy`` allows only that one.
  * **Risk → approval tier** — low risk = auto; medium / action = confirm_once;
    elevated external provider = confirm_once (and requires a provider key);
    high risk / active = step_confirm. The matching rule may override.
  * **Budget enforcement** — counts steps, tokens, wall-clock ms, and external
    API calls against the active budget; a tool that would breach the budget is
    denied with a clear reason. Budgets prevent non-termination of adaptive
    re-planning.
  * **Availability** — tools marked ``requires_key`` are denied unless their
    provider key is present (resolved via the existing settings store so keys
    updated from the Admin panel take effect immediately); ``disabled`` tools
    are always denied.
  * **Audit** — every decision is recorded: the guard returns the decision and
    the caller writes it onto the evidence graph as a tier-0 audit node (see
    :func:`evidence_graph.audit_tool_call`).

Phase B is deterministic scaffolding: no AI, no I/O beyond key resolution, and
no change to ``BrainPipeline`` / ``/analyze``. The guard is consumed by the
Phase C orchestrator loop.
"""
from __future__ import annotations

import fnmatch
import time
from dataclasses import dataclass, field
from typing import Optional

from . import schemas as S
from .tool_registry import Tool, registry

# Risk ordering for ``risk_min`` matches in policy rules.
_RISK_ORDER: dict[S.RiskLevel, int] = {
    S.RiskLevel.LOW: 0,
    S.RiskLevel.MEDIUM: 1,
    S.RiskLevel.ELEVATED: 2,
    S.RiskLevel.HIGH: 3,
}

# Risk -> default approval tier when no explicit rule matches.
_DEFAULT_TIER: dict[S.RiskLevel, S.ApprovalTier] = {
    S.RiskLevel.LOW: S.ApprovalTier.AUTO,
    S.RiskLevel.MEDIUM: S.ApprovalTier.CONFIRM_ONCE,
    S.RiskLevel.ELEVATED: S.ApprovalTier.CONFIRM_ONCE,
    S.RiskLevel.HIGH: S.ApprovalTier.STEP_CONFIRM,
}


class PermissionDenied(Exception):
    """Caller lacks the permissions required by the tool."""


class BudgetExceeded(Exception):
    """Executing the tool would breach the active budget."""


class ToolUnavailable(Exception):
    """The tool is disabled or its provider key is not configured."""


@dataclass
class BudgetUsage:
    """Live consumption against a budget. Mutated by the guard on each run."""
    budget: S.Budget = field(default_factory=S.Budget)
    steps: int = 0
    tokens: int = 0
    ms: int = 0
    api_calls: int = 0

    def exhausted(self) -> Optional[str]:
        """Return a reason string if any limit is breached, else None."""
        if self.steps >= self.budget.max_steps:
            return f"step budget exhausted ({self.steps}/{self.budget.max_steps})"
        if self.tokens >= self.budget.max_tokens:
            return f"token budget exhausted ({self.tokens}/{self.budget.max_tokens})"
        if self.ms >= self.budget.max_ms:
            return f"time budget exhausted ({self.ms}/{self.budget.max_ms} ms)"
        if self.api_calls >= self.budget.max_api_calls:
            return (f"api-call budget exhausted "
                    f"({self.api_calls}/{self.budget.max_api_calls})")
        return None

    def to_dict(self) -> dict:
        return {
            "budget": self.budget.model_dump(),
            "steps": self.steps, "tokens": self.tokens,
            "ms": self.ms, "api_calls": self.api_calls,
        }


def _key_resolver() -> "callable[[str], Optional[str]]":
    """Resolve provider keys via the existing settings store, lazily.

    Imported lazily so the guard is unit-testable without the full backend
    settings machinery. Falls back to ``None`` (no key) if the store is absent.
    """
    try:
        from ..services.settings_store import settings_store

        def _resolve(name: str) -> Optional[str]:
            # Map provider names to the settings-store key naming convention.
            key = settings_store.get_key(name) if hasattr(
                settings_store, "get_key") else None
            return key or None

        return _resolve
    except Exception:
        return lambda _name: None


def _provider_key_name(tool: Tool) -> str:
    """The settings-store key for a tool's provider (best-effort)."""
    p = tool.spec.provider
    mapping = {
        "geospy": "geospy_api_key",
        "geoinfer": "geoinfer_api_key",
        "vision_llm": "llm_api_key",
        "vision_ensemble": "llm_api_key",
        "reverse_search": "reverse_search_api_key",
        "nominatim": "nominatim_api_key",
    }
    return mapping.get(p, f"{p}_api_key")


def _permission_granted(required: list[S.Permission],
                        granted: list[str]) -> bool:
    """Capability check. ``call:provider`` (bare) implies any provider."""
    granted_set = set(granted)
    for perm in required:
        if perm in granted_set:
            continue
        if perm == S.Permission.CALL_PROVIDER:
            # Any specific call:provider:* grant satisfies a bare requirement.
            if any(g.startswith("call:provider:") for g in granted_set):
                continue
        return False
    return True


def _rule_matches(rule: S.PolicyRule, tool: Tool) -> bool:
    if not rule.enabled:
        return False
    m = rule.match
    if m.tool_id_glob is not None and not fnmatch.fnmatch(tool.tool_id,
                                                          m.tool_id_glob):
        return False
    if m.risk_min is not None and _RISK_ORDER[tool.spec.risk] < _RISK_ORDER[
            m.risk_min]:
        return False
    if m.category is not None and tool.spec.category != m.category:
        return False
    if m.domain is not None and tool.spec.domain != m.domain:
        return False
    return True


class PolicyGuard:
    """Evaluates and records policy decisions for tool invocations."""

    def __init__(
        self,
        rules: Optional[list[S.PolicyRule]] = None,
        granted_permissions: Optional[list[str]] = None,
        budget: Optional[S.Budget] = None,
        key_resolver: Optional["callable[[str], Optional[str]]"] = None,
    ) -> None:
        self.rules = rules if rules is not None else default_rules()
        self.granted = list(granted_permissions or [S.Permission.READ_EVIDENCE])
        self.usage = BudgetUsage(budget=budget or S.Budget())
        self._key = key_resolver or _key_resolver()

    # ------------------------------------------------------------------ #
    def set_budget(self, budget: S.Budget) -> None:
        self.usage = BudgetUsage(budget=budget)

    def add_rule(self, rule: S.PolicyRule) -> None:
        self.rules.append(rule)

    # ------------------------------------------------------------------ #
    def _resolve_approval(self, tool: Tool) -> tuple[S.ApprovalTier, str, str]:
        """Pick the most restrictive applicable approval tier for a tool."""
        chosen = _DEFAULT_TIER[tool.spec.risk]
        rule_id = "default"
        reason = f"default tier for risk={tool.spec.risk.value}"

        # The most specific (last) matching explicit rule wins, so admins can
        # tighten or relax a category without rewriting the whole ruleset.
        for rule in self.rules:
            if _rule_matches(rule, tool):
                if rule.require_confirmation_for and \
                        tool.spec.category in rule.require_confirmation_for:
                    chosen = S.ApprovalTier.STEP_CONFIRM
                else:
                    # Don't downgrade below the risk default — only raise.
                    if _RISK_ORDER_APPR(rule.approval_tier) >= \
                            _RISK_ORDER_APPR(chosen):
                        chosen = rule.approval_tier
                rule_id = rule.rule_id
                reason = f"rule {rule.rule_id} -> {rule.approval_tier.value}"
        return chosen, reason, rule_id

    def _check_availability(self, tool: Tool) -> Optional[str]:
        """Return a denial reason if the tool is unavailable, else None."""
        av = tool.spec.availability
        if av == S.Availability.DISABLED:
            return f"tool {tool.tool_id} is disabled"
        if av == S.Availability.REQUIRES_KEY:
            key = self._key(_provider_key_name(tool))
            if not key:
                return (f"tool {tool.tool_id} requires provider key "
                        f"{_provider_key_name(tool)} (not configured)")
        if av == S.Availability.REQUIRES_CONFIRMATION:
            return None  # handled via approval tier
        return None

    def evaluate(self, tool_id: str) -> S.PolicyDecision:
        """Compute the policy decision for a proposed tool call.

        Does **not** mutate budget usage — call :meth:`record_run` after the
        tool completes. Returns a :class:`PolicyDecision` with
        ``allowed``/``approval_tier``/``reason``/``rule_id``.
        """
        tool = registry.get(tool_id)
        if tool is None:
            return S.PolicyDecision(
                allowed=False, approval_tier=S.ApprovalTier.STEP_CONFIRM,
                reason=f"tool {tool_id} not registered",
                rule_id="registry",
            )

        # 1. Availability (disabled / missing provider key).
        avail_reason = self._check_availability(tool)
        if avail_reason:
            return S.PolicyDecision(
                allowed=False, approval_tier=tool.spec.risk and _DEFAULT_TIER[
                    tool.spec.risk],
                reason=avail_reason, rule_id="availability",
            )

        # 2. Capability/permission check.
        if not _permission_granted(tool.spec.permissions, self.granted):
            missing = [p.value for p in tool.spec.permissions
                       if p not in self.granted]
            return S.PolicyDecision(
                allowed=False, approval_tier=S.ApprovalTier.STEP_CONFIRM,
                reason=(f"missing permissions: {missing}"),
                rule_id="permissions",
            )

        # 3. Budget check (would this call breach a limit?).
        breach = self.usage.exhausted()
        if breach:
            return S.PolicyDecision(
                allowed=False, approval_tier=S.ApprovalTier.STEP_CONFIRM,
                reason=breach, rule_id="budget",
            )

        # 4. Approval tier.
        tier, reason, rule_id = self._resolve_approval(tool)
        return S.PolicyDecision(
            allowed=True, approval_tier=tier, reason=reason, rule_id=rule_id,
        )

    def authorize(self, tool_id: str) -> S.PolicyDecision:
        """Convenience: evaluate and raise on denial.

        Raises :class:`PermissionDenied`, :class:`ToolUnavailable`, or
        :class:`BudgetExceeded` so the orchestrator can branch on cause.
        """
        decision = self.evaluate(tool_id)
        if decision.allowed:
            return decision
        r = decision.reason
        if decision.rule_id == "budget":
            raise BudgetExceeded(r)
        if decision.rule_id == "availability":
            raise ToolUnavailable(r)
        raise PermissionDenied(r)

    def record_run(
        self,
        tool_id: str,
        tokens: int = 0,
        api_calls: int = 0,
        elapsed_ms: int = 0,
    ) -> None:
        """Account a completed tool run against the active budget.

        Every invocation counts as one step regardless of cost; token / ms /
        api-call counters are incremented by the tool's actual consumption.
        """
        self.usage.steps += 1
        self.usage.tokens += tokens
        self.usage.api_calls += api_calls
        self.usage.ms += elapsed_ms


# --------------------------------------------------------------------------- #
# Approval-tier ordering: AUTO < CONFIRM_ONCE < STEP_CONFIRM.
# --------------------------------------------------------------------------- #
_APPR_ORDER: dict[S.ApprovalTier, int] = {
    S.ApprovalTier.AUTO: 0,
    S.ApprovalTier.CONFIRM_ONCE: 1,
    S.ApprovalTier.STEP_CONFIRM: 2,
}


def _RISK_ORDER_APPR(tier: S.ApprovalTier) -> int:  # noqa: N802
    return _APPR_ORDER[tier]


# --------------------------------------------------------------------------- #
# Default ruleset
# --------------------------------------------------------------------------- #
def default_rules() -> list[S.PolicyRule]:
    """Sensible defaults so the orchestrator can run without explicit config.

    They only *raise* the approval tier above the risk default where it makes
    sense (action/high-risk tools get step_confirm); low-risk read/analysis
    tools run auto. Override or extend via :meth:`PolicyGuard.add_rule`.
    """
    return [
        S.PolicyRule(
            rule_id="default.action-step-confirm",
            match=S.PolicyMatch(category=S.ToolCategory.ACTION),
            approval_tier=S.ApprovalTier.STEP_CONFIRM,
            require_confirmation_for=[S.ToolCategory.ACTION],
        ),
        S.PolicyRule(
            rule_id="default.high-risk-step-confirm",
            match=S.PolicyMatch(category=S.ToolCategory.HIGH_RISK),
            approval_tier=S.ApprovalTier.STEP_CONFIRM,
            require_confirmation_for=[S.ToolCategory.HIGH_RISK],
        ),
        S.PolicyRule(
            rule_id="default.elevated-confirm",
            match=S.PolicyMatch(risk_min=S.RiskLevel.ELEVATED),
            approval_tier=S.ApprovalTier.CONFIRM_ONCE,
        ),
        S.PolicyRule(
            rule_id="default.medium-confirm",
            match=S.PolicyMatch(risk_min=S.RiskLevel.MEDIUM),
            approval_tier=S.ApprovalTier.CONFIRM_ONCE,
        ),
    ]


guard = PolicyGuard()
