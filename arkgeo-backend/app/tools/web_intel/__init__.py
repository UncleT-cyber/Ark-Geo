"""Web-intelligence tools — hardened retrieval and managed browsing.

Public surface:

* :mod:`guard` — the egress/SSRF security boundary.
* :mod:`fetcher` — static HTTP retrieval + extraction.
* :mod:`browser` — managed Playwright/Chromium runtime.
* :mod:`tools` — the ``web.*`` / ``browser.*`` catalogue handlers.
"""
from __future__ import annotations

from . import browser, fetcher, guard, tools  # noqa: F401

__all__ = ["guard", "fetcher", "browser", "tools"]
