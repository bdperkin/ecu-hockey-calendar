"""RFC 5545 iCalendar (.ics) subscription endpoint and webcal route handlers."""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from ecu_hockey_calendar.api.routes.common import (
    check_conditional_headers,
    get_active_games,
)
from ecu_hockey_calendar.api.service import (
    DEFAULT_ALARM_MINUTES,
    DEFAULT_CACHE_MAX_AGE,
    DEFAULT_STALE_WHILE_REVALIDATE,
    CalendarFeedService,
)

router = APIRouter(tags=["Calendar"])


def _build_webcal_url(request: Request) -> str:
    """Construct webcal:// subscription URL from incoming request.

    Args:
        request: Incoming HTTP request.

    Returns:
        URL with webcal:// protocol scheme.
    """
    raw_url = str(request.url)
    return re.sub(r"^https?://", "webcal://", raw_url)


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

    games = get_active_games(request, season)
    feed_service: CalendarFeedService = getattr(
        request.app.state,
        "calendar_service",
        CalendarFeedService(),
    )

    last_mod_dt = feed_service.get_last_modified(games)
    last_mod_str = feed_service.format_http_date(last_mod_dt)

    ics_content = feed_service.generate_ics_feed(
        games,
        season=season,
        include_past=include_past,
        alarm_minutes=alarm_minutes,
        dtstamp_override=last_mod_dt,
    )

    etag = feed_service.compute_etag(ics_content)

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
    if check_conditional_headers(request, etag, last_mod_str):
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


__all__ = [
    "get_calendar_feed",
    "head_calendar_feed",
]
