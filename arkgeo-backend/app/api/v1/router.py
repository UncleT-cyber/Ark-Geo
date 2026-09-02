"""API v1 router aggregation."""
from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin_console,
    agent,
    ai,
    analyst,
    analyze,
    cai,
    config,
    deadman,
    health,
    ingest,
    investigate,
    maps,
    network,
    react,
    security,
    settings,
    signaling,
    sos,
    telecom,
    tools,
)

router = APIRouter()
router.include_router(ingest.router, tags=["ingest"])
router.include_router(analyze.router, tags=["analyze"])
router.include_router(investigate.router, tags=["investigate"])
router.include_router(agent.router, tags=["agent"])
router.include_router(ai.router, tags=["ai"])
router.include_router(sos.router, tags=["sos"])
router.include_router(health.router, tags=["health"])
router.include_router(deadman.router, tags=["deadman"])
router.include_router(settings.router, tags=["admin"])
router.include_router(admin_console.router, tags=["admin"])
router.include_router(tools.router, tags=["tools"])
router.include_router(analyst.router, tags=["analyst"])
router.include_router(telecom.router, tags=["telecom"])
router.include_router(network.router, tags=["network"])
router.include_router(react.router, tags=["react"])
router.include_router(maps.router, tags=["maps"])
router.include_router(security.router, tags=["security"])
router.include_router(signaling.router, tags=["signaling"])
router.include_router(cai.router, tags=["cai"])
router.include_router(config.router, tags=["config"])
