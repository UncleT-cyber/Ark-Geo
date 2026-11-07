"""Public CAI error responses. Provider payloads stay in application logs.

Classification is **body-decisive, status-aware**: the provider response body is
read first because a status code alone cannot distinguish a genuine rate limit
from an exhausted quota. OpenAI returns "You exceeded your current quota" with a
429 — the same status as a transient throttle — while OpenRouter returns "Key
limit exceeded" with a 403. Classifying on the status alone (the previous
behaviour) mislabelled a spent key as a transient rate limit and invited
fruitless retries.

Only a sanitized, lowercased body string and the numeric status are ever read;
response headers (which carry credentials) are never inspected, and the raw
provider body is never returned to the client — the caller gets a fixed,
operator-safe message.
"""
from __future__ import annotations

import re

from app.agent.provider_tools import InvalidToolSchema

# Unambiguous body markers of an exhausted key/quota. Any one of these makes the
# condition a credit failure regardless of the HTTP status (401/402/403/429 all
# occur in the wild for this condition).
_CREDIT_TERMS = (
    "insufficient", "credit", "billing", "payment required",
    "out of funds", "exceeded your current", "quota", "monthly limit",
    "spending limit", "no credit",
)

# Body markers of an explicit throttle. Checked before the generic "limit
# exceeded" phrase so that "Rate limit exceeded" is not mistaken for a spent
# quota.
_THROTTLE_TERMS = (
    "rate limit", "rate-limit", "too many requests", "try again later",
    "requests per min", "tokens per min", "requests per day", "per minute",
    "per hour", "per day", "tpm", "rpm",
)

# Model-scoped throttles: the provider names the throttled dimension or model.
_MODEL_SCOPE_RE = re.compile(
    r"(free[- ]?model|per[- ]model|model[- ]limit|model-level|this model|"
    r"your (?:requests|rate) (?:for|on) (?:the )?model)",
    re.IGNORECASE,
)


def _provider_body(exc: Exception) -> str:
    """Best-effort lowercased body text from an exception (never headers).

    ``litellm`` exceptions expose the upstream response on ``.response``; the
    raw body there is fuller than ``str(exc)`` for some providers. Any failure
    to read it degrades to ``str(exc)`` — classification must never raise.
    """
    parts: list[str] = [str(exc)]
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            parts.append(response.text or "")
        except Exception:  # noqa: BLE001 — body read must never raise
            pass
    return " ".join(parts).lower()


def public_error(exc: Exception) -> dict[str, str]:
    status = getattr(exc, "status_code", None)
    detail = _provider_body(exc)

    has_throttle = any(term in detail for term in _THROTTLE_TERMS)
    # "limit exceeded" is ambiguous on its own: OpenRouter's "Key limit exceeded"
    # is a spent quota, but "Rate limit exceeded" is a throttle. Treat it as a
    # credit signal only when no throttle phrasing is present.
    has_credit = any(term in detail for term in _CREDIT_TERMS) or (
        "limit exceeded" in detail and not has_throttle
    )

    if isinstance(exc, InvalidToolSchema) or (
        status in (400, 422) and any(term in detail for term in ("invalid name", "function schema", "invalid schema"))
    ):
        code, message = "invalid_tool_schema", "A tool definition failed compatibility validation."
    elif has_credit:
        # Body-decisive: an exhausted quota/credit condition, whatever the
        # status. A 429 carrying this body is a spent quota, NOT a throttle.
        code = "insufficient_credits"
        message = "The model provider reports insufficient credits or an exhausted usage limit."
    elif status in (401, 403):
        code, message = "authentication_failed", "The model provider rejected its credentials or access."
    elif status == 402:
        code, message = "insufficient_credits", "The model provider reports insufficient credits."
    elif status == 429:
        # A genuine throttle. Distinguish a model-scoped limit from an
        # account-level one only when the body names the dimension; otherwise
        # report the general rate limit.
        if has_throttle and _MODEL_SCOPE_RE.search(detail):
            code = "rate_limited_model"
            message = "The selected model is rate-limited. Try again later or select another model."
        else:
            code = "rate_limited"
            message = "The model provider is rate-limited. Try again later."
    elif any(term in detail for term in ("support tool use", "support tool calling", "tool calling is not supported")):
        code, message = "unsupported_tool_calling", "No compatible provider endpoint accepted tool calling for this model."
    elif status == 404:
        code = "model_unavailable"
        message = "The requested model or endpoint is unavailable from the configured provider."
    else:
        code, message = "provider_rejected", "The model request failed. Check the configured provider and model."
    return {"event": "error", "code": code, "message": message}


# Codes that a caller may safely retry. A credit failure is never retryable
# (retrying cannot restore credit and would spend nothing but wastes attempts);
# a rate limit is retryable subject to a bounded, operator-enabled policy.
RETRYABLE_CODES = frozenset({"rate_limited", "rate_limited_model"})


def is_retryable(code: str) -> bool:
    """True when ``code`` denotes a condition a bounded retry may resolve."""
    return code in RETRYABLE_CODES
