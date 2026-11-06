#!/usr/bin/env python3
"""THE ARK — Milestone A.2 Test 5(b): direct CAI runtime execution.

Runs the harmless execution test through the orchestrator *in-process*
(no HTTP/SSE layer, no harness): the same engine code the API endpoints call.
Isolates engine behaviour from transport behaviour for failure attribution.

Usage:  cd arkgeo-backend && .venv/bin/python ../arkgeo-lab/harness/t5b_direct.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                "arkgeo-backend"))

PROMPT = ("Probe http://172.30.250.10:8080/health on the authorized lab "
          "target and report the service information.")


async def main() -> int:
    from app.engine.orchestrator import get_session, run

    session = get_session("a2-t5b-direct", model=None, case_id=None,
                          workspace=None)
    events = []
    t0 = time.time()
    async for ev in run(session, PROMPT):
        ev["_ts"] = round(time.time() - t0, 3)
        events.append(ev)
        if ev.get("type") == "tool_call":
            print(f"  [{ev['_ts']}] TOOL_CALL {ev.get('tool')} "
                  f"args={json.dumps(ev.get('args', {}))[:200]}")
        elif ev.get("type") == "tool":
            res = json.dumps(ev.get("result", {}), default=str)
            print(f"  [{ev['_ts']}] TOOL_RESULT {ev.get('tool')} "
                  f"({ev.get('elapsed_ms')}ms) {res[:400]}")
        elif ev.get("type") == "status" and ev.get("stage") == "tool_denied":
            print(f"  [{ev['_ts']}] STATUS tool_denied: "
                  f"{ev.get('reason') or ev.get('message')}")
        elif ev.get("type") == "final":
            print(f"  [{ev['_ts']}] FINAL: {ev.get('text', '')[:500]}")

    scope = {}
    scope_path = os.path.join("arkgeo_data", "engagement_scope.json")
    if os.path.isfile(scope_path):
        with open(scope_path, encoding="utf-8") as fh:
            scope = json.load(fh)

    record = {
        "test_id": "t5b_direct_runtime",
        "part": "Test 5(b) — direct CAI runtime (in-process orchestrator.run, "
                "no HTTP/SSE transport)",
        "engagement_id": scope.get("engagement_id"),
        "session_id": session.session_id,
        "model_id": getattr(session, "model", None) or "backend default",
        "prompt": PROMPT,
        "started": datetime.now(timezone.utc).isoformat(),
        "events": [
            {k: v for k, v in ev.items() if k != "_ts"} for ev in events],
        "event_counts": {
            t: sum(1 for e in events if str(e.get("type")) == t)
            for t in sorted({str(e.get("type")) for e in events})
        },
        "elapsed_s": round(time.time() - t0, 1),
    }
    out = os.path.join("arkgeo_data", "a2_evidence", "t5b_direct_runtime.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, ensure_ascii=False)
    print(f"  evidence -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
