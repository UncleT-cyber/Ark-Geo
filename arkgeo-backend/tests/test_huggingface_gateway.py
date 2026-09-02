"""HuggingFace gateway arm tests.

Covers the OpenAI-compatible client (chat completions / availability probe),
the provider key probe wiring (hf_ token → /v1/models), and the admin
provisioning resolver that builds a gateway from stored config + token.
"""
import httpx
import pytest
import respx

from app.agent.model_gateway import (
    HUGGINGFACE_DEFAULT_URL,
    HuggingFaceGateway,
    resolve_huggingface_gateway,
)


class TestHuggingFaceGateway:
    def test_default_spec_is_remote_hf(self):
        gw = HuggingFaceGateway(model_id="Qwen/Qwen3-8B", api_key="hf_test")
        spec = gw.default_spec()
        assert spec.provider.value == "huggingface"
        assert spec.local is False
        assert spec.offline_ok is False
        assert spec.endpoint == "Qwen/Qwen3-8B"

    @pytest.mark.asyncio
    async def test_chat_parses_openai_response(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["Authorization"] == "Bearer hf_test"
            assert "/chat/completions" in str(request.url)
            return httpx.Response(200, json={
                "choices": [{"message": {"content": '{"ok": true}'}}],
            })

        gw = HuggingFaceGateway(model_id="Qwen/Qwen3-8B", api_key="hf_test")
        async with respx.mock() as mock:
            mock.route(method="POST", host="router.huggingface.co").mock(side_effect=handler)
            out = await gw.chat([{"role": "user", "content": "hi"}], json_mode=True)
        assert out == '{"ok": true}'

    @pytest.mark.asyncio
    async def test_chat_degrades_on_http_error(self):
        gw = HuggingFaceGateway(model_id="Qwen/Qwen3-8B", api_key="hf_test")
        async with respx.mock() as mock:
            mock.post(url__startswith=HUGGINGFACE_DEFAULT_URL).mock(return_value=httpx.Response(401))
            out = await gw.chat([{"role": "user", "content": "hi"}])
        assert out is None

    @pytest.mark.asyncio
    async def test_chat_degrades_on_network_error(self):
        gw = HuggingFaceGateway(model_id="Qwen/Qwen3-8B", api_key="hf_test")
        async with respx.mock() as mock:
            mock.post(url__startswith=HUGGINGFACE_DEFAULT_URL).mock(side_effect=httpx.ConnectError("boom"))
            out = await gw.chat([{"role": "user", "content": "hi"}])
        assert out is None

    @pytest.mark.asyncio
    async def test_available_requires_token_and_200(self):
        gw = HuggingFaceGateway(model_id="Qwen/Qwen3-8B", api_key="hf_test")
        async with respx.mock() as mock:
            mock.get(url__startswith=HUGGINGFACE_DEFAULT_URL).mock(return_value=httpx.Response(200))
            assert await gw.available() is True
            mock.get(url__startswith=HUGGINGFACE_DEFAULT_URL).mock(return_value=httpx.Response(401))
            assert await gw.available() is False


class TestResolveHuggingFaceGateway:
    def test_returns_none_without_model(self, monkeypatch):
        class FakeStore:
            def get_gateway(self):
                return {"huggingface_model": "", "huggingface_url": "https://router.huggingface.co/v1"}

        import sys
        import types

        fakes = types.ModuleType("fakestores")
        fakes.admin_store = FakeStore()
        fakes.settings_store = types.SimpleNamespace(get_key=lambda _: "hf_test")
        monkeypatch.setitem(sys.modules, "app.services.admin_store", fakes)
        monkeypatch.setitem(sys.modules, "app.services.settings_store", fakes)
        assert resolve_huggingface_gateway() is None

    def test_returns_none_without_token(self, monkeypatch):
        import sys
        import types

        class FakeStore:
            def get_gateway(self):
                return {"huggingface_model": "Qwen/Qwen3-8B", "huggingface_url": "https://router.huggingface.co/v1"}

        fakes = types.ModuleType("fakestores")
        fakes.admin_store = FakeStore()
        fakes.settings_store = types.SimpleNamespace(get_key=lambda _: "")
        monkeypatch.setitem(sys.modules, "app.services.admin_store", fakes)
        monkeypatch.setitem(sys.modules, "app.services.settings_store", fakes)
        assert resolve_huggingface_gateway() is None

    def test_builds_gateway_when_provisioned(self, monkeypatch):
        import sys
        import types

        class FakeStore:
            def get_gateway(self):
                return {"huggingface_model": "Qwen/Qwen3-8B", "huggingface_url": "https://router.huggingface.co/v1"}

        fakes = types.ModuleType("fakestores")
        fakes.admin_store = FakeStore()
        fakes.settings_store = types.SimpleNamespace(get_key=lambda _: "hf_test")
        monkeypatch.setitem(sys.modules, "app.services.admin_store", fakes)
        monkeypatch.setitem(sys.modules, "app.services.settings_store", fakes)
        gw = resolve_huggingface_gateway()
        assert gw is not None
        assert gw.default_model == "Qwen/Qwen3-8B"
        assert gw.api_key == "hf_test"
