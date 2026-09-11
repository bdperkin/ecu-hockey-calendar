"""FastAPI Calendar & Data Service package for ECU Ice Hockey."""

from __future__ import annotations

from ecu_hockey_calendar.api.app import create_app
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
