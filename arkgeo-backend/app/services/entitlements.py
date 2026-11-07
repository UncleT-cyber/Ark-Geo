"""Model access entitlements (Phase 6).

The access-control boundary between a principal and a model.  Administrator
configuration (platform providers, default model, allowed providers/models,
plan grants, organizational policy) lives in the AdminStore gateway section;
this module only *evaluates* it against a principal.

Scope resolution is most-specific-wins: ``users`` → ``organizations`` →
``default``.  A scope replaces the list fields it defines; deny-lists union
across scopes so a narrower scope can never re-open something an outer scope
denied.

No billing is performed and no plans are invented — ``subscription_models`` is
empty by default, which is exactly why an ARK-managed (subscription) model is
denied until an operator grants it.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any, Optional

# ARK-managed (platform-hosted) models live under this provider namespace.
SUBSCRIPTION_PROVIDER = "ark"

# Credential source categories (Phase 3).
SOURCE_PLATFORM = "platform"
SOURCE_ORGANIZATION = "organization"
SOURCE_USER = "user"
SOURCE_LOCAL = "local"
SOURCE_NONE = "none"

_DEFAULT_ENTITLEMENT: dict[str, Any] = {
    "allow_platform": True,
    "allow_byok": True,
    "allow_local": True,
    "allowed_providers": ["*"],
    "denied_providers": [],
    "allowed_models": ["*"],
    "denied_models": [],
    "subscription_models": [],
    "plan": None,
    "usage_limits": {},
}

_LIST_FIELDS = ("allowed_providers", "denied_providers", "allowed_models",
                "denied_models", "subscription_models")
_BOOL_FIELDS = ("allow_platform", "allow_byok", "allow_local")


@dataclass(frozen=True)
class Principal:
    """An authenticated (or anonymous) caller.

    ``subject`` is an opaque, server-derived id.  The client sends it as a
    header only for development; a production deployment binds it from the
    authenticated session.
    """

    subject: str
    kind: str = "user"                 # user | organization | client | anonymous
    organization: Optional[str] = None
    roles: tuple[str, ...] = ()

    def namespace(self) -> str:
        """Storage namespace for this principal's prefs and credentials."""
        org = self.organization or "-"
        return f"{self.kind}:{self.subject}@{org}"


ANONYMOUS = Principal(subject="anonymous", kind="anonymous")


@dataclass
class AccessDecision:
    allowed: bool
    reason: str
    rule_id: str
    entitlement_source: str = "default"
    plan: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "rule_id": self.rule_id,
            "entitlement_source": self.entitlement_source,
            "plan": self.plan,
        }


@dataclass
class _Scope:
    data: dict[str, Any] = field(default_factory=dict)


def _merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Overlay a scope: lists replace, deny-lists union, bools/scalars override."""
    out = dict(base)
    for key, value in overlay.items():
        if key in _LIST_FIELDS and isinstance(value, list):
            if key in ("denied_providers", "denied_models"):
                out[key] = sorted(set(out.get(key, [])) | set(value))
            else:
                out[key] = list(value)
        elif key in _BOOL_FIELDS:
            out[key] = bool(value)
        else:
            out[key] = value
    return out


def _load_config() -> dict[str, Any]:
    from app.services.admin_store import admin_store

    gw = admin_store.get_gateway()
    cfg = gw.get("entitlements")
    return cfg if isinstance(cfg, dict) else {}


def resolve_entitlement(principal: Principal) -> tuple[dict[str, Any], str]:
    """Return ``(effective_entitlement, source_scope)`` for a principal."""
    cfg = _load_config()
    eff = dict(_DEFAULT_ENTITLEMENT)
    source = "default"

    if isinstance(cfg.get("default"), dict):
        eff = _merge(eff, cfg["default"])
        source = "default"

    orgs = cfg.get("organizations") or {}
    if principal.organization and isinstance(orgs.get(principal.organization), dict):
        eff = _merge(eff, orgs[principal.organization])
        source = "organization"

    users = cfg.get("users") or {}
    if isinstance(users.get(principal.subject), dict):
        eff = _merge(eff, users[principal.subject])
        source = "user"

    return eff, source


def _matches_any(value: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(value, pat) for pat in patterns)


def evaluate(
    principal: Principal,
    provider: str,
    model: str,
    *,
    credential_source: str = SOURCE_PLATFORM,
) -> AccessDecision:
    """Decide whether ``principal`` may run ``provider/model``."""
    eff, source = resolve_entitlement(principal)
    plan = eff.get("plan")
    provider = (provider or "").strip().lower()
    full_id = f"{provider}/{model}" if provider else model

    # 1. ARK-managed subscription models require an explicit grant.
    if provider == SUBSCRIPTION_PROVIDER:
        granted = eff.get("subscription_models") or []
        if model in granted or full_id in granted or _matches_any(full_id, granted):
            return AccessDecision(True, "subscription grant active", "entitlement.subscription_granted", source, plan)
        return AccessDecision(
            False,
            "This model requires an ARK subscription plan that is not enabled for your account.",
            "entitlement.subscription_required",
            source,
            plan,
        )

    # 2. Provider deny/allow.
    if provider in (eff.get("denied_providers") or []):
        return AccessDecision(False, f"Provider '{provider}' is disabled by policy.",
                              "entitlement.provider_denied", source, plan)
    allowed_providers = eff.get("allowed_providers") or ["*"]
    if not _matches_any(provider, allowed_providers):
        return AccessDecision(False, f"Provider '{provider}' is not permitted for your account.",
                              "entitlement.provider_not_allowed", source, plan)

    # 3. Model deny/allow.
    if _matches_any(full_id, eff.get("denied_models") or []):
        return AccessDecision(False, f"Model '{full_id}' is disabled by policy.",
                              "entitlement.model_denied", source, plan)
    allowed_models = eff.get("allowed_models") or ["*"]
    if not _matches_any(full_id, allowed_models):
        return AccessDecision(False, f"Model '{full_id}' is not permitted for your account.",
                              "entitlement.model_not_allowed", source, plan)

    # 4. Credential-source policy.
    if credential_source == SOURCE_USER and not eff.get("allow_byok", True):
        return AccessDecision(False, "Your own API keys (BYOK) are disabled by policy.",
                              "entitlement.byok_disabled", source, plan)
    if credential_source == SOURCE_LOCAL and not eff.get("allow_local", True):
        return AccessDecision(False, "Local model execution is disabled by policy.",
                              "entitlement.local_disabled", source, plan)
    if credential_source in (SOURCE_PLATFORM, SOURCE_ORGANIZATION) and not eff.get("allow_platform", True):
        return AccessDecision(False, "Platform-managed model access is disabled by policy.",
                              "entitlement.platform_disabled", source, plan)

    return AccessDecision(True, "permitted by entitlement", "entitlement.granted", source, plan)


def list_entitlements() -> dict[str, Any]:
    """Admin view of the configured entitlement document."""
    cfg = _load_config()
    return {
        "default": _merge(dict(_DEFAULT_ENTITLEMENT), cfg.get("default") or {}),
        "organizations": cfg.get("organizations") or {},
        "users": cfg.get("users") or {},
    }
