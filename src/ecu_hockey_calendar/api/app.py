"""FastAPI application factory for ECU Hockey Calendar & Data Service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ecu_hockey_calendar.api.routes import calendar_router
from ecu_hockey_calendar.api.service import CalendarFeedService
from ecu_hockey_calendar.calendar import ECUHockeyCalendar
from ecu_hockey_calendar.storage.engine import create_sync_engine

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

DEFAULT_API_TITLE = "ECU Men's Ice Hockey Calendar & Data API"
DEFAULT_API_DESCRIPTION = (
    "Public calendar subscription and data service for East Carolina University "
    "Men's Ice Hockey. Conforms to RFC 5545 iCalendar specification with "
    "webcal:// support."
)


def _resolve_package_version() -> str:
    """Resolve installed package version or return development fallback."""
    try:
        return version("ecu-hockey-calendar")
    except PackageNotFoundError:
        return "0.4.0.dev0"


def create_app(
    database_url: str | None = None,
    *,
    title: str = DEFAULT_API_TITLE,
    description: str = DEFAULT_API_DESCRIPTION,
    enable_cors: bool = True,
) -> FastAPI:
    """Create and configure the FastAPI application instance.

    Args:
        database_url: Optional database connection URL for persistence storage.
        title: API documentation title.
        description: API documentation description.
        enable_cors: Whether to mount CORSMiddleware for cross-origin access.

    Returns:
        Configured FastAPI application instance.
    """
    pkg_version = _resolve_package_version()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Manage application lifespan resources."""
        yield
        engine = getattr(app.state, "db_engine", None)
        if engine is not None:
            engine.dispose()

    app = FastAPI(
        title=title,
        description=description,
        version=pkg_version,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    if enable_cors:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["GET", "HEAD", "OPTIONS"],
            allow_headers=["*"],
        )

    # Initialize application state dependencies
    app.state.calendar_service = CalendarFeedService()
    app.state.default_calendar = ECUHockeyCalendar()

    if database_url is not None:
        app.state.db_engine = create_sync_engine(database_url)
    else:
        app.state.db_engine = None

    # Include routes
    app.include_router(calendar_router)

    @app.get(
        "/",
        summary="API Service Status and Information",
        tags=["General"],
    )
    def root() -> dict[str, Any]:
        """Return general API information and service endpoints."""
        return {
            "name": title,
            "version": pkg_version,
            "status": "online",
            "endpoints": {
                "calendar_ics": "/calendar.ics",
                "docs": "/docs",
                "redoc": "/redoc",
                "openapi": "/openapi.json",
            },
        }

    return app
