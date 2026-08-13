"""Shared LLM client for Tier-3 clue extractors.

Each extractor sends an image + a specialised system prompt to a
vision-capable LLM and parses the JSON response.  Centralising the HTTP
call here keeps the individual extractors thin and testable.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    """Thin wrapper around an OpenAI-compatible chat-completions endpoint."""

    def __init__(self) -> None:
        self._base_url = settings.llm_base_url
        self._key = settings.llm_api_key
        self._model = settings.llm_model
        self._timeout = settings.llm_request_timeout

    def is_configured(self) -> bool:
        return bool(self._key)

    def vision_query(self, image_bytes: bytes, system_prompt: str) -> Optional[dict[str, Any]]:
        """Send image + prompt; return parsed JSON dict or ``None``."""
        if not self.is_configured():
            logger.debug("LLM API key not configured; skipping extractor")
            return None
        b64 = base64.b64encode(image_bytes).decode()
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Analyze this image and return only JSON."},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                ],
            },
        ]
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(
                    f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._key}"},
                    json={
                        "model": self._model,
                        "messages": messages,
                        "max_tokens": settings.llm_max_tokens,
                        "temperature": 0.2,
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                return self._parse_json(content)
        except Exception as exc:
            logger.warning("LLM vision query failed: %s", exc)
            return None

    @staticmethod
    def _parse_json(content: str) -> Optional[dict[str, Any]]:
        """Best-effort extraction of a JSON object from LLM output."""
        content = content.strip()
        # Strip markdown fences if present
        if content.startswith("```"):
            content = content.split("```", 2)[1]
            if content.startswith("json"):
                content = content[4:]
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # Try to find the first {...} block
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
