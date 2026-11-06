#!/usr/bin/env python3
"""THE ARK — Milestone A.2 evidence harness.

Drives THE ARK terminal (`POST /api/v1/cai/terminal/stream`), captures every
SSE event as structured evidence, auto-responds to HITL prompts (operator
approval), redacts lab secrets, and writes a per-test evidence record.

Usage:
    python3 a2_harness.py <test_id> "<prompt>" [--session SID] [--deny]
                          [--workspace WS] [--no-approve]

Exit code 0 = run captured (pass/fail judgement is made by the tester from
the recorded events — the harness never claims success on its own).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone

BASE = os.environ.get("ARK_BASE", "http://127.0.0.1:12000/api/v1")
SCOPE_PATH = os.environ.get(
    "ARKGEO_ENGAGEMENT_SCOPE",
    os.path.join(os.path.dirname(__file__), "..", "..",
                 "arkgeo-backend", "arkgeo_data", "engagement_scope.json"),
)
EVIDENCE_DIR = os.path.join(os.path.dirname(__file__), "..", "..",
                            "arkgeo-backend", "arkgeo_data", "a2_evidence")

# Secrets that must never appear in evidence records.
_SECRET_PATTERNS = [
    re.compile(r"Arklab-Test-2026!"),
    re.compile(r"Intentionally-Wrong-Password-9x"),
    re.compile(r"(ARK_LAB_SSH_PASS[\"'=: ]+)[^\s\"']+", re.I),
    re.compile(r"(password[\"'=: ]+)[^\s\"',}]+", re.I),
]


def redact(text: str) -> str:
    out = text
    for pat in _SECRET_PATTERNS:
        if pat.groups:
            out = pat.sub(lambda m: (m.group(1) if m.lastindex else "") + "<REDACTED>", out)
        else:
            out = pat.sub("<REDACTED>", out)
    return out


def http_json(path: str, payload: dict | None = None, method: str = "POST") -> dict:
    url = f"{BASE}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def sse_stream(path: str, payload: dict):
    url = f"{BASE}{path}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            body = line[5:].strip()
            if not body:
                continue
            try:
                yield json.loads(body)
            except json.JSONDecodeError:
                yield {"type": "unparsed", "raw": body}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("test_id")
    ap.add_argument("prompt")
    ap.add_argument("--session", default=None)
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--model", default=None,
                    help="pin a model for this run (session-level model override)")
    ap.add_argument("--deny", action="store_true",
                    help="deny HITL prompts (operator-denial evidence)")
    ap.add_argument("--no-approve", action="store_true",
                    help="leave HITL prompts unanswered (timeout evidence)")
    args = ap.parse_args()

    session_id = args.session or f"a2-{args.test_id}-{int(time.time())}"
    ts_start = datetime.now(timezone.utc).isoformat()

    # Context metadata for the evidence record.
    model = http_json("/cai/model", method="GET")
    scope = {}
    if os.path.isfile(SCOPE_PATH):
        with open(SCOPE_PATH, encoding="utf-8") as fh:
            scope = json.load(fh)

    payload = {"prompt": args.prompt, "session_id": session_id}
    if args.workspace:
        payload["workspace"] = args.workspace
    if args.model:
        payload["model"] = args.model

    events = []
    approvals = []
    t0 = time.time()
    for ev in sse_stream("/cai/terminal/stream", payload):
        ev["_ts"] = round(time.time() - t0, 3)
        events.append(ev)

        if ev.get("type") == "hitl":
            if args.no_approve:
                continue
            decision = False if args.deny else True
            try:
                res = http_json("/cai/terminal/approve", {
                    "session_id": session_id, "decision": decision,
                    "execution_id": ev.get("execution_id"),
                })
                approvals.append({"ts": ev["_ts"], "tool": ev.get("tool"),
                                  "decision": decision, "response": res})
            except Exception as exc:  # noqa: BLE001
                approvals.append({"ts": ev["_ts"], "tool": ev.get("tool"),
                                  "decision": decision, "error": str(exc)})

    ts_end = datetime.now(timezone.utc).isoformat()

    # Compact trace for the console.
    print(f"### {args.test_id}  session={session_id}  "
          f"model={args.model or model.get('model')}  elapsed={round(time.time()-t0,1)}s")
    for ev in events:
        t = ev.get("type")
        if t == "tool_call":
            print(f"  [{ev['_ts']}] TOOL_CALL {ev.get('tool')} "
                  f"args={json.dumps(ev.get('args', {}))[:200]}")
        elif t == "tool":
            res = json.dumps(ev.get("result", {}), default=str)
            print(f"  [{ev['_ts']}] TOOL_RESULT {ev.get('tool')} "
                  f"({ev.get('elapsed_ms')}ms) {redact(res)[:400]}")
        elif t == "status" and ev.get("stage") in (
                "tool_denied", "error", "auto_approve"):
            print(f"  [{ev['_ts']}] STATUS {ev.get('stage')}: "
                  f"{redact(json.dumps({k: v for k, v in ev.items() if k != '_ts'}))[:400]}")
        elif t == "hitl":
            print(f"  [{ev['_ts']}] HITL {ev.get('tool')} "
                  f"risk={ev.get('risk')} -> operator "
                  f"{'approved' if not args.deny and not args.no_approve else ('denied' if args.deny else 'left pending')}")
        elif t == "error":
            print(f"  [{ev['_ts']}] ERROR {ev.get('code')}: {ev.get('message')}")
        elif t == "final":
            print(f"  [{ev['_ts']}] FINAL: {redact(ev.get('text', ''))[:600]}")

    record = {
        "test_id": args.test_id,
        "engagement_id": scope.get("engagement_id"),
        "session_id": session_id,
        "agent_role": "operator (workspace: %s)" % (args.workspace or "general"),
        "model_id": args.model or model.get("model"),
        "model_pinned_per_request": bool(args.model),
        "prompt": redact(args.prompt),
        "started": ts_start,
        "finished": ts_end,
        "operator_approvals": approvals,
        "events": events,
        "event_counts": {t: sum(1 for e in events if str(e.get("type")) == t)
                         for t in sorted({str(e.get("type")) for e in events})},
    }
    os.makedirs(EVIDENCE_DIR, exist_ok=True)
    out_path = os.path.join(EVIDENCE_DIR, f"{args.test_id}.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(json.loads(redact(json.dumps(record, default=str))),
                  fh, indent=2, ensure_ascii=False)
    print(f"  evidence -> {os.path.relpath(out_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
