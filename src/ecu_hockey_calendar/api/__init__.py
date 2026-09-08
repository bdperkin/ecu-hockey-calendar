"""FastAPI Calendar & Data Service package for ECU Ice Hockey."""

from __future__ import annotations

from ecu_hockey_calendar.api.app import create_app
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
    "VenueDetails",
    "create_app",
    "escape_text",
    "fold_line",
    "generate_game_uid",
    "resolve_venue_details",
    "run_server",
]
