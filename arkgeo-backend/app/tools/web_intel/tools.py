"""Web-intelligence catalogue handlers — the ``web.*`` and ``browser.*`` surface.

Thin, structured handlers over :mod:`app.tools.web_intel.fetcher` and
:mod:`app.tools.web_intel.browser`. Registered as first-class ARK substrate tools
in ``app.agent.tool_registry`` so they flow through the existing policy guard,
engagement scope, evidence recorder and unified registry with no new framework.

Every handler returns a plain dict (never raises) so the orchestrator can record
the outcome as evidence and the model can reason about the real result. Search
results are only ever the provider's real output — nothing is fabricated.
"""
from __future__ import annotations

from typing import Any

from . import browser as browser_runtime
from . import fetcher
from . import guard


# --------------------------------------------------------------------------- #
# web.search — reuses the existing Tavily/keyless-DDG provider
# --------------------------------------------------------------------------- #
async def web_search(query: str, max_results: int = 5, search_depth: str = "basic") -> dict[str, Any]:
    """Search the public web (Tavily when keyed, else keyless DuckDuckGo)."""
    from app.tools.web_search_tool import web_search as _impl
    return await _impl(query=query, max_results=max_results, search_depth=search_depth)


# --------------------------------------------------------------------------- #
# web.fetch — hardened static retrieval
# --------------------------------------------------------------------------- #
async def web_fetch(url: str, max_chars: int = 8000, timeout: int = 20) -> dict[str, Any]:
    """Fetch a permitted URL; return readable text + response metadata."""
    result = await fetcher.fetch(url, timeout=timeout)
    payload = result.to_dict()
    payload["text"] = (payload.get("text") or "")[:max_chars]
    return payload


# --------------------------------------------------------------------------- #
# web.extract — readable content + metadata
# --------------------------------------------------------------------------- #
async def web_extract(url: str, max_chars: int = 20000) -> dict[str, Any]:
    """Extract readable main content and page metadata from a URL."""
    result = await fetcher.fetch(url)
    payload = result.to_dict()
    payload["text"] = (payload.get("text") or "")[:max_chars]
    payload["title"] = payload.get("title")
    payload["metadata"] = payload.get("metadata") or {}
    return payload


# --------------------------------------------------------------------------- #
# web.links — hyperlink enumeration
# --------------------------------------------------------------------------- #
async def web_links(url: str, same_host_only: bool = False, limit: int = 200) -> dict[str, Any]:
    """Enumerate hyperlinks on a page, re-validated against the egress guard."""
    limit = max(1, min(int(limit or 200), 1000))
    from urllib.parse import urlsplit
    try:
        body, ctype, final_url = await _fetch_body(url)
    except guard.SSRFBlocked as exc:
        return {"state": "BLOCKED", "ok": False, "code": "ssrf_blocked",
                "url": url, "detail": f"Blocked by egress guard: {exc}",
                "links": [], "total": 0}
    except Exception as exc:  # noqa: BLE001
        return {"state": "ERROR", "ok": False, "url": url,
                "detail": f"link extraction failed: {type(exc).__name__}: {exc}",
                "links": [], "total": 0}
    found = fetcher.enumerate_links(body, ctype, final_url)
    host = urlsplit(url).hostname or ""
    links: list[dict] = []
    for link in found:
        if same_host_only and (urlsplit(link["url"]).hostname or "") != host:
            continue
        try:
            guard.check_url(link["url"])
            link["allowed"] = True
        except guard.SSRFBlocked:
            link["allowed"] = False
        links.append(link)
        if len(links) >= limit:
            break
    return {"state": "AVAILABLE", "ok": True, "url": url, "final_url": final_url,
            "links": links, "total": len(links)}


async def _fetch_body(url: str) -> tuple[bytes, str, str]:
    """Minimal guarded body fetch returning ``(body, content_type, final_url)``."""
    import httpx
    decision = guard.check_url(url)
    dial = guard.pinned_url(decision)
    headers = {"User-Agent": fetcher._USER_AGENT, "Host": decision.host_header}
    async with httpx.AsyncClient(follow_redirects=True, timeout=fetcher.DEFAULT_TIMEOUT) as client:
        from urllib.parse import urlsplit
        req = client.build_request("GET", dial, headers=headers)
        if urlsplit(url).scheme == "https" and urlsplit(url).hostname:
            req.extensions["sni_hostname"] = urlsplit(url).hostname
        resp = await client.send(req)
        return resp.content[: fetcher.DEFAULT_MAX_BYTES], \
            resp.headers.get("content-type", "").split(";", 1)[0].strip(), str(resp.url)


# --------------------------------------------------------------------------- #
# web.document — retrieve + inspect a supported document
# --------------------------------------------------------------------------- #
async def web_document(url: str, max_chars: int = 40000) -> dict[str, Any]:
    """Retrieve a document (PDF / text / JSON) and extract its readable text."""
    result = await fetcher.fetch(url)
    payload = result.to_dict()
    payload["text"] = (payload.get("text") or "")[:max_chars]
    payload["document_kind"] = payload.get("content_kind")
    return payload


# --------------------------------------------------------------------------- #
# browser.* — managed runtime
# --------------------------------------------------------------------------- #
def _unavailable(reason: str) -> dict[str, Any]:
    return {"state": "UNAVAILABLE", "ok": False, "detail": reason,
            "is_live": False}


def _wrap(fn):
    """Run a browser operation, converting runtime errors into classified dicts."""
    async def _inner(*args, **kwargs) -> dict[str, Any]:
        try:
            return await fn(*args, **kwargs)
        except browser_runtime.BrowserUnavailable as exc:
            return _unavailable(str(exc))
        except browser_runtime.SessionNotFound as exc:
            return {"state": "ERROR", "ok": False, "code": "session_not_found",
                    "detail": f"no such browser session: {exc}", "is_live": False}
        except browser_runtime.OperatorInControl as exc:
            return {"state": "ERROR", "ok": False, "code": "operator_in_control",
                    "detail": str(exc), "is_live": False}
        except guard.SSRFBlocked as exc:
            return {"state": "BLOCKED", "ok": False, "code": "ssrf_blocked",
                    "detail": f"Blocked by egress guard: {exc}", "is_live": False}
        except browser_runtime.BrowserError as exc:
            return {"state": "ERROR", "ok": False, "code": "browser_error",
                    "detail": str(exc), "is_live": False}
        except Exception as exc:  # noqa: BLE001
            return {"state": "ERROR", "ok": False,
                    "code": "browser_failure",
                    "detail": f"{type(exc).__name__}: {exc}", "is_live": False}
    return _inner


@_wrap
async def browser_open(url: str = "", investigation_id: str = "", case_id: str = "",
                       run_id: str = "") -> dict[str, Any]:
    """Open a managed browser session (optionally navigating to *url*)."""
    session = await browser_runtime.browser_manager.open(
        investigation_id=investigation_id, case_id=case_id, run_id=run_id, url=url)
    out = session.to_dict()
    out["state"] = "AVAILABLE"
    out["ok"] = True
    out["is_live"] = True
    return out


@_wrap
async def browser_navigate(session_id: str, url: str) -> dict[str, Any]:
    out = await browser_runtime.browser_manager.navigate(session_id, url)
    out.update({"state": "AVAILABLE", "ok": True, "is_live": True})
    return out


@_wrap
async def browser_snapshot(session_id: str) -> dict[str, Any]:
    out = await browser_runtime.browser_manager.snapshot(session_id)
    out.update({"state": "AVAILABLE", "ok": True, "is_live": True})
    return out


@_wrap
async def browser_screenshot(session_id: str, label: str = "", full_page: bool = True) -> dict[str, Any]:
    out = await browser_runtime.browser_manager.screenshot(
        session_id, label=label, full_page=full_page)
    out.update({"state": "AVAILABLE", "ok": True})
    return out


@_wrap
async def browser_extract(session_id: str, selector: str = "") -> dict[str, Any]:
    out = await browser_runtime.browser_manager.extract(session_id, selector=selector)
    out.update({"state": "AVAILABLE", "ok": True, "is_live": True})
    return out


@_wrap
async def browser_click(session_id: str, selector: str) -> dict[str, Any]:
    out = await browser_runtime.browser_manager.click(session_id, selector)
    out.update({"state": "AVAILABLE", "ok": True, "is_live": True})
    return out


@_wrap
async def browser_type(session_id: str, selector: str, text: str, submit: bool = False) -> dict[str, Any]:
    out = await browser_runtime.browser_manager.type(session_id, selector, text, submit=submit)
    out.update({"state": "AVAILABLE", "ok": True, "is_live": True})
    return out


@_wrap
async def browser_scroll(session_id: str, direction: str = "down", amount: int = 800) -> dict[str, Any]:
    out = await browser_runtime.browser_manager.scroll(session_id, direction=direction, amount=amount)
    out.update({"state": "AVAILABLE", "ok": True, "is_live": True})
    return out


@_wrap
async def browser_tabs(session_id: str, action: str = "list", tab_id: str = "") -> dict[str, Any]:
    out = await browser_runtime.browser_manager.tabs(session_id, action=action, tab_id=tab_id)
    out.update({"state": "AVAILABLE", "ok": True, "is_live": True})
    return out


@_wrap
async def browser_history(session_id: str, action: str = "reload") -> dict[str, Any]:
    out = await browser_runtime.browser_manager.history(session_id, action)
    out.update({"state": "AVAILABLE", "ok": True, "is_live": True})
    return out


@_wrap
async def browser_close(session_id: str) -> dict[str, Any]:
    out = await browser_runtime.browser_manager.close(session_id)
    out.update({"state": "AVAILABLE", "ok": True, "is_live": False})
    return out


# -- operator plane -------------------------------------------------------- #
# The operator transport drives the same managed session even while the
# operator holds control; agent-plane ``browser.*`` tools stay suspended then.

@_wrap
async def browser_operator_open(url: str = "", investigation_id: str = "",
                               case_id: str = "") -> dict[str, Any]:
    session = await browser_runtime.browser_manager.open(
        investigation_id=investigation_id or "operator", case_id=case_id, url=url)
    out = session.to_dict()
    out.update({"state": "AVAILABLE", "ok": True, "is_live": True})
    return out


@_wrap
async def browser_operator_navigate(session_id: str, url: str) -> dict[str, Any]:
    out = await browser_runtime.browser_manager.navigate(session_id, url, operator=True)
    out.update({"state": "AVAILABLE", "ok": True, "is_live": True})
    return out


@_wrap
async def browser_operator_history(session_id: str, action: str = "reload") -> dict[str, Any]:
    out = await browser_runtime.browser_manager.history(session_id, action, operator=True)
    out.update({"state": "AVAILABLE", "ok": True, "is_live": True})
    return out


@_wrap
async def browser_operator_capture(session_id: str, label: str = "operator-capture") -> dict[str, Any]:
    out = await browser_runtime.browser_manager.screenshot(
        session_id, label=label, full_page=False, operator=True)
    out.update({"state": "AVAILABLE", "ok": True})
    return out


def browser_status() -> dict[str, Any]:
    """Report runtime availability + live sessions (no side effects)."""
    info = browser_runtime.availability()
    info["sessions"] = browser_runtime.browser_manager.list_sessions()
    return info
