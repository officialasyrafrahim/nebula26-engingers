"""FastAPI application factory for Rail Access Optimisation."""

import contextlib
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.db import initialize_database
from app.domain import models as _models  # noqa: F401  (register ORM tables)
from app.modules.runs.api import router as runs_router

ROUTERS = (runs_router,)


def _inprocess_worker_loop() -> None:
    """Poll the in-process rail solve worker until shutdown."""

    from app.workers.rail_solver_worker import process_next_job

    settings = get_settings()
    while True:
        try:
            process_next_job(timeout=settings.worker_poll_seconds)
        except Exception:
            time.sleep(0.5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables and optionally start the in-process worker thread."""

    initialize_database()
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
        title="Rail Access Optimisation",
        version="2.0.0",
        lifespan=lifespan,
    )

    for router in ROUTERS:
        app.include_router(router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
