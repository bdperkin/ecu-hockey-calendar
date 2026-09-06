"""Ingestion pipeline for multi-source crawler, HTML parsing, and normalization."""

from __future__ import annotations

from ecu_hockey_calendar.ingestion.acchockey_crawler import (
    DEFAULT_ACCHL_SCHEDULE_URL,
    DEFAULT_PAGINATION_LIMIT,
    ACCHockeyCrawler,
)
from ecu_hockey_calendar.ingestion.acchockey_parser import (
    DEFAULT_ACCHL_SEASON,
    DEFAULT_BASE_URL,
    extract_pagination_urls,
    extract_schedule_urls,
    extract_season_from_html,
    extract_subseason_urls,
    parse_acchockey_game_html,
    parse_acchockey_schedule_html,
)
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
from ecu_hockey_calendar.ingestion.tickets_crawler import (
    DEFAULT_TICKETS_PAGE_URL,
    TicketsCrawler,
)
from ecu_hockey_calendar.ingestion.tickets_parser import (
    ParsedTicketRecord,
    TicketPriceTier,
    cross_reference_tickets_with_games,
    extract_opponent_from_title,
    extract_promotional_theme,
    identify_ticketing_vendor,
    parse_firestore_ticket_doc,
    parse_firestore_tickets_response,
    parse_html_ticket_listings,
    parse_price_text,
)

__all__ = [
    "DEFAULT_ACCHL_SCHEDULE_URL",
    "DEFAULT_ACCHL_SEASON",
    "DEFAULT_BACKOFF_FACTOR",
    "DEFAULT_BASE_URL",
    "DEFAULT_ECU_TEAM",
    "DEFAULT_FIRESTORE_URL",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_PAGINATION_LIMIT",
    "DEFAULT_RESULTS_HTML_URL",
    "DEFAULT_TEAM_ID",
    "DEFAULT_TICKETS_PAGE_URL",
    "DEFAULT_TIMEOUT",
    "DEFAULT_TIMEZONE",
    "DEFAULT_UPCOMING_HTML_URL",
    "DEFAULT_USER_AGENT",
    "RETRYABLE_STATUS_CODES",
    "ACCHockeyCrawler",
    "ECUHockeyCrawler",
    "ParsedGameRecord",
    "ParsedTicketRecord",
    "ResilientHttpClient",
    "TicketPriceTier",
    "TicketsCrawler",
    "compute_content_hash",
    "cross_reference_tickets_with_games",
    "extract_opponent_from_title",
    "extract_pagination_urls",
    "extract_promotional_theme",
    "extract_schedule_urls",
    "extract_season_from_html",
    "extract_subseason_urls",
    "identify_ticketing_vendor",
    "normalize_team_name",
    "parse_acchockey_game_html",
    "parse_acchockey_schedule_html",
    "parse_firestore_game_document",
    "parse_firestore_ticket_doc",
    "parse_firestore_tickets_response",
    "parse_game_datetime",
    "parse_game_score",
    "parse_game_status",
    "parse_html_ticket_listings",
    "parse_price_text",
    "parse_schedule_html",
]
