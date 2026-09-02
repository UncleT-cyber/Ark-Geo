"""Model Gateway — cognitive unit 09. Provider-agnostic LLM access.

Phase C uses a single local model (``qwen2.5-coder:3b`` via Ollama, already
cached on the host). The gateway is the abstraction boundary: **nothing else
in the orchestrator calls a model directly.** Model selection, availability,
and offline/zero-retention routing belong here and behind policy (Phase H).

Every call here is **best-effort**. An unreachable model must degrade to a
deterministic fallback in the planner — never a crash. That is a structural
invariant: the AI orchestrates the deterministic pipeline; it is never a hard
dependency of it.

See ``docs/ARK_INTEGRATED_SECURITY_ENVIRONMENT.md`` §2 unit 09 and the
master plan §3 (model strategy).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx

from . import schemas as S
from .context_builder import context_builder

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5-coder:3b"

HUGGINGFACE_DEFAULT_URL = "https://router.huggingface.co/v1"


# --------------------------------------------------------------------------- #
# Tool-calling wire-format helpers.
#
# The ReAct loop keeps messages in a provider-neutral shape:
#   * assistant with tool_calls:  {"role": "assistant", "content": str|None,
#                                  "tool_calls": [{"id", "name",
#                                                  "arguments": {dict}}]}
#   * tool result:                {"role": "tool", "tool_call_id": str,
#                                  "content": "<json string>"}
# These helpers convert to the provider's wire format on the way out and
# normalize provider responses back into the neutral shape.
# --------------------------------------------------------------------------- #
def _to_ollama_message(msg: dict) -> dict:
    """Convert a neutral message to Ollama's ``/api/chat`` wire format."""
    if msg.get("role") == "assistant" and msg.get("tool_calls"):
        calls = [
            {
                "function": {
                    "name": call.get("name"),
                    "arguments": json.dumps(call.get("arguments") or {},
                                            default=str),
                }
            }
            for call in msg["tool_calls"]
        ]
        return {
            "role": "assistant",
            "content": msg.get("content"),
            "tool_calls": calls,
        }
    return msg


def _to_openai_message(msg: dict) -> dict:
    """Convert a neutral message to the OpenAI-compatible wire format."""
    role = msg.get("role")
    if role == "assistant" and msg.get("tool_calls"):
        calls = [
            {
                "id": call.get("id") or f"call_{call.get('name', 'tool')}_{i}",
                "type": "function",
                "function": {
                    "name": call.get("name"),
                    "arguments": json.dumps(call.get("arguments") or {},
                                            default=str),
                },
            }
            for i, call in enumerate(msg["tool_calls"])
        ]
        return {
            "role": "assistant",
            "content": msg.get("content"),
            "tool_calls": calls,
        }
    if role == "tool":
        return {
            "role": "tool",
            "tool_call_id": msg.get("tool_call_id") or "",
            "content": msg.get("content", ""),
        }
    return msg


def _normalize_tool_message(message: dict) -> Optional[dict]:
    """Normalize a provider assistant message into the neutral tool shape.

    Returns ``None`` when the message carries neither content nor tool_calls
    (so the loop treats it as "no usable response").
    """
    content = message.get("content") or ""
    calls: list[dict] = []
    for tc in message.get("tool_calls") or []:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") or {}
        name = fn.get("name")
        args_raw = fn.get("arguments")
        arguments: dict = {}
        if isinstance(args_raw, str):
            try:
                parsed = json.loads(args_raw)
                if isinstance(parsed, dict):
                    arguments = parsed
            except (TypeError, ValueError):
                pass
        elif isinstance(args_raw, dict):
            arguments = args_raw
        if not name:
            continue
        calls.append({
            "id": tc.get("id") or f"call_{name}",
            "name": name,
            "arguments": arguments,
        })
    if not calls and not str(content).strip():
        return None
    return {"content": str(content), "tool_calls": calls}


class ModelGateway:
    """Thin, provider-agnostic client for the local Ollama runtime.

    Only the *planner* (unit 02) talks to this. Tool execution never does —
    tools run through the registry + policy guard.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model_id: str = DEFAULT_MODEL,
        timeout_s: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.default_model = model_id
        self.timeout_s = timeout_s

    # ------------------------------------------------------------------ #
    def default_spec(self) -> S.ModelSpec:
        return S.ModelSpec(
            model_id=self.default_model,
            name="Qwen 2.5 Coder 3B (local planner)",
            capabilities=[S.ModelCapability.PLANNING, S.ModelCapability.ROUTING],
            provider=S.ModelProvider.OLLAMA,
            local=True,
            version="2.5",
            offline_ok=True,
            zero_retention_safe=True,
            endpoint=self.default_model,
        )

    async def available(self) -> bool:
        """Best-effort health probe. Any failure ⇒ planner uses the template."""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(f"{self.base_url}/api/tags")
                return r.status_code == 200
        except Exception:  # noqa: BLE001 — probe must never raise
            return False

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model_id: Optional[str] = None,
        temperature: float = 0.2,
        json_mode: bool = False,
    ) -> Optional[str]:
        """Non-streaming chat completion. Returns assistant text or None.

        ``json_mode`` constrains Ollama to emit valid JSON (``format: json``),
        which the planner parses defensively regardless.
        """
        payload: dict[str, Any] = {
            "model": model_id or self.default_model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if json_mode:
            payload["format"] = "json"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                r = await client.post(f"{self.base_url}/api/chat", json=payload)
            if r.status_code != 200:
                logger.warning("Model gateway returned HTTP %s", r.status_code)
                return None
            data = r.json()
            return (data.get("message") or {}).get("content")
        except Exception as exc:  # noqa: BLE001 — network/model errors degrade
            logger.warning("Model gateway unavailable: %s", exc)
            return None

    async def chat_tool_round(
        self,
        messages: list[dict],
        *,
        tools: Optional[list[dict]] = None,
        model_id: Optional[str] = None,
        temperature: float = 0.2,
    ) -> Optional[dict]:
        """One native tool-calling round against the local Ollama runtime.

        ``messages`` uses the provider-neutral shape (see helpers above);
        ``tools`` is an OpenAI-format function schema list. Returns the
        normalized assistant message
        ``{"content": str, "tool_calls": [{"id", "name", "arguments"}]}`` or
        ``None`` on any failure. Best-effort — the ReAct loop degrades, never
        crashes, when this returns None.
        """
        payload: dict[str, Any] = {
            "model": model_id or self.default_model,
            "messages": [_to_ollama_message(m) for m in messages],
            "stream": False,
            "options": {"temperature": temperature},
        }
        if tools:
            payload["tools"] = tools
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                r = await client.post(f"{self.base_url}/api/chat", json=payload)
            if r.status_code != 200:
                logger.warning("Model gateway tool round returned HTTP %s",
                               r.status_code)
                return None
            data = r.json()
            return _normalize_tool_message(data.get("message") or {})
        except Exception as exc:  # noqa: BLE001 — network/model errors degrade
            logger.warning("Model gateway tool round unavailable: %s", exc)
            return None

    async def plan_steps(
        self,
        objective: S.InvestigationObjective,
        tool_specs: list[S.ToolSpec],
        domain_key: str,
    ) -> Optional[list[dict[str, str]]]:
        """Ask the model to propose an ordered tool plan.

        The prompt is composed by the ARK Identity Contract
        (:mod:`context_builder`): core identity + governance + tool + evidence
        + reasoning + reporting contracts, then the active domain's specialist
        identity/reasoning/tools, then the registered tool surface.

        Returns ``[{"tool_id": ..., "rationale": ...}, ...]`` or ``None`` on
        any failure. The planner validates every id against the registry and
        falls back to the deterministic template if anything is off — model
        output is *input*, never authority.
        """
        system_prompt, user_prompt = context_builder.build_plan_prompt(
            objective, tool_specs,
        )
        content = await self.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            json_mode=True,
        )
        if not content:
            return None
        try:
            import json

            data = json.loads(content)
            steps = data.get("steps")
            if not isinstance(steps, list):
                return None
            cleaned = [
                {"tool_id": str(s.get("tool_id", "")).strip(),
                 "rationale": str(s.get("rationale", "")).strip()}
                for s in steps if isinstance(s, dict)
            ]
            return cleaned or None
        except Exception:  # noqa: BLE001 — malformed model output
            logger.warning("Planner model returned unparseable JSON")
            return None

    async def propose_next(
        self,
        objective: S.InvestigationObjective,
        gap: dict,
        tool_specs: list[S.ToolSpec],
        budget_summary: str,
    ) -> Optional[list[dict[str, str]]]:
        """Unit 04 — ask the model which of a gap's candidate tools to run
        next (and in what order), or to terminate.

        The candidate set is *closed*: the model picks among ``tool_specs``
        only. ``None`` or an empty list ⇒ terminate the investigation.
        The system prompt is composed by the ARK Identity Contract for the
        objective's domain.
        """
        system_prompt, user_prompt = context_builder.build_next_prompt(
            objective, gap, tool_specs, budget_summary,
        )
        content = await self.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            json_mode=True,
        )
        if not content:
            return None
        try:
            import json

            data = json.loads(content)
            steps = data.get("steps")
            if not isinstance(steps, list):
                return None
            cleaned = [
                {"tool_id": str(s.get("tool_id", "")).strip(),
                 "rationale": str(s.get("rationale", "")).strip()}
                for s in steps if isinstance(s, dict)
            ]
            return cleaned
        except Exception:  # noqa: BLE001
            logger.warning("Adaptive model returned unparseable JSON")
            return None


gateway = ModelGateway()


class HuggingFaceGateway(ModelGateway):
    """Model gateway arm for HuggingFace Inference Providers.

    Talks to the OpenAI-compatible router (``https://router.huggingface.co/v1``)
    so chat completions, tool/JSON constraints and model listing all reuse the
    standard OpenAI wire format. Auth is a personal access token (``hf_...``)
    carrying the "Inference Providers" permission.

    Same best-effort contract as :class:`ModelGateway`: any failure returns
    ``None`` / ``False`` so the deterministic planner can degrade gracefully.
    """

    def __init__(
        self,
        base_url: str = HUGGINGFACE_DEFAULT_URL,
        model_id: str = "",
        api_key: str = "",
        timeout_s: float = 60.0,
    ) -> None:
        super().__init__(base_url=base_url, model_id=model_id, timeout_s=timeout_s)
        self.api_key = api_key

    # ------------------------------------------------------------------ #
    def default_spec(self) -> S.ModelSpec:
        return S.ModelSpec(
            model_id=self.default_model,
            name="HuggingFace Inference Providers",
            capabilities=[S.ModelCapability.PLANNING, S.ModelCapability.ROUTING],
            provider=S.ModelProvider.HUGGINGFACE,
            local=False,
            offline_ok=False,
            zero_retention_safe=True,
            endpoint=self.default_model,
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if self.api_key:
            return headers
        return {}

    async def available(self) -> bool:
        """Probe the token against the model catalog. Any failure ⇒ False."""
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                r = await client.get(
                    f"{self.base_url}/models",
                    headers=self._headers(),
                )
                return r.status_code == 200
        except Exception:  # noqa: BLE001 — probe must never raise
            return False

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model_id: Optional[str] = None,
        temperature: float = 0.2,
        json_mode: bool = False,
    ) -> Optional[str]:
        """Non-streaming chat completion against the OpenAI-compatible router."""
        payload: dict[str, Any] = {
            "model": model_id or self.default_model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                r = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=self._headers(),
                )
            if r.status_code != 200:
                logger.warning("HuggingFace gateway returned HTTP %s", r.status_code)
                return None
            data = r.json()
            choices = data.get("choices") or []
            return (choices[0].get("message") or {}).get("content") if choices else None
        except Exception as exc:  # noqa: BLE001 — network/model errors degrade
            logger.warning("HuggingFace gateway unavailable: %s", exc)
            return None

    async def chat_tool_round(
        self,
        messages: list[dict],
        *,
        tools: Optional[list[dict]] = None,
        model_id: Optional[str] = None,
        temperature: float = 0.2,
    ) -> Optional[dict]:
        """Native tool-calling round against the OpenAI-compatible router."""
        payload: dict[str, Any] = {
            "model": model_id or self.default_model,
            "messages": [_to_openai_message(m) for m in messages],
            "temperature": temperature,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                r = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=self._headers(),
                )
            if r.status_code != 200:
                logger.warning("HuggingFace tool round returned HTTP %s",
                               r.status_code)
                return None
            data = r.json()
            choices = data.get("choices") or []
            if not choices:
                return None
            return _normalize_tool_message(choices[0].get("message") or {})
        except Exception as exc:  # noqa: BLE001 — network/model errors degrade
            logger.warning("HuggingFace tool round unavailable: %s", exc)
            return None


def _default_model_gateway() -> ModelGateway:
    """Build the planner gateway from central config (no hardcoded model).

    The ARK planner is a local-Ollama planner by design, but its base URL and
    model tag are still read from the Admin Console gateway config so the
    single source of truth applies uniformly. Falls back to the Ollama default
    when config is unavailable.
    """
    try:
        from app.services.admin_store import admin_store

        gw = admin_store.get_gateway()
        base = (gw.get("ollama_url") or DEFAULT_BASE_URL).rstrip("/")
        model = (gw.get("ollama_model") or "").strip() or DEFAULT_MODEL
        return ModelGateway(base_url=base, model_id=model)
    except Exception:  # noqa: BLE001 — keep import graph acyclic / safe
        return ModelGateway()


gateway = _default_model_gateway()


def resolve_huggingface_gateway() -> Optional[HuggingFaceGateway]:
    """Build a HuggingFace gateway from Admin Console provisioning.

    Reads the stored gateway config (base URL + model name) and the encrypted
    ``huggingface_api_key``. Returns ``None`` when the model name or token is
    missing so callers fall back to the local gateway.
    """
    try:
        from app.services.admin_store import admin_store
        from app.services.settings_store import settings_store
    except Exception:  # noqa: BLE001 — keep import graph acyclic
        return None

    gw = admin_store.get_gateway()
    model_id = (gw.get("huggingface_model") or "").strip()
    if not model_id:
        return None
    api_key = settings_store.get_key("huggingface_api_key") or ""
    if not api_key:
        return None
    return HuggingFaceGateway(
        base_url=(gw.get("huggingface_url") or HUGGINGFACE_DEFAULT_URL).rstrip("/"),
        model_id=model_id,
        api_key=api_key,
    )
