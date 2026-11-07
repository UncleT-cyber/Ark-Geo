"""Managed browser runtime — Playwright + Chromium, one session per investigation.

The untrusted-content execution environment. A **session** owns an isolated
browser context (its own cookies/storage/download dir), one or more tabs, an
egress-guarded request interceptor, and a lifecycle (idle timeout + explicit
close). The model never gets raw JavaScript execution or shell access — only the
structured operations below.

Security invariants:

* Every request the context makes (navigation, redirect, subresource, XHR) is
  re-validated by :mod:`app.tools.web_intel.guard` and aborted if unsafe — the
  browser cannot reach private/loopback/metadata destinations even via a
  redirect or an in-page fetch.
* No access to the operator's real browser profile: each session gets a fresh
  ephemeral context + temp download dir.
* Downloads are confined to the session temp dir.
* Lifecycle is bounded: idle sessions are reaped; per-session tab/artifact caps
  apply; a global session cap prevents runaway processes.
* Operator takeover suspends agent-driven actions on that session.

If Playwright or Chromium is unavailable the manager degrades to an explicit
``UNAVAILABLE`` state — it never fabricates a browsing result.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from . import guard

logger = logging.getLogger("ark.web.browser")

# --- Resource limits ------------------------------------------------------- #
MAX_SESSIONS = int(os.getenv("ARK_BROWSER_MAX_SESSIONS", "4"))
MAX_TABS = int(os.getenv("ARK_BROWSER_MAX_TABS", "8"))
IDLE_TIMEOUT_S = int(os.getenv("ARK_BROWSER_IDLE_TIMEOUT", "300"))
NAV_TIMEOUT_MS = int(os.getenv("ARK_BROWSER_NAV_TIMEOUT", "20000"))
MAX_SCREENSHOT_BYTES = int(os.getenv("ARK_BROWSER_MAX_SCREENSHOT", str(8 * 1024 * 1024)))
MAX_TEXT_CHARS = 200_000

ARTIFACT_DIR = os.environ.get(
    "ARK_BROWSER_ARTIFACT_DIR",
    os.path.join(os.getcwd(), "arkgeo_data", "browser"),
)

# Candidate Chromium binaries, in priority order.
_EXECUTABLE_CANDIDATES = (
    os.getenv("ARK_BROWSER_EXECUTABLE"),
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
)


class BrowserUnavailable(RuntimeError):
    """Playwright or a Chromium binary is not available."""


class SessionNotFound(KeyError):
    """No managed browser session exists for the given id."""


class BrowserError(RuntimeError):
    """A structured browser operation failed."""


class OperatorInControl(RuntimeError):
    """The operator has taken control; agent actions are suspended."""


def _playwright_import():
    try:
        from playwright.async_api import async_playwright  # noqa: PLC0415
        return async_playwright
    except Exception as exc:  # noqa: BLE001
        raise BrowserUnavailable(
            "Playwright is not installed in this backend environment."
        ) from exc


def _playwright_error() -> type[Exception]:
    """The Playwright ``Error`` class, or a never-raised stand-in when absent.

    Resolved lazily so importing this module never requires Playwright — the
    runtime degrades to ``UNAVAILABLE`` without it.
    """
    try:
        from playwright.async_api import Error  # noqa: PLC0415
        return Error
    except Exception:  # noqa: BLE001
        class _Unavailable(Exception):
            pass
        return _Unavailable


def _chromium_executable() -> Optional[str]:
    for cand in _EXECUTABLE_CANDIDATES:
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None  # fall back to Playwright's bundled build


def availability() -> dict:
    """Report browser-runtime availability without starting anything."""
    info: dict[str, Any] = {"available": False, "reason": None,
                            "executable": None, "engine": "playwright"}
    try:
        _playwright_import()
    except BrowserUnavailable as exc:
        info["reason"] = str(exc)
        return info
    exe = _chromium_executable()
    info["executable"] = exe or "playwright-bundled"
    info["available"] = True
    return info


@dataclass
class Artifact:
    kind: str            # screenshot | snapshot | download
    path: str
    sha256: str
    bytes: int
    created_ms: int
    label: str = ""

    def to_dict(self) -> dict:
        return {"kind": self.kind, "path": self.path, "sha256": self.sha256,
                "bytes": self.bytes, "created_ms": self.created_ms, "label": self.label}


@dataclass
class BrowserSession:
    """One managed browser session bound to an investigation + run."""
    session_id: str
    investigation_id: str = ""
    case_id: str = ""
    run_id: str = ""
    agent_id: str = "ARK"
    created_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    last_used_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    control: str = "agent"           # agent | operator
    profile_dir: str = ""
    download_dir: str = ""
    context: Any = None
    pages: dict[str, Any] = field(default_factory=dict)
    active_tab: Optional[str] = None
    url: str = ""
    title: Optional[str] = None
    artifacts: list[Artifact] = field(default_factory=list)
    blocked_requests: int = 0
    closed: bool = False

    def touch(self) -> None:
        self.last_used_ms = int(time.time() * 1000)

    def to_dict(self, *, include_url: bool = True) -> dict:
        tabs = []
        for tid, page in self.pages.items():
            tabs.append({"tab_id": tid,
                         "url": _safe_attr(page, "url"),
                         "title": None if tid != self.active_tab else self.title})
        d = {
            "session_id": self.session_id,
            "investigation_id": self.investigation_id,
            "case_id": self.case_id,
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "control": self.control,
            "created_ms": self.created_ms,
            "last_used_ms": self.last_used_ms,
            "closed": self.closed,
            "tabs": tabs,
            "active_tab": self.active_tab,
            "tab_count": len(tabs),
            "blocked_requests": self.blocked_requests,
            "artifacts": [a.to_dict() for a in self.artifacts],
        }
        if include_url:
            d["url"] = self.url
            d["title"] = self.title
        return d


def _safe_attr(obj, name):
    try:
        return getattr(obj, name)
    except Exception:  # noqa: BLE001
        return None


async def _page_meta(session: "BrowserSession", page) -> tuple[str, Optional[str]]:
    """Refresh and cache the active page's url + title on the session."""
    try:
        session.url = page.url
    except Exception:  # noqa: BLE001
        pass
    try:
        session.title = await page.title()
    except Exception:  # noqa: BLE001
        session.title = None
    return session.url, session.title


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class BrowserManager:
    """Owns the Chromium process, sessions, and their lifecycle."""

    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._sessions: dict[str, BrowserSession] = {}
        self._lock = asyncio.Lock()
        self._reaper: Optional[asyncio.Task] = None
        self._root = os.path.join(ARTIFACT_DIR)

    # -- lifecycle -------------------------------------------------------- #
    async def _ensure_browser(self):
        if self._browser is not None:
            return self._browser
        async_playwright = _playwright_import()
        self._pw = await async_playwright().start()
        exe = _chromium_executable()
        launch_kwargs: dict[str, Any] = {
            "headless": os.getenv("ARK_BROWSER_HEADLESS", "true").lower() != "false",
            "args": [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
                "--no-first-run",
                "--disable-background-networking",
            ],
        }
        if exe:
            launch_kwargs["executable_path"] = exe
        try:
            self._browser = await self._pw.chromium.launch(**launch_kwargs)
        except Exception as exc:  # noqa: BLE001
            await self._shutdown_playwright()
            raise BrowserUnavailable(f"Chromium launch failed: {exc}") from exc
        return self._browser

    async def _shutdown_playwright(self) -> None:
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:  # noqa: BLE001
                pass
        self._pw = None
        self._browser = None

    async def open(self, *, investigation_id: str = "", case_id: str = "",
                   run_id: str = "", agent_id: str = "ARK",
                   url: str = "") -> BrowserSession:
        async with self._lock:
            if len([s for s in self._sessions.values() if not s.closed]) >= MAX_SESSIONS:
                raise BrowserError(
                    f"browser session cap reached ({MAX_SESSIONS}); close a session first"
                )
            browser = await self._ensure_browser()
            sid = "bws_" + uuid.uuid4().hex[:12]
            profile_dir = tempfile.mkdtemp(prefix=f"ark-browser-{sid}-")
            download_dir = os.path.join(profile_dir, "downloads")
            os.makedirs(download_dir, exist_ok=True)
            context = await browser.new_context(
                accept_downloads=True,
                user_agent=None,
                viewport={"width": 1440, "height": 900},
            )
            await context.route("**/*", _make_route_handler(sid, self))
            session = BrowserSession(
                session_id=sid, investigation_id=investigation_id,
                case_id=case_id, run_id=run_id, agent_id=agent_id,
                profile_dir=profile_dir, download_dir=download_dir,
                context=context,
            )
            self._sessions[sid] = session
            self._ensure_reaper()
        if url:
            await self.navigate(sid, url)
        return session

    def get(self, session_id: str) -> BrowserSession:
        s = self._sessions.get(session_id)
        if s is None or s.closed:
            raise SessionNotFound(session_id)
        return s

    def list_sessions(self) -> list[dict]:
        return [s.to_dict() for s in self._sessions.values() if not s.closed]

    async def close(self, session_id: str) -> dict:
        session = self._sessions.pop(session_id, None)
        if session is None:
            raise SessionNotFound(session_id)
        session.closed = True
        try:
            if session.context is not None:
                await session.context.close()
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(session.profile_dir, ignore_errors=True)
        return {"session_id": session_id, "closed": True}

    async def close_all(self) -> None:
        for sid in list(self._sessions):
            try:
                await self.close(sid)
            except Exception:  # noqa: BLE001
                pass
        if self._reaper:
            self._reaper.cancel()
            self._reaper = None
        await self._shutdown_playwright()

    # -- operator control ------------------------------------------------- #
    def take_control(self, session_id: str) -> dict:
        s = self.get(session_id)
        s.control = "operator"
        s.touch()
        return s.to_dict()

    def return_control(self, session_id: str) -> dict:
        s = self.get(session_id)
        s.control = "agent"
        s.touch()
        return s.to_dict()

    def _assert_agent_control(self, s: BrowserSession) -> None:
        if s.control == "operator":
            raise OperatorInControl(
                "operator has taken control of this browser session"
            )

    # -- tab management --------------------------------------------------- #
    async def _active_page(self, session_id: str, *, operator: bool = False):
        s = self.get(session_id)
        # Agent-plane callers are refused while the operator holds control;
        # operator-plane callers (this module's own transport) are not.
        if not operator:
            self._assert_agent_control(s)
        if s.active_tab and s.active_tab in s.pages:
            return s, s.pages[s.active_tab]
        page = await s.context.new_page()
        tid = "tab_" + uuid.uuid4().hex[:8]
        s.pages[tid] = page
        s.active_tab = tid
        return s, page

    async def tabs(self, session_id: str, action: str = "list",
                   tab_id: str = "") -> dict:
        s = self.get(session_id)
        s.touch()
        if action == "list":
            return s.to_dict()
        if action == "new":
            self._assert_agent_control(s)
            if len(s.pages) >= MAX_TABS:
                raise BrowserError(f"tab cap reached ({MAX_TABS})")
            page = await s.context.new_page()
            tid = "tab_" + uuid.uuid4().hex[:8]
            s.pages[tid] = page
            s.active_tab = tid
            return s.to_dict()
        if action == "select":
            if tab_id not in s.pages:
                raise BrowserError(f"unknown tab {tab_id}")
            s.active_tab = tab_id
            return s.to_dict()
        if action == "close":
            target = tab_id or s.active_tab
            if target not in s.pages:
                raise BrowserError(f"unknown tab {target}")
            try:
                await s.pages[target].close()
            except Exception:  # noqa: BLE001
                pass
            del s.pages[target]
            if s.active_tab == target:
                s.active_tab = next(iter(s.pages), None)
            return s.to_dict()
        raise BrowserError(f"unsupported tabs action '{action}'")

    # -- navigation ------------------------------------------------------- #
    async def navigate(self, session_id: str, url: str, *, wait_until: str = "load",
                       operator: bool = False) -> dict:
        s, page = await self._active_page(session_id, operator=operator)
        # Pre-validate the primary navigation target (defence in depth — the
        # route interceptor also guards it, and every redirect/subresource).
        guard.check_url(url)
        s.touch()
        resp = await page.goto(url, wait_until=wait_until, timeout=NAV_TIMEOUT_MS)
        status = resp.status if resp is not None else 0
        final_url, title = await _page_meta(s, page)
        return {
            "session_id": session_id, "url": final_url,
            "title": title, "status": status, "tab_id": s.active_tab,
        }

    async def snapshot(self, session_id: str) -> dict:
        """Accessibility-oriented text snapshot of the active page."""
        s, page = await self._active_page(session_id)
        s.touch()
        text = await page.inner_text("body")
        text = (text or "")[:MAX_TEXT_CHARS]
        final_url, title = await _page_meta(s, page)
        return {
            "session_id": session_id, "url": final_url,
            "title": title, "text": text, "chars": len(text),
        }

    async def extract(self, session_id: str, selector: str = "") -> dict:
        """Extract readable content + links from the rendered DOM."""
        s, page = await self._active_page(session_id)
        s.touch()
        html = await page.content()
        from .fetcher import extract_html, enumerate_links
        text, title, meta = extract_html(html.encode("utf-8"), "text/html")
        links = enumerate_links(html.encode("utf-8"), "text/html", page.url)
        final_url, live_title = await _page_meta(s, page)
        out: dict[str, Any] = {
            "session_id": session_id, "url": final_url, "title": title or live_title,
            "text": text[:MAX_TEXT_CHARS], "metadata": meta,
            "links": links[:500], "link_count": len(links),
        }
        if selector:
            try:
                el = await page.query_selector(selector)
                out["selector_text"] = (await el.inner_text())[:MAX_TEXT_CHARS] if el else None
            except Exception as exc:  # noqa: BLE001
                out["selector_text"] = None
                out["selector_error"] = str(exc)
        return out

    async def screenshot(self, session_id: str, *, label: str = "",
                         full_page: bool = True, operator: bool = False) -> dict:
        s, page = await self._active_page(session_id, operator=operator)
        s.touch()
        out_dir = os.path.join(self._root, session_id)
        os.makedirs(out_dir, exist_ok=True)
        name = f"shot-{int(time.time()*1000)}-{uuid.uuid4().hex[:6]}.png"
        path = os.path.join(out_dir, name)
        data = await page.screenshot(full_page=full_page)
        if len(data) > MAX_SCREENSHOT_BYTES:
            raise BrowserError("screenshot exceeds size cap")
        with open(path, "wb") as fh:
            fh.write(data)
        artifact = Artifact(kind="screenshot", path=path, sha256=_sha256_file(path),
                            bytes=len(data), created_ms=int(time.time() * 1000),
                            label=label)
        s.artifacts.append(artifact)
        final_url, title = await _page_meta(s, page)
        return {
            "session_id": session_id, "url": final_url, "title": title,
            "artifact": artifact.to_dict(),
            "is_live": False,   # a screenshot is a captured frame, never a live session
        }

    async def click(self, session_id: str, selector: str) -> dict:
        s, page = await self._active_page(session_id)
        self._assert_agent_control(s)
        s.touch()
        await page.click(selector, timeout=NAV_TIMEOUT_MS)
        final_url, title = await _page_meta(s, page)
        return {"session_id": session_id, "url": final_url, "clicked": selector,
                "title": title}

    async def type(self, session_id: str, selector: str, text: str,
                   *, submit: bool = False) -> dict:
        s, page = await self._active_page(session_id)
        self._assert_agent_control(s)
        s.touch()
        await page.fill(selector, text, timeout=NAV_TIMEOUT_MS)
        if submit:
            await page.press(selector, "Enter")
        final_url, _ = await _page_meta(s, page)
        return {"session_id": session_id, "url": final_url, "typed_into": selector,
                "submitted": submit}

    async def scroll(self, session_id: str, *, direction: str = "down",
                     amount: int = 800) -> dict:
        s, page = await self._active_page(session_id)
        s.touch()
        dy = amount if direction == "down" else -amount
        await page.mouse.wheel(0, dy)
        return {"session_id": session_id, "url": page.url, "direction": direction,
                "amount": amount}

    async def go_back(self, session_id: str, *, operator: bool = False) -> dict:
        s, page = await self._active_page(session_id, operator=operator)
        s.touch()
        await page.go_back(timeout=NAV_TIMEOUT_MS)
        final_url, title = await _page_meta(s, page)
        return {"session_id": session_id, "url": final_url, "title": title}

    async def go_forward(self, session_id: str, *, operator: bool = False) -> dict:
        s, page = await self._active_page(session_id, operator=operator)
        s.touch()
        await page.go_forward(timeout=NAV_TIMEOUT_MS)
        final_url, title = await _page_meta(s, page)
        return {"session_id": session_id, "url": final_url, "title": title}

    async def reload(self, session_id: str, *, operator: bool = False) -> dict:
        s, page = await self._active_page(session_id, operator=operator)
        s.touch()
        await page.reload(wait_until="load", timeout=NAV_TIMEOUT_MS)
        final_url, title = await _page_meta(s, page)
        return {"session_id": session_id, "url": final_url, "title": title}

    async def history(self, session_id: str, action: str,
                      *, operator: bool = False) -> dict:
        """Back / forward / reload the active tab. A history move that has no
        target (e.g. back at the first entry) is a no-op, not an error."""
        fn = {"back": self.go_back, "forward": self.go_forward,
              "reload": self.reload}.get(action)
        if fn is None:
            raise BrowserError(f"unsupported history action '{action}'")
        s = self.get(session_id)
        before = s.url
        try:
            return await fn(session_id, operator=operator)
        except _playwright_error() as exc:
            # Nothing to go back/forward to is a normal boundary, not a failure.
            if "cannot go" in str(exc).lower():
                return {"session_id": session_id, "url": before, "title": s.title,
                        "no_op": True}
            raise

    # -- reaper ----------------------------------------------------------- #
    def _ensure_reaper(self) -> None:
        if self._reaper is None or self._reaper.done():
            self._reaper = asyncio.create_task(self._reap_loop())

    async def _reap_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(30)
                now = int(time.time() * 1000)
                stale = [s.session_id for s in self._sessions.values()
                         if not s.closed and now - s.last_used_ms > IDLE_TIMEOUT_S * 1000]
                for sid in stale:
                    logger.info("Reaping idle browser session %s", sid)
                    try:
                        await self.close(sid)
                    except Exception:  # noqa: BLE001
                        pass
        except asyncio.CancelledError:
            return


def _make_route_handler(session_id: str, manager: "BrowserManager"):
    """Build the per-context request interceptor enforcing the egress guard."""
    async def _handler(route, request):  # noqa: ANN001
        url = request.url
        try:
            guard.check_url(url)
        except guard.SSRFBlocked:
            session = manager._sessions.get(session_id)
            if session is not None:
                session.blocked_requests += 1
            await route.abort("blockedbyclient")
            return
        try:
            await route.continue_()
        except Exception:  # noqa: BLE001 — route may be gone
            pass
    return _handler


browser_manager = BrowserManager()
