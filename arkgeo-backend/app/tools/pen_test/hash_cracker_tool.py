"""Hash cracker tool — offline hash-format recovery against an explicit wordlist.

Wraps the local ``hashcat`` binary (John the Ripper as a secondary fallback)
to recover the plaintext of a **single offline hash** against an explicit
wordlist. There is no remote target: the hash is already in the investigator's
possession (extracted from an artifact / config dump during an authorized
engagement). The tool never generates its own password guessing beyond the
wordlist supplied, and it refuses to fabricate a plaintext.

Degradation contract:

* no cracker binary → ``TOOL_MISSING`` with install guidance
* no wordlist configured → ``UNAVAILABLE``
* hash ran but not cracked → ``UNCRACKED`` (honest — no fabrication)
* parse/execution failure → ``ERROR``

``dry_run=True`` returns a labelled simulated outcome for offline chains.
"""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Heuristic hash-type detection for common formats (hashcat mode numbers).
_HASH_GUESSES: list[tuple[re.Pattern, int, str]] = [
    (re.compile(r"^[0-9a-f]{32}$", re.I), 0, "MD5"),
    (re.compile(r"^[0-9a-f]{40}$", re.I), 100, "SHA1"),
    (re.compile(r"^[0-9a-f]{56}$", re.I), 1400, "SHA256"),
    (re.compile(r"^[0-9a-f]{64}$", re.I), 1400, "SHA256"),
    (re.compile(r"^[0-9a-f]{128}$", re.I), 1700, "SHA512"),
    (re.compile(r"^\\$2[aby]\\$", re.I), 3200, "bcrypt"),
    (re.compile(r"^\\$6\\$", re.I), 1800, "sha512crypt"),
    (re.compile(r"^\\$1\\$", re.I), 500, "md5crypt"),
]

_HASHCAT_MODES = {"0": "MD5", "100": "SHA1", "500": "md5crypt", "1400": "SHA256",
                  "1700": "SHA512", "1800": "sha512crypt", "3200": "bcrypt"}
_JOHN_FORMATS = {"0": "Raw-MD5", "100": "Raw-SHA1", "1400": "Raw-SHA256",
                 "1700": "Raw-SHA512", "500": "md5crypt", "1800": "sha512crypt",
                 "3200": "bcrypt"}


def _guess_hash_type(hash_value: str, hash_type: str) -> tuple[int, str]:
    """Return ``(mode, label)`` — explicit hash_type wins over heuristics."""
    explicit = hash_type.strip().lower()
    if explicit in _HASHCAT_MODES:
        return int(explicit), _HASHCAT_MODES[explicit]
    for name, mode in (("md5", 0), ("sha1", 100), ("sha256", 1400),
                       ("sha512", 1700), ("bcrypt", 3200), ("md5crypt", 500),
                       ("sha512crypt", 1800)):
        if name == explicit:
            return mode, _HASHCAT_MODES[str(mode)]
    for pattern, mode, label in _HASH_GUESSES:
        if pattern.match(hash_value.strip()):
            return mode, label
    return 0, "MD5"


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
        raise TimeoutError(f"cracker exceeded {timeout}s timeout")
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


async def _crack_hashcat(hash_value: str, mode: int, wordlist: str,
                         timeout: int) -> tuple[bool, str]:
    args = ["hashcat", "-m", str(mode), "-a", "0", "--potfile-disable",
            "-o", "-", hash_value, wordlist]
    code, out, err = await _run(args, timeout)
    if code not in (0, 1):  # 1 = exhausted without cracking
        return False, f"hashcat exited {code}: {err.strip()[:300]}"
    match = re.search(r"^[^:]*:([^:\r\n]+)$", out, re.M)
    if match:
        return True, match.group(1).strip()
    if ":digits" not in out and len(out.strip()) > 4 and "Hash-mode" not in out:
        return False, "hashcat completed — not cracked"
    return False, "hashcat completed — not cracked"


async def _crack_john(hash_value: str, mode: int, wordlist: str,
                      timeout: int) -> tuple[bool, str]:
    fmt = _JOHN_FORMATS.get(str(mode), "Raw-MD5")
    args = ["john", f"--format={fmt}", f"--wordlist={wordlist}",
            "--pot", "-", hash_value]
    code, out, err = await _run(args, timeout)
    if code != 0 and "No password hashes" not in err:
        return False, f"john exited {code}: {err.strip()[:300]}"
    if re.search(r"(cracked|password hash(es)? cracked)", err, re.I):
        m = re.search(r"([^:\s]+)\s+\(\S+\)", err)
        return (True, m.group(1)) if m else (True, "cracked")
    return False, "john completed — not cracked"


async def _simulated(hash_value: str, wordlist: str) -> dict[str, Any]:
    return {
        "state": "UNCRACKED", "tool": "hash_cracker",
        "detail": "Simulated offline crack (dry_run) — no cracker executed.",
        "simulated": True,
        "hash_value": hash_value, "wordlist": wordlist,
        "cracked": False, "plaintext": None,
    }


async def crack_hash(
    hash_value: str = "",
    hash_type: str = "auto",
    wordlist: str = "",
    timeout: int = 60,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Crack a single offline hash against an explicit wordlist.

    Args:
        hash_value: the hash to recover (offline artifact).
        hash_type: ``auto`` or an explicit mode/label (md5, sha1, sha256,
            sha512, bcrypt, md5crypt, sha512crypt, or hashcat mode number).
        wordlist: path to a wordlist file to try.
        timeout: cracker timeout in seconds.
        dry_run: return a labelled simulated outcome (no cracker executed).
    """
    hash_value = (hash_value or "").strip()
    wordlist = (wordlist or "").strip()

    if not hash_value:
        return {
            "state": "UNAVAILABLE", "tool": "hash_cracker",
            "detail": "No hash value supplied.", "cracked": False,
            "plaintext": None,
        }
    if not wordlist:
        return {
            "state": "UNAVAILABLE", "tool": "hash_cracker",
            "detail": "No wordlist path supplied — supply the path to a wordlist "
                      "file (e.g. /usr/share/wordlists/rockyou.txt).",
            "cracked": False, "plaintext": None,
        }
    if dry_run:
        return await _simulated(hash_value, wordlist)

    mode, label = _guess_hash_type(hash_value, hash_type)
    cracker = "hashcat" if shutil.which("hashcat") else (
        "john" if shutil.which("john") else None)
    if cracker is None:
        return {
            "state": "TOOL_MISSING", "tool": "hash_cracker",
            "detail": "Neither hashcat nor john is installed on the ARK host. "
                      "Install hashcat ('brew install hashcat') to enable "
                      "offline cracking.",
            "hash_value": hash_value, "hash_type": label, "cracked": False,
            "plaintext": None,
        }

    started = time.perf_counter()
    try:
        if cracker == "hashcat":
            cracked, detail = await _crack_hashcat(hash_value, mode, wordlist, timeout)
        else:
            cracked, detail = await _crack_john(hash_value, mode, wordlist, timeout)
    except TimeoutError as exc:
        return {
            "state": "ERROR", "tool": "hash_cracker",
            "detail": str(exc), "cracked": False, "plaintext": None,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("hash crack failed: %s", exc)
        return {
            "state": "ERROR", "tool": "hash_cracker",
            "detail": f"Cracker execution failed: {type(exc).__name__}",
            "cracked": False, "plaintext": None,
        }
    elapsed = int((time.perf_counter() - started) * 1000)
    return {
        "state": "AVAILABLE" if cracked else "UNCRACKED",
        "tool": "hash_cracker",
        "detail": (f"{cracker} {label} crack {'succeeded' if cracked else 'not cracked'}: "
                   f"{detail}") if cracked else (
            f"{cracker} {label} run complete — {detail}"),
        "hash_value": hash_value, "hash_type": label, "cracker": cracker,
        "wordlist": wordlist,
        "cracked": cracked, "plaintext": detail if cracked else None,
        "elapsed_ms": elapsed,
    }
