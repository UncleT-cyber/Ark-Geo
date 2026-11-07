"""B.4 — investigation-intent routing.

An investigation-shaped utterance (verify a location, check an image is
authentic, find the source of a photo) surfaces a *proposed* objective so a
caller can route into the existing /investigate flow. Detection is heuristic,
side-effect free, and never calls a model.
"""
import pytest

from app.engine.router import classify_intent, detect_investigation


@pytest.mark.parametrize("text,goal", [
    ("Verify the GPS coordinates in this photo", "verify_location_credibility"),
    ("Where was this image taken?", "verify_location_credibility"),
    ("Geolocate this picture for me", "verify_location_credibility"),
    ("Check whether this image has been tampered with", "tamper_detection"),
    ("Is this photo authentic or photoshopped?", "tamper_detection"),
    ("Which camera took this image?", "device_attribution"),
    ("Find the original source of this photo", "source_discovery"),
    ("Run a reverse image search on this picture", "source_discovery"),
    ("Investigate this evidence image", "full_forensic_profile"),
])
def test_investigation_intents_map_to_goals(text, goal):
    decision = classify_intent(text)
    assert decision.investigation is True
    assert decision.objective is not None
    assert decision.objective["goal"] == goal
    assert decision.objective["domain"] == "image"
    assert decision.objective["natural_language"] == text


def test_tamper_wins_over_location_when_both_present():
    # "verify this image is authentic" must not be read as a location task.
    d = classify_intent("Verify this image is authentic — do not trust its location")
    assert d.objective["goal"] == "tamper_detection"


@pytest.mark.parametrize("text", [
    "Explain how EXIF GPS tags work",
    "What are the risks of metadata leakage?",
    "Enumerate subdomains of example.com",
    "Scan 10.0.0.0/24 for open ports",
    "Run nmap against the target",
])
def test_non_investigation_utterances_do_not_propose_a_case(text):
    decision = classify_intent(text)
    assert decision.investigation is False
    assert decision.objective is None


def test_plain_verify_without_forensic_signal_is_not_a_case():
    # "verify the account identity" is a general task, not a case file.
    assert detect_investigation("verify the account identity") is None


def test_objective_is_consumable_by_the_parse_shape():
    obj = detect_investigation("Verify the location of this photo")
    # The keys /investigate's _parse_objective reads must all be present.
    assert set(obj) <= {"goal", "subject", "domain", "natural_language"}
    assert obj["goal"] and obj["subject"] and obj["domain"]


def test_detect_investigation_uses_target_as_subject():
    obj = detect_investigation("Investigate this evidence", "CASE-42")
    assert obj["subject"] == "CASE-42"


def test_detect_investigation_is_empty_safe():
    assert detect_investigation("") is None
    assert detect_investigation(None) is None
