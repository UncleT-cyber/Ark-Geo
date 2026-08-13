"""API v1 router aggregation."""
from fastapi import APIRouter

from app.api.v1.endpoints import analyze, deadman, health, ingest, settings, sos

router = APIRouter()
router.include_router(ingest.router, tags=["ingest"])
router.include_router(analyze.router, tags=["analyze"])
router.include_router(sos.router, tags=["sos"])
router.include_router(health.router, tags=["health"])
router.include_router(deadman.router, tags=["deadman"])
router.include_router(settings.router, tags=["settings"])
