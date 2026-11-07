import re
from types import SimpleNamespace as NS

import pytest

from app.agent.policy_guard import PolicyGuard
from app.agent.provider_tools import InvalidToolSchema, ProviderTools, provider_name
from app.agent.unified_registry import unified_registry
from app.engine import orchestrator
from app.engine.provider_errors import public_error
from app.engine.router import classify_intent


def definition(tool_id, parameters=None):
    return {"type": "function", "function": {
        "name": tool_id,
        "parameters": parameters if parameters is not None else {
            "type": "object", "properties": {"host": {"type": "string"}}, "required": ["host"],
        },
    }}


def test_namespace_mapping_is_stable_reversible_and_distinct():
    ids = ["imint.exiftool", "imint_exiftool", "imint/exiftool", "x" * 80]
    original = [definition(tool_id) for tool_id in ids]
    tools = ProviderTools(original)
    aliases = [schema["function"]["name"] for schema in tools.schemas]
    assert len(set(aliases)) == len(ids)
    for tool_id, alias in zip(ids, aliases):
        assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", alias)
        assert alias == provider_name(tool_id)
        assert tools.resolve(alias, {"host": "example.com"}) == tool_id
        assert tools.resolve(alias, {}) is None
        assert tools.resolve(alias, {"host": 4}) is None
        assert tools.resolve(alias, {"host": "example.com", "surprise": True}) is None
    assert tools.resolve("imint.exiftool", {"host": "example.com"}) is None
    assert original[0]["function"]["name"] == "imint.exiftool"


def test_alias_collision_and_invalid_schema_are_rejected():
    with pytest.raises(InvalidToolSchema, match="Duplicate"):
        ProviderTools([definition("imint.exiftool"), definition(provider_name("imint.exiftool"))])
    with pytest.raises(InvalidToolSchema):
        ProviderTools([definition("broken", {"type": "object", "properties": {}, "required": ["host"]})])


def test_all_advertisable_registry_schemas_are_provider_safe():
    unified_registry.populate()
    tools = unified_registry.provider_tools(unified_registry.list())
    names = [schema["function"]["name"] for schema in tools.schemas]
    assert provider_name("imint.exiftool") in names
    assert len(names) == len(set(names))
    assert all(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) for name in names)


def test_context_and_policy_filter(monkeypatch):
    monkeypatch.setattr(orchestrator.shutil, "which", lambda name: f"/fixture/{name}")
    prompt = "Run a vulnerability assessment on landlordport.com"
    domains = orchestrator._task_domains(prompt, classify_intent(prompt).suggested_role, "imint")
    tools = orchestrator._select_provider_tools(domains, PolicyGuard())
    names = {schema["function"]["name"] for schema in tools.schemas}
    assert provider_name("net.dns_lookup") in names
    assert provider_name("imint.exiftool") not in names
    assert "execute_cli_command" not in names
    # Substrate nmap requires shell permission. The legacy assessment adapter
    # retains its own per-call HITL gate.
    assert "nmap_scan" not in names
    image_prompt = "Inspect image EXIF and case evidence"
    assert {"imint", "image", "case"} <= orchestrator._task_domains(
        image_prompt, classify_intent(image_prompt).suggested_role, None,
    )


@pytest.mark.asyncio
async def test_vulnerability_request_round_trip_with_parallel_calls(monkeypatch):
    dns = provider_name("net.dns_lookup")
    nmap = provider_name("net.nmap_scan")
    executed = []
    rounds = 0

    def call(call_id, name, raw):
        return NS(id=call_id, function=NS(name=name, arguments=raw))

    async def completion(**kwargs):
        nonlocal rounds
        rounds += 1
        assert kwargs["model"] == "openrouter/nvidia/nemotron-3.5-super-vl:free"
        assert kwargs["stream"] is False
        assert kwargs["extra_body"]["provider"]["require_parameters"] is True
        names = {schema["function"]["name"] for schema in kwargs["tools"]}
        assert dns in names
        assert nmap in names
        assert provider_name("imint.exiftool") not in names
        assert all(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) for name in names)
        if rounds == 1:
            calls = [
                call("dns", dns, '{"host":"landlordport.com"}'),
                call("scan", nmap, '{"target":"landlordport.com"}'),
                call("malformed", dns, '[]'),
                call("unknown", provider_name("imint.exiftool"), '{"image_path":"image.png"}'),
            ]
            return NS(choices=[NS(message=NS(content=None, tool_calls=calls))])
        messages = kwargs["messages"]
        assistant = next(message for message in messages if message.get("tool_calls"))
        assert [item["id"] for item in assistant["tool_calls"]] == ["dns", "scan", "malformed", "unknown"]
        assert [message["tool_call_id"] for message in messages if message["role"] == "tool"] == [
            "dns", "scan", "malformed", "unknown",
        ]
        return NS(choices=[NS(message=NS(content="Fixture finished.", tool_calls=[]))])

    async def dispatch(tool_id, arguments):
        executed.append((tool_id, arguments))
        return {"status": "ok", "result": "fixture"}

    monkeypatch.setattr(orchestrator.shutil, "which", lambda name: f"/fixture/{name}")
    monkeypatch.setattr(orchestrator, "_DEFAULT_MODEL_ENV", None)
    monkeypatch.setattr(orchestrator, "get_active_litellm_model", lambda **_: {
        "model": "openrouter/nvidia/nemotron-3.5-super-vl:free",
        "api_key": "fixture",
        "api_base": "https://openrouter.ai/api/v1",
    })
    monkeypatch.setattr(orchestrator.litellm, "acompletion", completion)
    monkeypatch.setattr(orchestrator, "_dispatch_tool", dispatch)
    session = orchestrator.get_session("provider-wire-fixture")
    events = []
    async for event in orchestrator.run(session, "Run a vulnerability assessment on landlordport.com"):
        events.append(event)
        if event["type"] == "hitl":
            assert event["tool"] == "net.nmap_scan"
            orchestrator.approve(session.session_id, False)
    assert executed == []  # DNS lookup denied by scope without configured scope
    final_events = [e for e in events if e["type"] == "final"]
    assert final_events[-1] == {"type": "final", "text": "Fixture finished."}


@pytest.mark.asyncio
async def test_advisory_stream_yields_text_without_tools(monkeypatch):
    async def completion(**kwargs):
        assert kwargs["stream"] is True
        assert "tools" not in kwargs

        async def chunks():
            yield NS(choices=[])
            yield NS(choices=[NS(delta=NS(content="First "))])
            yield NS(choices=[NS(delta=NS(content="second"))])

        return chunks()

    monkeypatch.setattr(orchestrator.litellm, "acompletion", completion)
    events = [event async for event in orchestrator.run(
        orchestrator.SessionState(session_id="stream-fixture"), "Review the evidence", advisory_only=True,
    )]
    assert [event["text"] for event in events if event["type"] == "token"] == ["First ", "second"]
    final_events = [event for event in events if event["type"] == "final"]
    assert final_events[-1]["text"] == "First second"


@pytest.mark.parametrize(("status", "detail", "code"), [
    # --- schema / request-shape failures -------------------------------------
    (400, "invalid name", "invalid_tool_schema"),
    (422, "invalid schema", "invalid_tool_schema"),
    (404, "No endpoints found that support tool use", "unsupported_tool_calling"),
    (404, "this endpoint does not support tool calling", "unsupported_tool_calling"),
    # --- credential failures (no credit marker in the body) ------------------
    (401, "fixture secret", "authentication_failed"),
    (403, "fixture secret", "authentication_failed"),
    # --- credit / quota exhaustion (body-decisive, any status) ---------------
    # OpenAI returns a 429 for "You exceeded your current quota" — the same
    # status as a throttle. The body must win: this is a spent quota, not a
    # transient rate limit (this is the OpenRouter/OpenAI defect fixed in B.0).
    (429, "You exceeded your current quota", "insufficient_credits"),
    (405, "You exceeded your current quota", "insufficient_credits"),
    (402, "fixture secret", "insufficient_credits"),
    (403, "Key limit exceeded (total limit)", "insufficient_credits"),
    (429, "insufficient credits remaining", "insufficient_credits"),
    (400, "Billing hard limit has been reached", "insufficient_credits"),
    # --- genuine throttle -----------------------------------------------------
    (429, "fixture secret", "rate_limited"),
    (429, "Rate limit reached. Please try again later", "rate_limited"),
    (429, "Too many requests", "rate_limited"),
    # --- model-scoped throttle (provider names the dimension/model) ----------
    (429, "Rate limit exceeded: free-models-per-day", "rate_limited_model"),
    (429, "This model is rate-limited; try another", "rate_limited_model"),
    # --- model / endpoint unavailable ----------------------------------------
    (404, "fixture secret", "model_unavailable"),
    # --- everything else ------------------------------------------------------
    (500, "fixture secret", "provider_rejected"),
    (503, "upstream unavailable", "provider_rejected"),
])
def test_provider_errors_are_classified_without_raw_details(status, detail, code):
    error = RuntimeError(detail)
    error.status_code = status
    assert public_error(error)["code"] == code
    assert "fixture secret" not in public_error(error)["message"]


def test_classification_reads_response_body_not_only_str():
    """A litellm-shaped exception carries the upstream body on ``.response``.

    The status alone is ambiguous for a 429; the body on the response object is
    what distinguishes a spent quota from a throttle.
    """

    class _Resp:
        def __init__(self, text):
            self.text = text
            self.headers = {"authorization": "Bearer super-secret-token"}

    error = RuntimeError("litellm.RateLimitError: provider rejected the request")
    error.status_code = 429
    error.response = _Resp('{"error": {"message": "You exceeded your current quota"}}')
    assert public_error(error)["code"] == "insufficient_credits"


def test_real_litellm_rate_limit_error_is_classified():
    """Exercise the actual litellm exception type, not a look-alike."""
    from litellm.exceptions import RateLimitError

    quota = RateLimitError(
        message="You exceeded your current quota, please check your plan and billing details",
        llm_provider="openrouter", model="openai/gpt-4o-mini",
    )
    assert public_error(quota)["code"] == "insufficient_credits"

    throttle = RateLimitError(
        message="Rate limit reached for requests. Please try again later.",
        llm_provider="openai", model="gpt-4o",
    )
    assert public_error(throttle)["code"] == "rate_limited"


def test_retryable_codes_exclude_credit_and_auth_failures():
    from app.engine.provider_errors import is_retryable

    assert is_retryable("rate_limited")
    assert is_retryable("rate_limited_model")
    for code in ("insufficient_credits", "authentication_failed", "invalid_tool_schema",
                 "unsupported_tool_calling", "provider_rejected", "model_unavailable"):
        assert not is_retryable(code)


@pytest.mark.asyncio
async def test_invalid_schema_fails_before_provider_submission(monkeypatch):
    def invalid_schema(_domains, _guard, _prompt):
        return ProviderTools([definition("broken", {"type": "array"})])

    async def unexpected_completion(**_):
        pytest.fail("invalid tool schema reached the provider")

    monkeypatch.setattr(orchestrator, "_select_provider_tools", invalid_schema)
    monkeypatch.setattr(orchestrator.litellm, "acompletion", unexpected_completion)
    with pytest.raises(InvalidToolSchema):
        async for _ in orchestrator.run(
            orchestrator.SessionState(session_id="invalid-wire-fixture"),
            "Run a vulnerability assessment on landlordport.com",
        ):
            pass


def test_unavailable_adapter_is_omitted(monkeypatch):
    monkeypatch.setattr(orchestrator.shutil, "which", lambda _: None)
    tools = orchestrator._select_provider_tools({"network", "recon"}, PolicyGuard())
    names = {schema["function"]["name"] for schema in tools.schemas}
    assert provider_name("net.dns_lookup") not in names
    assert provider_name("net.nmap_scan") not in names
    assert provider_name("recon.web_search") in names
