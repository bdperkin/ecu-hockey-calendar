"""Shared request extraction, caching, and conditional validation helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from ecu_hockey_calendar.api.service import CalendarFeedService
from ecu_hockey_calendar.storage.engine import get_sync_session
from ecu_hockey_calendar.storage.models import GameModel

if TYPE_CHECKING:
    from fastapi import Request
    from sqlalchemy.orm import Session

    from ecu_hockey_calendar.models import Game


def _resolve_season_query(session: Session, season: str) -> str | None:
    """Resolve season filter string to database season value or None for all."""
    clean = season.strip()
    if clean.lower() == "all":
        return None

    if clean.lower() in ("latest", "current"):
        return session.scalars(
            select(GameModel.season).order_by(GameModel.season.desc()).limit(1),
        ).first()

    return clean


def extract_games_from_database(
    request: Request,
    season: str | None = None,
) -> list[Game]:
    """Retrieve games from database storage or return empty list.

    Args:
        request: Incoming FastAPI HTTP request.
        season: Optional season filter string.

    Returns:
        List of domain Game entities.
    """
    engine = getattr(request.app.state, "db_engine", None)
    if engine is None:
        return []

    with get_sync_session(engine) as session:
        stmt = select(GameModel)
        if season:
            target_season = _resolve_season_query(session, season)
            if target_season:
                stmt = stmt.where(GameModel.season == target_season)

        orm_games = session.scalars(stmt).all()
        return [g.to_domain() for g in orm_games]


def get_active_games(
    request: Request,
    season: str | None = None,
) -> list[Game]:
    """Resolve games from database or fall back to application state defaults.

    Args:
        request: Incoming FastAPI request.
        season: Optional season filter.

    Returns:
        List of domain Game objects.
    """
    override_games = getattr(request.app.state, "games_override", None)
    if override_games is not None:
        return list(override_games)

    db_games = extract_games_from_database(request, season)
    if db_games:
        return db_games

    default_cal = getattr(request.app.state, "default_calendar", None)
    if default_cal is not None:
        return list(default_cal.schedule.games)

    return []


def is_etag_fresh(client_etag: str | None, current_etag: str) -> bool:
    """Check whether client ETag matches current ETag (strong or weak).

    Args:
        client_etag: If-None-Match header value.
        current_etag: Current computed ETag.

    Returns:
        True if client has cached copy matching ETag.
    """
    if not client_etag:
        return False

    clean = client_etag.strip()
    return clean in (current_etag, f"W/{current_etag}")


def is_modified_since_fresh(
    header_val: str | None,
    last_modified_str: str,
) -> bool:
    """Check whether If-Modified-Since date indicates cached feed is fresh.

    Args:
        header_val: If-Modified-Since header string.
        last_modified_str: Current Last-Modified HTTP date string.

    Returns:
        True if client cached copy is still fresh.
    """
    if not header_val:
        return False

    client_dt = CalendarFeedService.parse_http_date(header_val)
    current_dt = CalendarFeedService.parse_http_date(last_modified_str)
    return bool(client_dt and current_dt and client_dt >= current_dt)


def check_conditional_headers(
    request: Request,
    etag: str,
    last_modified_str: str,
) -> bool:
    """Check If-None-Match and If-Modified-Since conditional request headers.

    Args:
        request: Incoming request.
        etag: Current calculated ETag.
        last_modified_str: Current Last-Modified HTTP date string.

    Returns:
        True if client cache is still fresh (304 Not Modified), False otherwise.
    """
    if is_etag_fresh(request.headers.get("if-none-match"), etag):
        return True

    return is_modified_since_fresh(
        request.headers.get("if-modified-since"),
        last_modified_str,
    )


def resolve_past_and_future_filters(
    *,
    include_past: bool | None = None,
    future_only: bool | None = None,
    default_include_past: bool = True,
) -> tuple[bool, bool]:
    """Resolve normalized (include_past, future_only) boolean flags.

    Args:
        include_past: Optional include_past query parameter.
        future_only: Optional future_only query parameter.
        default_include_past: Default value if neither flag is passed.

    Returns:
        Tuple of (include_past, future_only) where future_only == not include_past.
    """
    if include_past is not None:
        inc = include_past
    elif future_only is not None:
        inc = not future_only
    else:
        inc = default_include_past

    return inc, not inc


__all__ = [
    "check_conditional_headers",
    "extract_games_from_database",
    "get_active_games",
    "is_etag_fresh",
    "is_modified_since_fresh",
    "resolve_past_and_future_filters",
]
