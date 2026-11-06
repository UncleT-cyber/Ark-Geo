#!/usr/bin/env python3
"""ARK Lab Target A — synthetic HTTP training service.

Deterministic, offline, synthetic data only. Endpoints:
    GET  /           service index (endpoint inventory)
    GET  /health     liveness/health probe
    GET  /api/data   synthetic application records
    GET  /slow       deliberate 25s delay (tool-timeout fixture)
    any other path   404

Every response carries predictable headers for verification.
"""
from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

START = time.time()
SERVICE = "ark-lab-http"
VERSION = "1.0.0"

# Synthetic-only records — no real customer/user data.
SYNTHETIC_RECORDS = [
    {"id": "SYN-0001", "type": "session", "label": "synthetic session record", "score": 0.13},
    {"id": "SYN-0002", "type": "asset", "label": "synthetic asset record", "score": 0.42},
    {"id": "SYN-0003", "type": "alert", "label": "synthetic alert record", "score": 0.87},
]


class Handler(BaseHTTPRequestHandler):
    server_version = "ArkLabHTTP/1.0"
    sys_version = ""

    # -- helpers ----------------------------------------------------------
    def _reply(self, code: int, payload: dict, ctype: str = "application/json") -> None:
        body = json.dumps(payload, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-ARK-Lab-Target", "A")
        self.send_header("X-ARK-Lab-Engagement", "A2-LAB-001")
        self.send_header("X-ARK-Lab-Service", f"{SERVICE}/{VERSION}")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:  # concise container logs
        print(f"[ark-lab-http] {self.address_string()} {fmt % args}", flush=True)

    # -- routes -----------------------------------------------------------
    def _route(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._reply(200, {
                "service": SERVICE, "version": VERSION,
                "endpoints": ["/health", "/api/data", "/slow"],
                "note": "Synthetic training target for authorized ARK lab engagement.",
            })
        elif path == "/health":
            self._reply(200, {
                "status": "ok",
                "service": SERVICE,
                "version": VERSION,
                "uptime_s": round(time.time() - START, 1),
            })
        elif path == "/api/data":
            self._reply(200, {"service": SERVICE, "records": SYNTHETIC_RECORDS,
                              "count": len(SYNTHETIC_RECORDS), "synthetic": True})
        elif path == "/slow":
            time.sleep(25)  # deliberate delay -> tool timeout fixture
            self._reply(200, {"service": SERVICE, "status": "slow-complete"})
        else:
            self._reply(404, {"error": "not_found", "path": path, "service": SERVICE})

    def do_GET(self) -> None:   # noqa: N802
        self._route()

    def do_HEAD(self) -> None:  # noqa: N802
        self._route()


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
    print(f"[ark-lab-http] listening on :8080 ({SERVICE} {VERSION})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
