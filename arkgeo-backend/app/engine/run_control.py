"""Run control plane — operator stop, steering and execution mode (Milestone B).

The orchestrator owns execution; this module owns the *operator's* authority
over a run in flight. It is deliberately small and process-local: a control is
created when a run starts, consulted by the orchestrator at safe checkpoints,
and removed when the run reaches a terminal state.

Design rules:

  * **Stop is cooperative, not pre-emptive.** A tool that is already executing
    cannot be safely interrupted mid-syscall; the orchestrator therefore
    honours a stop request at the next safe checkpoint (top of each ReAct
    iteration and immediately after a tool returns). The state is reported
    honestly: ``stop_requested`` until the loop actually yields
    ``run_cancelled``. Nothing claims execution has stopped before the backend
    confirms it.
  * **Steering is an inbox, not a mutation.** Instructions are queued and
    drained by the orchestrator at a safe checkpoint; each is acknowledged with
    ``accepted`` / ``deferred`` / ``rejected`` so the UI can never fabricate
    mid-run steering.
  * **Mode is backend-owned.** ``manual`` requires operator approval for every
    target-directed security-sensitive dispatch; ``auto`` lets the agent
    sequence permitted tools inside the active scope. Neither mode can bypass
    the engagement scope, the policy guard or credential protections.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

MODE_AUTO = "auto"
MODE_MANUAL = "manual"
MODES = {MODE_AUTO, MODE_MANUAL}


@dataclass
class SteerMessage:
    """One operator steering instruction awaiting a safe checkpoint."""

    id: str
    message: str
    instruction_type: str = "steer"
    created_at: float = field(default_factory=time.time)
    status: str = "pending"          # pending | accepted | deferred | rejected
    reason: Optional[str] = None


@dataclass
class RunControl:
    """Operator authority over a single run in flight."""

    run_id: str
    session_id: str
    mode: str = MODE_AUTO
    stop_requested: bool = False
    stop_reason: Optional[str] = None
    stop_type: str = "stop"
    cancelled: bool = False
    status: str = "running"          # running | stopping | cancelled | completed | failed
    steering: list[SteerMessage] = field(default_factory=list)

    def request_stop(self, stop_type: str = "stop", reason: Optional[str] = None) -> None:
        """Record an operator stop. Idempotent; never pre-empts a running tool."""
        self.stop_requested = True
        self.stop_type = stop_type
        self.stop_reason = reason or "operator requested stop"
        if self.status == "running":
            self.status = "stopping"

    def submit_steer(self, message: str, instruction_type: str = "steer",
                     steer_id: Optional[str] = None) -> SteerMessage:
        entry = SteerMessage(
            id=steer_id or f"steer-{int(time.time() * 1000) % 100000}",
            message=message,
            instruction_type=instruction_type,
        )
        self.steering.append(entry)
        return entry

    def drain_steering(self) -> list[SteerMessage]:
        """Return and clear the pending steering inbox (called at a checkpoint)."""
        pending = [s for s in self.steering if s.status == "pending"]
        self.steering = [s for s in self.steering if s.status != "pending"]
        return pending

    def steering_snapshot(self) -> list[dict]:
        return [
            {"id": s.id, "message": s.message, "instruction_type": s.instruction_type,
             "status": s.status, "reason": s.reason, "created_at": s.created_at}
            for s in self.steering
        ]


_CONTROLS: dict[str, RunControl] = {}
# Latest run id per session, so a stop addressed to a session without a run id
# still reaches the active run.
_LATEST_BY_SESSION: dict[str, str] = {}


def register(run_id: str, session_id: str, mode: str = MODE_AUTO) -> RunControl:
    control = RunControl(run_id=run_id, session_id=session_id,
                         mode=mode if mode in MODES else MODE_AUTO)
    _CONTROLS[run_id] = control
    _LATEST_BY_SESSION[session_id] = run_id
    return control


def get(run_id: Optional[str]) -> Optional[RunControl]:
    if not run_id:
        return None
    return _CONTROLS.get(run_id)


def get_for_session(session_id: str) -> Optional[RunControl]:
    run_id = _LATEST_BY_SESSION.get(session_id)
    return _CONTROLS.get(run_id) if run_id else None


def resolve(session_id: Optional[str], run_id: Optional[str]) -> Optional[RunControl]:
    """Resolve a control by run id, falling back to the session's latest run."""
    control = get(run_id)
    if control is None and session_id:
        control = get_for_session(session_id)
    return control


def unregister(run_id: str) -> None:
    control = _CONTROLS.pop(run_id, None)
    if control is None:
        return
    if _LATEST_BY_SESSION.get(control.session_id) == run_id:
        _LATEST_BY_SESSION.pop(control.session_id, None)


def request_stop(session_id: Optional[str], run_id: Optional[str],
                 stop_type: str = "stop", reason: Optional[str] = None) -> Optional[RunControl]:
    control = resolve(session_id, run_id)
    if control is not None:
        control.request_stop(stop_type=stop_type, reason=reason)
    return control


def submit_steer(session_id: Optional[str], run_id: Optional[str], message: str,
                 instruction_type: str = "steer") -> Optional[SteerMessage]:
    control = resolve(session_id, run_id)
    if control is None:
        return None
    return control.submit_steer(message, instruction_type)


def is_manual(mode: Optional[str]) -> bool:
    return (mode or MODE_AUTO).lower() == MODE_MANUAL


__all__ = [
    "RunControl", "SteerMessage", "MODE_AUTO", "MODE_MANUAL", "MODES",
    "register", "get", "get_for_session", "resolve", "unregister",
    "request_stop", "submit_steer", "is_manual",
]
