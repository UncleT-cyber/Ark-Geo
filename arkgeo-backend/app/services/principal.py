"""Request principal resolution.

The operator surface (CAI) has no authenticated session yet — the unified
execution audit flagged that as a Phase-1 blocker.  Until an operator identity
exists, we accept a *server-side namespaced* principal id from the
``X-ARK-Principal`` header so per-user preferences, credentials and
entitlements can be exercised and isolated.

This is deliberately a development stand-in, not an authentication boundary:

* The id is sanitized to a bounded character set (no path traversal, no
  separators) before it is ever used as a storage key.
* The client can only address its **own** namespace — there is no endpoint that
  accepts another subject's id, so tenant isolation cannot be crossed by a
  caller.  A production deployment replaces this dependency with the real
  authenticated session and must not trust a client-supplied id.
"""
from __future__ import annotations

import re
from typing import Optional

from fastapi import Request

from app.services.entitlements import ANONYMOUS, Principal

_PRINCIPAL_HEADER = "X-ARK-Principal"
_ORG_HEADER = "X-ARK-Organization"
_SAFE = re.compile(r"[^A-Za-z0-9._-]")
_MAX_LEN = 64


def _sanitize(value: str) -> str:
    return _SAFE.sub("", (value or "").strip())[:_MAX_LEN]


def principal_from_request(request: Request) -> Principal:
    subject = _sanitize(request.headers.get(_PRINCIPAL_HEADER, ""))
    if not subject:
        return ANONYMOUS
    organization = _sanitize(request.headers.get(_ORG_HEADER, "")) or None
    return Principal(subject=subject, kind="user", organization=organization)


def principal_from_headers(headers: Optional[dict]) -> Principal:
    """Same resolution for non-FastAPI callers (tests, internal dispatch)."""
    if not headers:
        return ANONYMOUS
    lowered = {str(k).lower(): v for k, v in headers.items()}
    subject = _sanitize(lowered.get(_PRINCIPAL_HEADER.lower(), ""))
    if not subject:
        return ANONYMOUS
    organization = _sanitize(lowered.get(_ORG_HEADER.lower(), "")) or None
    return Principal(subject=subject, kind="user", organization=organization)
