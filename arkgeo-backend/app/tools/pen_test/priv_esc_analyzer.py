"""Privilege-escalation analyzer — local host enumeration on an authorized box.

Scoped, read-only enumeration of the classic privilege-escalation primitives
on the ARK host (or a target root the operator owns): sudo policy, SUID/SGID
binaries, world-writable files, effective capabilities, and CTF flag files
(``user.txt`` / ``root.txt``) inside a bounded search root.

This is a **post-exploitation-style audit on your own / authorized system** —
the RE-ACT chain's Escalate phase uses it to confirm or dismiss elevation
primitive findings, never to attack a third party.

Honest degradation: ``find`` / ``sudo`` presence is checked; anything the OS
blocks (e.g. sudo requiring a password) is reported as such, never fabricated.
``dry_run=True`` returns a labelled simulated result.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

_FLAG_NAMES = ("user.txt", "root.txt", "flag.txt", "flag")

# Sub-paths skipped during the flag hunt (bounded traversal).
_SKIP_DIRS = {"/proc", "/sys", "/dev", "/private/var/folders", "/System"}


async def _run(argv: list[str], timeout: int) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise TimeoutError(f"enumeration exceeded {timeout}s timeout")
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


def _parse_sudo_l(text: str) -> list[str]:
    """Extract the commands a user may run from ``sudo -l -n`` output."""
    lines = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped or "may run the following" in stripped:
            continue
        if stripped.startswith("User ") and "may run" in stripped:
            continue
        lines.append(stripped)
    return lines[:50]


def _parse_suid(text: str) -> list[str]:
    return [ln for ln in (text or "").splitlines() if ln.strip()][:200]


def _find_flags(root: str, timeout: int) -> list[str]:
    """Bounded hunt for CTF-style flag files under ``root``."""
    found: list[str] = []
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames
                           if os.path.join(dirpath, d) not in _SKIP_DIRS]
            for fname in filenames:
                base = fname.lower()
                if any(base == flag or base.endswith(f".{flag}")
                       for flag in _FLAG_NAMES):
                    found.append(os.path.join(dirpath, fname))
                    if len(found) >= 25:
                        return found
            if len(found) >= 25:
                return found
    except (OSError, PermissionError) as exc:
        logger.warning("flag hunt under %s: %s", root, exc)
    return found


async def _build_enumeration(target_root: str, timeout: int) -> dict[str, Any]:
    """Run the bounded local enumeration; every failure degrades honestly."""
    findings: dict[str, Any] = {}
    if shutil.which("find") is not None:
        suid_cmd = ["find", target_root, "-type", "f", "-perm", "-4000"]
        ww_cmd = ["find", target_root, "-type", "f", "-perm", "-002"]

        code, out, err = await _run(suid_cmd, timeout)
        findings["suid_binaries"] = _parse_suid(out) if code == 0 and out.strip() else []

        code, out, err = await _run(ww_cmd, timeout)
        findings["world_writable_files"] = (
            _parse_suid(out)[:100] if code == 0 and out.strip() else [])
    else:
        findings["suid_binaries"] = []
        findings["world_writable_files"] = []

    if shutil.which("sudo") is not None:
        code, out, err = await _run(["sudo", "-l", "-n"], timeout)
        if code == 0 and out.strip():
            findings["sudo_policy"] = _parse_sudo_l(out)
        elif "password" in err.lower():
            findings["sudo_policy"] = []
            findings["sudo_note"] = ("sudo requires a password non-interactively "
                                     "— policy not readable without credentials")
        else:
            findings["sudo_policy"] = []
    else:
        findings["sudo_policy"] = []

    findings["flags"] = await asyncio.to_thread(_find_flags, target_root, timeout)
    return findings


def _severity(findings: dict[str, Any]) -> str:
    if findings.get("flags"):
        return "HIGH"
    if findings.get("suid_binaries") or findings.get("world_writable_files"):
        return "MEDIUM"
    return "LOW"


async def _simulated(target_root: str) -> dict[str, Any]:
    return {
        "state": "AVAILABLE", "tool": "priv_esc_analyzer",
        "detail": "Simulated privilege-escalation enumeration (dry_run) — no "
                  "system commands executed.",
        "simulated": True,
        "target_root": target_root,
        "findings": {
            "suid_binaries": [], "world_writable_files": [],
            "sudo_policy": [], "flags": [],
        },
        "severity": "LOW",
    }


async def analyze_privilege_escalation(
    target_root: str = "/",
    timeout: int = 30,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Enumerate local privilege-escalation primitives (authorized host only).

    Args:
        target_root: filesystem root to bound the SUID / world-writable / flag
            search (default ``/``; pass a smaller root for speed).
        timeout: per-command subprocess timeout seconds.
        dry_run: return a labelled simulated result (no commands executed).
    """
    target_root = (target_root or "/").strip()
    if dry_run:
        return await _simulated(target_root)

    if not os.path.isdir(target_root):
        return {
            "state": "UNAVAILABLE", "tool": "priv_esc_analyzer",
            "detail": f"target_root is not a readable directory: {target_root}",
            "findings": {}, "severity": "LOW",
        }
    started = time.perf_counter()
    try:
        findings = await _build_enumeration(target_root, timeout)
    except Exception as exc:  # noqa: BLE001
        logger.warning("priv-esc enumeration failed: %s", exc)
        return {
            "state": "ERROR", "tool": "priv_esc_analyzer",
            "detail": f"Enumeration failed: {type(exc).__name__}",
            "findings": {}, "severity": "LOW",
        }
    elapsed = int((time.perf_counter() - started) * 1000)
    return {
        "state": "AVAILABLE", "tool": "priv_esc_analyzer",
        "detail": "Privilege-escalation enumeration complete.",
        "target_root": target_root,
        "findings": findings,
        "severity": _severity(findings),
        "elapsed_ms": elapsed,
    }
