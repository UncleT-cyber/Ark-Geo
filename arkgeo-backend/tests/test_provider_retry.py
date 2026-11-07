"""Bounded, opt-in provider retry (Phase B.1).

Retries are OFF by default so a run can never silently multiply spend. When
enabled, only genuine throttles are retried — a credit or authentication
failure is never retried (retrying cannot succeed). All provider calls are
fabricated; no network, no model call.
"""
import asyncio

import pytest

from app.engine import orchestrator as orch
from app.engine.provider_errors import (
    classify_exception,
    is_retryable,
    retry_after_seconds,
)


class _RateLimit(Exception):
    def __init__(self, message="Rate limit reached. Please try again later.", status=429, headers=None):
        super().__init__(message)
        self.status_code = status
        if headers is not None:
            self.response = type("R", (), {"headers": headers, "text": message})()


class _Quota(Exception):
    def __init__(self, message="You exceeded your current quota", status=429):
        super().__init__(message)
        self.status_code = status


def _patch_calls(monkeypatch, outcomes):
    """litellm.acompletion returns/raises per ``outcomes`` in order; records calls."""
    calls = {"n": 0}

    async def fake(**kwargs):
        i = calls["n"]
        calls["n"] += 1
        item = outcomes[min(i, len(outcomes) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(orch.litellm, "acompletion", fake)
    # Never actually sleep in tests.
    async def _no_sleep(_):
        return None
    monkeypatch.setattr(orch.asyncio, "sleep", _no_sleep)
    return calls


@pytest.mark.asyncio
async def test_retry_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ARKGEO_PROVIDER_RETRY", raising=False)
    monkeypatch.setattr(orch, "_retry_enabled", lambda: False)
    calls = _patch_calls(monkeypatch, [_RateLimit(), "ok"])
    with pytest.raises(_RateLimit):
        await orch._acompletion({"model": "x"})
    assert calls["n"] == 1  # one attempt, no retry


@pytest.mark.asyncio
async def test_retry_enabled_retries_then_succeeds(monkeypatch):
    monkeypatch.setenv("ARKGEO_PROVIDER_RETRY", "1")
    monkeypatch.setenv("ARKGEO_PROVIDER_RETRY_MAX", "2")
    calls = _patch_calls(monkeypatch, [_RateLimit(), _RateLimit(), "ok"])
    result = await orch._acompletion({"model": "x"})
    assert result == "ok"
    assert calls["n"] == 3  # initial + 2 bounded retries


@pytest.mark.asyncio
async def test_retry_enabled_is_bounded(monkeypatch):
    monkeypatch.setenv("ARKGEO_PROVIDER_RETRY", "1")
    monkeypatch.setenv("ARKGEO_PROVIDER_RETRY_MAX", "2")
    calls = _patch_calls(monkeypatch, [_RateLimit()])  # always throttled
    with pytest.raises(_RateLimit):
        await orch._acompletion({"model": "x"})
    assert calls["n"] == 3  # initial + 2 retries, then give up


@pytest.mark.asyncio
async def test_credit_failure_is_never_retried(monkeypatch):
    monkeypatch.setenv("ARKGEO_PROVIDER_RETRY", "1")
    monkeypatch.setenv("ARKGEO_PROVIDER_RETRY_MAX", "3")
    calls = _patch_calls(monkeypatch, [_Quota(), "ok"])
    with pytest.raises(_Quota):
        await orch._acompletion({"model": "x"})
    assert calls["n"] == 1  # credit exhaustion is terminal


def test_retry_after_parsing():
    assert retry_after_seconds(_RateLimit(headers={"retry-after": "3"})) == 3.0
    assert retry_after_seconds(_RateLimit(headers={"Retry-After": "0"})) == 0.0
    # Malformed header → None (caller falls back to exponential backoff).
    assert retry_after_seconds(_RateLimit(headers={"retry-after": "soon"})) is None
    assert retry_after_seconds(_RateLimit()) is None  # no response object


def test_retryable_set():
    assert is_retryable("rate_limited") and is_retryable("rate_limited_model")
    assert not is_retryable(classify_exception(_Quota()))
    assert classify_exception(_Quota()) == "insufficient_credits"
