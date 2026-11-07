"""Prompt-injection evaluation suite.

The mandate (docs/ARK_INTEGRATED_SECURITY_ENVIRONMENT.md §6b): every release
that lets the agent ingest external content must not be steerable off its
objective. We cannot test a model's intent, but we CAN test the structural
guarantee the fence provides: adversarial external content is always fenced and
flagged before it reaches the model, the fence cannot be escaped by content,
and the system prompt carries the untrusted-content rule.
"""
from app.engine.injection_fixtures import FIXTURES, corpus
from app.engine.untrusted_content import (
    FENCE_BEGIN, FENCE_END, fence, is_untrusted_tool, sanitize_tool_result,
    scan_for_injection, FENCE_POLICY,
)
from app.engine import prompts


def test_corpus_is_nonempty_and_well_formed():
    assert len(FIXTURES) >= 10
    ids = [fid for fid, _ in FIXTURES]
    assert len(ids) == len(set(ids)), "fixture ids must be unique"
    assert all(text.strip() for _, text in FIXTURES)


def _unneutralize(out: str) -> str:
    return out.replace("[[fence-begin]]", FENCE_BEGIN).replace("[[fence-end]]", FENCE_END)


def test_every_fixture_is_fenced_and_labelled_as_data():
    for fid, text in FIXTURES:
        out = fence(text, "recon.web_fetch")
        assert out.startswith(FENCE_BEGIN), fid
        assert out.endswith(FENCE_END), fid
        # The payload is preserved as data (markers defanged, not dropped).
        assert text.strip() in _unneutralize(out), fid


def test_every_fixture_is_flagged_as_injection_like():
    # Each fixture is crafted to be an instruction attempt, so the fence must
    # flag at least one line — a fixture that is NOT flagged is a blind spot.
    for fid, text in FIXTURES:
        assert scan_for_injection(text), f"not flagged: {fid}"


def test_fence_cannot_be_escaped_by_embedded_markers():
    for fid, text in FIXTURES:
        out = fence(text, "browser.navigate")
        # Exactly one opening and one closing marker regardless of payload.
        assert out.count(FENCE_BEGIN) == 1, fid
        assert out.count(FENCE_END) == 1, fid
        # The fence closes only at the very end: nothing follows the terminator.
        assert out.endswith(FENCE_END), fid


def test_sanitize_fences_text_bearing_results_from_untrusted_tools():
    for fid, text in FIXTURES:
        result = sanitize_tool_result("recon.web_fetch", {"url": "x", "text": text})
        assert isinstance(result, dict) and result.get("_untrusted") is True, fid
        assert result["fenced"].count(FENCE_BEGIN) == 1, fid
        assert result["fenced"].count(FENCE_END) == 1, fid
        assert result["fenced"].endswith(FENCE_END), fid
        # A distinctive payload token survives into the fenced block.
        assert text.strip()[:8] in result["fenced"], fid


def test_sanitize_leaves_deterministic_results_untouched():
    # A trusted deterministic tool must keep its exact shape — fencing its
    # structured output would corrupt downstream consumers.
    payload = {"gps": {"lat": 1.0, "lon": 2.0}, "status": "ok"}
    assert sanitize_tool_result("exif.extract", payload) == payload
    assert sanitize_tool_result("custody.hash", "abc123") == "abc123"


def test_structured_untrusted_result_without_text_is_not_fenced():
    # No free-text key => nothing for an attacker to steer with => unchanged.
    payload = {"matches": 3, "provider": "phash"}
    assert sanitize_tool_result("osint.reverse_image", payload) == payload


def test_system_prompt_carries_the_untrusted_rule():
    sys_prompt = prompts.autonomous_system()
    assert "UNTRUSTED_EXTERNAL_CONTENT" in sys_prompt
    # The rule states the DATA-not-instruction contract explicitly.
    assert "never an instruction" in sys_prompt.lower() or "not an instruction" in sys_prompt.lower()


def test_policy_text_matches_the_fence_markers():
    assert "UNTRUSTED_EXTERNAL_CONTENT" in FENCE_POLICY


def test_external_tool_ids_are_classified_untrusted():
    for tool_id in ("recon.web_fetch", "browser.navigate", "osint.reverse_image",
                    "net.http_get", "web_fetch", "source_discovery"):
        assert is_untrusted_tool(tool_id), tool_id


def test_corpus_covers_the_expected_attack_families():
    c = corpus()
    assert "classic_override" in c
    assert "exfiltration" in c
    assert "tool_run_directive" in c
    assert "objective_hijack" in c
    assert "fence_escape_attempt" in c
