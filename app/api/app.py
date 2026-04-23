from __future__ import annotations

import logging
import time

from fastapi import FastAPI
from starlette.requests import Request

from app.api.routes.products import router as products_router
from app.infrastructure.db import configure_database, upgrade_database
from app.infrastructure.logging import (
    bind_log_context,
    configure_logging,
    get_logger,
    get_request_id,
    get_task_id,
    reset_log_context,
)
from app.infrastructure.settings import get_settings


def create_app() -> FastAPI:
    """Create and configure the FastAPI application with logging and middleware."""
    settings = get_settings()
    configure_logging(
        level=getattr(logging, settings.app_log_level.upper(), logging.INFO),
        log_dir=settings.app_log_dir,
    )
    application = FastAPI(title="FOKS API", version="1.0.0")
    application.include_router(products_router)
    logger = get_logger("app.api")

    @application.on_event("startup")
    def startup_initialize_database() -> None:
        """Run database migrations on startup so the app boots against the latest schema."""
        configure_database(
            url=settings.sqlalchemy_database_url,
            echo=settings.db_echo,
        )
        upgrade_database(url=settings.sqlalchemy_database_url)
        logger.info(
            "database_initialized",
            extra={
                "event": "database_initialized",
                "database_host": settings.db_host,
                "database_name": settings.db_name,
            },
        )

    @application.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        """Attach request/task ids to the log context for the lifetime of one HTTP request."""
        request_id = request.headers.get("X-Request-ID")
        task_id = request.headers.get("X-Task-ID")
        tokens = bind_log_context(request_id=request_id, task_id=task_id)
        started_at = time.perf_counter()
        logger.info(
            "request_started",
            extra={
                "event": "request_started",
                "method": request.method,
                "path": str(request.url.path),
            },
        )
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request_failed",
                extra={
                    "event": "request_failed",
                    "method": request.method,
                    "path": str(request.url.path),
                },
            )
            raise
        else:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            response.headers["X-Request-ID"] = get_request_id()
            response.headers["X-Task-ID"] = get_task_id()
            logger.info(
                "request_completed",
                extra={
                    "event": "request_completed",
                    "method": request.method,
                    "path": str(request.url.path),
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
            return response
        finally:
            reset_log_context(tokens)

    @application.get("/health", tags=["health"])
    def healthcheck() -> dict[str, str]:
        """Provide a lightweight health endpoint for infrastructure checks."""
        return {"status": "ok"}

    return application
