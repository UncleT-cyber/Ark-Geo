"""Osmocom Control Interface (CTRL) client for osmo-hlr.

osmo-hlr exposes its subscriber database over the plain-ASCII Osmocom Control
Interface (default TCP 4250).  Relevant GET operations used here:

    subscriber.by-msisdn-<MSISDN>.info      → subscriber dict
    subscriber.by-imsi-<IMSI>.info          → subscriber dict
    subscriber.by-id-<ID>.info-all          → full record incl. aud data
    subscriber.by-msisdn-<MSISDN>.aud2g     → GSM auth triplets
    subscriber.by-msisdn-<MSISDN>.aud3g     → UMTS auth vectors

Protocol (per OsmoHLR user manual §11 "Osmocom Control Interface"):
    request:   GET <var>\r\n
    success:   GET REPLY 200 <var> <value>\r\n
    error:     GET REPLY 400 <var> <error-message>\r\n
    (multi-line values continue with `#` lines)

This client is dependency-free (asyncio + socket) so it runs against a lab
osmo-hlr without any third-party packages.
"""
from __future__ import annotations

import asyncio
import logging
import socket
from typing import Any, Optional

from app.core.config import settings
from app.signaling.errors import BackendUnavailable

logger = logging.getLogger(__name__)

_REPLY_OK = "GET REPLY 200"
_REPLY_ERR = "GET REPLY 400"


class OsmocomCtrlClient:
    """Minimal asyncio line-protocol client for the osmo-hlr CTRL socket."""

    def __init__(self, host: str | None = None, port: int | None = None, timeout: int | None = None) -> None:
        self.host = host or settings.osmocom_hlr_ctrl_host
        self.port = port or settings.osmocom_hlr_ctrl_port
        self.timeout = timeout or settings.osmocom_ctrl_timeout
        self._writer: Optional[asyncio.StreamWriter] = None
        self._reader: Optional[asyncio.StreamReader] = None

    async def connect(self) -> None:
        if self._reader:
            return
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), timeout=self.timeout
            )
        except (OSError, asyncio.TimeoutError, socket.gaierror) as exc:
            raise BackendUnavailable(
                f"osmo-hlr CTRL unreachable at {self.host}:{self.port}: {exc}"
            ) from exc

    async def close(self) -> None:
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass
        self._reader = None
        self._writer = None

    async def get(self, variable: str) -> dict[str, Any]:
        """Issue a GET and return the parsed reply ``{status, value}``."""
        await self.connect()
        assert self._writer is not None and self._reader is not None  # noqa: S101
        self._writer.write(f"GET {variable}\r\n".encode("ascii"))
        await self._writer.drain()

        lines: list[str] = []
        try:
            while True:
                try:
                    line = await asyncio.wait_for(self._reader.readline(), timeout=self.timeout)
                except (ConnectionResetError, ConnectionError):
                    # osmo-hlr may close the socket right after replying; a reset
                    # is treated as end-of-stream once we already have the reply.
                    break
                if not line:
                    break
                text = line.decode("ascii", "replace").rstrip("\r\n")
                if not text:
                    continue
                lines.append(text)
                if text.startswith(_REPLY_OK) or text.startswith(_REPLY_ERR):
                    break
        except asyncio.TimeoutError as exc:
            raise BackendUnavailable(
                f"osmo-hlr CTRL timed out waiting for '{variable}'"
            ) from exc

        for line in lines:
            if line.startswith(_REPLY_OK):
                # GET REPLY 200 <var> <value>  (value may be empty)
                rest = line[len(_REPLY_OK) :].strip()
                parts = rest.split(" ", 1)
                value = parts[1] if len(parts) > 1 else ""
                return {"status": 200, "value": _parse_ctrl_value(value)}
            if line.startswith(_REPLY_ERR):
                rest = line[len(_REPLY_ERR) :].strip()
                parts = rest.split(" ", 1)
                message = parts[1] if len(parts) > 1 else rest
                return {"status": 400, "error": message}
        raise BackendUnavailable(f"osmo-hlr CTRL returned no reply for '{variable}'")

    async def get_ok(self, variable: str) -> dict[str, Any]:
        """GET that raises unless the reply is a 200 (empty value tolerated)."""
        reply = await self.get(variable)
        if reply.get("status") != 200:
            raise BackendUnavailable(
                f"osmo-hlr CTRL error for '{variable}': {reply.get('error', 'no value')}"
            )
        return reply


def _parse_ctrl_value(value: str) -> Any:
    """Parse a CTRL value string into a Python object.

    osmo-hlr returns JSON-encoded subscriber dicts for ``.info`` GETs.
    """
    stripped = value.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            import json

            return json.loads(stripped)
        except ValueError:
            return stripped
    return stripped
