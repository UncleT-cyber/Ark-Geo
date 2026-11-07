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
from typing import Optional

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


def classify_code(status: int | None, detail: str) -> str:
    """Classify a provider failure to a stable code from status + body text.

    Shared by :func:`public_error` (the CAI streaming path) and the AI gateway,
    so both AI paths speak one error vocabulary. ``detail`` is expected to be
    lowercased body text; pass through :func:`_provider_body` for an exception.
    """
    status = status if isinstance(status, int) else None
    has_throttle = any(term in detail for term in _THROTTLE_TERMS)
    # "limit exceeded" is ambiguous on its own: OpenRouter's "Key limit exceeded"
    # is a spent quota, but "Rate limit exceeded" is a throttle. Treat it as a
    # credit signal only when no throttle phrasing is present.
    has_credit = any(term in detail for term in _CREDIT_TERMS) or (
        "limit exceeded" in detail and not has_throttle
    )

    if status in (400, 422) and any(term in detail for term in ("invalid name", "function schema", "invalid schema")):
        return "invalid_tool_schema"
    if has_credit:
        # Body-decisive: an exhausted quota/credit condition, whatever the
        # status. A 429 carrying this body is a spent quota, NOT a throttle.
        return "insufficient_credits"
    if status in (401, 403):
        return "authentication_failed"
    if status == 402:
        return "insufficient_credits"
    if status == 429:
        # A genuine throttle. Distinguish a model-scoped limit from an
        # account-level one only when the body names the dimension.
        return "rate_limited_model" if (has_throttle and _MODEL_SCOPE_RE.search(detail)) else "rate_limited"
    if any(term in detail for term in ("support tool use", "support tool calling", "tool calling is not supported")):
        return "unsupported_tool_calling"
    if status == 404:
        return "model_unavailable"
    return "provider_rejected"


_MESSAGES: dict[str, str] = {
    "invalid_tool_schema": "A tool definition failed compatibility validation.",
    "insufficient_credits": "The model provider reports insufficient credits or an exhausted usage limit.",
    "authentication_failed": "The model provider rejected its credentials or access.",
    "rate_limited": "The model provider is rate-limited. Try again later.",
    "rate_limited_model": "The selected model is rate-limited. Try again later or select another model.",
    "unsupported_tool_calling": "No compatible provider endpoint accepted tool calling for this model.",
    "model_unavailable": "The requested model or endpoint is unavailable from the configured provider.",
    "provider_rejected": "The model request failed. Check the configured provider and model.",
}


def public_error(exc: Exception) -> dict[str, str]:
    if isinstance(exc, InvalidToolSchema):
        code = "invalid_tool_schema"
    else:
        code = classify_code(getattr(exc, "status_code", None), _provider_body(exc))
    return {"event": "error", "code": code, "message": _MESSAGES[code]}


def classify_exception(exc: Exception) -> str:
    """Stable code for an exception, reading status + body (never headers)."""
    if isinstance(exc, InvalidToolSchema):
        return "invalid_tool_schema"
    return classify_code(getattr(exc, "status_code", None), _provider_body(exc))


def retry_after_seconds(exc: Exception) -> Optional[float]:
    """Seconds to wait from a ``Retry-After`` header, or ``None``.

    Reads only the ``Retry-After`` header — never the body or any credential
    header — and accepts both the delta-seconds and HTTP-date forms. Any parse
    failure returns ``None`` so the caller falls back to exponential backoff.
    """
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) if response is not None else None
    if not headers:
        return None
    try:
        raw = headers.get("retry-after") or headers.get("Retry-After")
    except Exception:  # noqa: BLE001 — header read must never raise
        return None
    if raw is None:
        return None
    try:
        return max(0.0, float(str(raw).strip()))
    except (TypeError, ValueError):
        pass
    try:
        from email.utils import parsedate_to_datetime
        when = parsedate_to_datetime(str(raw))
        import time as _time
        return max(0.0, when.timestamp() - _time.time())
    except Exception:  # noqa: BLE001 — malformed date falls back to backoff
        return None


# Codes that a caller may safely retry. A credit failure is never retryable
# (retrying cannot restore credit and would spend nothing but wastes attempts);
# a rate limit is retryable subject to a bounded, operator-enabled policy.
RETRYABLE_CODES = frozenset({"rate_limited", "rate_limited_model"})


def is_retryable(code: str) -> bool:
    """True when ``code`` denotes a condition a bounded retry may resolve."""
    return code in RETRYABLE_CODES
