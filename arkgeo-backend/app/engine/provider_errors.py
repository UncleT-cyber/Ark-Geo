"""Public CAI error responses. Provider payloads stay in application logs."""
from app.agent.provider_tools import InvalidToolSchema


def public_error(exc: Exception) -> dict[str, str]:
    status = getattr(exc, "status_code", None)
    detail = str(exc).lower()
    # Providers signal an exhausted key/quota with assorted statuses — OpenAI and
    # Anthropic use 401, OpenRouter returns 403 "Key limit exceeded" — so a
    # credit/limit body must be classified before the credential branches or an
    # out-of-credit key is misreported as a rejected credential. 429 is left to
    # the rate-limit branch: an exhausted quota there is transient, not billing.
    credit_terms = (
        "insufficient", "credit", "billing", "payment required",
        "out of funds", "limit exceeded", "exceeded your current",
    )
    if isinstance(exc, InvalidToolSchema) or (
        status in (400, 422) and any(term in detail for term in ("invalid name", "function schema", "invalid schema"))
    ):
        code, message = "invalid_tool_schema", "A tool definition failed compatibility validation."
    elif status in (401, 402, 403) and any(term in detail for term in credit_terms):
        code, message = "insufficient_credits", "The model provider reports insufficient credits or an exhausted usage limit."
    elif status in (401, 403):
        code, message = "authentication_failed", "The model provider rejected its credentials or access."
    elif status == 402:
        code, message = "insufficient_credits", "The model provider reports insufficient credits."
    elif status == 429:
        code, message = "rate_limited", "The model provider is rate-limited. Try again later."
    elif any(term in detail for term in ("support tool use", "support tool calling", "tool calling is not supported")):
        code, message = "unsupported_tool_calling", "No compatible provider endpoint accepted tool calling for this model."
    else:
        code, message = "provider_rejected", "The model request failed. Check the configured provider and model."
    return {"event": "error", "code": code, "message": message}
