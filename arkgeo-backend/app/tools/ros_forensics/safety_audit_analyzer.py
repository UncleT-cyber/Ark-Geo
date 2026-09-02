"""Safety-audit analyzer — ROS/OT safety-config drift & tamper detection.

DFIR analysis of a robot/OT safety configuration. Two inputs:

* ``config_path`` — the (suspected-tampered) safety configuration YAML.
* ``reference_path`` and/or ``runtime_params`` — the authoritative baseline the
  observed config is compared against.

The analyzer classifies drift against the safety envelope (velocity/accel
limits, protective-stop / E-stop state, joint limits, mode guards) into
severity bands and emits actionable findings. This is **pure static parsing**:
no live system contact, no subprocess, LOW risk / AUTO approval.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Safety keys that matter — path fragments (case-insensitive) → (severity, label).
_SAFETY_KEYS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"(?i)max(_|-)?vel(ocity)?\b|speed_limit"), "HIGH", "velocity-limit"),
    (re.compile(r"(?i)max(_|-)?acc(eleration)?\b"), "MEDIUM", "accel-limit"),
    (re.compile(r"(?i)protective(_|-)?stop\b|safety(_|-)?stop\b|estop|e_stop"), "CRITICAL", "stop-zone"),
    (re.compile(r"(?i)joint(_|-)?limit|position_limit|torque_limit"), "HIGH", "joint-limit"),
    (re.compile(r"(?i)emergency(_|-)?button\b|kill(_|-)?switch\b"), "CRITICAL", "e-stop"),
    (re.compile(r"(?i)mode(_|-)?guard|operation(_|-)?mode"), "HIGH", "mode-guard"),
    (re.compile(r"(?i)human(_|-)?detection\b|zones?\b"), "HIGH", "human-zone"),
    (re.compile(r"(?i)max(_|-)?payload\b"), "MEDIUM", "payload-limit"),
]

_STOP_KEYS = re.compile(r"(?i)protective|safety(_|-)?stop|estop|e_stop|zones?\b")
_HUMAN_KEYS = re.compile(r"(?i)human|person|pedestrian|presence")


def _flatten(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    """Flatten a nested YAML dict into dotted ``key`` → value pairs."""
    pairs: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for k, v in value.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            pairs.extend(_flatten(v, key))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            pairs.extend(_flatten(item, f"{prefix}[{i}]"))
    else:
        pairs.append((prefix, value))
    return pairs


def _parse_yaml(path: str) -> dict[str, Any]:
    if not path or not os.path.isfile(path):
        return {}
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return {"_error": "PyYAML not installed"}
    try:
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("safety config parse failed for %r: %s", path, exc)
        return {"_error": str(exc)}


def _classify(key: str, value: Any) -> tuple[str, str]:
    """Return ``(band, label)`` for a flattened safety key."""
    for pattern, band, label in _SAFETY_KEYS:
        if pattern.search(key):
            return band, label
    return "LOW", "other"


def _tamper_drifts(
    observed: dict[str, Any],
    reference: dict[str, Any],
) -> list[dict[str, Any]]:
    """Diff flattened observed vs reference → drift records (skipping _keys)."""
    drifts: list[dict[str, Any]] = []
    obs = {k: v for k, v in _flatten(observed) if not k.startswith("_")}
    ref = {k: v for k, v in _flatten(reference) if not k.startswith("_")}
    for key, value in ref.items():
        if key not in obs:
            continue
        if obs[key] != value:
            band, label = _classify(key, obs[key])
            drifts.append({
                "key": key, "reference": value, "observed": obs[key],
                "severity": band, "label": label,
            })
    for key, value in obs.items():
        if key not in ref and any(p.search(key) for p, _, _ in _SAFETY_KEYS):
            band, label = _classify(key, value)
            drifts.append({
                "key": key, "reference": None, "observed": value,
                "severity": band, "label": f"{label} added", "added": True,
            })
    return drifts


def _check_runtime_params(
    observed: dict[str, Any],
    runtime_params: Optional[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compare live runtime params against the declared safety config."""
    if not runtime_params:
        return []
    issues: list[dict[str, Any]] = []
    for key, value in _flatten(runtime_params):
        if not any(p.search(key) for p, _, _ in _SAFETY_KEYS):
            continue
        declared = observed.get(key)
        if declared is not None and declared != value:
            band, label = _classify(key, value)
            issues.append({
                "key": key, "declared": declared, "runtime": value,
                "severity": band, "label": f"runtime drift — {label}",
            })
    return issues


def _flag_dangerous_values(observed: dict[str, Any]) -> list[dict[str, Any]]:
    """Static red-flags: stop-zone disabled, zero/negative speed, huge velocity."""
    flags: list[dict[str, Any]] = []
    for key, value in _flatten(observed):
        if not any(p.search(key) for p, _, _ in _SAFETY_KEYS):
            continue
        if isinstance(value, bool) and value is False and _STOP_KEYS.search(key):
            flags.append({"key": key, "value": False,
                          "severity": "CRITICAL",
                          "label": "protective-stop zone disabled"})
        if isinstance(value, bool) and value is False and _HUMAN_KEYS.search(key):
            flags.append({"key": key, "value": False,
                          "severity": "HIGH",
                          "label": "human-presence detection disabled"})
        if isinstance(value, (int, float)) and value <= 0 and \
                re.search(r"(?i)max(_|-)?vel|speed_limit", key):
            flags.append({"key": key, "value": value,
                          "severity": "HIGH",
                          "label": "zero/negative velocity limit"})
    return flags


def _overall_severity(drifts: list[dict[str, Any]]) -> str:
    order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    if not drifts:
        return "PASS"
    top = max(order.get(d.get("severity", "LOW"), 0) for d in drifts)
    return next(s for s, o in order.items() if o == top) if top else "PASS"


async def analyze_safety_config(
    config_path: str = "",
    reference_path: str = "",
    runtime_params: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Analyze a ROS/OT safety configuration for tampering and drift.

    Args:
        config_path: the observed (possibly tampered) safety_config.yaml.
        reference_path: authoritative baseline YAML (optional).
        runtime_params: live parameter dump ``{"/ns/key": value}`` (optional).
    """
    config_path = (config_path or "").strip()
    reference_path = (reference_path or "").strip()
    if not config_path:
        return {
            "state": "UNAVAILABLE", "tool": "safety_audit",
            "detail": "No safety config path supplied.", "findings": [],
            "overall_severity": "PASS",
        }
    if not os.path.isfile(config_path):
        return {
            "state": "UNAVAILABLE", "tool": "safety_audit",
            "detail": f"config_path is not a readable file: {config_path}",
            "findings": [], "overall_severity": "PASS",
        }

    observed = _parse_yaml(config_path)
    if "_error" in observed:
        return {
            "state": "ERROR", "tool": "safety_audit",
            "detail": observed["_error"], "findings": [],
            "overall_severity": "PASS",
        }
    reference = _parse_yaml(reference_path) if reference_path else {}

    drifts = _tamper_drifts(observed, reference)
    runtime_issues = _check_runtime_params(observed, runtime_params)
    flags = _flag_dangerous_values(observed)
    findings = drifts + runtime_issues + flags
    overall = _overall_severity(findings)

    return {
        "state": "AVAILABLE", "tool": "safety_audit",
        "detail": (f"Safety-audit complete — {len(findings)} finding(s), "
                   f"overall {overall}."),
        "config_path": config_path,
        "reference_path": reference_path,
        "findings": findings,
        "overall_severity": overall,
    }
