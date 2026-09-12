"""FastAPI Calendar & Data Service package for ECU Ice Hockey."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ecu_hockey_calendar.api.auth import resolve_admin_token, verify_admin_token
from ecu_hockey_calendar.api.errors import register_exception_handlers
from ecu_hockey_calendar.api.negotiation import (
    determine_response_format,
    negotiate_response,
)
from ecu_hockey_calendar.api.schedule_service import (
    ScheduleDataService,
    filter_games,
    resolve_game_season,
    resolve_pdf_filename,
)
from ecu_hockey_calendar.api.server import run_server
from ecu_hockey_calendar.api.service import (
    DEFAULT_ALARM_MINUTES,
    DEFAULT_CACHE_MAX_AGE,
    DEFAULT_CALENDAR_DESC,
    DEFAULT_CALENDAR_NAME,
    DEFAULT_PROD_ID,
    DEFAULT_STALE_WHILE_REVALIDATE,
    DEFAULT_TIMEZONE,
    KNOWN_VENUES,
    CalendarFeedConfig,
    CalendarFeedService,
    VenueDetails,
    escape_text,
    fold_line,
    generate_game_uid,
    resolve_venue_details,
)

if TYPE_CHECKING:
    from fastapi import FastAPI


def create_app(
    database_url: str | None = None,
    *,
    admin_token: str | None = None,
    title: str = "ECU Men's Ice Hockey Calendar & Data API",
    description: str = (
        "Official calendar subscription feeds and schedule data endpoints "
        "for ECU Ice Hockey."
    ),
    enable_cors: bool = True,
    enable_sync_trigger: bool | None = None,
    sync_cooldown_seconds: int | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application instance.

    Args:
        database_url: Optional database connection URL for persistence storage.
        admin_token: Optional administrative authentication Bearer token.
        title: API documentation title.
        description: API documentation description.
        enable_cors: Whether to mount CORSMiddleware for cross-origin access.
        enable_sync_trigger: Whether to enable background sync trigger API endpoint.
        sync_cooldown_seconds: Optional minimum cooldown between sync cycles.

    Returns:
        Configured FastAPI application instance.
    """
    from ecu_hockey_calendar.api.app import (  # noqa: PLC0415 # pylint: disable=import-outside-toplevel
        create_app as _create_app,
    )

    return _create_app(
        database_url=database_url,
        admin_token=admin_token,
        title=title,
        description=description,
        enable_cors=enable_cors,
        enable_sync_trigger=enable_sync_trigger,
        sync_cooldown_seconds=sync_cooldown_seconds,
    )


__all__ = [
    "DEFAULT_ALARM_MINUTES",
    "DEFAULT_CACHE_MAX_AGE",
    "DEFAULT_CALENDAR_DESC",
    "DEFAULT_CALENDAR_NAME",
    "DEFAULT_PROD_ID",
    "DEFAULT_STALE_WHILE_REVALIDATE",
    "DEFAULT_TIMEZONE",
    "KNOWN_VENUES",
    "CalendarFeedConfig",
    "CalendarFeedService",
    "ScheduleDataService",
    "VenueDetails",
    "create_app",
    "determine_response_format",
    "escape_text",
    "filter_games",
    "fold_line",
    "generate_game_uid",
    "negotiate_response",
    "register_exception_handlers",
    "resolve_admin_token",
    "resolve_game_season",
    "resolve_pdf_filename",
    "resolve_venue_details",
    "run_server",
    "verify_admin_token",
]
