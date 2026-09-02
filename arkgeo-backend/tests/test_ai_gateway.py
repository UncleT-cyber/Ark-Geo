"""AIGateway — unified AI provider gateway tests.

Covers the cloud → local Ollama → offline cascade, vision payload routing,
the status surface (``cloud`` / ``local_ollama`` / ``offline``), and the
``GET /api/v1/ai/status`` endpoint.  All provider legs are monkeypatched so
no test ever touches the network or the host's key store.
"""
import asyncio

import pytest
from unittest.mock import AsyncMock

from app.services.ai_gateway import GenerationResult, ai_gateway


def _reset_caches() -> None:
    ai_gateway._status_cache = {"ts": 0.0, "data": None}
    ai_gateway._ollama_cache = {"ts": 0.0, "models": []}


def _gw(**overrides):
    """Minimal gateway-store shape used to drive the vision toggle + rotator."""
    base = {
        "active_llm_provider": "openai",
        "ollama_url": "http://localhost:11434",
        "ollama_model": "llama3.2-vision:latest",
        "vision_enabled": True,
        "task_models": {"terminal": "", "vision_imint": ""},
    }
    base.update(overrides)
    return base


def _hf_gw(model: str):
    """Gateway store with a configured HuggingFace model."""
    return _gw(active_llm_provider="huggingface", huggingface_model=model)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    _reset_caches()
    # No cloud keys by default; no local models by default.
    monkeypatch.setattr(ai_gateway, "_cloud_key", lambda provider: "")
    monkeypatch.setattr(ai_gateway, "_ollama_models_sync", lambda: [])
    yield
    _reset_caches()


# --------------------------------------------------------------------------- #
# Cascade
# --------------------------------------------------------------------------- #
class TestCascade:
    @pytest.mark.asyncio
    async def test_cloud_first_when_key_present(self, monkeypatch):
        async def fake_cloud(provider, *a, **k):
            if provider == "openai":
                return GenerationResult("hello", "openai", "gpt-4o", 10, "HTTP 200")
            return None

        async def fake_ollama(*a, **k):
            return GenerationResult("local", "ollama", "qwen2.5-coder:3b", 5, "local Ollama")

        monkeypatch.setattr(ai_gateway, "_cloud_call", fake_cloud)
        monkeypatch.setattr(ai_gateway, "_ollama_call", fake_ollama)

        res = await ai_gateway.generate_completion("hi")
        assert res.content == "hello"
        assert res.provider == "openai"
        assert res.model == "gpt-4o"

    @pytest.mark.asyncio
    async def test_falls_back_to_ollama_when_cloud_fails(self, monkeypatch):
        async def fake_cloud(provider, *a, **k):
            return None

        async def fake_ollama(*a, **k):
            return GenerationResult("local", "ollama", "qwen2.5-coder:3b", 5, "local Ollama")

        monkeypatch.setattr(ai_gateway, "_cloud_call", fake_cloud)
        monkeypatch.setattr(ai_gateway, "_ollama_call", fake_ollama)

        res = await ai_gateway.generate_completion("hi")
        assert res.provider == "ollama"
        assert res.content == "local"

    @pytest.mark.asyncio
    async def test_offline_when_nothing_reachable(self, monkeypatch):
        monkeypatch.setattr(ai_gateway, "_cloud_call", AsyncMock(return_value=None))
        monkeypatch.setattr(ai_gateway, "_ollama_call", AsyncMock(return_value=None))

        res = await ai_gateway.generate_completion("hi")
        assert res.content is None
        assert res.provider == "offline"
        assert res.detail

    @pytest.mark.asyncio
    async def test_local_first_when_active_provider_is_ollama(self, monkeypatch):
        """When the admin selected ollama as the active provider, the local
        runtime is attempted before any cloud provider."""
        monkeypatch.setattr(
            "app.services.admin_store.admin_store.get_gateway",
            lambda: {
                "active_llm_provider": "ollama",
                "ollama_url": "http://localhost:11434",
                "ollama_model": "qwen2.5-coder:3b",
                "openai_model": "",
            },
        )
        order = []

        async def fake_ollama(*a, **k):
            order.append("ollama")
            return GenerationResult("local", "ollama", "qwen2.5-coder:3b", 5, "local Ollama")

        async def fake_cloud(provider, *a, **k):
            order.append(provider)
            return None

        monkeypatch.setattr(ai_gateway, "_ollama_call", fake_ollama)
        monkeypatch.setattr(ai_gateway, "_cloud_call", fake_cloud)

        res = await ai_gateway.generate_completion("hi")
        assert res.provider == "ollama"
        assert order[0] == "ollama"

    @pytest.mark.asyncio
    async def test_sync_variant_matches_async(self, monkeypatch):
        async def fake_cloud(provider, *a, **k):
            if provider == "openai":
                return GenerationResult("sync-ok", "openai", "gpt-4o", 10, "HTTP 200")
            return None

        monkeypatch.setattr(ai_gateway, "_cloud_call", fake_cloud)
        monkeypatch.setattr(ai_gateway, "_ollama_call", AsyncMock(return_value=None))

        res = ai_gateway.generate_completion_sync("hi")
        assert res.content == "sync-ok"
        assert res.provider == "openai"


# --------------------------------------------------------------------------- #
# is_configured / has_vision_llm
# --------------------------------------------------------------------------- #
class TestConfigured:
    def test_not_configured_without_keys_or_ollama(self):
        assert ai_gateway.is_configured() is False
        assert ai_gateway.has_vision_llm() is False

    def test_configured_with_cloud_key(self, monkeypatch):
        monkeypatch.setattr(ai_gateway, "_cloud_key", lambda p: "sk-" if p == "openai" else "")
        assert ai_gateway.is_configured() is True
        assert ai_gateway.has_vision_llm() is True

    def test_configured_with_ollama_text_model(self, monkeypatch):
        monkeypatch.setattr(ai_gateway, "_ollama_models_sync", lambda: ["deepseek-r1:7b"])
        assert ai_gateway.is_configured() is True
        # A pure text model is NOT a vision path.
        assert ai_gateway.has_vision_llm() is False

    def test_vision_with_ollama_vision_model(self, monkeypatch):
        monkeypatch.setattr(ai_gateway, "_ollama_models_sync", lambda: ["llava:latest"])
        assert ai_gateway.has_vision_llm() is True

    def test_vision_with_qwen25_coder(self, monkeypatch):
        monkeypatch.setattr(ai_gateway, "_ollama_models_sync", lambda: ["qwen2.5-coder:3b"])
        assert ai_gateway.has_vision_llm() is True

    def test_vision_disabled_gates_has_vision_llm(self, monkeypatch):
        """The vision master switch overrides an installed vision model."""
        monkeypatch.setattr(
            "app.services.admin_store.admin_store.get_gateway",
            lambda: _gw(vision_enabled=False),
        )
        monkeypatch.setattr(ai_gateway, "_ollama_models_sync", lambda: ["llava:latest"])
        assert ai_gateway.has_vision_llm() is False

    def test_has_vision_llm_true_with_hf_qwen2vl(self, monkeypatch):
        """HF configured with a registered Qwen2-VL model is a vision path."""
        monkeypatch.setattr(ai_gateway, "_cloud_key", lambda p: "hf-" if p == "huggingface" else "")
        monkeypatch.setattr(
            "app.services.admin_store.admin_store.get_gateway",
            lambda: _hf_gw("Qwen/Qwen2-VL-7B-Instruct"),
        )
        assert ai_gateway.has_vision_llm() is True

    def test_has_vision_llm_false_with_only_ollama_text_model(self, monkeypatch):
        monkeypatch.setattr(ai_gateway, "_cloud_key", lambda p: "")
        monkeypatch.setattr(ai_gateway, "_ollama_models_sync", lambda: ["deepseek-r1:7b"])
        assert ai_gateway.has_vision_llm() is False


# --------------------------------------------------------------------------- #
# Vision payload routing
# --------------------------------------------------------------------------- #
class TestVisionRouting:
    def test_openai_compat_request_embeds_image_data_uri(self):
        req = ai_gateway._build_cloud_request(
            "openai", "https://api.openai.com/v1", "gpt-4o", "sk-test",
            "analyze", b"\xff\xd8\xff\xe0", "system", True, 0.2,
        )
        messages = req["json"]["messages"]
        user = messages[-1]["content"]
        assert user[0]["type"] == "text"
        assert user[1]["type"] == "image_url"
        assert user[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")

    def test_huggingface_vision_payload_is_image_first_with_json_header(self):
        """Qwen2-VL / HF Inference routers require the image block FIRST and
        the request must carry an explicit JSON Content-Type."""
        req = ai_gateway._build_cloud_request(
            "huggingface", "https://router.huggingface.co/v1", "Qwen/Qwen2-VL-7B-Instruct",
            "hf-test", "analyze", b"\xff\xd8\xff\xe0", None, True, 0.2,
        )
        user = req["json"]["messages"][-1]["content"]
        assert user[0]["type"] == "image_url"
        assert user[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        assert user[1]["type"] == "text"
        assert user[1]["text"] == "analyze"
        assert req["headers"]["Authorization"] == "Bearer hf-test"
        assert req["headers"]["Content-Type"] == "application/json"

    def test_huggingface_text_payload_has_no_image_block(self):
        req = ai_gateway._build_cloud_request(
            "huggingface", "https://router.huggingface.co/v1", "Qwen/Qwen2.5-Coder-7B-Instruct",
            "hf-test", "hello", None, None, False, 0.2,
        )
        assert req["json"]["messages"][-1]["content"] == "hello"
        assert req["headers"]["Content-Type"] == "application/json"

    def test_is_vision_model_registers_qwen_vl_models(self):
        """Qwen2-VL / Qwen2.5-VL are registered vision-capable; text-only
        Qwen2.5-Coder is not."""
        assert ai_gateway._is_vision_model("huggingface", "Qwen/Qwen2-VL-7B-Instruct") is True
        assert ai_gateway._is_vision_model("huggingface", "Qwen/Qwen2.5-VL-7B-Instruct") is True
        assert ai_gateway._is_vision_model("huggingface", "Qwen/Qwen2.5-Coder-7B-Instruct") is False
        assert ai_gateway._is_vision_model("huggingface", "meta-llama/Llama-3.1-8B-Instruct") is False
        # Non-HF providers accept images by default.
        assert ai_gateway._is_vision_model("openai", "gpt-4o-mini") is True

    def test_resolve_model_never_routes_text_only_hf_model_to_images(self, monkeypatch):
        """A text-only configured HF model is replaced by the vision default
        for image payloads instead of 400-ing."""
        monkeypatch.setattr(
            "app.services.admin_store.admin_store.get_gateway",
            lambda: _hf_gw("Qwen/Qwen2.5-Coder-7B-Instruct"),
        )
        assert ai_gateway._resolve_model("huggingface", True) == "Qwen/Qwen2.5-VL-7B-Instruct"
        # Text calls still use the configured model.
        assert ai_gateway._resolve_model("huggingface", False) == "Qwen/Qwen2.5-Coder-7B-Instruct"

    def test_resolve_model_keeps_registered_vision_hf_model(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.admin_store.admin_store.get_gateway",
            lambda: _hf_gw("Qwen/Qwen2-VL-7B-Instruct"),
        )
        assert ai_gateway._resolve_model("huggingface", True) == "Qwen/Qwen2-VL-7B-Instruct"

    def test_ollama_model_resolution_prefers_vision_model(self):
        monkeypatch_none = None  # noqa
        # Configurable vision model installed wins.
        ai_gateway._ollama_cache = {"ts": 0.0, "models": []}
        assert ai_gateway._resolve_ollama_model(["llava:latest", "qwen2.5-coder:3b"], True) == "llava:latest"
        # No vision model → qwen2.5-coder per the ARK local model tier.
        assert ai_gateway._resolve_ollama_model(["deepseek-r1:7b", "qwen2.5-coder:3b"], True) == "qwen2.5-coder:3b"
        # Text call → first installed model.
        assert ai_gateway._resolve_ollama_model(["deepseek-r1:7b"], False) == "deepseek-r1:7b"

    def test_task_models_pin_ollama_roles(self, monkeypatch):
        """The Vision Model Rotator pins per-role Ollama models."""
        monkeypatch.setattr(
            "app.services.admin_store.admin_store.get_gateway",
            lambda: _gw(task_models={"terminal": "deepseek-r1:7b", "vision_imint": "llava:latest"}),
        )
        tags = ["llava:latest", "deepseek-r1:7b", "qwen2.5-coder:3b"]
        assert ai_gateway._resolve_ollama_model(tags, True) == "llava:latest"
        assert ai_gateway._resolve_ollama_model(tags, False) == "deepseek-r1:7b"

    def test_task_model_ignored_when_not_installed(self, monkeypatch):
        """A pinned model that isn't installed must never be emitted — the
        gateway falls back to its own auto-resolution rules."""
        monkeypatch.setattr(
            "app.services.admin_store.admin_store.get_gateway",
            lambda: _gw(task_models={"vision_imint": "not-installed:latest"}),
        )
        tags = ["qwen2.5-coder:3b"]
        assert ai_gateway._resolve_ollama_model(tags, True) == "qwen2.5-coder:3b"

    def test_vision_disabled_ollama_call_refuses_image(self, monkeypatch):
        """With the vision toggle off, image payloads never reach Ollama."""
        monkeypatch.setattr(
            "app.services.admin_store.admin_store.get_gateway",
            lambda: _gw(vision_enabled=False),
        )
        result = asyncio.run(ai_gateway._ollama_call("img", b"image-bytes", None, False, 0.2))
        assert result.content is None
        assert "vision disabled" in result.detail


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #
class TestStatus:
    @pytest.mark.asyncio
    async def test_status_cloud_when_provider_reachable(self, monkeypatch):
        monkeypatch.setattr(ai_gateway, "_cloud_key", lambda p: "sk-" if p == "openai" else "")
        monkeypatch.setattr(
            "app.services.ai_gateway.live_probe",
            AsyncMock(return_value={"valid": True, "detail": "HTTP 200", "latency_ms": 12}),
        )
        monkeypatch.setattr(ai_gateway, "_ollama_tags", AsyncMock(return_value=[]))

        data = await ai_gateway.status()
        assert data["status"] == "cloud"
        assert data["route"]["provider"] == "openai"
        assert data["cloud"]["openai"]["probed"] is True

    @pytest.mark.asyncio
    async def test_status_local_ollama_when_no_cloud(self, monkeypatch):
        monkeypatch.setattr(ai_gateway, "_ollama_tags", AsyncMock(return_value=["qwen2.5-coder:3b"]))

        data = await ai_gateway.status()
        assert data["status"] == "local_ollama"
        assert data["route"]["provider"] == "ollama"
        assert data["ollama"]["models"] == ["qwen2.5-coder:3b"]

    @pytest.mark.asyncio
    async def test_status_offline_when_nothing(self, monkeypatch):
        monkeypatch.setattr(ai_gateway, "_ollama_tags", AsyncMock(return_value=[]))

        data = await ai_gateway.status()
        assert data["status"] == "offline"
        assert data["route"]["provider"] is None

    @pytest.mark.asyncio
    async def test_status_respects_vision_toggle(self, monkeypatch):
        """vision_enabled=False forces vision False and exposes the toggle +
        rotator assignments for the AI & OSINT Gateway panel."""
        monkeypatch.setattr(
            "app.services.admin_store.admin_store.get_gateway",
            lambda: _gw(
                vision_enabled=False,
                task_models={"terminal": "qwen2.5-coder:3b", "vision_imint": ""},
            ),
        )
        monkeypatch.setattr(ai_gateway, "_ollama_tags", AsyncMock(return_value=["llava:latest", "qwen2.5-coder:3b"]))

        data = await ai_gateway.status()
        assert data["vision"] is False
        assert data["vision_enabled"] is False
        assert data["task_models"]["terminal"] == "qwen2.5-coder:3b"
        assert data["task_models"]["vision_imint"] == ""

    @pytest.mark.asyncio
    async def test_status_vision_true_when_enabled_with_vision_model(self, monkeypatch):
        monkeypatch.setattr(ai_gateway, "_ollama_tags", AsyncMock(return_value=["llava:latest"]))

        data = await ai_gateway.status()
        assert data["vision"] is True
        assert data["vision_enabled"] is True
        assert "vision_imint" in data["task_models"]

    @pytest.mark.asyncio
    async def test_status_vision_true_when_hf_qwen2vl_selected(self, monkeypatch):
        """HuggingFace with a registered Qwen2-VL model reports vision: true."""
        monkeypatch.setattr(ai_gateway, "_cloud_key", lambda p: "hf-qwen2vl" if p == "huggingface" else "")
        monkeypatch.setattr(
            "app.services.ai_gateway.live_probe",
            AsyncMock(return_value={"valid": True, "detail": "HTTP 200", "latency_ms": 10}),
        )
        monkeypatch.setattr(
            "app.services.admin_store.admin_store.get_gateway",
            lambda: _hf_gw("Qwen/Qwen2-VL-7B-Instruct"),
        )
        monkeypatch.setattr(ai_gateway, "_ollama_tags", AsyncMock(return_value=[]))

        data = await ai_gateway.status()
        assert data["status"] == "cloud"
        assert data["route"]["provider"] == "huggingface"
        assert data["vision"] is True

    @pytest.mark.asyncio
    async def test_status_vision_false_when_only_ollama_text_model(self, monkeypatch):
        monkeypatch.setattr(ai_gateway, "_ollama_tags", AsyncMock(return_value=["deepseek-r1:7b"]))

        data = await ai_gateway.status()
        assert data["vision"] is False


# --------------------------------------------------------------------------- #
# Endpoint
# --------------------------------------------------------------------------- #
class TestAIStatusEndpoint:
    def test_ai_status_endpoint_contract(self, monkeypatch):
        from fastapi.testclient import TestClient
        from main import app

        monkeypatch.setattr(ai_gateway, "_cloud_key", lambda p: "")
        monkeypatch.setattr(ai_gateway, "_ollama_tags", AsyncMock(return_value=["qwen2.5-coder:3b"]))

        client = TestClient(app)
        resp = client.get("/api/v1/ai/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("cloud", "local_ollama", "offline")
        assert "route" in data and "cloud" in data and "ollama" in data
        assert "openai" in data["cloud"] and "anthropic" in data["cloud"]
        assert data["ollama"]["available"] is True
        assert data["vision"] is True
