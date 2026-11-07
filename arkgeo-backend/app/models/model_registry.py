"""Normalized model registry.

Single, provider-agnostic description of every model THE ARK can run.  The
model picker, the resolver and the run metadata all read this record, so a
capability is stated in exactly one place.

Honesty rules (mirrored from the platform's epistemic contract):
* Unknown is represented as ``None`` (serialized as ``"unknown"``).  We never
  invent a capability we have not seen declared by a metadata source.
* ``advertised`` holds what a catalogue/provider *claims*; ``verified`` holds
  what we have actually exercised through the configured endpoint.  A claim is
  not proof.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

UNKNOWN = "unknown"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Provider identity: canonical provider id -> display name + logo reference.
PROVIDER_IDENTITY: dict[str, dict[str, str]] = {
    "openai": {"name": "OpenAI", "logo": "openai"},
    "anthropic": {"name": "Anthropic", "logo": "anthropic"},
    "gemini": {"name": "Google Gemini", "logo": "google"},
    "openrouter": {"name": "OpenRouter", "logo": "openrouter"},
    "huggingface": {"name": "Hugging Face", "logo": "huggingface"},
    "ollama": {"name": "Ollama (Local)", "logo": "ollama"},
}


@dataclass
class ModelRecord:
    """Normalized model record (Phase 4)."""

    id: str                       # stable canonical id: "<provider>/<model>"
    provider: str                 # canonical provider id
    model: str                    # provider-native model name
    display_name: str
    logo: str                     # logo reference for the picker
    local: bool = False
    pricing: str = UNKNOWN        # free | paid | unknown
    pricing_detail: str = ""
    availability: str = UNKNOWN   # available | unavailable | unknown
    availability_reason: str = ""

    context_window: Optional[int] = None
    max_input_tokens: Optional[int] = None
    max_output_tokens: Optional[int] = None

    reasoning: Optional[bool] = None
    tool_calling: Optional[bool] = None
    image_input: Optional[bool] = None
    image_output: Optional[bool] = None
    audio_input: Optional[bool] = None
    audio_output: Optional[bool] = None
    video_input: Optional[bool] = None
    structured_output: Optional[bool] = None

    metadata_source: str = UNKNOWN  # catalog | config | provider | inferred
    last_verified: Optional[str] = None
    advertised: dict[str, Any] = field(default_factory=dict)
    verified: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # Serialize unknown capability as the literal string so the client can
        # render "unknown" without guessing from a missing key.
        for key in (
            "reasoning", "tool_calling", "image_input", "image_output",
            "audio_input", "audio_output", "video_input", "structured_output",
        ):
            if data[key] is None:
                data[key] = UNKNOWN
        return data


# Curated capability catalogue.  ``metadata_source`` is recorded as "catalog"
# and ``last_verified`` is left None until a live probe confirms a field.
# Capabilities we are not certain about are omitted -> unknown, not invented.
_CATALOG: dict[str, dict[str, Any]] = {
    # provider/model -> capability facts
    "openrouter/openai/gpt-4o": dict(display="GPT-4o", context=128000, max_out=16384,
                                     reasoning=True, tools=True, image_in=True, structured=True, pricing="paid"),
    "openrouter/openai/gpt-4o-mini": dict(display="GPT-4o mini", context=128000, max_out=16384,
                                          reasoning=True, tools=True, image_in=True, structured=True, pricing="paid"),
    "openrouter/openai/gpt-4-turbo": dict(display="GPT-4 Turbo", context=128000,
                                          reasoning=True, tools=True, image_in=True, structured=True, pricing="paid"),
    "openrouter/anthropic/claude-3.5-sonnet": dict(display="Claude 3.5 Sonnet", context=200000, max_out=8192,
                                                   reasoning=True, tools=True, image_in=True, structured=True, pricing="paid"),
    "openrouter/anthropic/claude-3-haiku": dict(display="Claude 3 Haiku", context=200000, max_out=4096,
                                                reasoning=True, tools=True, image_in=True, structured=True, pricing="paid"),
    "openrouter/google/gemini-2.0-flash": dict(display="Gemini 2.0 Flash", context=1000000,
                                               reasoning=True, tools=True, image_in=True, audio_in=True, video_in=True, structured=True, pricing="paid"),
    "openrouter/google/gemini-2.5-flash": dict(display="Gemini 2.5 Flash", context=1000000,
                                               reasoning=True, tools=True, image_in=True, audio_in=True, video_in=True, structured=True, pricing="paid"),
    "openrouter/meta-llama/llama-3.1-8b-instruct": dict(display="Llama 3.1 8B Instruct", context=131072, tools=True, pricing="paid"),
    "openrouter/meta-llama/llama-3.1-70b-instruct": dict(display="Llama 3.1 70B Instruct", context=131072, tools=True, pricing="paid"),
    "openrouter/nvidia/nemotron-3.5-lightning": dict(display="Nemotron 3.5 Lightning", context=131072, tools=True, pricing="paid"),
    "openrouter/nvidia/nemotron-3.5-super-vl": dict(display="Nemotron 3.5 Super VL", context=131072,
                                                    tools=True, image_in=True, pricing="paid"),
    "openrouter/nvidia/nemotron-3.5-lightning:free": dict(display="Nemotron 3.5 Lightning (free)", context=131072,
                                                          tools=True, pricing="free"),
    "openrouter/nvidia/nemotron-3.5-super-vl:free": dict(display="Nemotron 3.5 Super VL (free)", context=131072,
                                                         tools=True, image_in=True, pricing="free"),
    "openrouter/qwen/qwen2.5-coder:3b": dict(display="Qwen2.5 Coder 3B", context=131072, tools=True, pricing="free"),
    "openrouter/qwen/qwen2.5-coder:7b": dict(display="Qwen2.5 Coder 7B", context=131072, tools=True, pricing="free"),
    "openrouter/cohere/north-mini-code:free": dict(display="North Mini Code (free)", context=131072,
                                                   tools=True, pricing="free"),
    "openai/gpt-4o": dict(display="GPT-4o", context=128000, max_out=16384,
                          reasoning=True, tools=True, image_in=True, structured=True, pricing="paid"),
    "openai/gpt-4o-mini": dict(display="GPT-4o mini", context=128000, max_out=16384,
                               reasoning=True, tools=True, image_in=True, structured=True, pricing="paid"),
    "openai/gpt-4-turbo": dict(display="GPT-4 Turbo", context=128000,
                               reasoning=True, tools=True, image_in=True, structured=True, pricing="paid"),
    "openai/gpt-3.5-turbo": dict(display="GPT-3.5 Turbo", context=16385, tools=True, pricing="paid"),
    "anthropic/claude-3-5-sonnet-latest": dict(display="Claude 3.5 Sonnet", context=200000, max_out=8192,
                                               reasoning=True, tools=True, image_in=True, structured=True, pricing="paid"),
    "anthropic/claude-3-haiku-latest": dict(display="Claude 3 Haiku", context=200000, max_out=4096,
                                            reasoning=True, tools=True, image_in=True, structured=True, pricing="paid"),
    "anthropic/claude-3-opus-latest": dict(display="Claude 3 Opus", context=200000,
                                           reasoning=True, tools=True, image_in=True, structured=True, pricing="paid"),
    "gemini/gemini-2.0-flash": dict(display="Gemini 2.0 Flash", context=1000000,
                                    reasoning=True, tools=True, image_in=True, audio_in=True, video_in=True, structured=True, pricing="paid"),
    "gemini/gemini-2.5-flash": dict(display="Gemini 2.5 Flash", context=1000000,
                                    reasoning=True, tools=True, image_in=True, audio_in=True, video_in=True, structured=True, pricing="paid"),
    "gemini/gemini-1.5-pro": dict(display="Gemini 1.5 Pro", context=2000000,
                                  reasoning=True, tools=True, image_in=True, audio_in=True, video_in=True, structured=True, pricing="paid"),
    "huggingface/Qwen/Qwen2.5-Coder-7B-Instruct": dict(display="Qwen2.5 Coder 7B Instruct", context=32768, tools=True, pricing="paid"),
    "huggingface/Qwen/Qwen2.5-Coder-32B-Instruct": dict(display="Qwen2.5 Coder 32B Instruct", context=32768, tools=True, pricing="paid"),
    "huggingface/Qwen/Qwen2.5-VL-7B-Instruct": dict(display="Qwen2.5 VL 7B Instruct", context=32768,
                                                    tools=True, image_in=True, pricing="paid"),
    "huggingface/meta-llama/Llama-3.2-3B-Instruct": dict(display="Llama 3.2 3B Instruct", context=131072, tools=True, pricing="paid"),
    "huggingface/meta-llama/Llama-3.2-11B-Instruct": dict(display="Llama 3.2 11B Instruct", context=131072, tools=True, pricing="paid"),
    "huggingface/meta-llama/Llama-3.1-8B-Instruct": dict(display="Llama 3.1 8B Instruct", context=131072, tools=True, pricing="paid"),
}


def _record_from_catalog(provider: str, model: str, *, local: bool = False) -> ModelRecord:
    ident = PROVIDER_IDENTITY.get(provider, {"name": provider.capitalize(), "logo": provider})
    key = f"{provider}/{model}"
    spec = _CATALOG.get(key)
    rec = ModelRecord(
        id=key,
        provider=provider,
        model=model,
        display_name=(spec or {}).get("display") or model,
        logo=ident["logo"],
        local=local,
        metadata_source="catalog" if spec else "inferred",
    )
    if spec:
        rec.context_window = spec.get("context")
        rec.max_input_tokens = spec.get("context")
        rec.max_output_tokens = spec.get("max_out")
        rec.reasoning = spec.get("reasoning")
        rec.tool_calling = spec.get("tools")
        rec.image_input = spec.get("image_in")
        rec.image_output = spec.get("image_out")
        rec.audio_input = spec.get("audio_in")
        rec.audio_output = spec.get("audio_out")
        rec.video_input = spec.get("video_in")
        rec.structured_output = spec.get("structured")
        rec.pricing = spec.get("pricing", UNKNOWN)
        rec.advertised = {
            k: v for k, v in {
                "reasoning": rec.reasoning, "tool_calling": rec.tool_calling,
                "image_input": rec.image_input, "structured_output": rec.structured_output,
                "context_window": rec.context_window,
            }.items() if v is not None
        }
    return rec


# Provider -> the model ids that provider offers in the picker.
PROVIDER_MODELS: dict[str, list[str]] = {
    "openrouter": [
        "openai/gpt-4o", "openai/gpt-4o-mini", "openai/gpt-4-turbo",
        "anthropic/claude-3.5-sonnet", "anthropic/claude-3-haiku",
        "google/gemini-2.0-flash", "google/gemini-2.5-flash",
        "meta-llama/llama-3.1-8b-instruct", "meta-llama/llama-3.1-70b-instruct",
        "nvidia/nemotron-3.5-lightning", "nvidia/nemotron-3.5-super-vl",
        "nvidia/nemotron-3.5-lightning:free", "nvidia/nemotron-3.5-super-vl:free",
        "qwen/qwen2.5-coder:3b", "qwen/qwen2.5-coder:7b",
        "cohere/north-mini-code:free",
    ],
    "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
    "anthropic": ["claude-3-5-sonnet-latest", "claude-3-haiku-latest", "claude-3-opus-latest"],
    "gemini": ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-1.5-pro"],
    "huggingface": [
        "Qwen/Qwen2.5-Coder-7B-Instruct", "Qwen/Qwen2.5-Coder-32B-Instruct",
        "Qwen/Qwen2.5-VL-7B-Instruct", "meta-llama/Llama-3.2-3B-Instruct",
        "meta-llama/Llama-3.2-11B-Instruct", "meta-llama/Llama-3.1-8B-Instruct",
    ],
}


def known_model(provider: str, model: str) -> bool:
    """True when the (provider, model) pair is in the picker catalogue."""
    return model in PROVIDER_MODELS.get(provider, ())


# ARK-managed (platform-hosted) models — the subscription surface.  These are
# declared so the picker can render them, but they are denied until an operator
# grants them in an entitlement (``subscription_models``).  No billing.
SUBSCRIPTION_MODELS: list[str] = [
    "ark-reasoner-pro",
    "ark-vision-max",
    "ark-local-tactical",
]


def lookup(provider: str, model: str) -> ModelRecord:
    """Return the normalized record for a pair (catalog or inferred)."""
    if provider == "ark":
        ident = {"name": "ARK Managed", "logo": "ark"}
        return ModelRecord(
            id=f"ark/{model}",
            provider="ark",
            model=model,
            display_name=model.replace("-", " ").title(),
            logo=ident["logo"],
            pricing="paid",
            pricing_detail="ARK subscription",
            metadata_source="platform",
        )
    return _record_from_catalog(provider, model, local=(provider == "ollama"))


def subscription_records() -> list[ModelRecord]:
    return [lookup("ark", m) for m in SUBSCRIPTION_MODELS]


def parse_model_id(model_id: str) -> tuple[str, str]:
    """Split a canonical id into ``(provider, model)``.

    Only the *first* segment is the provider; the remainder is the model name
    (OpenRouter/HF names contain slashes).  Falls back to the admin-active
    provider when the id carries no provider prefix.
    """
    model_id = (model_id or "").strip()
    if "/" in model_id:
        prov, mdl = model_id.split("/", 1)
        return prov.strip().lower(), mdl.strip()
    return "", model_id


def catalogue() -> list[ModelRecord]:
    """Every catalogued record across all providers (excluding live Ollama)."""
    out: list[ModelRecord] = []
    for provider, models in PROVIDER_MODELS.items():
        for m in models:
            out.append(_record_from_catalog(provider, m))
    return out
