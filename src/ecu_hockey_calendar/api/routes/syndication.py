"""RSS 2.0 and Atom 1.0 schedule syndication feed route handlers.

Provides standardized schedule feeds for external syndication, press media,
and fan automation workflows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Query, Request, Response
from fastapi import status as fastapi_status

from ecu_hockey_calendar.api.routes.common import (
    check_conditional_headers,
    get_active_games,
)
from ecu_hockey_calendar.syndication import (
    ATOM_MEDIA_TYPE,
    RSS_MEDIA_TYPE,
    SyndicationFeedService,
    build_syndication_caching_headers,
)

if TYPE_CHECKING:
    from ecu_hockey_calendar.models import Game

router = APIRouter(tags=["Syndication"])


def _generate_feed_content(  # noqa: PLR0913 # pylint: disable=too-many-arguments
    syndication_service: SyndicationFeedService,
    games: list[Game],
    *,
    is_atom: bool,
    season: str | None,
    opponent: str | None,
    home_only: bool,
    future_only: bool,
    status_query: str | None,
    feed_url: str,
) -> tuple[str, str, str]:
    """Generate XML content, media type, and attachment filename."""
    if is_atom:
        content = syndication_service.generate_atom_feed(
            games,
            season=season,
            opponent=opponent,
            home_only=home_only,
            future_only=future_only,
            status=status_query,
            feed_url=feed_url,
        )
        return content, ATOM_MEDIA_TYPE, "ecu-hockey-schedule.atom"

    content = syndication_service.generate_rss_feed(
        games,
        season=season,
        opponent=opponent,
        home_only=home_only,
        future_only=future_only,
        status=status_query,
        feed_url=feed_url,
    )
    return content, RSS_MEDIA_TYPE, "ecu-hockey-schedule.rss"


def _handle_syndication_feed(
    request: Request,
    *,
    is_atom: bool,
    season: str | None,
    opponent: str | None,
    home_only: bool,
    future_only: bool,
    status_query: str | None,
) -> Response:
    """Generate conditional syndication feed response."""
    games = get_active_games(request, season)
    feed_service: SyndicationFeedService = getattr(
        request.app.state,
        "syndication_service",
        SyndicationFeedService(),
    )
    content, media_type, filename = _generate_feed_content(
        feed_service,
        games,
        is_atom=is_atom,
        season=season,
        opponent=opponent,
        home_only=home_only,
        future_only=future_only,
        status_query=status_query,
        feed_url=str(request.url),
    )
    headers = build_syndication_caching_headers(content, games, media_type)
    headers["Content-Disposition"] = f'inline; filename="{filename}"'

    if check_conditional_headers(request, headers["ETag"], headers["Last-Modified"]):
        return Response(
            status_code=fastapi_status.HTTP_304_NOT_MODIFIED,
            headers=headers,
        )

    return Response(
        content=content,
        status_code=fastapi_status.HTTP_200_OK,
        media_type=media_type,
        headers=headers,
    )


def _handle_head(response: Response) -> Response:
    """Return HEAD response stripping body payload."""
    return Response(
        status_code=response.status_code,
        headers=dict(response.headers),
    )


@router.get(
    "/feed.rss",
    summary="RSS 2.0 Master Schedule Feed",
    description="Syndicated RSS 2.0 XML feed of ECU Hockey schedule and results.",
    response_class=Response,
    responses={
        200: {"content": {"application/rss+xml": {}}, "description": "RSS 2.0 feed."},
        304: {"description": "Feed not modified since last poll."},
    },
)
def get_feed_rss(
    request: Request,
    *,
    season: Annotated[
        str | None,
        Query(description="Filter games by season (e.g. '2026-2027')."),
    ] = None,
    opponent: Annotated[
        str | None,
        Query(description="Filter games by opponent team name substring."),
    ] = None,
    home_only: Annotated[
        bool,
        Query(description="Filter games to only home fixtures hosted by ECU."),
    ] = False,
    future_only: Annotated[
        bool,
        Query(description="Filter games to only upcoming matches."),
    ] = False,
    status: Annotated[
        str | None,
        Query(description="Filter games by match status (e.g., 'scheduled', 'final')."),
    ] = None,
) -> Response:
    """Serve master schedule as RSS 2.0 XML syndication feed."""
    return _handle_syndication_feed(
        request,
        is_atom=False,
        season=season,
        opponent=opponent,
        home_only=home_only,
        future_only=future_only,
        status_query=status,
    )


@router.head(
    "/feed.rss",
    summary="RSS 2.0 Master Schedule Feed Headers",
    description="Inspect caching and syndication headers for RSS 2.0 feed.",
    response_class=Response,
)
def head_feed_rss(
    request: Request,
    *,
    season: Annotated[str | None, Query(description="Filter games by season.")] = None,
    opponent: Annotated[str | None, Query(description="Opponent filter.")] = None,
    home_only: Annotated[bool, Query(description="Home only filter.")] = False,
    future_only: Annotated[bool, Query(description="Upcoming only filter.")] = False,
    status: Annotated[str | None, Query(description="Match status filter.")] = None,
) -> Response:
    """Serve HEAD response for RSS 2.0 syndication feed."""
    return _handle_head(
        get_feed_rss(
            request,
            season=season,
            opponent=opponent,
            home_only=home_only,
            future_only=future_only,
            status=status,
        ),
    )


@router.get(
    "/api/schedule.rss",
    summary="RSS 2.0 Schedule API Feed Alias",
    description="Alias endpoint for RSS 2.0 schedule syndication feed under /api/.",
    response_class=Response,
    responses={
        200: {"content": {"application/rss+xml": {}}, "description": "RSS 2.0 feed."},
        304: {"description": "Feed not modified since last poll."},
    },
)
def get_api_schedule_rss(
    request: Request,
    *,
    season: Annotated[
        str | None,
        Query(description="Filter games by season (e.g. '2026-2027')."),
    ] = None,
    opponent: Annotated[
        str | None,
        Query(description="Filter games by opponent team name substring."),
    ] = None,
    home_only: Annotated[
        bool,
        Query(description="Filter games to only home fixtures hosted by ECU."),
    ] = False,
    future_only: Annotated[
        bool,
        Query(description="Filter games to only upcoming matches."),
    ] = False,
    status: Annotated[
        str | None,
        Query(description="Filter games by match status (e.g., 'scheduled', 'final')."),
    ] = None,
) -> Response:
    """Serve alias RSS 2.0 schedule feed under /api/."""
    return get_feed_rss(
        request,
        season=season,
        opponent=opponent,
        home_only=home_only,
        future_only=future_only,
        status=status,
    )


@router.head(
    "/api/schedule.rss",
    summary="RSS 2.0 Schedule API Feed Headers Alias",
    description="Inspect caching and syndication headers for /api/schedule.rss.",
    response_class=Response,
)
def head_api_schedule_rss(
    request: Request,
    *,
    season: Annotated[str | None, Query(description="Filter games by season.")] = None,
    opponent: Annotated[str | None, Query(description="Opponent filter.")] = None,
    home_only: Annotated[bool, Query(description="Home only filter.")] = False,
    future_only: Annotated[bool, Query(description="Upcoming only filter.")] = False,
    status: Annotated[str | None, Query(description="Match status filter.")] = None,
) -> Response:
    """Serve HEAD response for /api/schedule.rss."""
    return _handle_head(
        get_api_schedule_rss(
            request,
            season=season,
            opponent=opponent,
            home_only=home_only,
            future_only=future_only,
            status=status,
        ),
    )


@router.get(
    "/feed.atom",
    summary="Atom 1.0 Master Schedule Feed",
    description="Syndicated Atom 1.0 XML feed of ECU Hockey schedule and results.",
    response_class=Response,
    responses={
        200: {
            "content": {"application/atom+xml": {}},
            "description": "Atom 1.0 feed.",
        },
        304: {"description": "Feed not modified since last poll."},
    },
)
def get_feed_atom(
    request: Request,
    *,
    season: Annotated[
        str | None,
        Query(description="Filter games by season (e.g. '2026-2027')."),
    ] = None,
    opponent: Annotated[
        str | None,
        Query(description="Filter games by opponent team name substring."),
    ] = None,
    home_only: Annotated[
        bool,
        Query(description="Filter games to only home fixtures hosted by ECU."),
    ] = False,
    future_only: Annotated[
        bool,
        Query(description="Filter games to only upcoming matches."),
    ] = False,
    status: Annotated[
        str | None,
        Query(description="Filter games by match status (e.g., 'scheduled', 'final')."),
    ] = None,
) -> Response:
    """Serve master schedule as Atom 1.0 XML syndication feed."""
    return _handle_syndication_feed(
        request,
        is_atom=True,
        season=season,
        opponent=opponent,
        home_only=home_only,
        future_only=future_only,
        status_query=status,
    )


@router.head(
    "/feed.atom",
    summary="Atom 1.0 Master Schedule Feed Headers",
    description="Inspect caching and syndication headers for Atom 1.0 feed.",
    response_class=Response,
)
def head_feed_atom(
    request: Request,
    *,
    season: Annotated[str | None, Query(description="Filter games by season.")] = None,
    opponent: Annotated[str | None, Query(description="Opponent filter.")] = None,
    home_only: Annotated[bool, Query(description="Home only filter.")] = False,
    future_only: Annotated[bool, Query(description="Upcoming only filter.")] = False,
    status: Annotated[str | None, Query(description="Match status filter.")] = None,
) -> Response:
    """Serve HEAD response for Atom 1.0 syndication feed."""
    return _handle_head(
        get_feed_atom(
            request,
            season=season,
            opponent=opponent,
            home_only=home_only,
            future_only=future_only,
            status=status,
        ),
    )


@router.get(
    "/api/schedule.atom",
    summary="Atom 1.0 Schedule API Feed Alias",
    description="Alias endpoint for Atom 1.0 schedule syndication feed under /api/.",
    response_class=Response,
    responses={
        200: {
            "content": {"application/atom+xml": {}},
            "description": "Atom 1.0 feed.",
        },
        304: {"description": "Feed not modified since last poll."},
    },
)
def get_api_schedule_atom(
    request: Request,
    *,
    season: Annotated[
        str | None,
        Query(description="Filter games by season (e.g. '2026-2027')."),
    ] = None,
    opponent: Annotated[
        str | None,
        Query(description="Filter games by opponent team name substring."),
    ] = None,
    home_only: Annotated[
        bool,
        Query(description="Filter games to only home fixtures hosted by ECU."),
    ] = False,
    future_only: Annotated[
        bool,
        Query(description="Filter games to only upcoming matches."),
    ] = False,
    status: Annotated[
        str | None,
        Query(description="Filter games by match status (e.g., 'scheduled', 'final')."),
    ] = None,
) -> Response:
    """Serve alias Atom 1.0 schedule feed under /api/."""
    return get_feed_atom(
        request,
        season=season,
        opponent=opponent,
        home_only=home_only,
        future_only=future_only,
        status=status,
    )


@router.head(
    "/api/schedule.atom",
    summary="Atom 1.0 Schedule API Feed Headers Alias",
    description="Inspect caching and syndication headers for /api/schedule.atom.",
    response_class=Response,
)
def head_api_schedule_atom(
    request: Request,
    *,
    season: Annotated[str | None, Query(description="Filter games by season.")] = None,
    opponent: Annotated[str | None, Query(description="Opponent filter.")] = None,
    home_only: Annotated[bool, Query(description="Home only filter.")] = False,
    future_only: Annotated[bool, Query(description="Upcoming only filter.")] = False,
    status: Annotated[str | None, Query(description="Match status filter.")] = None,
) -> Response:
    """Serve HEAD response for /api/schedule.atom."""
    return _handle_head(
        get_api_schedule_atom(
            request,
            season=season,
            opponent=opponent,
            home_only=home_only,
            future_only=future_only,
            status=status,
        ),
    )
