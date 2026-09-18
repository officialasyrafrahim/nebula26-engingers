"""FastAPI application factory."""

import contextlib
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.db import Base, engine
from app.domain import models as _models  # noqa: F401
from app.modules.approvals.api import router as approvals_router
from app.modules.assessment.api import router as assessment_router
from app.modules.assets.api import router as assets_router
from app.modules.assistant.api import router as assistant_router
from app.modules.condition.api import router as condition_router
from app.modules.execution.api import router as execution_router
from app.modules.ingestion.api import router as ingestion_router
from app.modules.integration.api import router as integration_router
from app.modules.model_registry.api import router as model_registry_router
from app.modules.planning.api import router as planning_router
from app.workers.solver_worker import process_next_job

ROUTERS = (
    assets_router,
    ingestion_router,
    condition_router,
    assessment_router,
    planning_router,
    approvals_router,
    execution_router,
    integration_router,
    assistant_router,
    model_registry_router,
)


def _inprocess_worker_loop() -> None:
    """Poll the in-process solver worker until shutdown."""
    while True:
        try:
            process_next_job(timeout=1.0)
        except NotImplementedError:
            time.sleep(0.5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables and optionally start the in-process worker thread."""
    Base.metadata.create_all(bind=engine)
    settings = get_settings()
    worker_thread: threading.Thread | None = None
    if settings.start_inprocess_worker:
        worker_thread = threading.Thread(target=_inprocess_worker_loop, daemon=True)
        worker_thread.start()
    try:
        yield
    finally:
        with contextlib.suppress(Exception):
            if worker_thread is not None:
                worker_thread.join(timeout=0.1)


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    app = FastAPI(
        title="Rail Maintenance Intelligence System",
        version="0.1.0",
        lifespan=lifespan,
    )

    for router in ROUTERS:
        app.include_router(router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
