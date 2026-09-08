"""RFC 5545 iCalendar (.ics) subscription endpoint and webcal route handlers."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from ecu_hockey_calendar.api.service import (
    DEFAULT_ALARM_MINUTES,
    DEFAULT_CACHE_MAX_AGE,
    DEFAULT_STALE_WHILE_REVALIDATE,
    CalendarFeedService,
)
from ecu_hockey_calendar.storage.engine import get_sync_session
from ecu_hockey_calendar.storage.models import GameModel

if TYPE_CHECKING:
    from ecu_hockey_calendar.models import Game

router = APIRouter(tags=["Calendar"])


def _extract_games_from_database(
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
            stmt = stmt.where(GameModel.season == season)

        orm_games = session.scalars(stmt).all()
        return [g.to_domain() for g in orm_games]


def _get_active_games(
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
    # 1. Check if mock/static games were explicitly set on app state (useful for tests)
    override_games = getattr(request.app.state, "games_override", None)
    if override_games is not None:
        return list(override_games)

    # 2. Query database
    db_games = _extract_games_from_database(request, season)
    if db_games:
        return db_games

    # 3. Fall back to default calendar schedule if present
    default_cal = getattr(request.app.state, "default_calendar", None)
    if default_cal is not None:
        return list(default_cal.schedule.games)

    return []


def _build_webcal_url(request: Request) -> str:
    """Construct webcal:// subscription URL from incoming request.

    Args:
        request: Incoming HTTP request.

    Returns:
        URL with webcal:// protocol scheme.
    """
    raw_url = str(request.url)
    return re.sub(r"^https?://", "webcal://", raw_url)


def _is_etag_fresh(client_etag: str | None, current_etag: str) -> bool:
    """Check whether client ETag matches current ETag (strong or weak)."""
    if not client_etag:
        return False

    clean = client_etag.strip()
    return clean in (current_etag, f"W/{current_etag}")


def _is_modified_since_fresh(
    header_val: str | None,
    last_modified_str: str,
    feed_service: CalendarFeedService,
) -> bool:
    """Check whether If-Modified-Since date indicates cached feed is fresh."""
    if not header_val:
        return False

    client_dt = feed_service.parse_http_date(header_val)
    current_dt = feed_service.parse_http_date(last_modified_str)
    return bool(client_dt and current_dt and client_dt >= current_dt)


def _check_conditional_headers(
    request: Request,
    etag: str,
    last_modified_str: str,
    feed_service: CalendarFeedService,
) -> bool:
    """Check If-None-Match and If-Modified-Since conditional request headers.

    Args:
        request: Incoming request.
        etag: Current calculated ETag.
        last_modified_str: Current Last-Modified HTTP date string.
        feed_service: CalendarFeedService instance.

    Returns:
        True if client cache is still fresh (304 Not Modified), False otherwise.
    """
    if _is_etag_fresh(request.headers.get("if-none-match"), etag):
        return True

    return _is_modified_since_fresh(
        request.headers.get("if-modified-since"),
        last_modified_str,
        feed_service,
    )


@router.get(
    "/calendar.ics",
    summary="RFC 5545 iCalendar (.ics) Subscription Feed",
    description=(
        "Public calendar subscription endpoint conforming strictly to RFC 5545. "
        "Supports webcal:// scheme subscription headers, Apple Calendar, "
        "Google Calendar, and Microsoft Outlook."
    ),
    response_class=Response,
    responses={
        200: {
            "content": {"text/calendar": {}},
            "description": "Valid RFC 5545 iCalendar stream.",
        },
        304: {"description": "Calendar feed not modified since last poll."},
    },
)
def get_calendar_feed(
    request: Request,
    *,
    season: Annotated[
        str | None,
        Query(
            description=(
                "Filter games by season (e.g. '2026-2027'). Defaults to current season."
            ),
        ),
    ] = None,
    include_past: Annotated[
        bool,
        Query(description="Whether to include past fixtures or only upcoming matches."),
    ] = True,
    alarm_minutes: Annotated[
        int,
        Query(
            ge=0,
            description=(
                "Reminder alarm trigger in minutes before puck drop (0 disables alarm)."
            ),
        ),
    ] = DEFAULT_ALARM_MINUTES,
    webcal: Annotated[
        bool,
        Query(description="If True, redirect browser to webcal:// subscription URL."),
    ] = False,
) -> Response:
    """Serve the RFC 5545 iCalendar feed with webcal and conditional caching headers.

    Args:
        request: Incoming HTTP request.
        season: Optional season filter.
        include_past: Include past fixtures flag.
        alarm_minutes: Reminder alarm offset.
        webcal: Redirect to webcal scheme flag.

    Returns:
        FastAPI Response with text/calendar content and subscription headers.
    """
    webcal_url = _build_webcal_url(request)

    # Handle webcal browser redirect parameter if requested
    if webcal:
        return RedirectResponse(
            url=webcal_url,
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )

    games = _get_active_games(request, season)
    feed_service: CalendarFeedService = getattr(
        request.app.state,
        "calendar_service",
        CalendarFeedService(),
    )

    ics_content = feed_service.generate_ics_feed(
        games,
        season=season,
        include_past=include_past,
        alarm_minutes=alarm_minutes,
    )

    etag = feed_service.compute_etag(ics_content)
    last_mod_dt = feed_service.get_last_modified(games)
    last_mod_str = feed_service.format_http_date(last_mod_dt)

    # Prepare standard caching and webcal headers
    headers = {
        "Content-Type": "text/calendar; charset=utf-8",
        "Content-Disposition": 'inline; filename="ecu-hockey-schedule.ics"',
        "Cache-Control": (
            f"public, max-age={DEFAULT_CACHE_MAX_AGE}, "
            f"stale-while-revalidate={DEFAULT_STALE_WHILE_REVALIDATE}"
        ),
        "ETag": etag,
        "Last-Modified": last_mod_str,
        "X-Webcal-Location": webcal_url,
        "Link": f'<{webcal_url}>; rel="alternate"; type="text/calendar"',
    }

    # Evaluate conditional request
    if _check_conditional_headers(request, etag, last_mod_str, feed_service):
        return Response(
            status_code=status.HTTP_304_NOT_MODIFIED,
            headers=headers,
        )

    return Response(
        content=ics_content,
        status_code=status.HTTP_200_OK,
        media_type="text/calendar",
        headers=headers,
    )


@router.head(
    "/calendar.ics",
    summary="RFC 5545 iCalendar Feed Headers",
    description=(
        "Inspect calendar feed subscription and cache headers without "
        "retrieving body payload."
    ),
    response_class=Response,
)
def head_calendar_feed(
    request: Request,
    *,
    season: Annotated[
        str | None,
        Query(
            description=(
                "Filter games by season (e.g. '2026-2027'). Defaults to current season."
            ),
        ),
    ] = None,
    include_past: Annotated[
        bool,
        Query(description="Whether to include past fixtures or only upcoming matches."),
    ] = True,
    alarm_minutes: Annotated[
        int,
        Query(
            ge=0,
            description=(
                "Reminder alarm trigger in minutes before puck drop (0 disables alarm)."
            ),
        ),
    ] = DEFAULT_ALARM_MINUTES,
) -> Response:
    """Serve HEAD response for calendar subscription endpoint.

    Args:
        request: Incoming HTTP request.
        season: Optional season filter.
        include_past: Include past fixtures flag.
        alarm_minutes: Reminder alarm offset.

    Returns:
        Empty response containing headers.
    """
    res = get_calendar_feed(
        request=request,
        season=season,
        include_past=include_past,
        alarm_minutes=alarm_minutes,
        webcal=False,
    )
    return Response(
        status_code=res.status_code,
        headers=dict(res.headers),
    )
