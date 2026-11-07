"""Model-selection authority (Phase 2).

One place decides which model actually runs, and why.  Precedence, in order:

1. Explicit request (Prompt Dock selection / ``/model`` pin) — **highest**.
2. The principal's saved preference.
3. The administrator's default (platform policy — a *fallback*, never an
   override of an explicit user choice).

A denied or unavailable selection returns a clear error; there is **no silent
substitution**.  A configured fallback is used only when the operator enables
it, and the actual model is then disclosed in ``routing_reason``.

Credential source is resolved per provider (Phase 3) and reported as a
*category* — never a secret value.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.services import entitlements as ent
from app.services.entitlements import Principal
from app.models.model_registry import (
    PROVIDER_MODELS,
    PROVIDER_IDENTITY,
    known_model,
    parse_model_id,
)
from app.services.user_credentials import user_credentials
from app.services.user_preferences import user_preferences

_LOCAL_PROVIDERS = ("ollama",)


@dataclass
class Resolution:
    ok: bool
    requested_model: Optional[str] = None
    resolved_model: Optional[str] = None      # canonical "<provider>/<model>"
    provider: Optional[str] = None
    model_name: Optional[str] = None
    credential_source: str = ent.SOURCE_NONE
    routing_reason: str = ""
    entitlement_source: str = "default"
    plan: Optional[str] = None
    fallback_used: bool = False
    error: Optional[str] = None
    error_code: Optional[str] = None
    kwargs: dict[str, Any] = field(default_factory=dict)

    def metadata(self) -> dict[str, Any]:
        """Safe run metadata — categories and ids only, never secrets."""
        return {
            "requested_model": self.requested_model,
            "resolved_model": self.resolved_model,
            "provider": self.provider,
            "credential_source": self.credential_source,
            "routing_reason": self.routing_reason,
            "entitlement_source": self.entitlement_source,
            "plan": self.plan,
            "fallback_used": self.fallback_used,
        }


# --------------------------------------------------------------------------- #
# Credential + availability resolution
# --------------------------------------------------------------------------- #
def _platform_key(provider: str) -> str:
    from app.services.ai_gateway import AIGateway

    return AIGateway()._cloud_key(provider)


def _resolve_credential(principal: Principal, provider: str) -> tuple[str, str]:
    """Return ``(api_key, source_category)`` for a provider.

    Order: user BYOK → platform-managed → none.  (Organization-managed keys are
    a declared-but-unwired source; see the BYOK design notes.)
    """
    if provider in _LOCAL_PROVIDERS:
        return "ollama", ent.SOURCE_LOCAL

    ns = principal.namespace()
    user_key = user_credentials.get_key(ns, provider)
    if user_key:
        return user_key, ent.SOURCE_USER

    platform_key = _platform_key(provider)
    if platform_key:
        return platform_key, ent.SOURCE_PLATFORM

    return "", ent.SOURCE_NONE


def _ollama_available(model: str) -> tuple[bool, str]:
    from app.services.ai_gateway import ai_gateway

    tags = ai_gateway._ollama_models_sync()
    if not tags:
        return False, "Local model runtime (Ollama) is not reachable."
    if model and model not in tags:
        return False, f"Model '{model}' is not installed on the local runtime."
    return True, ""


def _availability(principal: Principal, provider: str, model: str) -> tuple[bool, str, str]:
    """Return ``(available, reason, credential_source)``."""
    if provider == ent.SUBSCRIPTION_PROVIDER:
        # ARK-managed models are gated purely by entitlement, not credentials.
        return False, "ARK-managed model — subscription required.", ent.SOURCE_PLATFORM

    if provider not in PROVIDER_MODELS and provider not in _LOCAL_PROVIDERS:
        return False, f"Unknown provider '{provider}'.", ent.SOURCE_NONE

    if provider in _LOCAL_PROVIDERS:
        ok, reason = _ollama_available(model)
        return ok, reason, ent.SOURCE_LOCAL

    if provider in PROVIDER_MODELS and not known_model(provider, model):
        return False, f"Model '{model}' is not in the {PROVIDER_IDENTITY.get(provider, {}).get('name', provider)} catalogue.", ent.SOURCE_NONE

    key, source = _resolve_credential(principal, provider)
    if not key:
        pretty = PROVIDER_IDENTITY.get(provider, {}).get("name", provider)
        return False, f"No credential available for {pretty}. Add a key in Settings or ask an administrator.", ent.SOURCE_NONE
    return True, "", source


def _build_kwargs(provider: str, model: str, api_key: str) -> dict[str, Any]:
    from app.services.ai_gateway import AIGateway

    if provider in _LOCAL_PROVIDERS:
        from app.services.admin_store import admin_store
        from app.services.ai_gateway import DEFAULT_OLLAMA_BASE

        gw = admin_store.get_gateway()
        return {
            "model": f"ollama/{model}",
            "api_base": (gw.get("ollama_url") or DEFAULT_OLLAMA_BASE).rstrip("/"),
            "api_key": "ollama",
        }
    instance = AIGateway()
    return {
        "model": f"{provider}/{model}",
        "api_base": instance._cloud_base(provider),
        "api_key": api_key,
    }


def _admin_default() -> tuple[str, str]:
    """The administrator's default ``(provider, model)`` from the gateway.

    ``ARKGEO_CAI_MODEL`` (operator-set) is honoured as the *top of the admin
    layer* — it is a platform default, so it still ranks below an explicit user
    selection or saved user preference.
    """
    import os

    from app.services.admin_store import admin_store
    from app.services.ai_gateway import AIGateway

    env_default = (os.environ.get("ARKGEO_CAI_MODEL") or "").strip()
    if env_default:
        prov, mdl = parse_model_id(env_default)
        if prov:
            return prov, mdl

    gw = admin_store.get_gateway()
    provider = (gw.get("active_llm_provider") or "openai").strip().lower()
    if provider in _LOCAL_PROVIDERS:
        tags = AIGateway()._ollama_models_sync()
        model = AIGateway()._resolve_ollama_model(tags, False)
        return provider, model
    model_field = {
        "openai": "openai_model",
        "anthropic": "anthropic_model",
        "gemini": "gemini_model",
        "openrouter": "openrouter_model",
        "huggingface": "huggingface_model",
    }.get(provider)
    model = (gw.get(model_field) or "").strip() if model_field else ""
    if not model:
        model = AIGateway()._resolve_model(provider, False)
    return provider, model


def _fallback_enabled() -> tuple[bool, list[str]]:
    from app.services.admin_store import admin_store

    gw = admin_store.get_gateway()
    cfg = gw.get("fallback") or {}
    enabled = bool(cfg.get("enabled", False))
    chain = cfg.get("chain") or []
    return enabled, [str(x) for x in chain]


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def resolve(
    principal: Principal,
    requested_model: Optional[str] = None,
    *,
    has_image: bool = False,
) -> Resolution:
    """Resolve the model that will actually execute, with full provenance."""
    # ---- precedence: explicit → user pref → admin default ----
    requested = (requested_model or "").strip() or None
    if requested:
        source_of_choice = "explicit request"
    else:
        pref = user_preferences.get(principal.namespace()).get("selected_model")
        if pref:
            requested = pref
            source_of_choice = "saved user preference"
        else:
            prov, mdl = _admin_default()
            requested = f"{prov}/{mdl}" if prov else mdl
            source_of_choice = "administrator default"

    provider, model = parse_model_id(requested)
    if not provider:
        prov, mdl = _admin_default()
        provider, model = prov, mdl
        requested = f"{prov}/{mdl}"

    # ---- availability + entitlement ----
    available, reason, cred_source = _availability(principal, provider, model)
    decision = ent.evaluate(principal, provider, model, credential_source=cred_source)

    if available and decision.allowed:
        return Resolution(
            ok=True,
            requested_model=requested,
            resolved_model=f"{provider}/{model}",
            provider=provider,
            model_name=model,
            credential_source=cred_source,
            routing_reason=f"{source_of_choice} · permitted by entitlement",
            entitlement_source=decision.entitlement_source,
            plan=decision.plan,
            kwargs=_build_kwargs(provider, model, _resolve_credential(principal, provider)[0]),
        )

    # ---- no silent fallback: report the real reason ----
    code = "model_unavailable" if not available else "model_not_entitled"
    message = reason or decision.reason

    enabled, chain = _fallback_enabled()
    if enabled and chain:
        for candidate in chain:
            c_prov, c_model = parse_model_id(candidate)
            if not c_prov or candidate == f"{provider}/{model}":
                continue
            c_avail, _c_reason, c_source = _availability(principal, c_prov, c_model)
            c_decision = ent.evaluate(principal, c_prov, c_model, credential_source=c_source)
            if c_avail and c_decision.allowed:
                return Resolution(
                    ok=True,
                    requested_model=requested,
                    resolved_model=f"{c_prov}/{c_model}",
                    provider=c_prov,
                    model_name=c_model,
                    credential_source=c_source,
                    routing_reason=(
                        f"fallback from '{requested}' ({message}); "
                        f"actual model '{c_prov}/{c_model}' disclosed"
                    ),
                    entitlement_source=c_decision.entitlement_source,
                    plan=c_decision.plan,
                    fallback_used=True,
                    kwargs=_build_kwargs(c_prov, c_model, _resolve_credential(principal, c_prov)[0]),
                )

    return Resolution(
        ok=False,
        requested_model=requested,
        resolved_model=None,
        provider=provider,
        model_name=model,
        credential_source=cred_source,
        routing_reason=f"{source_of_choice} · denied",
        entitlement_source=decision.entitlement_source,
        plan=decision.plan,
        error=message,
        error_code=code,
    )
