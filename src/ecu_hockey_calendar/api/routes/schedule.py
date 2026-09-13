"""Public master schedule JSON and CSV data feed route handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Query, Request, Response, status

from ecu_hockey_calendar.api.routes.common import (
    check_conditional_headers,
    get_active_games,
)
from ecu_hockey_calendar.api.schedule_service import (
    ScheduleDataService,
    resolve_pdf_filename,
)
from ecu_hockey_calendar.api.service import (
    DEFAULT_CACHE_MAX_AGE,
    DEFAULT_STALE_WHILE_REVALIDATE,
    CalendarFeedService,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ecu_hockey_calendar.models import Game

schedule_router = APIRouter(prefix="/api", tags=["Schedule"])


def _build_schedule_caching_headers(
    content: str | bytes,
    games: Sequence[Game],
    media_type: str,
    filename: str,
) -> dict[str, str]:
    """Construct caching and content headers for schedule feeds."""
    etag = CalendarFeedService.compute_etag(content)
    last_mod_dt = CalendarFeedService.get_last_modified(games)
    last_mod_str = CalendarFeedService.format_http_date(last_mod_dt)
    disposition = "inline" if "json" in media_type else "attachment"

    return {
        "Content-Type": media_type,
        "Content-Disposition": f'{disposition}; filename="{filename}"',
        "Cache-Control": (
            f"public, max-age={DEFAULT_CACHE_MAX_AGE}, "
            f"stale-while-revalidate={DEFAULT_STALE_WHILE_REVALIDATE}"
        ),
        "ETag": etag,
        "Last-Modified": last_mod_str,
    }


@schedule_router.get(
    "/schedule.json",
    summary="Public Master Schedule JSON Feed",
    description=(
        "Normalized JSON feed providing complete master schedule data for upcoming "
        "and past matches with query filtering."
    ),
    response_class=Response,
    responses={
        200: {
            "content": {"application/json": {}},
            "description": "Normalized master schedule JSON document.",
        },
        304: {"description": "Schedule data not modified since last poll."},
    },
)
def get_schedule_json(
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
        Query(description="If True, only home matches are included in the feed."),
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
    """Serve normalized JSON master schedule feed with filtering and caching.

    Args:
        request: Incoming HTTP request.
        season: Optional season filter string.
        opponent: Optional opponent substring query.
        home_only: If True, include only home matches.
        status_filter: Optional match status filter.

    Returns:
        FastAPI Response with application/json body and caching headers.
    """
    games = get_active_games(request, season)
    service: ScheduleDataService = getattr(
        request.app.state,
        "schedule_service",
        ScheduleDataService(),
    )

    json_content = service.generate_json_string(
        games,
        season=season,
        opponent=opponent,
        home_only=home_only,
        status=status_filter,
    )

    headers = _build_schedule_caching_headers(
        content=json_content,
        games=games,
        media_type="application/json",
        filename="ecu-hockey-schedule.json",
    )

    if check_conditional_headers(request, headers["ETag"], headers["Last-Modified"]):
        return Response(
            status_code=status.HTTP_304_NOT_MODIFIED,
            headers=headers,
        )

    return Response(
        content=json_content,
        status_code=status.HTTP_200_OK,
        media_type="application/json",
        headers=headers,
    )


@schedule_router.head(
    "/schedule.json",
    summary="Master Schedule JSON Headers",
    description=(
        "Inspect master schedule JSON cache headers without retrieving body payload."
    ),
    response_class=Response,
)
def head_schedule_json(
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
        Query(description="If True, only home matches are included in the feed."),
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
    """Serve HEAD response for schedule JSON endpoint.

    Args:
        request: Incoming HTTP request.
        season: Optional season filter.
        opponent: Optional opponent query.
        home_only: Home games only flag.
        status_filter: Optional status filter.

    Returns:
        Empty Response containing cache headers.
    """
    res = get_schedule_json(
        request=request,
        season=season,
        opponent=opponent,
        home_only=home_only,
        status_filter=status_filter,
    )
    return Response(status_code=res.status_code, headers=dict(res.headers))


@schedule_router.get(
    "/schedule.csv",
    summary="Downloadable Master Schedule CSV Export",
    description=(
        "Downloadable CSV schedule export with standard column headers for "
        "spreadsheet analysis and external tool ingestion."
    ),
    response_class=Response,
    responses={
        200: {
            "content": {"text/csv": {}},
            "description": "Standard CSV formatted master schedule.",
        },
        304: {"description": "Schedule data not modified since last poll."},
    },
)
def get_schedule_csv(
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
        Query(description="If True, only home matches are included in the export."),
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
    """Serve downloadable CSV master schedule feed with filtering and caching.

    Args:
        request: Incoming HTTP request.
        season: Optional season filter string.
        opponent: Optional opponent substring query.
        home_only: If True, include only home matches.
        status_filter: Optional match status filter.

    Returns:
        FastAPI Response with text/csv body and attachment download headers.
    """
    games = get_active_games(request, season)
    service: ScheduleDataService = getattr(
        request.app.state,
        "schedule_service",
        ScheduleDataService(),
    )

    csv_content = service.generate_csv_feed(
        games,
        season=season,
        opponent=opponent,
        home_only=home_only,
        status=status_filter,
    )

    headers = _build_schedule_caching_headers(
        content=csv_content,
        games=games,
        media_type="text/csv; charset=utf-8",
        filename="ecu-hockey-schedule.csv",
    )

    if check_conditional_headers(request, headers["ETag"], headers["Last-Modified"]):
        return Response(
            status_code=status.HTTP_304_NOT_MODIFIED,
            headers=headers,
        )

    return Response(
        content=csv_content,
        status_code=status.HTTP_200_OK,
        media_type="text/csv",
        headers=headers,
    )


@schedule_router.head(
    "/schedule.csv",
    summary="Master Schedule CSV Headers",
    description=(
        "Inspect master schedule CSV cache headers without retrieving body payload."
    ),
    response_class=Response,
)
def head_schedule_csv(
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
        Query(description="If True, only home matches are included in the export."),
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
    """Serve HEAD response for schedule CSV endpoint.

    Args:
        request: Incoming HTTP request.
        season: Optional season filter.
        opponent: Optional opponent query.
        home_only: Home games only flag.
        status_filter: Optional status filter.

    Returns:
        Empty Response containing cache headers.
    """
    res = get_schedule_csv(
        request=request,
        season=season,
        opponent=opponent,
        home_only=home_only,
        status_filter=status_filter,
    )
    return Response(status_code=res.status_code, headers=dict(res.headers))


def serve_schedule_pdf(
    request: Request,
    *,
    season: str | None = None,
    opponent: str | None = None,
    home_only: bool = False,
    status_filter: str | None = None,
) -> Response:
    """Serve printable high-contrast PDF master schedule grid.

    Args:
        request: Incoming HTTP request.
        season: Optional season filter string.
        opponent: Optional opponent substring query.
        home_only: If True, include only home matches.
        status_filter: Optional match status filter.

    Returns:
        FastAPI Response with application/pdf body and caching headers.
    """
    games = get_active_games(request, season)
    service: ScheduleDataService = getattr(
        request.app.state,
        "schedule_service",
        ScheduleDataService(),
    )
    pdf_bytes = service.generate_pdf_schedule(
        games,
        season=season,
        opponent=opponent,
        home_only=home_only,
        status=status_filter,
    )
    filename = resolve_pdf_filename(season, games)
    headers = _build_schedule_caching_headers(
        content=pdf_bytes,
        games=games,
        media_type="application/pdf",
        filename=filename,
    )
    if check_conditional_headers(request, headers["ETag"], headers["Last-Modified"]):
        return Response(
            status_code=status.HTTP_304_NOT_MODIFIED,
            headers=headers,
        )

    return Response(
        content=pdf_bytes,
        status_code=status.HTTP_200_OK,
        media_type="application/pdf",
        headers=headers,
    )


def serve_head_schedule_pdf(
    request: Request,
    *,
    season: str | None = None,
    opponent: str | None = None,
    home_only: bool = False,
    status_filter: str | None = None,
) -> Response:
    """Serve HEAD response for schedule PDF endpoint.

    Args:
        request: Incoming HTTP request.
        season: Optional season filter.
        opponent: Optional opponent query.
        home_only: Home games only flag.
        status_filter: Optional status filter.

    Returns:
        Empty Response containing cache headers.
    """
    res = serve_schedule_pdf(
        request=request,
        season=season,
        opponent=opponent,
        home_only=home_only,
        status_filter=status_filter,
    )
    return Response(status_code=res.status_code, headers=dict(res.headers))


@schedule_router.get(
    "/schedule.pdf",
    summary="Printable Master Schedule PDF Grid",
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
def get_schedule_pdf(
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
    """Serve printable schedule grid PDF from API prefix route."""
    return serve_schedule_pdf(
        request=request,
        season=season,
        opponent=opponent,
        home_only=home_only,
        status_filter=status_filter,
    )


@schedule_router.head(
    "/schedule.pdf",
    summary="Master Schedule PDF Headers",
    description=(
        "Inspect master schedule PDF cache headers without retrieving body payload."
    ),
    response_class=Response,
)
def head_schedule_pdf(
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
    """Serve HEAD response for API schedule PDF endpoint."""
    return serve_head_schedule_pdf(
        request=request,
        season=season,
        opponent=opponent,
        home_only=home_only,
        status_filter=status_filter,
    )


__all__ = [
    "get_schedule_csv",
    "get_schedule_json",
    "get_schedule_pdf",
    "head_schedule_csv",
    "head_schedule_json",
    "head_schedule_pdf",
    "serve_head_schedule_pdf",
    "serve_schedule_pdf",
]
