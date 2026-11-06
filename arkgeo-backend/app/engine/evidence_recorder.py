"""THE ARK — Evidence Recording for CAI Execution.

Persists structured execution evidence for every tool dispatch through the
CAI orchestrator. Each run receives a run ID; every execution event
(tool_started, tool_completed, scope_checked, approval_required, etc.) is
recorded with timestamp, source component, and execution references.

Records are stored as JSON lines in ``arkgeo_data/a2_evidence/`` keyed by
run ID, plus a per-run index file. Secrets are redacted before persistence.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

EVIDENCE_DIR = os.environ.get(
    "ARKGEO_EVIDENCE_DIR",
    os.path.join(os.getcwd(), "arkgeo_data", "a2_evidence"),
)

# Patterns for secrets that must never be persisted.
_SECRET_PATTERNS = [
    re.compile(r"(ARK_LAB_SSH_PASS[\"'=: ]+)[^\s\"'}]+", re.I),
    re.compile(r"(password[\"'=: ]+)[^\s\"'}]+", re.I),
    re.compile(r"Arklab-Test-2026!"),
    re.compile(r"Intentionally-Wrong-Password-9x"),
]


def redact(text: str) -> str:
    out = text
    for pat in _SECRET_PATTERNS:
        if pat.groups:
            out = pat.sub(lambda m: (m.group(1) or "") + "<REDACTED>", out)
        else:
            out = pat.sub("<REDACTED>", out)
    return out


def redact_obj(obj: Any) -> Any:
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        return {k: redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_obj(v) for v in obj]
    return obj


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_id() -> str:
    return uuid.uuid4().hex


def _evidence_path(run_id: str) -> str:
    return os.path.join(EVIDENCE_DIR, f"run_{run_id}.json")


def _index_path() -> str:
    return os.path.join(EVIDENCE_DIR, "runs_index.json")


class EvidenceRecorder:
    """Records typed execution events for a single CAI run."""

    def __init__(self, run_id: Optional[str] = None):
        self.run_id = run_id or _run_id()
        self.events: list[dict] = []
        os.makedirs(EVIDENCE_DIR, exist_ok=True)

    def record_event(
        self,
        event_type: str,
        source: str = "orchestrator",
        **fields: Any,
    ) -> dict:
        """Append a typed execution event and persist."""
        event = {
            "event": event_type,
            "run_id": self.run_id,
            "timestamp": _now_iso(),
            "source": source,
            "fields": redact_obj(fields),
        }
        self.events.append(event)
        self._persist()
        self._update_index()
        return event

    def record_tool_started(
        self,
        tool_id: str,
        args: dict,
        execution_id: str,
        session_id: str,
        risk: str,
    ) -> dict:
        return self.record_event(
            "tool_started",
            source="orchestrator.dispatch",
            tool_id=tool_id,
            args=redact_obj(args),
            execution_id=execution_id,
            session_id=session_id,
            risk=risk,
        )

    def record_tool_completed(
        self,
        tool_id: str,
        execution_id: str,
        result: dict,
        elapsed_ms: int,
    ) -> dict:
        return self.record_event(
            "tool_completed",
            source="orchestrator.dispatch",
            tool_id=tool_id,
            execution_id=execution_id,
            result=redact_obj(result),
            elapsed_ms=elapsed_ms,
        )

    def record_tool_failed(
        self,
        tool_id: str,
        execution_id: str,
        error: str,
        elapsed_ms: int,
    ) -> dict:
        return self.record_event(
            "tool_failed",
            source="orchestrator.dispatch",
            tool_id=tool_id,
            execution_id=execution_id,
            error=redact(error),
            elapsed_ms=elapsed_ms,
        )

    def record_scope_checked(
        self,
        tool_id: str,
        args: dict,
        allowed: bool,
        reason: str,
    ) -> dict:
        return self.record_event(
            "scope_checked",
            source="orchestrator.scope",
            tool_id=tool_id,
            args=redact_obj(args),
            allowed=allowed,
            reason=redact(reason),
        )

    def record_approval_required(
        self,
        tool_id: str,
        args: dict,
        execution_id: str,
        risk: str,
    ) -> dict:
        return self.record_event(
            "approval_required",
            source="orchestrator.hitl",
            tool_id=tool_id,
            args=redact_obj(args),
            execution_id=execution_id,
            risk=risk,
        )

    def record_result_verified(
        self,
        tool_id: str,
        execution_id: str,
        verified: bool,
        basis: str,
    ) -> dict:
        return self.record_event(
            "result_verified",
            source="orchestrator.verify",
            tool_id=tool_id,
            execution_id=execution_id,
            verified=verified,
            basis=redact(basis),
        )

    def record_agent_selected(
        self,
        role: str,
        path: str,
    ) -> dict:
        return self.record_event(
            "agent_selected",
            source="orchestrator.classify",
            role=role,
            path=path,
        )

    def record_run_completed(self) -> dict:
        return self.record_event("run_completed", source="orchestrator.run")

    def record_run_failed(self, reason: str) -> dict:
        return self.record_event("run_failed", source="orchestrator.run", reason=redact(reason))

    def get_record(self) -> dict:
        return {
            "run_id": self.run_id,
            "events": self.events,
            "recorded_at": _now_iso(),
        }

    def _persist(self) -> None:
        path = _evidence_path(self.run_id)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.get_record(), fh, indent=2, ensure_ascii=False)

    def _update_index(self) -> None:
        idx_path = _index_path()
        index: list[dict] = []
        if os.path.isfile(idx_path):
            try:
                with open(idx_path, encoding="utf-8") as fh:
                    index = json.load(fh)
            except (json.JSONDecodeError, OSError):
                index = []
        # Replace or append this run's latest entry
        index = [e for e in index if e.get("run_id") != self.run_id]
        index.append(
            {
                "run_id": self.run_id,
                "last_event": self.events[-1]["event"] if self.events else None,
                "last_timestamp": self.events[-1]["timestamp"] if self.events else None,
                "event_count": len(self.events),
            }
        )
        with open(idx_path, "w", encoding="utf-8") as fh:
            json.dump(index, fh, indent=2, ensure_ascii=False)


__all__ = [
    "EvidenceRecorder",
    "redact",
    "redact_obj",
]
