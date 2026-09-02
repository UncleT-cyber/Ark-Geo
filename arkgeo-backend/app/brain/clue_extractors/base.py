"""Shared LLM client for Tier-3 clue extractors.

Each extractor sends an image + a specialised system prompt to a
vision-capable LLM and parses the JSON response.  Centralising the call here
keeps the individual extractors thin and testable.  All completions route
through the unified AI provider gateway (:mod:`app.services.ai_gateway`), so
a cloud key, a local Ollama runtime, or neither are handled by one cascade.

The async variants (``vision_query_async``, ``chat_json_async``) enforce a
hard timeout and fall back to the local Ollama-only ModelGateway, mirroring
the 3-tier pattern used by phone_analysis — never blocking the pipeline.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from app.core.config import settings
from app.services.ai_gateway import ai_gateway

logger = logging.getLogger(__name__)

VISION_USER_PROMPT = "Analyze this image and return only JSON."

# Hard caps so no single LLM call stalls the entire cascade.
_CLOUD_TIMEOUT_S = 30.0
_LOCAL_TIMEOUT_S = 45.0


class LLMClient:
    """Thin wrapper around the unified AI provider gateway.

    Keeps the old attribute surface (``_key``/``_model``) so existing callers
    and tests that introspect the client keep working, but every completion
    is resolved by :data:`ai_gateway` with its cloud → local cascade.
    """

    def __init__(self) -> None:
        self._base_url = settings.llm_base_url
        self._key = settings.llm_api_key
        self._model = settings.llm_model
        self._timeout = settings.llm_request_timeout

    def is_configured(self) -> bool:
        """True when any AI path exists — a cloud key or a reachable local
        Ollama runtime.  This is what fixes "AI keys are not configured"
        when the server runs a local model: the gateway will use it."""
        if bool(self._key):
            return True
        return ai_gateway.is_configured()

    @property
    def model(self) -> str:
        return self._model

    # ------------------------------------------------------------------ #
    # Sync variants (legacy — used by callers that cannot await)
    # ------------------------------------------------------------------ #
    def chat_json(self, system_prompt: str, user_prompt: str) -> Optional[dict[str, Any]]:
        """Text-only chat; return parsed JSON dict or ``None`` (sync)."""
        if not self.is_configured():
            logger.debug("No AI provider configured; skipping text query")
            return None
        result = ai_gateway.generate_completion_sync(
            user_prompt, system_prompt=system_prompt, json_mode=True, temperature=0.2,
        )
        if result is None or not result.content:
            logger.warning("AI gateway text query failed (%s)", result.detail if result else "no result")
            return None
        return self._parse_json(result.content)

    def vision_query(self, image_bytes: bytes, system_prompt: str) -> Optional[dict[str, Any]]:
        """Send image + prompt; return parsed JSON dict or ``None`` (sync)."""
        if not self.is_configured():
            logger.debug("No AI provider configured; skipping extractor")
            return None
        result = ai_gateway.generate_completion_sync(
            VISION_USER_PROMPT,
            image_bytes=image_bytes,
            system_prompt=system_prompt,
            json_mode=True,
            temperature=0.2,
        )
        if result is None or not result.content:
            logger.warning("AI gateway vision query failed (%s)", result.detail if result else "no result")
            return None
        return self._parse_json(result.content)

    # ------------------------------------------------------------------ #
    # Async variants — timeout-guarded, with ModelGateway fallback
    # ------------------------------------------------------------------ #
    async def vision_query_async(
        self, image_bytes: bytes, system_prompt: str, timeout: float = _LOCAL_TIMEOUT_S,
    ) -> Optional[dict[str, Any]]:
        """Async vision query with hard timeout + Ollama fallback.

        Tier 1: ai_gateway (cloud → Ollama cascade, global model)
        Tier 2: ModelGateway (Ollama-only, local fallback)
        Tier 3: None (honest degradation)
        """
        if not self.is_configured():
            logger.debug("No AI provider configured; skipping async vision query")
            return None

        # Tier 1: global ai_gateway cascade
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    ai_gateway.generate_completion_sync,
                    VISION_USER_PROMPT,
                    image_bytes=image_bytes,
                    system_prompt=system_prompt,
                    json_mode=True,
                    temperature=0.2,
                ),
                timeout=timeout,
            )
            if result and result.content:
                parsed = self._parse_json(result.content)
                if parsed:
                    return parsed
        except asyncio.TimeoutError:
            logger.warning("ai_gateway vision query timed out after %ss", timeout)
        except Exception as exc:
            logger.warning("ai_gateway vision query failed: %s", exc)

        # Tier 2: local ModelGateway fallback (Ollama-only)
        try:
            from app.agent.model_gateway import gateway as model_gateway
            if await model_gateway.available():
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": VISION_USER_PROMPT},
                ]
                import base64 as _b64
                content = await asyncio.wait_for(
                    model_gateway.chat(messages, json_mode=True, temperature=0.2, images=[_b64.b64encode(image_bytes).decode()]),
                    timeout=30.0,
                )
                if content:
                    parsed = self._parse_json(content)
                    if parsed:
                        return parsed
        except asyncio.TimeoutError:
            logger.warning("ModelGateway fallback timed out")
        except Exception as exc:
            logger.debug("ModelGateway fallback failed: %s", exc)

        return None

    async def chat_json_async(
        self, system_prompt: str, user_prompt: str, timeout: float = 30.0,
    ) -> Optional[dict[str, Any]]:
        """Async text chat with hard timeout."""
        if not self.is_configured():
            return None
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    ai_gateway.generate_completion_sync,
                    user_prompt,
                    system_prompt=system_prompt,
                    json_mode=True,
                    temperature=0.2,
                ),
                timeout=timeout,
            )
            if result and result.content:
                return self._parse_json(result.content)
        except asyncio.TimeoutError:
            logger.warning("ai_gateway text query timed out after %ss", timeout)
        except Exception as exc:
            logger.warning("ai_gateway text query failed: %s", exc)
        return None

    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_json(content: str) -> Optional[dict[str, Any]]:
        """Best-effort extraction of a JSON object from LLM output."""
        content = content.strip()
        if content.startswith("```"):
            content = content.split("```", 2)[1]
            if content.startswith("json"):
                content = content[4:]
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1:
                try:
                    return json.loads(content[start : end + 1])
                except json.JSONDecodeError:
                    pass
            logger.warning("Could not parse LLM JSON output")
            return None


# Singleton
llm_client = LLMClient()
