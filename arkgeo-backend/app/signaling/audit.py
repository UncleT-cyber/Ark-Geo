"""Append-only audit trail for every signaling action.

Records are written to a JSONL file (``<signaling_audit_path>/signaling.jsonl``
or ``<local_storage_path>/audit/signaling.jsonl``).  Every accepted operation
AND every denied attempt is recorded with actor, role, operator authorization
trace, target, outcome and a per-request trace id.  Logs are never pruned by
the runtime; retention is a deployment policy.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


def new_trace_id(prefix: str = "sig") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class AuditLog:
    def __init__(self, path: str | None = None) -> None:
        self._path = path or self._default_path()
        self._lock = threading.Lock()

    @staticmethod
    def _default_path() -> str:
        if settings.signaling_audit_path:
            base = settings.signaling_audit_path
        else:
            base = os.path.join(settings.local_storage_path, "audit")
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, "signaling.jsonl")

    def append(self, entry: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        record = {
            "ts_iso": now.isoformat(timespec="milliseconds"),
            "ts_ms": int(now.timestamp() * 1000),
            **entry,
        }
        line = json.dumps(record, separators=(",", ":"), sort_keys=True)
        with self._lock:
            try:
                with open(self._path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError as exc:
                logger.error("AuditLog write failed: %s", exc)

    def record(
        self,
        *,
        actor: str,
        role: str,
        op: str,
        target: str,
        operator: str = "",
        mcc: str = "",
        trace_id: str,
        outcome: str,
        detail: str = "",
    ) -> None:
        self.append(
            {
                "actor": actor,
                "role": role,
                "op": op,
                "target": target,
                "operator": operator,
                "mcc": mcc,
                "trace_id": trace_id,
                "outcome": outcome,
                "detail": detail,
            }
        )

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        if not os.path.exists(self._path):
            return []
        entries: list[dict[str, Any]] = []
        try:
            with open(self._path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except ValueError:
                        continue
        except OSError as exc:
            logger.error("AuditLog read failed: %s", exc)
            return []
        return entries[-limit:][::-1]


audit_log = AuditLog()
