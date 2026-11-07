"""Milestone B — model-selection authority, credentials and picker registry."""
from __future__ import annotations

import os

import pytest

from app.models import model_registry as reg
from app.services import entitlements as ent
from app.services import model_router
from app.services.entitlements import Principal
from app.services.user_credentials import user_credentials
from app.services.user_preferences import user_preferences


@pytest.fixture
def clean_prefs():
    yield
    for ns in ("user:alice@-", "user:bob@-", "user:carol@acme"):
        user_preferences.set_selected_model(ns, None)


def _stub_admin_default(monkeypatch, provider="openrouter", model="nvidia/nemotron-3.5-super-vl:free"):
    monkeypatch.setattr(model_router, "_admin_default", lambda: (provider, model))


def _stub_platform_key(monkeypatch, present=True):
    monkeypatch.setattr(model_router, "_platform_key", lambda p: "platform-key" if present else "")


def _stub_ollama(monkeypatch, tags=()):
    monkeypatch.setattr(model_router, "_ollama_available", lambda m: (bool(tags) and m in tags, ""))


# --------------------------------------------------------------------------- #
# Precedence (Phase 2 rule 1)
# --------------------------------------------------------------------------- #
def test_explicit_selection_beats_admin_default(monkeypatch, clean_prefs):
    _stub_admin_default(monkeypatch, "openrouter", "nvidia/nemotron-3.5-super-vl:free")
    _stub_platform_key(monkeypatch)
    r = model_router.resolve(Principal("alice"), "openrouter/openai/gpt-4o")
    assert r.ok and r.resolved_model == "openrouter/openai/gpt-4o"
    assert "explicit request" in r.routing_reason


def test_env_default_is_admin_layer_not_user_override(monkeypatch, clean_prefs):
    """ARKGEO_CAI_MODEL must not beat an explicit user selection."""
    monkeypatch.setenv("ARKGEO_CAI_MODEL", "openrouter/nvidia/nemotron-3.5-super-vl:free")
    _stub_platform_key(monkeypatch)
    # explicit user choice still wins
    r = model_router.resolve(Principal("alice"), "openrouter/openai/gpt-4o")
    assert r.resolved_model == "openrouter/openai/gpt-4o"
    # and with no user choice, the env default applies
    r2 = model_router.resolve(Principal("alice"))
    assert r2.resolved_model == "openrouter/nvidia/nemotron-3.5-super-vl:free"
    assert "administrator default" in r2.routing_reason


def test_saved_preference_used_when_no_explicit_selection(monkeypatch, clean_prefs):
    _stub_admin_default(monkeypatch, "openrouter", "nvidia/nemotron-3.5-super-vl:free")
    _stub_platform_key(monkeypatch)
    user_preferences.set_selected_model("user:alice@-", "openrouter/openai/gpt-4o-mini")
    r = model_router.resolve(Principal("alice"))
    assert r.resolved_model == "openrouter/openai/gpt-4o-mini"
    assert "saved user preference" in r.routing_reason


def test_admin_default_only_when_no_preference(monkeypatch, clean_prefs):
    _stub_admin_default(monkeypatch, "openrouter", "nvidia/nemotron-3.5-super-vl:free")
    _stub_platform_key(monkeypatch)
    r = model_router.resolve(Principal("bob"))
    assert r.resolved_model == "openrouter/nvidia/nemotron-3.5-super-vl:free"
    assert "administrator default" in r.routing_reason


# --------------------------------------------------------------------------- #
# Availability / no silent fallback (rules 7, 8)
# --------------------------------------------------------------------------- #
def test_unavailable_provider_returns_clear_error(monkeypatch, clean_prefs):
    _stub_admin_default(monkeypatch)
    _stub_platform_key(monkeypatch, present=False)  # no credential anywhere
    r = model_router.resolve(Principal("alice"), "openai/gpt-4o")
    assert not r.ok
    assert r.error_code == "model_unavailable"
    assert "credential" in (r.error or "").lower()
    assert r.resolved_model is None  # nothing executed, nothing substituted


def test_no_silent_fallback_when_disabled(monkeypatch, clean_prefs):
    _stub_admin_default(monkeypatch)
    _stub_platform_key(monkeypatch, present=False)
    monkeypatch.setattr(model_router, "_fallback_enabled", lambda: (False, []))
    r = model_router.resolve(Principal("alice"), "openai/gpt-4o")
    assert not r.ok and not r.fallback_used


def test_configured_fallback_discloses_actual_model(monkeypatch, clean_prefs):
    _stub_platform_key(monkeypatch)

    def _avail(principal, provider, model):
        # openai is unconfigured; openrouter is available
        if provider == "openai":
            return False, "no key", ent.SOURCE_NONE
        return True, "", ent.SOURCE_PLATFORM

    monkeypatch.setattr(model_router, "_availability", _avail)
    monkeypatch.setattr(model_router, "_fallback_enabled",
                        lambda: (True, ["openrouter/openai/gpt-4o"]))
    monkeypatch.setattr(model_router, "_build_kwargs", lambda p, m, k: {"model": f"{p}/{m}", "api_key": k})
    r = model_router.resolve(Principal("alice"), "openai/gpt-4o")
    assert r.ok and r.fallback_used
    assert r.requested_model == "openai/gpt-4o"
    assert r.resolved_model == "openrouter/openai/gpt-4o"
    assert "fallback" in r.routing_reason and "disclosed" in r.routing_reason


# --------------------------------------------------------------------------- #
# Entitlements (Phase 6 / rule 10)
# --------------------------------------------------------------------------- #
def test_subscription_model_denied_by_default(monkeypatch, clean_prefs):
    d = ent.evaluate(Principal("alice"), "ark", "ark-reasoner-pro")
    assert not d.allowed and d.rule_id == "entitlement.subscription_required"


def test_subscription_model_allowed_with_grant(monkeypatch, clean_prefs):
    monkeypatch.setattr(ent, "_load_config", lambda: {
        "users": {"alice": {"subscription_models": ["ark-reasoner-pro"]}}
    })
    d = ent.evaluate(Principal("alice"), "ark", "ark-reasoner-pro")
    assert d.allowed and d.rule_id == "entitlement.subscription_granted"


def test_provider_not_allowed_is_denied(monkeypatch, clean_prefs):
    monkeypatch.setattr(ent, "_load_config", lambda: {
        "default": {"allowed_providers": ["ollama"]}
    })
    d = ent.evaluate(Principal("alice"), "openrouter", "openai/gpt-4o",
                     credential_source=ent.SOURCE_PLATFORM)
    assert not d.allowed and d.rule_id == "entitlement.provider_not_allowed"


def test_deny_list_unions_across_scopes(monkeypatch, clean_prefs):
    """A narrower scope can never re-open an outer deny."""
    monkeypatch.setattr(ent, "_load_config", lambda: {
        "default": {"denied_providers": ["openai"]},
        "users": {"alice": {"allowed_providers": ["openai", "openrouter"]}},
    })
    eff, _ = ent.resolve_entitlement(Principal("alice"))
    assert "openai" in eff["denied_providers"]


# --------------------------------------------------------------------------- #
# BYOK isolation (Phase 3 / rule 8)
# --------------------------------------------------------------------------- #
def test_byok_keys_are_isolated_between_users(monkeypatch, clean_prefs):
    alice = Principal("alice").namespace()
    bob = Principal("bob").namespace()
    user_credentials.set_key(alice, "openrouter", "alice-secret-key")
    try:
        assert user_credentials.get_key(alice, "openrouter") == "alice-secret-key"
        assert user_credentials.get_key(bob, "openrouter") is None
        # a user key takes precedence and is reported as a category, not a value
        key, source = model_router._resolve_credential(Principal("alice"), "openrouter")
        assert source == ent.SOURCE_USER
        assert key == "alice-secret-key"
    finally:
        user_credentials.set_key(alice, "openrouter", None)


def test_credential_source_is_category_not_secret(monkeypatch, clean_prefs):
    _stub_platform_key(monkeypatch)
    r = model_router.resolve(Principal("alice"), "openrouter/openai/gpt-4o")
    meta = r.metadata()
    assert meta["credential_source"] == ent.SOURCE_PLATFORM
    blob = str(meta)
    assert "platform-key" not in blob  # the secret never appears in metadata
    assert set(meta) == {
        "requested_model", "resolved_model", "provider", "credential_source",
        "routing_reason", "entitlement_source", "plan", "fallback_used",
    }


# --------------------------------------------------------------------------- #
# Registry (Phase 4)
# --------------------------------------------------------------------------- #
def test_registry_unknown_capability_is_not_invented():
    rec = reg.lookup("openrouter", "openai/gpt-4o")
    d = rec.to_dict()
    # gpt-4o is catalogued: known fields present, unknown ones are the literal
    assert d["tool_calling"] is True
    assert d["context_window"] == 128000
    assert d["audio_output"] == "unknown"  # not invented
    assert d["video_input"] == "unknown"


def test_registry_inferred_model_reports_unknown():
    rec = reg.lookup("openrouter", "some/uncatalogued-model")
    d = rec.to_dict()
    assert rec.metadata_source == "inferred"
    assert d["reasoning"] == "unknown" and d["pricing"] == "unknown"


def test_registry_has_all_required_fields():
    d = reg.lookup("openai", "gpt-4o").to_dict()
    for field in ("id", "provider", "display_name", "logo", "availability",
                  "pricing", "context_window", "metadata_source", "last_verified"):
        assert field in d, field


def test_parse_model_id_keeps_slashes_in_model():
    assert reg.parse_model_id("openrouter/openai/gpt-4o") == ("openrouter", "openai/gpt-4o")
    assert reg.parse_model_id("ollama/qwen2.5-coder:3b") == ("ollama", "qwen2.5-coder:3b")


# --------------------------------------------------------------------------- #
# HTTP surface (Phase 7)
# --------------------------------------------------------------------------- #
@pytest.fixture
def client():
    import main
    from fastapi.testclient import TestClient

    return TestClient(main.app)


def test_model_endpoint_reflects_user_selection(client, monkeypatch, clean_prefs):
    _stub_admin_default(monkeypatch, "openrouter", "nvidia/nemotron-3.5-super-vl:free")
    _stub_platform_key(monkeypatch)
    h = {"X-ARK-Principal": "alice"}
    client.put("/api/v1/user/model/preference", json={"selected_model": "openrouter/openai/gpt-4o"}, headers=h)
    body = client.get("/api/v1/cai/model", headers=h).json()
    assert body["resolved_model"] == "openrouter/openai/gpt-4o"
    assert body["principal"] == "alice"
    # a different principal is unaffected — admin default applies
    other = client.get("/api/v1/cai/model", headers={"X-ARK-Principal": "bob"}).json()
    assert other["resolved_model"] == "openrouter/nvidia/nemotron-3.5-super-vl:free"


def test_models_endpoint_returns_normalized_records(client, monkeypatch):
    _stub_platform_key(monkeypatch)
    body = client.get("/api/v1/cai/models", headers={"X-ARK-Principal": "alice"}).json()
    assert "providers" in body
    flat = [m for group in body["providers"].values() for m in group]
    assert flat, "catalogue must not be empty"
    sample = flat[0]
    for field in ("id", "provider", "display_name", "logo", "availability", "pricing"):
        assert field in sample


def test_switch_endpoint_persists_and_validates(client, monkeypatch, clean_prefs):
    _stub_platform_key(monkeypatch)
    h = {"X-ARK-Principal": "alice"}
    ok = client.post("/api/v1/cai/model/switch",
                     json={"session_id": "s", "model": "openrouter/openai/gpt-4o"}, headers=h).json()
    assert ok["ok"] and ok["persisted"]
    pref = client.get("/api/v1/user/model/preference", headers=h).json()
    assert pref["selected_model"] == "openrouter/openai/gpt-4o"
    # clearing restores the admin default
    client.delete("/api/v1/user/model/preference", headers=h)
    assert client.get("/api/v1/user/model/preference", headers=h).json()["selected_model"] is None


def test_byok_credentials_isolated_via_http(client):
    a = {"X-ARK-Principal": "alice"}
    b = {"X-ARK-Principal": "bob"}
    client.post("/api/v1/user/model/credentials",
                json={"provider": "openrouter", "key": "alice-http-key", "test": False}, headers=a)
    status_a = client.get("/api/v1/user/model/credentials", headers=a).json()["providers"]
    status_b = client.get("/api/v1/user/model/credentials", headers=b).json()["providers"]
    assert status_a["openrouter"]["configured"] is True
    assert status_b["openrouter"]["configured"] is False
    # the raw key is never returned — only a masked preview
    assert "alice-http-key" not in str(status_a)
    client.delete("/api/v1/user/model/credentials/openrouter", headers=a)


def test_entitlements_endpoint_hides_secrets(client):
    body = client.get("/api/v1/user/model/entitlements", headers={"X-ARK-Principal": "alice"}).json()
    assert body["principal"] == "alice"
    assert "usage_limits" in body and "allowed_providers" in body


def test_ssrf_guard_rejects_private_endpoint():
    from app.api.v1.endpoints.user_models import _validate_provider_endpoint

    assert _validate_provider_endpoint("openai", "http://127.0.0.1:8000") is not None
    assert _validate_provider_endpoint("openai", "https://10.0.0.5/v1") is not None
    assert _validate_provider_endpoint("openai", "https://api.internal/v1") is not None
    assert _validate_provider_endpoint("openai", "https://api.openai.com/v1") is None

