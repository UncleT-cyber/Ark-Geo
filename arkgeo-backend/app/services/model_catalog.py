"""Provider model catalogs for the Admin Console.

Backs the unified "Active Provider & Model" selector.  Every provider can
either fetch its model list *live* (Ollama / OpenAI / Gemini / Anthropic /
OpenRouter) or falls back to a curated on-file whitelist (HuggingFace, which
sticks to ``HF_CURATED_MODELS`` — the ARK ISE model tiers).

Like the key probes (:mod:`app.services.key_probe`), this module is strictly
best-effort: it never raises, uses short timeouts, and reports an honest
``source`` + ``detail`` so the UI can explain why a list is live, curated,
or missing.  Keys are read inside the request handler from the encrypted
SettingsStore and used only inside the outgoing request.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT_S = 5.0
_MAX_MODELS = 300

# Providers that expose a model list.  ``ollama`` is the local runtime; the
# cloud LLMs need a configured key (OpenRouter also works without one — the
# public catalog is available unauthenticated).
MODEL_PROVIDERS = ("ollama", "openai", "gemini", "anthropic", "openrouter", "huggingface")

# Per-provider SettingsStore key field used to authenticate a live fetch.
PROVIDER_MODEL_KEY: dict[str, str] = {
    "openai": "llm_api_key",
    "gemini": "gemini_api_key",
    "anthropic": "anthropic_api_key",
    "openrouter": "openrouter_api_key",
    "huggingface": "huggingface_api_key",
}

# Fixed live-catalog endpoints (Ollama + HuggingFace use the configured
# base URL instead).
_MODEL_ENDPOINTS: dict[str, str] = {
    "openai": "https://api.openai.com/v1/models",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models",
    "anthropic": "https://api.anthropic.com/v1/models",
    "openrouter": "https://openrouter.ai/api/v1/models",
}

# Curated HuggingFace Inference Providers whitelist (on-file, authoritative).
# Must stay in sync with the click-to-provision chips in ApiGateway.tsx
# (HF_RECOMMENDED_MODELS).  Kept here as the single backend source of truth
# so the catalog endpoint and the model selector agree.
HF_CURATED_MODELS: list[str] = [
    # Technical & cyber orchestration
    "Qwen/Qwen2.5-Coder-7B-Instruct",
    "Qwen/Qwen2.5-Coder-32B-Instruct",
    "meta-llama/Llama-3.3-70B-Instruct",
    # Speed & high throughput
    "meta-llama/Llama-3.2-3B-Instruct",
    "meta-llama/Meta-Llama-3.1-8B-Instruct",
    # Image intelligence & OSINT
    "Qwen/Qwen2-VL-7B-Instruct",
    "meta-llama/Llama-3.2-11B-Vision-Instruct",
]


def _model_ids(data: dict[str, Any], key: str, *, prefix: str = "") -> list[str]:
    """Extract model id strings from a provider response.

    ``key`` is the field holding the model array; ``prefix`` (e.g. Gemini's
    ``models/``) is stripped from each id.  Order is preserved, dups dropped.
    """
    node = data.get(key)
    if not isinstance(node, list):
        return []
    ids: list[str] = []
    for item in node:
        if not isinstance(item, dict):
            continue
        mid = item.get("id") or item.get("name")
        if not isinstance(mid, str):
            continue
        mid = mid.strip()
        if prefix and mid.startswith(prefix):
            mid = mid[len(prefix):]
        if mid and mid not in ids:
            ids.append(mid)
    return ids


def _normalize(names: list[str]) -> list[str]:
    return sorted(dict.fromkeys(n for n in names if n))[:_MAX_MODELS]


async def _fetch_live(
    provider: str,
    *,
    api_key: str,
    base_url: str,
) -> tuple[list[str], str]:
    """Fetch a provider model list. Returns ``(models, detail)`` — never raises."""
    if provider == "ollama":
        url = (base_url or "http://localhost:11434").rstrip("/") + "/api/tags"
    else:
        url = _MODEL_ENDPOINTS[provider]

    headers: dict[str, str] = {}
    params: dict[str, str] | None = None
    if provider == "openai" or provider == "openrouter":
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
    elif provider == "anthropic":
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
    elif provider == "gemini":
        params = {"key": api_key}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S, follow_redirects=True) as client:
            r = await client.get(url, headers=headers, params=params)
    except Exception as exc:  # noqa: BLE001
        return [], f"Connection failed: {type(exc).__name__}"

    if r.status_code != 200:
        return [], f"HTTP {r.status_code}"
    try:
        data = r.json() or {}
    except Exception:  # noqa: BLE001
        return [], "HTTP 200 (non-JSON body)"

    if provider == "ollama":
        ids = [str(m.get("name", "")).strip() for m in data.get("models", []) if isinstance(m, dict)]
    elif provider == "gemini":
        ids = _model_ids(data, "models", prefix="models/")
    else:
        ids = _model_ids(data, "data")
    return _normalize(ids), f"HTTP {r.status_code}"


async def fetch_models(
    provider: str,
    *,
    api_key: str = "",
    base_url: str = "",
) -> dict[str, Any]:
    """Best-effort model catalog fetch for one provider.

    Returns ``{models, source, detail, latency_ms}``.  ``source`` is
    ``"live"``, ``"curated"`` (HuggingFace whitelist), or ``"error"``.
    Never raises.
    """
    provider = (provider or "").lower().strip()
    started = time.time()
    if provider == "huggingface":
        # Live catalog from the HuggingFace router (free-tier models available
        # at https://router.huggingface.co/v1). Falls back to the curated ARK
        # ISE whitelist if the router is unreachable.
        url = (base_url or "https://router.huggingface.co/v1").rstrip("/") + "/models"
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_S, follow_redirects=True) as client:
                r = await client.get(url, headers=headers)
            if r.status_code == 200:
                data = r.json() or {}
                ids = _model_ids(data, "data") or _model_ids(data, "models")
                if ids:
                    return {
                        "models": _normalize(ids),
                        "source": "live",
                        "detail": f"HuggingFace router — {len(ids)} models",
                        "latency_ms": round((time.time() - started) * 1000),
                    }
        except Exception as exc:  # noqa: BLE001
            logger.warning("HuggingFace live model fetch failed: %s", exc)
        return {
            "models": list(HF_CURATED_MODELS),
            "source": "curated",
            "detail": f"Curated on-file whitelist — {len(HF_CURATED_MODELS)} ARK ISE models",
            "latency_ms": round((time.time() - started) * 1000),
        }
    if provider != "ollama" and provider not in _MODEL_ENDPOINTS:
        return {
            "models": [],
            "source": "error",
            "detail": f"No model catalog for provider '{provider}'",
            "latency_ms": round((time.time() - started) * 1000),
        }

    models, detail = await _fetch_live(provider, api_key=api_key, base_url=base_url)
    latency = round((time.time() - started) * 1000)
    if not models:
        return {"models": [], "source": "error", "detail": detail, "latency_ms": latency}
    return {
        "models": models,
        "source": "live",
        "detail": f"{detail} — {len(models)} models",
        "latency_ms": latency,
    }
