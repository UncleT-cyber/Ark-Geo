"""Static HTTP retrieval with an egress guard, redirect chain and extraction.

The low-level engine behind the ``web.*`` catalogue tools. Every hop is
re-validated by :mod:`app.tools.web_intel.guard` and dialled against the pinned
IP (DNS-rebinding resistance). Responses are byte- and time-capped. Content is
decoded to readable text/Markdown (HTML), plain text, pretty JSON, or PDF text.
"""
from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from . import guard

DEFAULT_TIMEOUT = 20
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 ArkGeo/0.2"
)

_SCRIPT_STYLE_RE = re.compile(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_CHARSET_RE = re.compile(r"charset=([\w\-]+)", re.I)
_LINK_RE = re.compile(r"""<a\b[^>]*?\bhref\s*=\s*["']([^"']+)["']""", re.I)
_META_RE = re.compile(
    r"""<meta\b[^>]*?\b(?:name|property)\s*=\s*["']([^"']+)["'][^>]*?\bcontent\s*=\s*["']([^"']*)["']""",
    re.I,
)


@dataclass
class FetchResult:
    """Structured outcome of a fetch. ``ok`` is False for any failure state."""
    url: str
    final_url: str = ""
    ok: bool = False
    state: str = "UNAVAILABLE"     # AVAILABLE | BLOCKED | ERROR | UNAVAILABLE
    status: int = 0
    content_type: str = ""
    content_kind: str = "unknown"  # html | pdf | json | text | unknown
    title: Optional[str] = None
    text: str = ""
    bytes: int = 0
    elapsed_ms: int = 0
    redirect_chain: list[str] = field(default_factory=list)
    detail: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url, "final_url": self.final_url or self.url,
            "ok": self.ok, "state": self.state, "status": self.status,
            "content_type": self.content_type, "content_kind": self.content_kind,
            "title": self.title, "text": self.text, "bytes": self.bytes,
            "elapsed_ms": self.elapsed_ms,
            "redirect_chain": list(self.redirect_chain),
            "detail": self.detail, "metadata": dict(self.metadata),
        }


def detect_kind(body: bytes, content_type: str) -> str:
    """Classify a response body: html | pdf | json | text | unknown."""
    ct = (content_type or "").lower()
    if body[:5] == b"%PDF-" or ct.startswith("application/pdf"):
        return "pdf"
    if ct.startswith("application/json") or ct.endswith("+json"):
        return "json"
    if ct.startswith("text/html") or ct in {"application/xhtml+xml", "application/xml", "text/xml"}:
        return "html"
    if not ct:
        head = body[:64].lstrip()
        if head[:1] in (b"{", b"["):
            try:
                json.loads(body.decode("utf-8", errors="replace"))
                return "json"
            except (ValueError, UnicodeDecodeError):
                pass
        low = body[:1024].lower()
        if b"<html" in low or b"<!doctype html" in low:
            return "html"
    if ct.startswith("text/"):
        return "text"
    return "unknown"


def _decode(body: bytes, content_type: str) -> str:
    m = _CHARSET_RE.search(content_type or "")
    if m:
        try:
            return body.decode(m.group(1), errors="replace")
        except LookupError:
            pass
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return body.decode("latin-1", errors="replace")


def _strip_html(html: str) -> str:
    text = _SCRIPT_STYLE_RE.sub(" ", html or "")
    text = _TAG_RE.sub(" ", text)
    import html as html_mod
    return _WS_RE.sub(" ", html_mod.unescape(text)).strip()


def extract_html(body: bytes, content_type: str) -> tuple[str, Optional[str], dict]:
    """Return ``(readable_text, title, metadata)`` for an HTML body.

    Prefers trafilatura (main-content + Markdown); falls back to a tag strip.
    """
    html = _decode(body, content_type)
    title_m = _TITLE_RE.search(html)
    import html as html_mod
    title = html_mod.unescape(_TAG_RE.sub("", title_m.group(1))).strip() if title_m else None

    metadata: dict[str, Any] = {}
    for name, content in _META_RE.findall(html):
        key = name.strip().lower()
        if key in {"description", "og:title", "og:description", "og:site_name",
                   "og:type", "article:published_time", "author"} and content:
            metadata.setdefault(key, html_mod.unescape(content).strip())

    text = ""
    try:
        import trafilatura  # local import — heavy
        text = trafilatura.extract(
            html, output_format="markdown", include_links=True,
            include_tables=True, include_formatting=True, favor_recall=True,
        ) or ""
    except Exception:  # noqa: BLE001 — extraction is best-effort
        text = ""
    if not text:
        text = _strip_html(html)
    return text, title, metadata


def extract_pdf(body: bytes) -> str:
    """Extract text from a PDF, one section per page."""
    from pypdf import PdfReader  # local import
    reader = PdfReader(io.BytesIO(body))
    pages: list[str] = []
    for idx, page in enumerate(reader.pages, start=1):
        try:
            txt = (page.extract_text() or "").strip()
        except Exception:  # noqa: BLE001
            txt = ""
        pages.append(f"## Page {idx}\n\n{txt}")
    return "\n\n".join(pages) if pages else "[empty PDF]"


def extract_text(body: bytes, content_type: str) -> str:
    """Extract readable text for any supported body."""
    kind = detect_kind(body, content_type)
    if kind == "pdf":
        return extract_pdf(body)
    if kind == "html":
        return extract_html(body, content_type)[0]
    if kind == "json":
        try:
            return json.dumps(json.loads(_decode(body, content_type)), indent=2, ensure_ascii=False)
        except ValueError:
            return _decode(body, content_type)
    if kind == "text":
        return _decode(body, content_type)
    return f"[Unsupported content type: {content_type or 'unknown'}]"


def enumerate_links(body: bytes, content_type: str, base_url: str) -> list[dict]:
    """Return ``[{url, text}]`` absolute hyperlinks found in an HTML body."""
    from urllib.parse import urljoin, urldefrag
    html = _decode(body, content_type)
    out: list[dict] = []
    seen: set[str] = set()
    for href in _LINK_RE.findall(html):
        href = href.strip()
        if not href or href.lower().startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        absolute = urldefrag(urljoin(base_url, href))[0]
        if not absolute.startswith(("http://", "https://")):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        out.append({"url": absolute})
    return out


async def fetch(
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    extract: bool = True,
    user_agent: Optional[str] = None,
) -> FetchResult:
    """Fetch *url*, following up to :data:`MAX_REDIRECTS` validated hops.

    Every hop is re-checked by the egress guard and dialled against its pinned
    IP. Never raises — failures are returned as a classified :class:`FetchResult`.
    """
    import time
    started = time.perf_counter()
    url = (url or "").strip()
    if not url:
        return FetchResult(url=url, state="UNAVAILABLE", detail="No URL supplied.")

    redirect_chain: list[str] = []
    current = url
    headers_base = {
        "User-Agent": user_agent or _USER_AGENT,
        "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                   "application/pdf,application/json;q=0.9,*/*;q=0.5"),
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=timeout, http2=False) as client:
            for _ in range(MAX_REDIRECTS + 1):
                decision = guard.check_url(current)
                dial = guard.pinned_url(decision)
                headers = dict(headers_base)
                headers["Host"] = decision.host_header
                req = client.build_request("GET", dial, headers=headers)
                from urllib.parse import urlsplit
                if urlsplit(current).scheme == "https" and urlsplit(current).hostname:
                    req.extensions["sni_hostname"] = urlsplit(current).hostname
                resp = await client.send(req, stream=True)
                try:
                    chunks: list[bytes] = []
                    received = 0
                    async for chunk in resp.aiter_bytes():
                        chunks.append(chunk)
                        received += len(chunk)
                        if received >= max_bytes:
                            break
                    body = b"".join(chunks)[:max_bytes]
                    ctype = resp.headers.get("content-type", "").split(";", 1)[0].strip()
                    status = resp.status_code
                    location = resp.headers.get("location") if 300 <= status < 400 else None
                finally:
                    await resp.aclose()

                if location and 300 <= status < 400:
                    redirect_chain.append(current)
                    current = str(httpx.URL(current).join(location))
                    continue

                kind = detect_kind(body, ctype)
                result = FetchResult(
                    url=url, final_url=current, status=status, content_type=ctype,
                    content_kind=kind, bytes=len(body),
                    redirect_chain=redirect_chain,
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                )
                if status >= 400:
                    result.state = "ERROR"
                    result.detail = f"HTTP {status}"
                    return result
                if not extract:
                    result.ok = True
                    result.state = "AVAILABLE"
                    return result
                if kind == "html":
                    text, title, meta = extract_html(body, ctype)
                    result.title, result.metadata = title, meta
                    result.text = text
                else:
                    result.text = extract_text(body, ctype)
                result.ok = True
                result.state = "AVAILABLE"
                result.detail = "Page fetched."
                return result

        # Redirect budget exhausted.
        return FetchResult(
            url=url, final_url=current, state="ERROR", redirect_chain=redirect_chain,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            detail=f"too many redirects (>{MAX_REDIRECTS})",
        )
    except guard.SSRFBlocked as exc:
        return FetchResult(
            url=url, state="BLOCKED", redirect_chain=redirect_chain,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            detail=f"Blocked by egress guard: {exc}",
        )
    except Exception as exc:  # noqa: BLE001 — classify, never crash
        return FetchResult(
            url=url, state="ERROR", redirect_chain=redirect_chain,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            detail=f"Fetch failed: {type(exc).__name__}: {exc}",
        )
