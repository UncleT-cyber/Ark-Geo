"""API v1 router aggregation."""
from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin_console,
    agent,
    ai,
    analyst,
    analyze,
    browser,
    cai,
    config,
    deadman,
    engagement,
    health,
    ingest,
    investigate,
    maps,
    network,
    overview,
    react,
    security,
    settings,
    signaling,
    sos,
    telecom,
    tools,
    user_models,
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
router.include_router(engagement.router, tags=["engagement"])
router.include_router(maps.router, tags=["maps"])
router.include_router(security.router, tags=["security"])
router.include_router(signaling.router, tags=["signaling"])
router.include_router(cai.router, tags=["cai"])
router.include_router(overview.router, tags=["overview"])
router.include_router(user_models.router, tags=["user-models"])
router.include_router(config.router, tags=["config"])
router.include_router(browser.router, tags=["browser"])
