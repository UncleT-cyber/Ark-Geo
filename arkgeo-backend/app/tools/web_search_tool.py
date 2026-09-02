"""Web search tool — Tavily primary, keyless DuckDuckGo fallback.

Headless OSINT capability for the orchestrator's iterative loop
(``web_search`` → ``web_fetch`` → parse HTML → verified location).  Tavily is
used when a ``tavily_api_key`` is configured; otherwise the keyless
DuckDuckGo HTML endpoint keeps the tool usable without any key.  Results are
returned as structured dicts; a missing key or a failed provider degrades to
an honest ``UNAVAILABLE``/``ERROR`` state — nothing is fabricated.
"""
from __future__ import annotations

import html as html_mod
import logging
import re
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import httpx

from app.core.config import settings
from app.services.settings_store import settings_store

logger = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"
DDG_URL = "https://html.duckduckgo.com/html/"

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 "
    "ArkGeo/0.1"
)

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", re.S | re.I)
_WS_RE = re.compile(r"[ \t\r\f\v]+")


def _tavily_key() -> Optional[str]:
    return settings_store.get_key("tavily_api_key") or settings.tavily_api_key


async def _tavily_search(query: str, max_results: int, search_depth: str) -> Optional[dict[str, Any]]:
    key = _tavily_key()
    if not key:
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                TAVILY_URL,
                headers={
                    "Authorization": f"Bearer {key}",
                    "x-api-key": key,
                    "Content-Type": "application/json",
                },
                json={
                    "query": query,
                    "max_results": max_results,
                    "search_depth": search_depth,
                    "include_answer": True,
                    "include_raw_content": False,
                },
            )
        if r.status_code != 200:
            logger.warning("Tavily search HTTP %s for %r", r.status_code, query)
            return None
        data = r.json() or {}
    except Exception as exc:  # noqa: BLE001 — degrade, never crash
        logger.warning("Tavily search failed for %r: %s", query, exc)
        return None
    results = []
    for item in data.get("results") or []:
        results.append({
            "title": item.get("title"),
            "url": item.get("url"),
            "content": item.get("content"),
            "score": item.get("score"),
        })
    return {
        "provider": "tavily",
        "query": query,
        "answer": data.get("answer"),
        "results": results,
        "total": len(results),
    }


def _unescape(text: str) -> str:
    return html_mod.unescape(text or "")


def _parse_ddg(html_text: str, max_results: int) -> list[dict[str, str]]:
    """Parse DuckDuckGo's HTML result page (no external dependency)."""
    results: list[dict[str, str]] = []
    for block in re.split(r'<div class="result', html_text)[1:]:
        link_m = re.search(r'class="result__a"[^>]*href="([^"]+)"', block)
        title_m = re.search(r'class="result__a"[^>]*>(.*?)</a>', block, re.S)
        if not (link_m and title_m):
            continue
        raw = link_m.group(1).replace("&amp;", "&")
        url = raw if raw.startswith("http") else f"https:{raw.lstrip('/')}"
        if "/l/?uddg=" in url:
            qs = parse_qs(urlparse(url).query)
            if qs.get("uddg"):
                url = qs["uddg"][0]
        title = _unescape(_TAG_RE.sub("", title_m.group(1))).strip()
        snippet = ""
        snip_m = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', block, re.S)
        if snip_m:
            snippet = _unescape(_TAG_RE.sub("", snip_m.group(1))).strip()
        if title or url:
            results.append({"title": title, "url": url, "content": snippet})
        if len(results) >= max_results:
            break
    return results


async def _ddg_search(query: str, max_results: int) -> Optional[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(
            timeout=15, follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            r = await client.post(DDG_URL, data={"q": query})
        if r.status_code != 200:
            logger.warning("DuckDuckGo search HTTP %s for %r", r.status_code, query)
            return None
        html_text = r.text
    except Exception as exc:  # noqa: BLE001
        logger.warning("DuckDuckGo search failed for %r: %s", query, exc)
        return None
    results = _parse_ddg(html_text, max_results)
    if not results:
        return None
    return {
        "provider": "duckduckgo",
        "query": query,
        "answer": None,
        "results": results,
        "total": len(results),
    }


async def web_search(
    query: str,
    max_results: int = 5,
    search_depth: str = "basic",
) -> dict[str, Any]:
    """Web search via Tavily when keyed, else the keyless DuckDuckGo HTML page."""
    query = (query or "").strip()
    max_results = max(1, min(int(max_results or 5), 10))
    if not query:
        return {
            "state": "UNAVAILABLE", "provider": None, "query": query,
            "detail": "No query supplied.", "answer": None, "results": [], "total": 0,
        }
    if _tavily_key():
        res = await _tavily_search(query, max_results, search_depth)
        if res is not None:
            return {"state": "AVAILABLE", "detail": "Tavily search completed.", **res}
        return {
            "state": "ERROR", "provider": "tavily", "query": query,
            "detail": "Tavily search failed — provider returned no usable results.",
            "answer": None, "results": [], "total": 0,
        }
    res = await _ddg_search(query, max_results)
    if res is not None:
        return {"state": "AVAILABLE", "detail": "DuckDuckGo keyless search completed.", **res}
    return {
        "state": "UNAVAILABLE", "provider": None, "query": query,
        "detail": (
            "No web search provider available (no Tavily key configured and the "
            "keyless DuckDuckGo fallback failed)."
        ),
        "answer": None, "results": [], "total": 0,
    }


def _extract_title(html_text: str) -> Optional[str]:
    m = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.S | re.I)
    if not m:
        return None
    return _unescape(_TAG_RE.sub("", m.group(1))).strip() or None


def _strip_html(html_text: str) -> str:
    text = _SCRIPT_STYLE_RE.sub(" ", html_text or "")
    text = _TAG_RE.sub(" ", text)
    text = _unescape(text)
    return _WS_RE.sub(" ", text).strip()


async def web_fetch(url: str, max_chars: int = 8000) -> dict[str, Any]:
    """Fetch a public HTTP(S) page and return its title + trimmed visible text."""
    url = (url or "").strip()
    max_chars = max(200, min(int(max_chars or 8000), 50000))
    if not url.startswith(("http://", "https://")):
        return {
            "state": "UNAVAILABLE", "url": url,
            "detail": "URL must start with http:// or https://.",
            "title": None, "text": "",
        }
    try:
        async with httpx.AsyncClient(
            timeout=15, follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            r = await client.get(url)
        r.raise_for_status()
        html_text = r.text
    except Exception as exc:  # noqa: BLE001
        return {
            "state": "ERROR", "url": url,
            "detail": f"Fetch failed: {type(exc).__name__}",
            "title": None, "text": "",
        }
    return {
        "state": "AVAILABLE", "url": url, "detail": "Page fetched.",
        "title": _extract_title(html_text),
        "text": _strip_html(html_text)[:max_chars],
    }
