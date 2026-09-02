"""ROS inspector tool — node graph + parameter surface for ROS 1 / ROS 2.

Introspects a live ROS system through the local toolchain: for ROS 1 that is
``rosnode`` / ``rostopic`` / ``rosparam``; for ROS 2 it is ``ros2 node`` /
``ros2 topic`` / ``ros2 param``. Optionally parses a ``safety_config.yaml`` to
correlate the declared safety envelope with the live graph.

Honest degradation (mirrors the ARK tool contract): a missing toolchain or an
unsourced workspace returns ``TOOL_MISSING`` / ``UNAVAILABLE`` with actionable
detail; command failures return ``ERROR``. ``dry_run=True`` returns a labelled
simulated graph for offline chains.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

_ROS1_CMDS = {
    "nodes": ["rosnode", "list"],
    "topics": ["rostopic", "list", "-v"],
    "params": ["rosparam", "list"],
}
_ROS2_CMDS = {
    "nodes": ["ros2", "node", "list"],
    "topics": ["ros2", "topic", "list"],
    "params": ["ros2", "param", "list"],
}


async def _run(argv: list[str], timeout: int) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=os.environ.copy(),
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise TimeoutError(f"ROS introspection exceeded {timeout}s timeout")
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


def _safety_keys(path: str) -> dict[str, Any]:
    """Best-effort parse of a safety_config.yaml into a flat dict."""
    if not path or not os.path.isfile(path):
        return {}
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return {"_note": "PyYAML not installed — raw view only"}
    try:
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("safety config parse failed for %r: %s", path, exc)
        return {"_error": str(exc)}


def _parse_topic_lines(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("Published topics", "Subscribed topics", "Services")):
            continue
        m = re.match(r"^([\w/._:-]+)\s+(\d+)\s+publisher", stripped)
        if m:
            rows.append({"name": m.group(1), "publishers": m.group(2)})
            continue
        m = re.match(r"^([\w/._:-]+)\s+(\d+)\s+subscriber", stripped)
        if m:
            rows.append({"name": m.group(1), "subscribers": m.group(2)})
            continue
        rows.append({"name": stripped, "publishers": "", "subscribers": ""})
    return rows[:200]


def _simulated(ros2: bool) -> dict[str, Any]:
    version = "ROS 2" if ros2 else "ROS 1"
    return {
        "state": "AVAILABLE", "tool": "ros_inspector",
        "detail": f"Simulated {version} node-graph introspection (dry_run) — no "
                  "live ROS commands executed.",
        "simulated": True,
        "ros_version": version,
        "nodes": ["/talker", "/listener", "/safety_monitor"],
        "topics": [{"name": "/cmd_vel", "publishers": "1", "subscribers": "1"},
                   {"name": "/odom", "publishers": "1", "subscribers": "1"}],
        "params": {"/safety_monitor/max_velocity": "1.0"},
        "safety_config": {},
        "safety_config_path": None,
    }


async def inspect_ros(
    ros2: bool = False,
    safety_config_path: str = "",
    timeout: int = 20,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Introspect a live ROS node graph + parameter surface.

    Args:
        ros2: introspect a ROS 2 system (default ROS 1).
        safety_config_path: optional ``safety_config.yaml`` to parse alongside.
        timeout: per-command subprocess timeout seconds.
        dry_run: return a labelled simulated graph (no ROS commands executed).
    """
    ros2 = bool(ros2)
    safety_config_path = (safety_config_path or "").strip()
    if dry_run:
        return _simulated(ros2)

    version = "ROS 2" if ros2 else "ROS 1"
    commands = _ROS2_CMDS if ros2 else _ROS1_CMDS
    probe = commands["nodes"][0]
    if shutil.which(probe) is None:
        return {
            "state": "TOOL_MISSING", "tool": "ros_inspector",
            "detail": (f"{probe} is not on PATH — the ROS {'2' if ros2 else '1'} "
                       f"environment is not sourced. Source the workspace "
                       f"('source install/setup.bash' or 'source devel/setup.bash') "
                       f"or install the ROS toolchain on the ARK host."),
            "ros_version": version, "nodes": [], "topics": [],
            "params": {}, "safety_config": {},
            "safety_config_path": safety_config_path,
        }

    results: dict[str, Any] = {}
    for section, argv in commands.items():
        try:
            code, out, err = await _run(argv, timeout)
        except TimeoutError as exc:
            results[section] = {"error": str(exc)}
            continue
        except Exception as exc:  # noqa: BLE001
            results[section] = {"error": type(exc).__name__}
            continue
        if code != 0:
            results[section] = {"error": err.strip()[:300] or f"exit {code}"}
        else:
            results[section] = {"raw": out.strip()}

    nodes = [ln.strip() for ln in
             results.get("nodes", {}).get("raw", "").splitlines() if ln.strip()]
    topics = _parse_topic_lines(results.get("topics", {}).get("raw", ""))
    params_raw = results.get("params", {}).get("raw", "")
    params: dict[str, str] = {}
    for ln in params_raw.splitlines():
        ln = ln.strip()
        if ln:
            parts = ln.split("/")
            params[ln] = "set" if len(parts) >= 2 else "unset"
    safety_config = _safety_keys(safety_config_path)

    return {
        "state": "AVAILABLE", "tool": "ros_inspector",
        "detail": f"{version} introspection complete — {len(nodes)} node(s), "
                  f"{len(topics)} topic row(s).",
        "ros_version": version,
        "nodes": nodes,
        "topics": topics,
        "params": params,
        "safety_config": safety_config,
        "safety_config_path": safety_config_path,
        "errors": {k: v for k, v in results.items() if "error" in v},
    }
