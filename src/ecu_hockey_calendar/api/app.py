"""FastAPI application factory for ECU Hockey Calendar & Data Service."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from ecu_hockey_calendar.api.errors import register_exception_handlers
from ecu_hockey_calendar.api.negotiation import negotiate_response
from ecu_hockey_calendar.api.routes import (
    calendar_router,
    conflicts_router,
    health_router,
    schedule_router,
    sync_router,
    web_router,
)
from ecu_hockey_calendar.api.schedule_service import ScheduleDataService
from ecu_hockey_calendar.api.service import CalendarFeedService
from ecu_hockey_calendar.calendar import ECUHockeyCalendar
from ecu_hockey_calendar.storage.engine import create_sync_engine
from ecu_hockey_calendar.version import get_version

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

DEFAULT_API_TITLE = "ECU Men's Ice Hockey Calendar & Data API"
DEFAULT_API_DESCRIPTION = (
    "Public calendar subscription and data service for East Carolina University "
    "Men's Ice Hockey. Conforms to RFC 5545 iCalendar specification with "
    "webcal:// support."
)


def create_app(
    database_url: str | None = None,
    *,
    admin_token: str | None = None,
    title: str = DEFAULT_API_TITLE,
    description: str = DEFAULT_API_DESCRIPTION,
    enable_cors: bool = True,
) -> FastAPI:
    """Create and configure the FastAPI application instance.

    Args:
        database_url: Optional database connection URL for persistence storage.
        admin_token: Optional administrative authentication Bearer token.
        title: API documentation title.
        description: API documentation description.
        enable_cors: Whether to mount CORSMiddleware for cross-origin access.

    Returns:
        Configured FastAPI application instance.
    """
    pkg_version = get_version()

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

    # Register content-negotiated exception handlers
    register_exception_handlers(app)

    # Initialize application state dependencies
    app.state.start_time = datetime.now(UTC)
    resolved_admin_token = (
        admin_token if admin_token is not None else os.environ.get("ADMIN_API_TOKEN")
    )
    app.state.admin_token = resolved_admin_token
    app.state.calendar_service = CalendarFeedService()
    app.state.schedule_service = ScheduleDataService()
    app.state.default_calendar = ECUHockeyCalendar()

    resolved_db_url = (
        database_url if database_url is not None else os.environ.get("DATABASE_URL")
    )
    if resolved_db_url:
        app.state.db_engine = create_sync_engine(resolved_db_url)
    else:
        app.state.db_engine = None

    # Include routers
    app.include_router(web_router)
    app.include_router(health_router)
    app.include_router(calendar_router)
    app.include_router(schedule_router)
    app.include_router(sync_router)
    app.include_router(conflicts_router)

    @app.get(
        "/",
        summary="API Service Status and Information",
        tags=["General"],
        response_class=HTMLResponse,
        response_model=None,
        responses={
            200: {
                "description": "API service status and available endpoints",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "version": {"type": "string"},
                                "status": {"type": "string"},
                                "endpoints": {
                                    "type": "object",
                                    "additionalProperties": {"type": "string"},
                                },
                            },
                            "required": ["name", "version", "status", "endpoints"],
                        },
                    },
                    "text/html": {
                        "schema": {"type": "string"},
                    },
                },
            },
        },
    )
    def root(request: Request) -> Response:
        """Return API information and service endpoints via content negotiation."""
        payload: dict[str, Any] = {
            "name": title,
            "version": pkg_version,
            "status": "online",
            "endpoints": {
                "calendar_ics": "/calendar.ics",
                "conflicts": "/api/v1/conflicts",
                "docs": "/docs",
                "health": "/health",
                "openapi": "/openapi.json",
                "redoc": "/redoc",
                "schedule_csv": "/api/schedule.csv",
                "schedule_embed": "/schedule/embed",
                "schedule_html": "/schedule",
                "schedule_json": "/api/schedule.json",
                "sync_status": "/api/v1/sync/status",
            },
        }
        return negotiate_response(
            request,
            payload,
            "root.html",
            context={"active_tab": "home"},
        )

    @app.head("/", include_in_schema=False)
    def root_head(request: Request) -> Response:
        """Return HEAD response for root endpoint."""
        return root(request)

    return app
