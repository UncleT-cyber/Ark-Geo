"""ArkGeo backend entry point.

Wires the FastAPI app, CORS, the v1 router, and starts the Dead-Man
background poller.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import router as v1_router
from app.core.config import settings
from app.services.deadman_service import deadman

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("arkgeo")


@asynccontextmanager
async def lifespan(app: FastAPI):
    deadman.start()
    logger.info("ArkGeo backend started (v%s)", settings.app_version)
    # Any run still marked "running" belongs to a previous process whose
    # execution backend is gone. Report it honestly as interrupted instead of
    # leaving it looking live or fabricating a resume.
    try:
        from app.services.session_store import session_store

        interrupted = session_store.mark_interrupted_runs()
        if interrupted:
            logger.info("Marked %d run(s) as interrupted after restart", interrupted)
    except Exception as exc:  # pragma: no cover - never block startup
        logger.warning("Session-store recovery skipped: %s", exc)
    # Synchronise THE ARK forensic suite with 100% of native CAI tools/roles
    # and print the ARK initialisation banner in the terminal.
    try:
        from app.engine.cai.registry import print_startup_report

        print_startup_report()
    except Exception as exc:  # pragma: no cover - never block startup
        logger.warning("ARK startup report skipped: %s", exc)
    # Report optional external-binary availability once, so a missing ExifTool
    # or Chromium is visible at boot rather than only when a tool runs.
    try:
        from app.core import preflight

        preflight.report()
    except Exception as exc:  # pragma: no cover - never block startup
        logger.warning("Preflight skipped: %s", exc)
    # Reinstall the operator's declared engagement, if any, so an authorized
    # scope survives a backend restart (fail-closed when none is declared).
    try:
        from app.agent import engagement_scope
        from app.agent.engagement_store import EngagementStore

        store = EngagementStore()
        active = None
        for owner in store.list_owners():
            active = store.get_active(owner_id=owner)
            if active:
                break
        engagement_scope.set_operator_engagement(active)
        if active:
            logger.info("Engagement restored: %s targets=%s",
                        active.get("engagement_id"),
                        active.get("approved_addresses"))
    except Exception as exc:  # pragma: no cover - never block startup
        logger.warning("Engagement restore skipped: %s", exc)
    yield
    deadman.stop()
    logger.info("ArkGeo backend stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="ArkGeo modular AI geolocation & personal safety engine.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(v1_router, prefix="/api/v1")
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
