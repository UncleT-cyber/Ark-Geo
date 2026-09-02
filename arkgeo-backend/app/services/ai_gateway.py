"""Unified AI Provider Gateway — the single abstraction every module uses
to talk to a model.

Image Intelligence / Vision (brain clue extractors + vision ensemble),
Terminal Orchestrator, Network Discovery & Threat Ops, and OSINT & Synthesis
Reports all resolve completions through :class:`AIGateway`.  It implements
the fallback cascade:

    cloud providers (configured + reachable)  ->  local Ollama  ->  offline

Vision payloads are routed to a vision-capable model at every hop:

- OpenAI-compatible providers (OpenAI / OpenRouter / HuggingFace) receive an
  ``image_url`` data-URI content block;
- Gemini and Anthropic receive their native image blocks;
- local Ollama receives the image via the ``images`` message field, routed to
  the admin-configured vision model first (default ``llama3.2-vision:latest``),
  then any installed vision-capable model, then ``qwen2.5-coder`` (the ARK
  local model tier).  If no installed model can accept the image the call
  fails *honestly* — it never degrades into a fabricated text-only analysis.

Every call here is **best-effort and never raises**.  A failed provider
degrades to the next one and ultimately to ``None`` so the deterministic
fallbacks in the callers stay authoritative.  That is the same structural
invariant as the planner gateway (unit 09): the AI orchestrates the
deterministic pipeline; it is never a hard dependency of it.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.services.key_probe import live_probe

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_BASE = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "qwen2.5-coder:3b"
DEFAULT_VISION_MODEL = "llama3.2-vision:latest"
HUGGINGFACE_DEFAULT_URL = "https://router.huggingface.co/v1"

# Order of the cloud fallback cascade (after the admin-active provider).
CLOUD_PROVIDERS = ("openai", "anthropic", "gemini", "openrouter", "huggingface")

# provider -> (settings-store key, base URL, default text model)
_PROVIDER_DEFAULTS: dict[str, tuple[str, str, str]] = {
    "openai": ("llm_api_key", settings.llm_base_url, "gpt-4o"),
    "anthropic": ("anthropic_api_key", settings.anthropic_api_url, "claude-3-5-sonnet-latest"),
    "gemini": ("gemini_api_key", settings.gemini_api_url, "gemini-2.0-flash"),
    "openrouter": ("openrouter_api_key", "https://openrouter.ai/api/v1", "openai/gpt-4o-mini"),
    "huggingface": ("huggingface_api_key", HUGGINGFACE_DEFAULT_URL, "Qwen/Qwen2.5-Coder-7B-Instruct"),
}

# provider -> default model used when an image is attached and no explicit
# model was provisioned through the Admin Console.
_VISION_DEFAULTS: dict[str, str] = {
    "openai": "gpt-4o",
    "anthropic": "claude-3-5-sonnet-latest",
    "gemini": "gemini-2.0-flash",
    "openrouter": "openai/gpt-4o-mini",
    "huggingface": "Qwen/Qwen2.5-VL-7B-Instruct",
}

# HuggingFace models explicitly registered as multi-modal vision capable.
# Only ids in this set (or ids carrying a vision marker such as ``-VL-`` /
# ``Vision``) may be selected for an image payload.  A text-only configured
# model (e.g. ``Qwen/Qwen2.5-Coder-7B-Instruct``) must never receive an
# image — the gateway falls back to a registered vision model instead of
# 400-ing on a payload the model cannot accept.
_HF_VISION_MODELS: frozenset[str] = frozenset({
    "Qwen/Qwen2-VL-7B-Instruct",
    "Qwen/Qwen2-VL-72B-Instruct",
    "Qwen/Qwen2.5-VL-7B-Instruct",
    "Qwen/Qwen2.5-VL-72B-Instruct",
    "Qwen/Qwen3-VL-30B-A3B-Instruct",
    "meta-llama/Llama-3.2-11B-Vision-Instruct",
    "meta-llama/Llama-3.2-90B-Vision-Instruct",
    "CohereLabs/aya-vision-32b",
    "CohereLabs/command-a-vision-07-2025",
})

# Models whose name indicates vision capability (local Ollama routing).
_VISION_NAME_RE = re.compile(
    r"(vision|llava|minicpm-v|qwen2-vl|qwen2\.5-vl|qwen2\.5-coder|bakllava|moondream|gemma3)",
    re.IGNORECASE,
)

_CLOUD_TIMEOUT_S = 30.0
_OLLAMA_TIMEOUT_S = 90.0
_OLLAMA_PROBE_S = 1.5
_OLLAMA_CACHE_TTL_S = 5.0
_STATUS_CACHE_TTL_S = 10.0

_IMAGE_MEDIA_TYPE = "image/jpeg"


@dataclass
class GenerationResult:
    """Outcome of a gateway completion attempt.

    ``content`` is ``None`` when the provider failed; ``detail`` then carries
    an honest reason so callers / status surfaces can explain the route.
    """

    content: Optional[str]
    provider: str
    model: Optional[str]
    latency_ms: int
    detail: str


class AIGateway:
    """Provider-agnostic completion gateway with cloud → local cascade.

    Reads provider keys from the encrypted SettingsStore (with env/config
    bootstrap fallback) and the admin Model Gateway config (active provider,
    per-provider model, Ollama base URL / model).  All reads are dynamic, so
    keys and model selections take effect without a restart.
    """

    def __init__(self) -> None:
        self._ollama_cache: dict[str, Any] = {"ts": 0.0, "models": []}
        self._status_cache: dict[str, Any] = {"ts": 0.0, "data": None}

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    async def generate_completion(
        self,
        prompt: str,
        image_bytes: Optional[bytes] = None,
        system_prompt: Optional[str] = None,
        json_mode: bool = False,
        temperature: float = 0.2,
    ) -> GenerationResult:
        """Resolve a completion through the full cascade (async)."""
        return await self._complete(
            prompt, system_prompt, image_bytes, json_mode, temperature,
        )

    async def chat(
        self,
        messages: list[dict[str, str]],
        image_bytes: Optional[bytes] = None,
        json_mode: bool = False,
        temperature: float = 0.2,
    ) -> GenerationResult:
        """Message-list variant of :meth:`generate_completion`."""
        system = " ".join(
            m.get("content", "") for m in messages if m.get("role") == "system"
        )
        prompt = " ".join(
            str(m.get("content", "")) for m in messages if m.get("role") != "system"
        )
        return await self._complete(
            prompt, system or None, image_bytes, json_mode, temperature,
        )

    def generate_completion_sync(
        self,
        prompt: str,
        image_bytes: Optional[bytes] = None,
        system_prompt: Optional[str] = None,
        json_mode: bool = False,
        temperature: float = 0.2,
    ) -> GenerationResult:
        """Sync variant for callers that cannot ``await`` (brain extractors).

        Runs the same async cascade in a dedicated event-loop thread, so it is
        safe to call from inside a running event loop.
        """
        return self._run_sync(
            lambda: self.generate_completion(
                prompt, image_bytes=image_bytes, system_prompt=system_prompt,
                json_mode=json_mode, temperature=temperature,
            )
        )

    async def status(self) -> dict[str, Any]:
        """Current runtime route: ``cloud`` | ``local_ollama`` | ``offline``.

        Result is cached for :data:`_STATUS_CACHE_TTL_S` seconds so badge
        polling never hammers the providers.
        """
        now = time.time()
        cached = self._status_cache
        if cached["data"] and (now - cached["ts"]) < _STATUS_CACHE_TTL_S:
            return cached["data"]

        started = time.time()
        cloud: dict[str, dict[str, Any]] = {}
        for provider in CLOUD_PROVIDERS:
            key = self._cloud_key(provider)
            entry: dict[str, Any] = {
                "configured": bool(key),
                "probed": False,
                "detail": "no key" if not key else "key set (not probed)",
                "latency_ms": None,
            }
            if key:
                try:
                    probe = await live_probe(provider, key)
                    entry["probed"] = bool(probe.get("valid"))
                    entry["detail"] = str(probe.get("detail") or "probe failed")
                    entry["latency_ms"] = probe.get("latency_ms")
                except Exception as exc:  # noqa: BLE001 — probe must never raise
                    entry["detail"] = f"probe failed: {type(exc).__name__}"
            cloud[provider] = entry

        ollama_base = self._ollama_base()
        tags = await self._ollama_tags(ollama_base)
        ollama = {
            "available": bool(tags),
            "models": tags,
            "base_url": ollama_base,
        }

        route = self._pick_route(cloud, ollama)
        data = {
            "status": route["status"],
            "route": route,
            "cloud": cloud,
            "ollama": ollama,
            "vision": self._vision_enabled() and (
                self._cloud_vision_available(cloud)
                or any(_VISION_NAME_RE.search(m) for m in tags)
            ),
            "vision_enabled": self._vision_enabled(),
            "task_models": self._gateway_task_models(),
            "latency_ms": round((time.time() - started) * 1000),
        }
        self._status_cache = {"ts": time.time(), "data": data}
        return data

    def _cloud_vision_available(self, cloud: dict[str, dict[str, Any]]) -> bool:
        """True when some configured cloud provider routes image payloads to a
        vision-capable model.

        OpenAI / OpenRouter / Gemini / Anthropic accept images by default, so
        any configured key counts.  HuggingFace is checked against the
        registered vision model set (or the ``-VL-``/``Vision`` marker) using
        the model the gateway would actually resolve for an image call.
        """
        for provider in CLOUD_PROVIDERS:
            if not cloud.get(provider, {}).get("configured"):
                continue
            if provider == "huggingface":
                if self._is_vision_model(provider, self._resolve_model(provider, True)):
                    return True
                continue
            return True
        return False

    def is_configured(self) -> bool:
        """True when any AI path exists: a cloud key or a reachable local
        Ollama runtime with at least one usable model."""
        if any(self._cloud_key(p) for p in CLOUD_PROVIDERS):
            return True
        return bool(self._ollama_models_sync())

    def has_vision_llm(self) -> bool:
        """True when a vision-capable AI path exists (a cloud provider whose
        image routing resolves to a vision-capable model, or a local
        vision-capable model installed in Ollama) *and* the operator has not
        disabled the vision master switch."""
        if not self._vision_enabled():
            return False
        for provider in CLOUD_PROVIDERS:
            if not self._cloud_key(provider):
                continue
            if provider == "huggingface":
                if self._is_vision_model(provider, self._resolve_model(provider, True)):
                    return True
                continue
            return True
        models = self._ollama_models_sync()
        return bool(models) and any(_VISION_NAME_RE.search(m) for m in models)

    # ------------------------------------------------------------------ #
    # Cascade core
    # ------------------------------------------------------------------ #
    async def _complete(
        self,
        prompt: str,
        system_prompt: Optional[str],
        image_bytes: Optional[bytes],
        json_mode: bool,
        temperature: float,
    ) -> GenerationResult:
        started = time.time()
        attempts: list[str] = []
        notes: list[str] = []
        cloud_order, local_first = self._provider_order()

        if local_first:
            attempts.append("ollama")
            ollama_res = await self._ollama_call(
                prompt, image_bytes, system_prompt, json_mode, temperature,
            )
            if ollama_res is not None and ollama_res.content:
                return ollama_res
            notes.append(f"ollama: {ollama_res.detail if ollama_res else 'unavailable'}")

        for provider in cloud_order:
            attempts.append(provider)
            res = await self._cloud_call(
                provider, prompt, image_bytes, system_prompt, json_mode, temperature,
            )
            if res is not None and res.content:
                return res
            notes.append(f"{provider}: {res.detail if res else 'unconfigured'}")

        if not local_first:
            attempts.append("ollama")
            ollama_res = await self._ollama_call(
                prompt, image_bytes, system_prompt, json_mode, temperature,
            )
            if ollama_res is not None and ollama_res.content:
                return ollama_res
            notes.append(f"ollama: {ollama_res.detail if ollama_res else 'unavailable'}")

        return GenerationResult(
            content=None,
            provider="offline",
            model=None,
            latency_ms=round((time.time() - started) * 1000),
            detail="; ".join(notes) or "no provider attempted",
        )

    def _provider_order(self) -> tuple[list[str], bool]:
        """Return ``(cloud_order, local_first)``.

        The admin-active provider is tried first.  When the admin selected
        ``ollama`` as the active provider the local runtime is attempted
        before the cloud providers.
        """
        from app.services.admin_store import admin_store
        active = ((admin_store.get_gateway().get("active_llm_provider")) or "openai").strip().lower()
        if active == "ollama":
            return list(CLOUD_PROVIDERS), True
        rest = [p for p in CLOUD_PROVIDERS if p != active]
        return [active] + rest, False

    # ------------------------------------------------------------------ #
    # Cloud leg
    # ------------------------------------------------------------------ #
    def _cloud_key(self, provider: str) -> str:
        key_name, _, _ = _PROVIDER_DEFAULTS.get(provider, ("", "", ""))
        if not key_name:
            return ""
        from app.services.settings_store import settings_store
        return (settings_store.get_key(key_name) or getattr(settings, key_name, None) or "").strip()

    def _cloud_base(self, provider: str) -> str:
        if provider == "huggingface":
            from app.services.admin_store import admin_store
            gw = admin_store.get_gateway()
            return (gw.get("huggingface_url") or HUGGINGFACE_DEFAULT_URL).rstrip("/")
        _, base, _ = _PROVIDER_DEFAULTS.get(provider, ("", "", ""))
        return (base or "").rstrip("/")

    def _resolve_model(self, provider: str, has_image: bool) -> str:
        from app.services.admin_store import admin_store
        gw = admin_store.get_gateway()
        field = {
            "openai": "openai_model",
            "anthropic": "anthropic_model",
            "gemini": "gemini_model",
            "openrouter": "openrouter_model",
            "huggingface": "huggingface_model",
        }.get(provider)
        provisioned = (gw.get(field) or "").strip() if field else ""
        if provider == "openai":
            provisioned = provisioned or (settings.llm_model or "").strip() or "gpt-4o"
        _, _, default = _PROVIDER_DEFAULTS.get(provider, ("", "", ""))
        if has_image:
            if provisioned and self._is_vision_model(provider, provisioned):
                return provisioned
            # The configured model cannot accept images (e.g. a text-only
            # HuggingFace model) — fall back to a registered vision model.
            if _VISION_DEFAULTS.get(provider):
                return _VISION_DEFAULTS[provider]
        else:
            # Text / terminal tasks must never be routed to a vision-only
            # model (the HF router rejects it for text generation). Fall back
            # to the provider's text/coder default in that case.
            if provider == "huggingface" and provisioned and self._is_vision_model(provider, provisioned):
                provisioned = ""
        return provisioned or default

    @staticmethod
    def _is_vision_model(provider: str, model: str) -> bool:
        """True when ``model`` accepts multi-modal image payloads.

        OpenAI-compatible / Gemini / Anthropic current models accept images by
        default, so only HuggingFace is checked against the explicit registry
        (or the ``-VL-`` / ``Vision`` id markers).  Text-only HF models such
        as ``Qwen/Qwen2.5-Coder-7B-Instruct`` resolve to ``False``.
        """
        if provider != "huggingface":
            return True
        name = (model or "").strip()
        lowered = name.lower()
        return name in _HF_VISION_MODELS or "-vl" in lowered or "vision" in lowered

    def _build_cloud_request(
        self,
        provider: str,
        base: str,
        model: str,
        key: str,
        prompt: str,
        image_bytes: Optional[bytes],
        system_prompt: Optional[str],
        json_mode: bool,
        temperature: float,
    ) -> Optional[dict[str, Any]]:
        b64 = base64.b64encode(image_bytes).decode() if image_bytes else None

        if provider in ("openai", "openrouter", "huggingface"):
            messages: list[dict[str, Any]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            if b64:
                if provider == "huggingface":
                    # Qwen2-VL / HuggingFace Inference routers expect the
                    # image block FIRST, then the instruction text.  Routing
                    # text-first here is what produces HTTP 400 on models
                    # that validate the multi-modal content order.
                    content_blocks: list[dict[str, Any]] = [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{_IMAGE_MEDIA_TYPE};base64,{b64}"},
                        },
                        {"type": "text", "text": prompt},
                    ]
                else:
                    content_blocks = [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{_IMAGE_MEDIA_TYPE};base64,{b64}"},
                        },
                    ]
                messages.append({"role": "user", "content": content_blocks})
            else:
                messages.append({"role": "user", "content": prompt})
            payload: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "stream": False,
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            headers: dict[str, str] = {"Authorization": f"Bearer {key}"}
            if provider == "huggingface":
                headers["Content-Type"] = "application/json"
            return {
                "url": f"{base}/chat/completions",
                "headers": headers,
                "params": None,
                "json": payload,
            }

        if provider == "anthropic":
            content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
            if b64:
                content.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": _IMAGE_MEDIA_TYPE, "data": b64},
                })
            payload = {
                "model": model,
                "max_tokens": settings.llm_max_tokens,
                "temperature": temperature,
                "messages": [{"role": "user", "content": content}],
            }
            if system_prompt:
                payload["system"] = system_prompt
            return {
                "url": f"{base}/messages",
                "headers": {"x-api-key": key, "anthropic-version": "2023-06-01"},
                "params": None,
                "json": payload,
            }

        if provider == "gemini":
            parts: list[dict[str, Any]] = [{"text": prompt}]
            if b64:
                parts.append({"inline_data": {"mime_type": _IMAGE_MEDIA_TYPE, "data": b64}})
            body: dict[str, Any] = {"contents": [{"role": "user", "parts": parts}]}
            if system_prompt:
                body["system_instruction"] = {"parts": [{"text": system_prompt}]}
            return {
                "url": f"{base}/models/{model}:generateContent",
                "headers": {},
                "params": {"key": key},
                "json": body,
            }

        return None

    @staticmethod
    def _parse_cloud_response(provider: str, r: httpx.Response) -> Optional[str]:
        if r.status_code != 200:
            return None
        try:
            data = r.json()
        except Exception:  # noqa: BLE001 — non-JSON bodies are empty responses
            return None

        if provider in ("openai", "openrouter", "huggingface"):
            choices = data.get("choices") or []
            return (choices[0].get("message") or {}).get("content") if choices else None

        if provider == "anthropic":
            blocks = data.get("content") or []
            text = "".join(
                b.get("text", "") for b in blocks
                if isinstance(b, dict) and b.get("type") == "text"
            )
            return text or None

        if provider == "gemini":
            parts: list[str] = []
            for candidate in data.get("candidates") or []:
                for part in ((candidate.get("content") or {}).get("parts") or []):
                    if isinstance(part, dict) and part.get("text"):
                        parts.append(part["text"])
            return "".join(parts) or None

        return None

    async def _cloud_call(
        self,
        provider: str,
        prompt: str,
        image_bytes: Optional[bytes],
        system_prompt: Optional[str],
        json_mode: bool,
        temperature: float,
    ) -> Optional[GenerationResult]:
        key = self._cloud_key(provider)
        if not key:
            return None
        model = self._resolve_model(provider, image_bytes is not None)
        base = self._cloud_base(provider)
        req = self._build_cloud_request(
            provider, base, model, key, prompt, image_bytes,
            system_prompt, json_mode, temperature,
        )
        if req is None:
            return None
        started = time.time()
        try:
            timeout = _CLOUD_TIMEOUT_S + (20.0 if image_bytes else 0.0)
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                r = await client.request(
                    "POST", req["url"], headers=req["headers"],
                    params=req["params"], json=req["json"],
                )
        except Exception as exc:  # noqa: BLE001 — degrade to next provider
            return GenerationResult(
                content=None, provider=provider, model=model,
                latency_ms=round((time.time() - started) * 1000),
                detail=f"Connection failed: {type(exc).__name__}",
            )
        latency = round((time.time() - started) * 1000)
        content = self._parse_cloud_response(provider, r)
        if content is None:
            return GenerationResult(
                content=None, provider=provider, model=model,
                latency_ms=latency, detail=f"HTTP {r.status_code}",
            )
        return GenerationResult(
            content=content, provider=provider, model=model,
            latency_ms=latency, detail=f"HTTP {r.status_code}",
        )

    # ------------------------------------------------------------------ #
    # Local Ollama leg
    # ------------------------------------------------------------------ #
    def _ollama_base(self) -> str:
        from app.services.admin_store import admin_store
        gw = admin_store.get_gateway()
        return (gw.get("ollama_url") or DEFAULT_OLLAMA_BASE).rstrip("/")

    def _vision_enabled(self) -> bool:
        from app.services.admin_store import admin_store
        gw = admin_store.get_gateway()
        return bool(gw.get("vision_enabled", True))

    def _task_model(self, task: str, tags: list[str]) -> str:
        """Admin-assigned model for a task role (the Vision Model Rotator).

        Returns the assigned tag when the operator pinned one *and* it is
        actually installed in the local runtime — otherwise ``""`` so the
        normal auto-resolution rules stay authoritative.
        """
        from app.services.admin_store import admin_store
        gw = admin_store.get_gateway()
        assigned = ((gw.get("task_models") or {}).get(task) or "").strip()
        if assigned and assigned in tags:
            return assigned
        return ""

    def _gateway_task_models(self) -> dict[str, str]:
        from app.services.admin_store import admin_store
        gw = admin_store.get_gateway()
        return {str(k): str(v) for k, v in (gw.get("task_models") or {}).items()}

    def _resolve_ollama_model(self, tags: list[str], has_image: bool) -> str:
        from app.services.admin_store import admin_store
        gw = admin_store.get_gateway()
        configured = (gw.get("ollama_model") or "").strip()
        role = "vision_imint" if has_image else "terminal"
        pinned = self._task_model(role, tags)
        if pinned:
            return pinned
        if has_image:
            if not self._vision_enabled():
                return self._resolve_ollama_model(tags, False)
            candidate = configured or DEFAULT_VISION_MODEL
            if candidate in tags:
                return candidate
            for m in tags:
                if _VISION_NAME_RE.search(m):
                    return m
            for m in tags:
                if m == DEFAULT_OLLAMA_MODEL or m.startswith("qwen2.5-coder"):
                    return m
            return candidate
        if configured in tags:
            return configured
        if tags:
            return tags[0]
        return configured or DEFAULT_OLLAMA_MODEL

    def _ollama_models_sync(self) -> list[str]:
        """Cached model list; refreshes with a fast blocking probe when stale."""
        cache = self._ollama_cache
        if (time.time() - cache["ts"]) < _OLLAMA_CACHE_TTL_S:
            return list(cache["models"])
        models: list[str] = []
        try:
            with httpx.Client(timeout=_OLLAMA_PROBE_S) as client:
                r = client.get(f"{self._ollama_base()}/api/tags")
                if r.status_code == 200:
                    data = r.json() or {}
                    models = [
                        str(m.get("name", "")).strip()
                        for m in data.get("models", [])
                        if isinstance(m, dict) and m.get("name")
                    ]
        except Exception:  # noqa: BLE001 — probe must never raise
            models = []
        self._ollama_cache = {"ts": time.time(), "models": models}
        return models

    async def _ollama_tags(self, base: str) -> list[str]:
        cache = self._ollama_cache
        if (time.time() - cache["ts"]) < _OLLAMA_CACHE_TTL_S:
            return list(cache["models"])
        models: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=_OLLAMA_PROBE_S) as client:
                r = await client.get(f"{base}/api/tags")
                if r.status_code == 200:
                    data = r.json() or {}
                    models = [
                        str(m.get("name", "")).strip()
                        for m in data.get("models", [])
                        if isinstance(m, dict) and m.get("name")
                    ]
        except Exception:  # noqa: BLE001
            models = []
        self._ollama_cache = {"ts": time.time(), "models": models}
        return models

    async def _ollama_call(
        self,
        prompt: str,
        image_bytes: Optional[bytes],
        system_prompt: Optional[str],
        json_mode: bool,
        temperature: float,
    ) -> Optional[GenerationResult]:
        if image_bytes and not self._vision_enabled():
            return GenerationResult(
                content=None, provider="ollama", model=None,
                latency_ms=0, detail="vision disabled by operator (Local Engine toggle)",
            )
        base = self._ollama_base()
        tags = await self._ollama_tags(base)
        if not tags:
            return None
        model = self._resolve_ollama_model(tags, image_bytes is not None)

        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        user: dict[str, Any] = {"role": "user", "content": prompt}
        if image_bytes:
            user["images"] = [base64.b64encode(image_bytes).decode()]
        messages.append(user)

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if json_mode:
            payload["format"] = "json"

        started = time.time()
        try:
            async with httpx.AsyncClient(timeout=_OLLAMA_TIMEOUT_S) as client:
                r = await client.post(f"{base}/api/chat", json=payload)
        except Exception as exc:  # noqa: BLE001
            return GenerationResult(
                content=None, provider="ollama", model=model,
                latency_ms=round((time.time() - started) * 1000),
                detail=f"Connection failed: {type(exc).__name__}",
            )
        latency = round((time.time() - started) * 1000)
        if r.status_code != 200:
            return GenerationResult(
                content=None, provider="ollama", model=model,
                latency_ms=latency, detail=f"HTTP {r.status_code}",
            )
        try:
            content = (r.json().get("message") or {}).get("content")
        except Exception:  # noqa: BLE001
            content = None
        if not content:
            return GenerationResult(
                content=None, provider="ollama", model=model,
                latency_ms=latency, detail="empty model response",
            )
        return GenerationResult(
            content=content, provider="ollama", model=model,
            latency_ms=latency, detail="local Ollama",
        )

    # ------------------------------------------------------------------ #
    # Status routing
    # ------------------------------------------------------------------ #
    def _pick_route(
        self,
        cloud: dict[str, dict[str, Any]],
        ollama: dict[str, Any],
    ) -> dict[str, Any]:
        from app.services.admin_store import admin_store
        active = ((admin_store.get_gateway().get("active_llm_provider")) or "openai").strip().lower()

        def _route(provider: str) -> dict[str, Any]:
            model = self._resolve_model(provider, False)
            return {
                "status": "cloud",
                "provider": provider,
                "model": model,
                "detail": f"{provider} reachable",
            }

        if active in CLOUD_PROVIDERS and cloud.get(active, {}).get("probed"):
            return _route(active)
        for provider in CLOUD_PROVIDERS:
            if cloud.get(provider, {}).get("probed"):
                return _route(provider)
        if ollama.get("available"):
            return {
                "status": "local_ollama",
                "provider": "ollama",
                "model": self._resolve_ollama_model(ollama.get("models") or [], True),
                "detail": "local Ollama runtime reachable",
            }
        return {
            "status": "offline",
            "provider": None,
            "model": None,
            "detail": "no AI provider reachable (add a cloud key or start Ollama)",
        }

    # ------------------------------------------------------------------ #
    # Sync executor
    # ------------------------------------------------------------------ #
    @staticmethod
    def _run_sync(coro_factory) -> Optional[GenerationResult]:
        """Run an async gateway coroutine in a dedicated event-loop thread.

        Safe to call from anywhere (including inside a running event loop);
        the coroutine is bounded by its own httpx timeouts.
        """
        box: dict[str, Any] = {}

        def _worker() -> None:
            try:
                box["result"] = asyncio.run(coro_factory())
            except Exception as exc:  # noqa: BLE001
                box["error"] = exc

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        thread.join()
        if "error" in box:
            logger.warning("AI gateway sync completion failed: %s", box["error"])
            return None
        return box.get("result")


# Singleton
ai_gateway = AIGateway()


def get_active_litellm_model(
    provider_override: Optional[str] = None,
    model_override: Optional[str] = None,
    has_image: bool = False,
) -> dict[str, str]:
    """Single source of truth for the active LLM used across ARK.

    Returns the LiteLLM kwargs (``model`` / ``api_base`` / ``api_key``) for the
    admin-selected provider. The CAI terminal orchestrator and every workspace
    agent use this so changing the model in the **Admin Console** or the
    **Settings panel** instantly rebinds *all* AI activity — terminal, IMINT,
    network, SECOPS and case workspaces.

    ``provider_override`` / ``model_override`` allow a per-session pin (e.g. the
    ``/model`` command) while still inheriting the provider's credentials and
    base URL from central config. ``has_image`` selects a vision-capable model
    when the task carries an image payload.
    """
    from app.services.admin_store import admin_store

    gw = admin_store.get_gateway()
    active = (provider_override or gw.get("active_llm_provider") or "openai").strip().lower()
    instance = AIGateway()

    # Honour an explicit terminal task-model override from central config first.
    task_terminal = (gw.get("task_models", {}).get("terminal") or "").strip()

    if active == "ollama":
        # Resolve against the *actually installed* models so a misconfigured or
        # missing ``ollama_model`` never yields a "model not found" error. Text
        # tasks prefer a coder/text model; image tasks prefer a vision model.
        tags = instance._ollama_models_sync()
        model = (
            model_override
            or task_terminal
            or instance._resolve_ollama_model(tags, has_image)
        )
        return {
            "model": f"ollama/{model}",
            "api_base": (gw.get("ollama_url") or DEFAULT_OLLAMA_BASE).rstrip("/"),
            "api_key": "ollama",
        }

    model = model_override or task_terminal or instance._resolve_model(active, has_image)
    base = instance._cloud_base(active)
    key = instance._cloud_key(active)
    if active in ("openai", "anthropic", "gemini", "openrouter", "huggingface"):
        model_str = f"{active}/{model}" if model else active
    else:
        model_str = model or active
    result: dict[str, str] = {"model": model_str, "api_key": key}
    if base:
        result["api_base"] = base
    return result


def get_active_model_string() -> str:
    """Return just the ``provider/model`` string for status surfaces / banners."""
    return get_active_litellm_model().get("model", "unknown")
