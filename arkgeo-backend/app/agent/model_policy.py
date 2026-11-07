"""Model Policy — policy-decided model routing (Phase H).

Sibling of :mod:`app.agent.policy_guard`: the guard authorizes *tools*, this
module decides *which model* a capability may use. Both are deterministic and
auditable — no I/O beyond reading the registry, no AI.

The contract, in order of precedence:

1. **Sensitivity forces local.** A zero-retention objective (or an explicit
   ``local_only`` request) may only use a local, ``zero_retention_safe``
   model. This is a structural guarantee, not a rule that can be misconfigured:
   no rule can route a sensitive request to a cloud model.
2. **Explicit rules pin a capability** to a preferred model id. A rule whose
   ``require_local`` is set narrows the candidate set to local arms.
3. **Default** is local-first (see :meth:`ModelRegistry.default_for`).

The outcome is a :class:`~app.agent.schemas.ModelDecision`; the caller records
``spec.model_id`` on the finding/session so the chosen model is part of
provenance. See ``docs/ARK_INTEGRATED_SECURITY_ENVIRONMENT.md`` §5 Phase H.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import schemas as S
from .model_registry import Model, ModelRegistry, registry as default_registry


@dataclass
class ModelRequest:
    """What a caller wants a model for.

    ``capability`` is required; ``domain`` and ``zero_retention`` come from the
    active objective. ``local_only`` is set by callers that already know the
    data must not leave the box.
    """
    capability: S.ModelCapability
    domain: Optional[str] = None
    zero_retention: bool = False
    local_only: bool = False


def _rule_matches(rule: S.ModelPolicyRule, req: ModelRequest) -> bool:
    if not rule.enabled:
        return False
    m = rule.match
    if m.capability is not None and m.capability != req.capability:
        return False
    if m.domain is not None and m.domain != req.domain:
        return False
    if m.zero_retention is not None and m.zero_retention != req.zero_retention:
        return False
    if m.local_only is not None and m.local_only != req.local_only:
        return False
    return True


def default_model_rules() -> list[S.ModelPolicyRule]:
    """Sensible defaults. They only *narrow* — never route sensitive data out.

    The default set is intentionally empty of cloud pinning: with no rules the
    router is local-first, which is the safe and deterministic-planner-aligned
    choice. Deployments add rules to pin a capability to a specific model.
    """
    return []


class ModelPolicy:
    """Decides which registered model serves a request."""

    def __init__(
        self,
        registry: Optional[ModelRegistry] = None,
        rules: Optional[list[S.ModelPolicyRule]] = None,
    ) -> None:
        self.registry = registry or default_registry
        self.rules = rules if rules is not None else default_model_rules()

    def add_rule(self, rule: S.ModelPolicyRule) -> None:
        self.rules.append(rule)

    # ------------------------------------------------------------------ #
    def decide(self, req: ModelRequest) -> S.ModelDecision:
        """Route one request to a model, or deny when nothing may serve it."""
        sensitive = req.zero_retention or req.local_only

        # 1. Sensitivity → local only. Hard guarantee: this is checked before
        #    any rule, so a misconfigured rule cannot leak sensitive data.
        if sensitive:
            local = self._local_candidate(req)
            if local is not None:
                return S.ModelDecision(
                    allowed=True, spec=local.spec,
                    reason=("zero-retention/local-only constraint forces the "
                            "local model" if req.zero_retention
                            else "local-only constraint forces the local model"),
                    rule_id="constraint.local-only",
                    forced_local=True,
                )
            return S.ModelDecision(
                allowed=False, spec=None,
                reason=("no local, zero-retention-safe model serves "
                        f"{req.capability.value}"),
                rule_id="constraint.local-only", forced_local=True,
            )

        # 2. Explicit rules pin a capability. The first matching rule that
        #    yields a usable model wins; rules are evaluated in order, so an
        #    operator orders them most-specific-first.
        for rule in self.rules:
            if not _rule_matches(rule, req):
                continue
            candidate = self._rule_candidate(rule, req)
            if candidate is not None:
                return S.ModelDecision(
                    allowed=True, spec=candidate.spec,
                    reason=f"rule {rule.rule_id} -> {candidate.model_id}",
                    rule_id=rule.rule_id,
                )
            # The rule matched but its model is unregistered or unavailable.
            # Disclose the substitution rather than hard-failing: a rule that
            # names a model this deployment did not provision must not take the
            # whole investigation down.
            fallback = self._available_default(req.capability)
            if fallback is not None:
                return S.ModelDecision(
                    allowed=True, spec=fallback.spec,
                    reason=(f"rule {rule.rule_id} unavailable; "
                            f"falling back to {fallback.model_id}"),
                    rule_id=rule.rule_id, fallback_used=True,
                )

        # 3. Default: local-first for the capability.
        fallback = self._available_default(req.capability)
        if fallback is None:
            return S.ModelDecision(
                allowed=False, spec=None,
                reason=f"no model registered for capability {req.capability.value}",
                rule_id="default",
            )
        return S.ModelDecision(
            allowed=True, spec=fallback.spec,
            reason=f"default model for {req.capability.value}",
            rule_id="default",
        )

    # ------------------------------------------------------------------ #
    def _local_candidate(self, req: ModelRequest) -> Optional[Model]:
        return self.registry.local_for(req.capability)

    def _available_default(self, capability: S.ModelCapability) -> Optional[Model]:
        """Local-first default that can actually be served.

        A local arm is always servable (the deterministic template path does
        not need the runtime); a cloud arm is only chosen when its gateway
        factory resolves, i.e. it is provisioned with a credential.
        """
        local = self.registry.local_for(capability)
        if local is not None:
            return local
        for m in self.registry.list(capability):
            if m.gateway() is not None:
                return m
        return next(iter(self.registry.list(capability)), None)

    def _rule_candidate(
        self, rule: S.ModelPolicyRule, req: ModelRequest,
    ) -> Optional[Model]:
        if rule.require_local:
            if rule.prefer:
                m = self.registry.get(rule.prefer)
                if m is not None and m.spec.local and m.spec.zero_retention_safe:
                    return m
            return self.registry.local_for(req.capability)
        if rule.prefer:
            m = self.registry.get(rule.prefer)
            if m is None or req.capability not in m.spec.capabilities:
                return None
            if not m.spec.local and m.gateway() is None:
                return None  # remote arm has no credential → unavailable
            return m
        return self.registry.default_for(req.capability)


policy = ModelPolicy()


def route(
    capability: S.ModelCapability,
    *,
    domain: Optional[str] = None,
    zero_retention: bool = False,
    local_only: bool = False,
) -> S.ModelDecision:
    """Convenience wrapper over the module-level policy."""
    return policy.decide(ModelRequest(
        capability=capability, domain=domain,
        zero_retention=zero_retention, local_only=local_only,
    ))
