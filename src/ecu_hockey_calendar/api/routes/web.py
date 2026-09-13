"""Public responsive HTML schedule view and embeddable widget route handlers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import FileResponse

from ecu_hockey_calendar.api.routes.common import (
    check_conditional_headers,
    get_active_games,
)
from ecu_hockey_calendar.api.routes.schedule import (
    serve_head_schedule_pdf,
    serve_schedule_pdf,
)
from ecu_hockey_calendar.api.schedule_service import ScheduleDataService
from ecu_hockey_calendar.api.service import (
    DEFAULT_CACHE_MAX_AGE,
    DEFAULT_STALE_WHILE_REVALIDATE,
    CalendarFeedService,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ecu_hockey_calendar.models import Game

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
web_router = APIRouter(tags=["Web Views"])


def _build_web_caching_headers(
    content: str,
    games: Sequence[Game],
    filename: str,
) -> dict[str, str]:
    """Construct caching and content headers for HTML web views.

    Args:
        content: Rendered HTML payload string.
        games: Sequence of domain Game objects.
        filename: Suggested attachment/inline filename.

    Returns:
        Dictionary containing HTTP response headers.
    """
    etag = CalendarFeedService.compute_etag(content)
    last_mod_dt = CalendarFeedService.get_last_modified(games)
    last_mod_str = CalendarFeedService.format_http_date(last_mod_dt)

    return {
        "Content-Type": "text/html; charset=utf-8",
        "Content-Disposition": f'inline; filename="{filename}"',
        "Cache-Control": (
            f"public, max-age={DEFAULT_CACHE_MAX_AGE}, "
            f"stale-while-revalidate={DEFAULT_STALE_WHILE_REVALIDATE}"
        ),
        "ETag": etag,
        "Last-Modified": last_mod_str,
    }


def _render_schedule_view(
    request: Request,
    *,
    season: str | None,
    opponent: str | None,
    home_only: bool,
    status_filter: str | None,
    embed: bool,
    filename: str,
) -> Response:
    """Render HTML response with query filtering and conditional caching.

    Args:
        request: Incoming HTTP request.
        season: Optional season filter string.
        opponent: Optional opponent substring query.
        home_only: Whether to filter to home matches only.
        status_filter: Optional match status filter.
        embed: Whether to render the embeddable widget view.
        filename: Output filename for disposition header.

    Returns:
        HTTP response containing HTML or 304 Not Modified.
    """
    games = get_active_games(request, season=None)
    service: ScheduleDataService = getattr(
        request.app.state,
        "schedule_service",
        ScheduleDataService(),
    )
    base_url = str(request.base_url).rstrip("/")
    html_content = service.generate_html_schedule(
        games,
        season=season,
        opponent=opponent,
        home_only=home_only,
        status=status_filter,
        embed=embed,
        base_url=base_url,
    )

    headers = _build_web_caching_headers(
        content=html_content,
        games=games,
        filename=filename,
    )

    if check_conditional_headers(request, headers["ETag"], headers["Last-Modified"]):
        return Response(
            status_code=status.HTTP_304_NOT_MODIFIED,
            headers=headers,
        )

    return Response(
        content=html_content,
        status_code=status.HTTP_200_OK,
        media_type="text/html",
        headers=headers,
    )


@web_router.get(
    "/schedule",
    summary="Responsive HTML Schedule View",
    description=(
        "Responsive, mobile-first web interface for viewing the ECU Men's Ice "
        "Hockey schedule with venue directions, ticket links, and live score badges."
    ),
    response_class=Response,
    responses={
        200: {
            "content": {"text/html": {}},
            "description": "Rendered responsive HTML schedule view.",
        },
        304: {"description": "Schedule data not modified since last poll."},
    },
)
def get_schedule_html(
    request: Request,
    *,
    season: Annotated[
        str | None,
        Query(
            description=(
                "Filter games by season (e.g. '2026-2027'). Defaults to all seasons."
            ),
        ),
    ] = None,
    opponent: Annotated[
        str | None,
        Query(
            description=(
                "Filter games by opponent team name (case-insensitive substring)."
            ),
        ),
    ] = None,
    home_only: Annotated[
        bool,
        Query(description="If True, only home matches are included in the view."),
    ] = False,
    status_filter: Annotated[
        str | None,
        Query(
            alias="status",
            description=(
                "Filter games by match status (e.g. 'SCHEDULED', 'W', 'CANCELLED')."
            ),
        ),
    ] = None,
) -> Response:
    """Serve responsive HTML master schedule view with filtering and caching.

    Args:
        request: Incoming HTTP request.
        season: Optional season filter string.
        opponent: Optional opponent query substring.
        home_only: If True, include only home games.
        status_filter: Optional status filter.

    Returns:
        FastAPI Response with text/html body and caching headers.
    """
    return _render_schedule_view(
        request,
        season=season,
        opponent=opponent,
        home_only=home_only,
        status_filter=status_filter,
        embed=False,
        filename="ecu-hockey-schedule.html",
    )


@web_router.head(
    "/schedule",
    summary="Master Schedule HTML Headers",
    description="Inspect master schedule HTML cache headers without retrieving body.",
    response_class=Response,
)
def head_schedule_html(
    request: Request,
    *,
    season: Annotated[
        str | None,
        Query(description="Filter games by season (e.g. '2026-2027')."),
    ] = None,
    opponent: Annotated[
        str | None,
        Query(description="Filter games by opponent team name."),
    ] = None,
    home_only: Annotated[
        bool,
        Query(description="If True, only home matches are included."),
    ] = False,
    status_filter: Annotated[
        str | None,
        Query(alias="status", description="Filter games by match status."),
    ] = None,
) -> Response:
    """Serve HEAD response for schedule HTML endpoint.

    Args:
        request: Incoming HTTP request.
        season: Optional season filter.
        opponent: Optional opponent query.
        home_only: Home games only flag.
        status_filter: Optional status filter.

    Returns:
        Empty Response containing cache headers.
    """
    res = get_schedule_html(
        request=request,
        season=season,
        opponent=opponent,
        home_only=home_only,
        status_filter=status_filter,
    )
    return Response(status_code=res.status_code, headers=dict(res.headers))


@web_router.get(
    "/schedule/embed",
    summary="Embeddable iFrame Schedule Widget",
    description=(
        "Dedicated lightweight HTML schedule widget optimized for embedding in "
        "third-party websites, sports blogs, and rink portals via iframe."
    ),
    response_class=Response,
    responses={
        200: {
            "content": {"text/html": {}},
            "description": "Rendered embeddable schedule widget HTML.",
        },
        304: {"description": "Schedule data not modified since last poll."},
    },
)
def get_schedule_embed(
    request: Request,
    *,
    season: Annotated[
        str | None,
        Query(
            description=(
                "Filter games by season (e.g. '2026-2027'). Defaults to all seasons."
            ),
        ),
    ] = None,
    opponent: Annotated[
        str | None,
        Query(
            description=(
                "Filter games by opponent team name (case-insensitive substring)."
            ),
        ),
    ] = None,
    home_only: Annotated[
        bool,
        Query(description="If True, only home matches are included in the widget."),
    ] = False,
    status_filter: Annotated[
        str | None,
        Query(
            alias="status",
            description=(
                "Filter games by match status (e.g. 'SCHEDULED', 'W', 'CANCELLED')."
            ),
        ),
    ] = None,
) -> Response:
    """Serve embeddable HTML schedule widget with filtering and caching.

    Args:
        request: Incoming HTTP request.
        season: Optional season filter string.
        opponent: Optional opponent query substring.
        home_only: If True, include only home games.
        status_filter: Optional status filter.

    Returns:
        FastAPI Response with text/html widget body and caching headers.
    """
    return _render_schedule_view(
        request,
        season=season,
        opponent=opponent,
        home_only=home_only,
        status_filter=status_filter,
        embed=True,
        filename="ecu-hockey-schedule-embed.html",
    )


@web_router.head(
    "/schedule/embed",
    summary="Schedule Embed Widget Headers",
    description="Inspect embed widget cache headers without retrieving body.",
    response_class=Response,
)
def head_schedule_embed(
    request: Request,
    *,
    season: Annotated[
        str | None,
        Query(description="Filter games by season (e.g. '2026-2027')."),
    ] = None,
    opponent: Annotated[
        str | None,
        Query(description="Filter games by opponent team name."),
    ] = None,
    home_only: Annotated[
        bool,
        Query(description="If True, only home matches are included."),
    ] = False,
    status_filter: Annotated[
        str | None,
        Query(alias="status", description="Filter games by match status."),
    ] = None,
) -> Response:
    """Serve HEAD response for schedule embed endpoint.

    Args:
        request: Incoming HTTP request.
        season: Optional season filter.
        opponent: Optional opponent query.
        home_only: Home games only flag.
        status_filter: Optional status filter.

    Returns:
        Empty Response containing cache headers.
    """
    res = get_schedule_embed(
        request=request,
        season=season,
        opponent=opponent,
        home_only=home_only,
        status_filter=status_filter,
    )
    return Response(status_code=res.status_code, headers=dict(res.headers))


@web_router.get(
    "/schedule.pdf",
    summary="Printable Schedule PDF Grid",
    description=(
        "High-contrast printable PDF schedule grid formatted for parents, coaches, "
        "refrigerators, and bench clipboards on standard US Letter paper."
    ),
    response_class=Response,
    responses={
        200: {
            "content": {"application/pdf": {}},
            "description": "Printable master schedule PDF grid document.",
        },
        304: {"description": "Schedule data not modified since last poll."},
    },
)
def get_web_schedule_pdf(
    request: Request,
    *,
    season: Annotated[
        str | None,
        Query(
            description=(
                "Filter games by season (e.g. '2026-2027'). Defaults to all seasons."
            ),
        ),
    ] = None,
    opponent: Annotated[
        str | None,
        Query(
            description=(
                "Filter games by opponent team name (case-insensitive substring)."
            ),
        ),
    ] = None,
    home_only: Annotated[
        bool,
        Query(description="If True, only home matches are included in the PDF."),
    ] = False,
    status_filter: Annotated[
        str | None,
        Query(
            alias="status",
            description=(
                "Filter games by match status (e.g. 'SCHEDULED', 'W', 'CANCELLED')."
            ),
        ),
    ] = None,
) -> Response:
    """Serve printable schedule grid PDF from web root route."""
    return serve_schedule_pdf(
        request=request,
        season=season,
        opponent=opponent,
        home_only=home_only,
        status_filter=status_filter,
    )


@web_router.head(
    "/schedule.pdf",
    summary="Web Schedule PDF Headers",
    description=(
        "Inspect web schedule PDF cache headers without retrieving body payload."
    ),
    response_class=Response,
)
def head_web_schedule_pdf(
    request: Request,
    *,
    season: Annotated[
        str | None,
        Query(
            description=(
                "Filter games by season (e.g. '2026-2027'). Defaults to all seasons."
            ),
        ),
    ] = None,
    opponent: Annotated[
        str | None,
        Query(
            description=(
                "Filter games by opponent team name (case-insensitive substring)."
            ),
        ),
    ] = None,
    home_only: Annotated[
        bool,
        Query(description="If True, only home matches are included in the PDF."),
    ] = False,
    status_filter: Annotated[
        str | None,
        Query(
            alias="status",
            description=(
                "Filter games by match status (e.g. 'SCHEDULED', 'W', 'CANCELLED')."
            ),
        ),
    ] = None,
) -> Response:
    """Serve HEAD response for web schedule PDF endpoint."""
    return serve_head_schedule_pdf(
        request=request,
        season=season,
        opponent=opponent,
        home_only=home_only,
        status_filter=status_filter,
    )


@web_router.get(
    "/favicon.ico",
    summary="Website Favicon",
    description="Serve multi-resolution website favicon icon.",
    include_in_schema=False,
)
def get_favicon() -> Response:
    """Serve website favicon.

    Returns:
        FastAPI Response streaming the multi-resolution favicon.ico asset.
    """
    return FileResponse(
        STATIC_DIR / "favicon.ico",
        media_type="image/x-icon",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@web_router.head("/favicon.ico", include_in_schema=False)
def head_favicon() -> Response:
    """Serve HEAD response for website favicon.

    Returns:
        Empty FastAPI Response with favicon headers.
    """
    return get_favicon()


@web_router.get(
    "/site.webmanifest",
    summary="Web Application Manifest",
    description=(
        "Progressive Web Application manifest providing application metadata and icons."
    ),
    include_in_schema=False,
)
def get_site_manifest() -> Response:
    """Serve web application manifest.

    Returns:
        FastAPI Response streaming the site.webmanifest JSON metadata.
    """
    return FileResponse(
        STATIC_DIR / "site.webmanifest",
        media_type="application/manifest+json",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@web_router.head("/site.webmanifest", include_in_schema=False)
def head_site_manifest() -> Response:
    """Serve HEAD response for web application manifest.

    Returns:
        Empty FastAPI Response with manifest headers.
    """
    return get_site_manifest()
