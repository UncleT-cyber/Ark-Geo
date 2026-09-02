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
    # Synchronise THE ARK forensic suite with 100% of native CAI tools/roles
    # and print the ARK-CAI initialisation banner in the terminal.
    try:
        from app.engine.cai.registry import print_startup_report

        print_startup_report()
    except Exception as exc:  # pragma: no cover - never block startup
        logger.warning("ARK-CAI startup report skipped: %s", exc)
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
