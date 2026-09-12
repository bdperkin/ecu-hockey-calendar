"""RSS 2.0 and Atom 1.0 schedule syndication feed generation service.

This module provides the SyndicationFeedService to generate standardized,
well-formed RSS 2.0 and Atom 1.0 XML feeds directly from domain schedule collections,
supporting downstream automation workflows, student newspapers, media outlets,
and fan subscriptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast
from zoneinfo import ZoneInfo

from feedgen.feed import FeedGenerator

from ecu_hockey_calendar.api.schedule_service import filter_games
from ecu_hockey_calendar.api.service import (
    CalendarFeedService,
    resolve_venue_details,
)
from ecu_hockey_calendar.models import GameResult

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ecu_hockey_calendar.models import Game, Team

DEFAULT_SYNDICATION_TITLE: str = "ECU Men's Ice Hockey Schedule"
DEFAULT_SYNDICATION_DESCRIPTION: str = (
    "Official schedule, fixture updates, and game results for East Carolina "
    "University Men's Ice Hockey (ACHA M2 / ACCHL)."
)
DEFAULT_SYNDICATION_BASE_URL: str = "https://ecuhockey.com"
DEFAULT_SYNDICATION_LANGUAGE: str = "en-US"
DEFAULT_CACHE_MAX_AGE: int = 300
DEFAULT_STALE_WHILE_REVALIDATE: int = 600
DEFAULT_TICKETS_URL: str = "https://ecuhockey.com/tickets"
DEFAULT_ECU_TEAM_NAME: str = "East Carolina University"
RSS_MEDIA_TYPE: str = "application/rss+xml; charset=utf-8"
ATOM_MEDIA_TYPE: str = "application/atom+xml; charset=utf-8"
EASTERN_TZ: ZoneInfo = ZoneInfo("America/New_York")

DEFAULT_CATEGORIES: tuple[dict[str, str], ...] = (
    {"term": "ACCHL", "label": "ACCHL"},
    {"term": "ACHA M2", "label": "ACHA M2"},
    {"term": "Hockey", "label": "Hockey"},
    {"term": "ECU", "label": "ECU"},
)


@dataclass(frozen=True)
class SyndicationConfig:
    """Configuration settings for RSS and Atom syndication feeds.

    Attributes:
        title: Top-level feed channel title.
        description: Informative feed description summary.
        base_url: Canonical base URL for schedule fixture links.
        language: RFC 5646 language tag (defaults to 'en-US').
        primary_team_name: Canonical name of the primary team.
    """

    title: str = DEFAULT_SYNDICATION_TITLE
    description: str = DEFAULT_SYNDICATION_DESCRIPTION
    base_url: str = DEFAULT_SYNDICATION_BASE_URL
    language: str = DEFAULT_SYNDICATION_LANGUAGE
    primary_team_name: str = DEFAULT_ECU_TEAM_NAME


def _resolve_match_scores(
    game: Game,
    *,
    is_home: bool,
) -> tuple[int | None, int | None]:
    """Extract primary and opponent scores for a game."""
    if is_home:
        return game.home_score, game.away_score

    return game.away_score, game.home_score


def _format_completed_title(
    game: Game,
    *,
    is_home: bool,
    opponent_name: str,
) -> str | None:
    """Format title for completed game with scores."""
    if game.result not in (
        GameResult.WIN,
        GameResult.LOSS,
        GameResult.TIE,
        GameResult.OVERTIME_LOSS,
    ):
        return None

    ecu_score, opp_score = _resolve_match_scores(game, is_home=is_home)
    if ecu_score is None or opp_score is None:
        return None

    prefix = "Final (OT)" if game.result == GameResult.OVERTIME_LOSS else "Final"
    return f"{prefix}: ECU {ecu_score}, {opponent_name} {opp_score}"


def _format_abnormal_status_title(
    game: Game,
    match_vs: str,
    match_suffix: str,
) -> str | None:
    """Format title for cancelled or postponed game."""
    if game.result == GameResult.CANCELLED:
        return f"Cancelled: {match_vs} ({match_suffix})"

    if game.result == GameResult.POSTPONED:
        return f"Postponed: {match_vs} ({match_suffix})"

    return None


def format_match_title(
    game: Game,
    primary_team: str = DEFAULT_ECU_TEAM_NAME,
) -> str:
    """Format an informative title for a syndicated match fixture.

    Args:
        game: Domain Game instance.
        primary_team: Canonical name of primary team (ECU).

    Returns:
        Formatted match title string.
    """
    is_home = game.is_home_game(primary_team)
    opponent = game.opponent_of(primary_team)
    match_suffix = "Home Match" if is_home else "Away Match"
    match_vs = (
        f"ECU Hockey vs {opponent.name}"
        if is_home
        else f"ECU Hockey at {opponent.name}"
    )

    completed = _format_completed_title(
        game,
        is_home=is_home,
        opponent_name=opponent.name,
    )
    if completed is not None:
        return completed

    abnormal = _format_abnormal_status_title(game, match_vs, match_suffix)
    if abnormal is not None:
        return abnormal

    return f"{match_vs} ({match_suffix})"


def _build_division_conference_line(opponent: Team) -> str | None:
    """Construct division and conference detail line."""
    details: list[str] = []
    if opponent.division:
        details.append(f"Division: {opponent.division}")

    if opponent.conference:
        details.append(f"Conference: {opponent.conference}")

    return " | ".join(details) if details else None


def _build_description_details(
    game: Game,
    *,
    is_home: bool,
    opponent_name: str,
) -> list[str]:
    """Construct score and ticket lines for match description."""
    lines: list[str] = []
    ecu_score, opp_score = _resolve_match_scores(game, is_home=is_home)
    if ecu_score is not None and opp_score is not None:
        lines.append(f"Score: ECU {ecu_score}, {opponent_name} {opp_score}")

    if is_home:
        lines.append(f"Tickets: {DEFAULT_TICKETS_URL}")

    return lines


def format_match_description(
    game: Game,
    primary_team: str = DEFAULT_ECU_TEAM_NAME,
) -> str:
    """Format rich text description block for syndicated match item.

    Args:
        game: Domain Game instance.
        primary_team: Canonical name of primary team (ECU).

    Returns:
        Formatted plain-text description string.
    """
    is_home = game.is_home_game(primary_team)
    opponent = game.opponent_of(primary_team)
    eastern_dt = game.start_time.astimezone(EASTERN_TZ)
    date_str = eastern_dt.strftime("%A, %B %d, %Y")
    time_str = eastern_dt.strftime("%I:%M %p %Z").lstrip("0")
    loc_str, _ = resolve_venue_details(game.venue)

    lines = [
        f"ECU Men's Ice Hockey match against {opponent.name}.",
        "",
        f"Date: {date_str}",
        f"Puck Drop: {time_str}",
        f"Venue: {loc_str}",
        f"Designation: {'Home' if is_home else 'Away'}",
        f"Status: {game.result.value.capitalize()}",
    ]
    lines.extend(
        _build_description_details(
            game,
            is_home=is_home,
            opponent_name=opponent.name,
        ),
    )
    div_line = _build_division_conference_line(opponent)
    if div_line:
        lines.append(div_line)

    return "\n".join(lines)


def build_syndication_caching_headers(
    content: str | bytes,
    games: Sequence[Game],
    media_type: str,
    max_age: int = DEFAULT_CACHE_MAX_AGE,
) -> dict[str, str]:
    """Construct HTTP caching and content negotiation headers for feeds.

    Args:
        content: Feed document payload for ETag calculation.
        games: Sequence of games for Last-Modified calculation.
        media_type: Content-Type MIME string.
        max_age: Cache-Control max-age in seconds.

    Returns:
        Dictionary of HTTP response headers.
    """
    etag = CalendarFeedService.compute_etag(content)
    last_mod_dt = CalendarFeedService.get_last_modified(games)
    last_mod_str = CalendarFeedService.format_http_date(last_mod_dt)
    return {
        "Content-Type": media_type,
        "Cache-Control": (
            f"public, max-age={max_age}, "
            f"stale-while-revalidate={DEFAULT_STALE_WHILE_REVALIDATE}"
        ),
        "ETag": etag,
        "Last-Modified": last_mod_str,
    }


class SyndicationFeedService:
    """Service generating standard RSS 2.0 and Atom 1.0 schedule feeds."""

    def __init__(self, config: SyndicationConfig | None = None) -> None:
        """Initialize SyndicationFeedService with optional configuration.

        Args:
            config: Optional custom SyndicationConfig instance.
        """
        self.config = config or SyndicationConfig()

    def _configure_feed_metadata(
        self,
        fg: FeedGenerator,
        feed_url: str | None,
        last_modified: datetime,
    ) -> None:
        """Configure top-level channel and feed metadata."""
        fg.id(feed_url or self.config.base_url)
        fg.title(self.config.title)
        fg.link(href=self.config.base_url, rel="alternate")
        if feed_url:
            fg.link(href=feed_url, rel="self")

        fg.description(self.config.description)
        fg.subtitle(self.config.description)
        fg.language(self.config.language)
        fg.updated(last_modified)
        fg.lastBuildDate(last_modified)

    def _add_game_entry(self, fg: FeedGenerator, game: Game) -> None:
        """Construct and register a single syndicated game entry."""
        is_home = game.is_home_game(self.config.primary_team_name)
        title = format_match_title(game, self.config.primary_team_name)
        desc = format_match_description(game, self.config.primary_team_name)
        guid = f"urn:ecu-hockey:game:{game.game_id}"
        link_url = (
            DEFAULT_TICKETS_URL
            if is_home
            else f"{self.config.base_url}/schedule#{game.game_id}"
        )
        pub_dt = game.start_time.astimezone(UTC)

        fe = fg.add_entry()
        fe.id(guid)
        fe.guid(guid, permalink=False)
        fe.title(title)
        fe.link(href=link_url, rel="alternate")
        fe.description(desc)
        fe.content(desc)
        fe.published(pub_dt)
        fe.updated(pub_dt)

        for cat in DEFAULT_CATEGORIES:
            fe.category(cat)

    def build_feed(
        self,
        games: Sequence[Game],
        *,
        season: str | None = None,
        opponent: str | None = None,
        home_only: bool = False,
        future_only: bool = False,
        status: str | None = None,
        feed_url: str | None = None,
        now_utc: datetime | None = None,
    ) -> FeedGenerator:
        """Construct a configured FeedGenerator instance populated with games.

        Args:
            games: Collection of domain Game instances.
            season: Optional season filter string (e.g., '2026-2027').
            opponent: Optional opponent substring query.
            home_only: If True, include only home games.
            future_only: If True, include only future upcoming matches.
            status: Optional match status filter.
            feed_url: Optional canonical self URL for feed link.
            now_utc: Optional current UTC datetime for determinism.

        Returns:
            A populated FeedGenerator instance.
        """
        filtered = filter_games(
            games,
            season=season,
            opponent=opponent,
            home_only=home_only,
            status=status,
            future_only=future_only,
            primary_team=self.config.primary_team_name,
            now_utc=now_utc,
        )
        last_mod = CalendarFeedService.get_last_modified(filtered, default_dt=now_utc)
        fg = FeedGenerator()
        self._configure_feed_metadata(fg, feed_url, last_mod)

        for game in filtered:
            self._add_game_entry(fg, game)

        return fg

    def generate_rss_feed(  # noqa: PLR0913 # pylint: disable=too-many-arguments
        self,
        games: Sequence[Game],
        *,
        season: str | None = None,
        opponent: str | None = None,
        home_only: bool = False,
        future_only: bool = False,
        status: str | None = None,
        feed_url: str | None = None,
        now_utc: datetime | None = None,
        pretty: bool = True,
    ) -> str:
        """Generate a valid RSS 2.0 XML document as a string.

        Args:
            games: Collection of domain Game instances.
            season: Optional season filter string.
            opponent: Optional opponent substring query.
            home_only: If True, include only home games.
            future_only: If True, include only future upcoming matches.
            status: Optional match status filter.
            feed_url: Optional canonical self URL.
            now_utc: Optional current UTC datetime override.
            pretty: If True, format XML with indentation.

        Returns:
            String containing formatted RSS 2.0 XML.
        """
        fg = self.build_feed(
            games,
            season=season,
            opponent=opponent,
            home_only=home_only,
            future_only=future_only,
            status=status,
            feed_url=feed_url,
            now_utc=now_utc,
        )
        raw_rss = cast("bytes", fg.rss_str(pretty=pretty))
        return raw_rss.decode("utf-8")

    def generate_atom_feed(  # noqa: PLR0913 # pylint: disable=too-many-arguments
        self,
        games: Sequence[Game],
        *,
        season: str | None = None,
        opponent: str | None = None,
        home_only: bool = False,
        future_only: bool = False,
        status: str | None = None,
        feed_url: str | None = None,
        now_utc: datetime | None = None,
        pretty: bool = True,
    ) -> str:
        """Generate a valid Atom 1.0 XML document as a string.

        Args:
            games: Collection of domain Game instances.
            season: Optional season filter string.
            opponent: Optional opponent substring query.
            home_only: If True, include only home games.
            future_only: If True, include only future upcoming matches.
            status: Optional match status filter.
            feed_url: Optional canonical self URL.
            now_utc: Optional current UTC datetime override.
            pretty: If True, format XML with indentation.

        Returns:
            String containing formatted Atom 1.0 XML.
        """
        fg = self.build_feed(
            games,
            season=season,
            opponent=opponent,
            home_only=home_only,
            future_only=future_only,
            status=status,
            feed_url=feed_url,
            now_utc=now_utc,
        )
        raw_atom = cast("bytes", fg.atom_str(pretty=pretty))
        return raw_atom.decode("utf-8")
