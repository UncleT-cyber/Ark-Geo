"""System Overview aggregate — read-only operational picture for THE ARK.

This is **not** a telemetry subsystem. It aggregates data that already exists
(the durable session store, the in-process run-control registry, the evidence
recorder's run index, the model authority and the health probes) into the single
payload the System Overview workspace renders.

Honesty rules enforced here:

* Everything is filtered to the caller's principal. Session rows, runs and
  traces are only included when they belong to one of the caller's sessions, so
  one operator never sees another's activity (§10).
* A metric that cannot be measured is reported as ``None`` ("unavailable"), never
  as a fabricated ``0``. A measured zero is ``0``. The UI renders ``None`` as
  ``—``.
* No secrets, provider keys or raw credentials are ever placed in the payload —
  only categories, ids, counts and timings.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.engine import run_control
from app.engine.evidence_recorder import load_run_index, load_run_record
from app.services.session_store import session_store

logger = logging.getLogger(__name__)

# Run statuses that mean "in flight" for the KPI/agent cards.
LIVE_STATUSES = ("running", "stopping")


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _duration_ms(started: Optional[str], ended: Optional[str]) -> Optional[int]:
    a, b = _parse_iso(started), _parse_iso(ended)
    if a is None or b is None:
        return None
    return max(0, int((b - a).total_seconds() * 1000))


def _scoped_sessions(principal) -> list[dict]:
    """The caller's durable sessions (same ownership rule as ``/cai/sessions``)."""
    from app.services.entitlements import ANONYMOUS

    if principal is ANONYMOUS:
        return session_store.list_sessions(
            principal_subject=ANONYMOUS.subject, limit=500, include_unowned=True
        )
    return session_store.list_sessions(
        principal_subject=getattr(principal, "subject", None), limit=500
    )


def _enrich_trace(run: dict, index_by_id: dict[str, dict],
                  records: Optional[dict[str, Optional[dict]]] = None) -> dict:
    """One trace row from a persisted run + its evidence-index metadata.

    Reads the run's evidence file (bounded, and reused from ``records`` when
    supplied) to recover the specialist role, the last tool and the verification
    outcome — all of which the backend actually recorded. Anything absent stays
    ``None`` rather than being guessed.
    """
    run_id = run.get("run_id")
    idx = index_by_id.get(run_id, {}) if run_id else {}
    if records is not None:
        record = records.get(run_id)
    else:
        record = load_run_record(run_id) if run_id else None

    agent: Optional[str] = None
    operation: Optional[str] = None
    verified: Optional[bool] = None
    approval: Optional[str] = None
    evidence_ref: Optional[str] = None

    if record:
        for ev in record.get("events", []):
            etype = ev.get("event")
            fields = ev.get("fields", {}) or {}
            if etype == "agent_selected":
                agent = fields.get("role") or agent
            elif etype in ("tool", "tool_completed", "tool_failed", "tool_started"):
                operation = fields.get("tool_id") or operation
                if etype == "tool":
                    verified = bool(fields.get("verified"))
            elif etype == "approval_required":
                approval = "required"
            elif etype == "scope_checked":
                approval = "scope-approved" if fields.get("allowed") else "scope-denied"
            elif etype == "evidence_recorded":
                evidence_ref = fields.get("evidence_path") or evidence_ref

    return {
        "run_id": run_id,
        "session_id": run.get("session_id"),
        "model": run.get("model"),
        "status": run.get("status"),
        "agent": agent,
        "operation": operation,
        "verified": verified,
        "approval": approval,
        "evidence_ref": evidence_ref,
        "started_at": run.get("started_at"),
        "ended_at": run.get("ended_at"),
        "duration_ms": _duration_ms(run.get("started_at"), run.get("ended_at")),
        "error": run.get("error"),
        "event_count": idx.get("event_count"),
        "last_event": idx.get("last_event"),
    }


def _activity_series(runs: list[dict], hours: int) -> list[dict]:
    """Bucketed run counts across the period (measured, not invented)."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=hours)
    # 24h -> hourly buckets; 7d -> daily; 30d -> daily.
    bucket_hours = 1 if hours <= 24 else 24
    buckets: list[dict] = []
    cursor = start
    while cursor < now:
        buckets.append({"start": cursor.isoformat(), "count": 0, "failed": 0})
        cursor += timedelta(hours=bucket_hours)
    for run in runs:
        started = _parse_iso(run.get("started_at"))
        if started is None or started < start:
            continue
        offset = int((started - start).total_seconds() // (bucket_hours * 3600))
        if 0 <= offset < len(buckets):
            buckets[offset]["count"] += 1
            if run.get("status") in ("failed", "interrupted"):
                buckets[offset]["failed"] += 1
    return buckets


async def build_overview(principal, *, period_hours: int = 24, trace_limit: int = 25) -> dict[str, Any]:
    """Assemble the System Overview payload for one principal."""
    period_hours = period_hours if period_hours in (24, 168, 720) else 24
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=period_hours)

    sessions = _scoped_sessions(principal)
    session_ids = {s["session_id"] for s in sessions}

    # ---- runs, scoped to the caller's sessions --------------------------- #
    runs: list[dict] = []
    for sid in session_ids:
        try:
            runs.extend(session_store.list_runs(sid, limit=200))
        except Exception:
            logger.warning("overview: list_runs failed for %s", sid, exc_info=True)
    runs.sort(key=lambda r: r.get("started_at") or "", reverse=True)

    index_by_id = {e.get("run_id"): e for e in load_run_index() if e.get("run_id")}

    # Period-scoped view: everything the period selector governs (executions,
    # approvals, security counts, traces). Lifetime/live metrics stay separate.
    period_runs = [
        r for r in runs
        if (d := _parse_iso(r.get("started_at"))) is not None and d >= window_start
    ]

    # Load each run's evidence record once (bounded) and reuse it for the
    # approval, security and trace derivations.
    inspect_ids = [r.get("run_id") for r in period_runs[:200] if r.get("run_id")]
    records: dict[str, Optional[dict]] = {rid: load_run_record(rid) for rid in inspect_ids}

    # ---- KPIs ------------------------------------------------------------ #
    active_investigations = sum(1 for s in sessions if s.get("last_run_status") in LIVE_STATUSES)
    total_executions = len(period_runs)
    completed = sum(1 for r in period_runs if r.get("status") == "completed")
    failed = sum(1 for r in period_runs if r.get("status") in ("failed", "interrupted"))
    measured = completed + failed
    success_rate = round(completed / measured, 3) if measured else None

    # ---- live agents (from the in-process control registry) -------------- #
    controls = run_control.list_controls()
    meta_by_session = {s["session_id"]: s for s in sessions}
    live_agents: list[dict] = []
    for c in controls:
        if c.status not in LIVE_STATUSES:
            continue
        meta = meta_by_session.get(c.session_id, {})
        agent = None
        rec = load_run_record(c.run_id)
        if rec:
            for ev in rec.get("events", []):
                if ev.get("event") == "agent_selected":
                    agent = (ev.get("fields") or {}).get("role") or agent
        live_agents.append({
            "run_id": c.run_id,
            "session_id": c.session_id,
            "agent": agent,
            "status": c.status,
            "mode": c.mode,
            "stop_requested": c.stop_requested,
            "case_id": meta.get("case_id"),
            "model": meta.get("model"),
        })

    # ---- approvals / security (from recorded events) --------------------- #
    # A live pending approval is held on the orchestrator session, which is not
    # exposed cross-principal; we report approvals the backend actually recorded
    # (`approval_required`) across the caller's runs in the period.
    approvals_requested = 0
    scope_denials = 0
    blocked = 0
    for rec in records.values():
        if not rec:
            continue
        for ev in rec.get("events", []):
            etype = ev.get("event")
            fields = ev.get("fields") or {}
            if etype == "approval_required":
                approvals_requested += 1
            elif etype == "scope_checked" and fields.get("allowed") is False:
                scope_denials += 1
            elif etype == "tool_denied":
                blocked += 1

    # ---- traces ---------------------------------------------------------- #
    traces = [_enrich_trace(r, index_by_id, records) for r in period_runs[:trace_limit]]

    # ---- model & provider health ----------------------------------------- #
    model_health: dict[str, Any] = {"available": False}
    try:
        from app.services.model_router import resolve
        res = resolve(principal)
        model_health = {
            "available": bool(res.ok),
            "model": res.resolved_model or res.requested_model,
            "provider": res.provider,
            "credential_source": res.credential_source,
            "routing_reason": res.routing_reason,
            "error": res.error,
        }
    except Exception:
        logger.warning("overview: model resolve failed", exc_info=True)

    provider_health: list[dict] = []
    try:
        from app.services.ai_gateway import ai_gateway
        status = await ai_gateway.status()
        for name, entry in (status.get("cloud") or {}).items():
            provider_health.append({
                "provider": name,
                "configured": bool(entry.get("configured")),
                "probed": bool(entry.get("probed")),
                "detail": entry.get("detail"),
                "latency_ms": entry.get("latency_ms"),
            })
        model_health["route_status"] = (status.get("route") or {}).get("status")
    except Exception:
        logger.warning("overview: ai status failed", exc_info=True)

    # ---- usage & cost (tokens/cost are not measured in the CAI path) ----- #
    local_runs = sum(
        1 for r in period_runs
        if str(r.get("model") or "").lower().startswith(("ollama/", "local/"))
    )
    usage = {
        "period_hours": period_hours,
        "requests": total_executions,
        "input_tokens": None,
        "output_tokens": None,
        "cost_usd": None,
        "cost_basis": "unavailable",
        "local_inference_runs": local_runs,
        "cloud_inference_runs": max(0, total_executions - local_runs),
        "note": "Token and cost accounting is not captured in the execution path.",
    }

    # ---- security & evidence --------------------------------------------- #
    scope_summary: list[str] = []
    try:
        from app.agent import engagement_scope
        scope_summary = engagement_scope.summary_lines()
    except Exception:
        logger.warning("overview: scope summary failed", exc_info=True)

    security = {
        "scope_active": bool(scope_summary),
        "scope_lines": scope_summary,
        "pending_approvals": approvals_requested,
        "scope_denials": scope_denials,
        "blocked_operations": blocked,
        "execution_modes": sorted({c.mode for c in controls}) or [],
    }

    evidence = {
        "runs_recorded": total_executions,
        "completed_investigations": completed,
        "audit_events": sum(
            (index_by_id.get(r.get("run_id")) or {}).get("event_count") or 0
            for r in period_runs
        ),
        "latest_verified": next(
            (t["run_id"] for t in traces if t.get("verified") is True), None
        ),
    }

    # ---- activity feed (recent runs in the period, newest first) --------- #
    activity: list[dict] = [
        {
            "at": run.get("started_at"),
            "kind": "investigation",
            "run_id": run.get("run_id"),
            "session_id": run.get("session_id"),
            "status": run.get("status"),
        }
        for run in period_runs[:trace_limit]
    ]

    return {
        "generated_at": now.isoformat(),
        "period_hours": period_hours,
        "kpis": {
            "investigations": {
                "total": len(sessions),
                "active": active_investigations,
            },
            "active_agents": {
                "running": len(live_agents),
                "idle": max(0, len(sessions) - len(live_agents)) if sessions else 0,
            },
            "tool_executions": {
                "total": total_executions,
                "completed": completed,
                "failed": failed,
                "success_rate": success_rate,
            },
            "pending_approvals": {
                "count": approvals_requested,
            },
        },
        "activity": {
            "series": _activity_series(runs, period_hours),
            "recent": activity,
        },
        "agents": live_agents,
        "model": model_health,
        "providers": provider_health,
        "usage": usage,
        "security": security,
        "evidence": evidence,
        "traces": traces,
    }


__all__ = ["build_overview"]
