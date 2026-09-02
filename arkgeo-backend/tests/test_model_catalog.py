"""Model catalog tests — live fetchers + curated whitelist + endpoint.

The live fetchers are exercised against respx-mocked provider endpoints
(never real network).  The HuggingFace catalog is curated on-file and needs
no network at all.  All fetchers are best-effort: a failed fetch reports
``source == "error"`` and never raises.
"""
import asyncio
import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from main import app
from app.api.v1.endpoints.settings import admin_login
from app.core.config import settings
from app.services.model_catalog import (
    HF_CURATED_MODELS,
    MODEL_PROVIDERS,
    fetch_models,
)

client = TestClient(app)


def _admin_token() -> str:
    resp = client.post(
        "/api/v1/admin/login",
        json={"username": settings.admin_username, "password": "arkgeo-admin"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# Curated HuggingFace whitelist (no network)
# --------------------------------------------------------------------------- #
def test_hf_catalog_is_curated_and_matches_whitelist():
    out = asyncio.run(fetch_models("huggingface"))
    assert out["source"] == "curated"
    assert out["latency_ms"] == 0
    assert out["models"] == HF_CURATED_MODELS
    assert len(out["models"]) == len(set(out["models"]))
    for mid in out["models"]:
        assert "/" in mid, "HF model ids are org/Model-Name"


# --------------------------------------------------------------------------- #
# Live fetchers (respx-mocked)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_ollama_catalog_parses_tags():
    async with respx.mock() as mock:
        mock.get("http://localhost:11434/api/tags").mock(
            return_value=httpx.Response(200, json={
                "models": [
                    {"name": "qwen2.5-coder:3b"},
                    {"name": "llama3.2-vision:latest"},
                    {"name": "qwen2.5-coder:3b"},  # dup — must be dropped
                ],
            }),
        )
        out = await fetch_models("ollama", base_url="http://localhost:11434")
    assert out["source"] == "live"
    assert out["models"] == ["llama3.2-vision:latest", "qwen2.5-coder:3b"]
    assert "2 models" in out["detail"]


@pytest.mark.asyncio
async def test_openai_catalog_sends_bearer_and_parses():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer sk-test"
        return httpx.Response(200, json={
            "data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}, {"id": "gpt-4o"}],
        })

    async with respx.mock() as mock:
        mock.get("https://api.openai.com/v1/models").mock(side_effect=handler)
        out = await fetch_models("openai", api_key="sk-test")
    assert out["source"] == "live"
    assert out["models"] == ["gpt-4o", "gpt-4o-mini"]


@pytest.mark.asyncio
async def test_gemini_catalog_strips_models_prefix():
    async with respx.mock() as mock:
        mock.get("https://generativelanguage.googleapis.com/v1beta/models").mock(
            return_value=httpx.Response(200, json={
                "models": [
                    {"name": "models/gemini-2.5-pro"},
                    {"name": "models/gemini-2.5-flash"},
                ],
            }),
        )
        out = await fetch_models("gemini", api_key="ai-test")
    assert out["source"] == "live"
    assert out["models"] == ["gemini-2.5-flash", "gemini-2.5-pro"]


@pytest.mark.asyncio
async def test_anthropic_catalog_sends_key_and_version():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "ant-test"
        assert request.headers["anthropic-version"] == "2023-06-01"
        return httpx.Response(200, json={
            "data": [{"id": "claude-3-7-sonnet-20250219"}, {"id": "claude-sonnet-4-20250514"}],
        })

    async with respx.mock() as mock:
        mock.get("https://api.anthropic.com/v1/models").mock(side_effect=handler)
        out = await fetch_models("anthropic", api_key="ant-test")
    assert out["source"] == "live"
    assert any("claude-3-7-sonnet" in m for m in out["models"])


@pytest.mark.asyncio
async def test_openrouter_catalog_is_public():
    async with respx.mock() as mock:
        mock.get("https://openrouter.ai/api/v1/models").mock(
            return_value=httpx.Response(200, json={
                "data": [{"id": "openai/gpt-4o"}, {"id": "anthropic/claude-3.5-sonnet"}],
            }),
        )
        out = await fetch_models("openrouter")  # no key — public catalog
    assert out["source"] == "live"
    assert "openai/gpt-4o" in out["models"]


# --------------------------------------------------------------------------- #
# Failure modes — best-effort, never raise
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_http_error_reports_error_source():
    async with respx.mock() as mock:
        mock.get("https://api.openai.com/v1/models").mock(return_value=httpx.Response(401))
        out = await fetch_models("openai", api_key="bad")
    assert out["source"] == "error"
    assert out["models"] == []
    assert "401" in out["detail"]


@pytest.mark.asyncio
async def test_network_error_never_raises():
    async with respx.mock() as mock:
        mock.get("https://api.openai.com/v1/models").mock(side_effect=httpx.ConnectError("boom"))
        out = await fetch_models("openai", api_key="sk-test")
    assert out["source"] == "error"
    assert out["models"] == []
    assert "Connection failed" in out["detail"]


@pytest.mark.asyncio
async def test_unknown_provider_reports_error():
    out = await fetch_models("not-a-provider")
    assert out["source"] == "error"
    assert "No model catalog" in out["detail"]


# --------------------------------------------------------------------------- #
# Endpoint wiring
# --------------------------------------------------------------------------- #
def test_gateway_models_requires_jwt():
    resp = client.get("/api/v1/admin/gateway/models", params={"provider": "huggingface"})
    assert resp.status_code == 401


def test_gateway_models_rejects_unknown_provider(token=_admin_token()):
    resp = client.get("/api/v1/admin/gateway/models",
                      params={"provider": "nope"}, headers=_auth(token))
    assert resp.status_code == 422


def test_gateway_models_returns_curated_hf(token=_admin_token()):
    resp = client.get("/api/v1/admin/gateway/models",
                      params={"provider": "huggingface"}, headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "huggingface"
    assert body["source"] == "curated"
    assert body["models"] == HF_CURATED_MODELS


def test_gateway_models_accepts_any_model_provider(token=_admin_token()):
    for provider in MODEL_PROVIDERS:
        resp = client.get("/api/v1/admin/gateway/models",
                          params={"provider": provider}, headers=_auth(token))
        assert resp.status_code == 200, f"{provider} -> {resp.text}"
        assert "models" in resp.json()
