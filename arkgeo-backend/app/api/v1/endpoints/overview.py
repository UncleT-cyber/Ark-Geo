"""System Overview endpoint — the operational picture for THE ARK.

Read-only, principal-scoped aggregate over existing stores (durable sessions,
run history, evidence index, model authority, provider health). It introduces no
new telemetry: see ``app/services/overview_service.py`` for the honesty rules.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from app.services.overview_service import build_overview
from app.services.principal import principal_from_request

router = APIRouter()


@router.get("/overview")
async def system_overview(request: Request, period: str = "24h", traces: int = 25):
    """Aggregated operational snapshot for the caller's principal.

    ``period`` is one of ``24h`` | ``7d`` | ``30d``; anything else falls back to
    ``24h``. ``traces`` bounds the recent-execution table.
    """
    hours = {"24h": 24, "7d": 168, "30d": 720}.get((period or "24h").lower(), 24)
    principal = principal_from_request(request)
    trace_limit = max(1, min(int(traces or 25), 100))
    return await build_overview(principal, period_hours=hours, trace_limit=trace_limit)


__all__ = ["router"]
