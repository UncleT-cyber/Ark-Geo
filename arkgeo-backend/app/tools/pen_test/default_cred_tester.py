"""Default-credential tester — authorized factory-default credential checks.

Probes a single, explicitly authorized web target for a small, fixed set of
**factory-default** credentials (vendor manuals, not a wordlist). Two
mechanisms are supported: HTTP Basic auth and the common HTML login form.

Safety contract:

* **Authorization is mandatory** — the tool refuses to run (``UNAUTHORIZED``
  state) unless ``authorized=True`` is passed. The RE-ACT chain only passes
  ``True`` when the target is inside the operator's declared engagement scope
  (attestation / authorization allowlist).
* **Tiny, fixed attempt set** (≈10 combos) — this is a default-credential
  check, not a brute-force spray. No dictionary is used, no lockout risk.
* **Rate limiting** — a short inter-attempt delay keeps the probe gentle.
* **Honest degradation** — network failure / non-HTTP target returns
  ``ERROR``/``UNAVAILABLE``; per-credential outcomes are reported individually.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 "
    "ArkGeo/0.1"
)

# Fixed factory-default credential set (small, curated — not a wordlist).
_DEFAULT_CREDS: dict[str, list[tuple[str, str]]] = {
    "generic": [
        ("admin", "admin"), ("admin", "password"), ("admin", "1234"),
        ("admin", "12345"), ("admin", ""), ("root", "toor"),
        ("root", "password"), ("admin", "root"), ("administrator", "admin"),
        ("user", "user"),
    ],
    "web": [
        ("admin", "admin"), ("admin", "password"), ("admin", ""),
        ("admin", "123456"), ("root", "root"), ("test", "test"),
    ],
    "router": [
        ("admin", "admin"), ("admin", "password"), ("admin", "1234"),
        ("root", "12345"), ("cisco", "cisco"), ("admin", ""),
    ],
    "cctv": [
        ("admin", "admin"), ("admin", "12345"), ("admin", "123456"),
        ("root", "root"), ("admin", "4321"), ("admin", "9999"),
    ],
    "iot": [
        ("admin", "admin"), ("admin", "password"), ("root", "root"),
        ("admin", "1234"), ("user", "user"), ("admin", "root"),
    ],
}

# Form-field shapes tried in order; the first matching field set wins.
_FORM_FIELDS = (
    ("username", "password"),
    ("user", "pass"),
    ("login", "passwd"),
    ("email", "password"),
)

_LOGIN_FAIL_HINTS = (
    "invalid", "incorrect", "failed", "error", "wrong", "denied", "unauthor",
)

_MAX_ATTEMPTS = 12
_RATE_LIMIT_MS = 250


def _looks_like_login_form(html: str) -> bool:
    """Heuristic: the page carries an HTML password input + form action."""
    lowered = (html or "").lower()
    if "password" not in lowered and "passwd" not in lowered:
        return False
    return "<form" in lowered and "action=" in lowered


def _target_url_valid(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _is_success_response(resp: httpx.Response, body: str) -> bool:
    """Best-effort login-success heuristic for form submissions."""
    if resp.status_code in (301, 302, 303, 307, 308):
        return True  # redirect to a post-login page
    if resp.status_code == 200:
        lowered = body.lower()
        if any(hint in lowered for hint in _LOGIN_FAIL_HINTS):
            return False
        return True
    return False


async def _check_basic(
    client: httpx.AsyncClient,
    url: str,
    username: str,
    password: str,
    timeout: int,
) -> tuple[str, str]:
    try:
        resp = await client.get(url, auth=(username, password), timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return "unknown", f"request failed: {type(exc).__name__}"
    if resp.status_code in (200, 204, 301, 302, 303, 307, 308):
        return "success", f"HTTP {resp.status_code} after authenticated request"
    if resp.status_code == 401:
        return "failed", "HTTP 401 — credentials rejected"
    return "unknown", f"HTTP {resp.status_code}"


async def _check_form(
    client: httpx.AsyncClient,
    url: str,
    username: str,
    password: str,
    timeout: int,
) -> tuple[str, str]:
    """Probe the HTML login form; discover fields from the GET page."""
    try:
        page = await client.get(url, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return "unknown", f"form fetch failed: {type(exc).__name__}"
    if page.status_code >= 400:
        return "unknown", f"form GET returned HTTP {page.status_code}"
    html = page.text
    if "password" not in html.lower() and "passwd" not in html.lower():
        return "unknown", "no password field detected on the page"
    data: dict[str, str] = {}
    user_field = pass_field = None
    for user_cand, pass_cand in _FORM_FIELDS:
        if f'name="{pass_cand}"' in html or f"name='{pass_cand}'" in html:
            user_field, pass_field = user_cand, pass_cand
            break
    if not pass_field:
        user_field, pass_field = "username", "password"
    data[user_field] = username
    data[pass_field] = password
    try:
        resp = await client.post(url, data=data, follow_redirects=True, timeout=timeout)
        body = resp.text
    except Exception as exc:  # noqa: BLE001
        return "unknown", f"form POST failed: {type(exc).__name__}"
    if _is_success_response(resp, body):
        return "success", "form POST yielded an authenticated response"
    return "failed", "form POST returned an unauthenticated response"


async def _simulated(target_url: str, profile: str, mechanism: str) -> dict[str, Any]:
    creds = _DEFAULT_CREDS.get(profile, _DEFAULT_CREDS["generic"])[:_MAX_ATTEMPTS]
    attempts = []
    for username, password in creds[:4]:
        attempts.append({
            "username": username, "password": password, "mechanism": mechanism,
            "outcome": "failed", "detail": "simulated — credentials rejected",
        })
    return {
        "state": "AVAILABLE", "tool": "default_cred_tester",
        "detail": "Simulated default-credential test (dry_run) — no request sent.",
        "simulated": True,
        "target_url": target_url, "profile": profile, "mechanism": mechanism,
        "attempts": attempts,
        "success_count": 0, "total_attempts": len(attempts),
    }


async def test_default_creds(
    target_url: str = "",
    profile: str = "generic",
    mechanism: str = "auto",
    authorized: bool = False,
    timeout: int = 15,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Test factory-default credentials against an authorized web target.

    Args:
        target_url: base http(s) URL of the target (authorized scope).
        profile: ``generic`` | ``web`` | ``router`` | ``cctv`` | ``iot``.
        mechanism: ``auto`` | ``basic`` | ``form``.
        authorized: MUST be ``True`` for any request to be sent. The RE-ACT
            chain passes this only for targets inside the declared scope.
        timeout: per-request timeout seconds.
        dry_run: simulate without sending any request.
    """
    target_url = (target_url or "").strip()
    profile = (profile or "generic").strip().lower()
    mechanism = (mechanism or "auto").strip().lower()

    if not target_url:
        return {
            "state": "UNAVAILABLE", "tool": "default_cred_tester",
            "detail": "No target URL supplied.", "attempts": [],
            "success_count": 0, "total_attempts": 0,
        }
    if not _target_url_valid(target_url):
        return {
            "state": "UNAVAILABLE", "tool": "default_cred_tester",
            "detail": "target_url must be an absolute http(s) URL.",
            "attempts": [], "success_count": 0, "total_attempts": 0,
        }
    if not authorized:
        return {
            "state": "UNAUTHORIZED", "tool": "default_cred_tester",
            "detail": "Refused: target is not inside the declared authorized "
                      "engagement scope (authorized=True is required).",
            "attempts": [], "success_count": 0, "total_attempts": 0,
        }
    if dry_run:
        return await _simulated(target_url, profile, mechanism)

    creds = _DEFAULT_CREDS.get(profile, _DEFAULT_CREDS["generic"])[:_MAX_ATTEMPTS]
    attempts: list[dict[str, Any]] = []
    success_count = 0
    headers = {"User-Agent": _USER_AGENT}
    try:
        async with httpx.AsyncClient(headers=headers, follow_redirects=False) as client:
            # Auto mode first discovers whether an auth boundary exists, so a
            # plain 200 page is never misread as a successful basic-auth login.
            if mechanism == "auto":
                probe = await client.get(target_url, timeout=timeout)
                if probe.status_code == 401:
                    mechanism = "basic"
                elif probe.status_code < 400 and _looks_like_login_form(probe.text):
                    mechanism = "form"
                elif probe.status_code >= 400:
                    return {
                        "state": "ERROR", "tool": "default_cred_tester",
                        "detail": f"Target unreachable — HTTP {probe.status_code}.",
                        "target_url": target_url, "attempts": [],
                        "success_count": 0, "total_attempts": 0,
                    }
                else:
                    return {
                        "state": "AVAILABLE", "tool": "default_cred_tester",
                        "detail": "No authentication boundary detected at the "
                                  "target URL (no 401, no login form) — nothing "
                                  "to test.",
                        "target_url": target_url, "profile": profile,
                        "mechanism": "none", "attempts": [],
                        "success_count": 0, "total_attempts": 0,
                    }

            for username, password in creds:
                if mechanism == "basic":
                    used = "basic"
                    outcome, detail = await _check_basic(
                        client, target_url, username, password, timeout)
                else:
                    used = "form"
                    outcome, detail = await _check_form(
                        client, target_url, username, password, timeout)
                attempts.append({
                    "username": username, "password": password,
                    "mechanism": used,
                    "outcome": outcome, "detail": detail,
                })
                if outcome == "success":
                    success_count += 1
                await asyncio.sleep(_RATE_LIMIT_MS / 1000)
    except Exception as exc:  # noqa: BLE001
        logger.warning("default-cred test failed for %r: %s", target_url, exc)
        return {
            "state": "ERROR", "tool": "default_cred_tester",
            "detail": f"Credential test failed: {type(exc).__name__}",
            "target_url": target_url, "attempts": attempts,
            "success_count": success_count, "total_attempts": len(attempts),
        }

    return {
        "state": "AVAILABLE", "tool": "default_cred_tester",
        "detail": (f"Default-credential test complete — {success_count} "
                   f"successful login(s) out of {len(attempts)} attempts."),
        "target_url": target_url, "profile": profile, "mechanism": mechanism,
        "attempts": attempts,
        "success_count": success_count, "total_attempts": len(attempts),
    }
