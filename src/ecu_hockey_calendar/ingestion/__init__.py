"""Ingestion pipeline for multi-source crawler, HTML parsing, and normalization."""

from __future__ import annotations

from ecu_hockey_calendar.ingestion.client import (
    DEFAULT_BACKOFF_FACTOR,
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    RETRYABLE_STATUS_CODES,
    ResilientHttpClient,
    compute_content_hash,
)
from ecu_hockey_calendar.ingestion.ecuhockey_crawler import (
    DEFAULT_FIRESTORE_URL,
    DEFAULT_RESULTS_HTML_URL,
    DEFAULT_TEAM_ID,
    DEFAULT_UPCOMING_HTML_URL,
    ECUHockeyCrawler,
    parse_firestore_game_document,
)
from ecu_hockey_calendar.ingestion.html_parser import (
    DEFAULT_ECU_TEAM,
    ParsedGameRecord,
    parse_schedule_html,
)
from ecu_hockey_calendar.ingestion.normalizer import (
    DEFAULT_TIMEZONE,
    normalize_team_name,
    parse_game_datetime,
    parse_game_score,
    parse_game_status,
)

__all__ = [
    "DEFAULT_BACKOFF_FACTOR",
    "DEFAULT_ECU_TEAM",
    "DEFAULT_FIRESTORE_URL",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_RESULTS_HTML_URL",
    "DEFAULT_TEAM_ID",
    "DEFAULT_TIMEOUT",
    "DEFAULT_TIMEZONE",
    "DEFAULT_UPCOMING_HTML_URL",
    "DEFAULT_USER_AGENT",
    "RETRYABLE_STATUS_CODES",
    "ECUHockeyCrawler",
    "ParsedGameRecord",
    "ResilientHttpClient",
    "compute_content_hash",
    "normalize_team_name",
    "parse_firestore_game_document",
    "parse_game_datetime",
    "parse_game_score",
    "parse_game_status",
    "parse_schedule_html",
]
