"""Schedule data serialization and query filtering service for feeds."""

from __future__ import annotations

import csv
import io
import json
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from zoneinfo import ZoneInfo

import jinja2
import weasyprint

from ecu_hockey_calendar.api.service import (
    DEFAULT_ECU_TEAM_NAME,
    DEFAULT_TICKETS_URL,
    CalendarFeedService,
    resolve_venue_details,
)
from ecu_hockey_calendar.models import GameResult

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ecu_hockey_calendar.models import Game

AUGUST_MONTH_CUTOFF = 8
DEFAULT_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"
ECU_LOGO_FILE = STATIC_DIR / "ecu_hockey_logo.png"
EASTERN_TZ = ZoneInfo("America/New_York")

FINAL_RESULTS = frozenset(
    {
        GameResult.WIN,
        GameResult.LOSS,
        GameResult.TIE,
        GameResult.OVERTIME_LOSS,
    },
)

STATUS_ALIASES: dict[str, set[str]] = {
    "W": {"WIN", "WINS"},
    "L": {"LOSS", "LOSSES"},
    "T": {"TIE", "TIES"},
    "OTL": {"OVERTIME_LOSS", "OT_LOSS"},
    "CANCELLED": {"CANCELED"},
    "SCHEDULED": {"UPCOMING"},
}

STATUS_METADATA: dict[GameResult, tuple[str, str, str]] = {
    GameResult.WIN: ("Final", "status-win", "W"),
    GameResult.LOSS: ("Final", "status-loss", "L"),
    GameResult.OVERTIME_LOSS: ("Final (OT)", "status-otl", "OTL"),
    GameResult.TIE: ("Final (Tie)", "status-tie", "T"),
    GameResult.CANCELLED: ("Cancelled", "status-cancelled", ""),
    GameResult.POSTPONED: ("Postponed", "status-postponed", ""),
}


def resolve_game_season(game: Game) -> str:
    """Determine the collegiate season string for a given game based on start time.

    Args:
        game: Domain Game instance.

    Returns:
        Season string formatted as 'YYYY-YYYY' (e.g., '2026-2027').
    """
    dt = game.start_time.astimezone(UTC)
    if dt.month >= AUGUST_MONTH_CUTOFF:
        return f"{dt.year}-{dt.year + 1}"

    return f"{dt.year - 1}-{dt.year}"


def _extract_available_seasons(games: Sequence[Game]) -> list[str]:
    """Extract sorted distinct collegiate seasons from games."""
    return sorted({resolve_game_season(g) for g in games}, reverse=True)


def resolve_latest_season(
    games: Sequence[Game] | None = None,
    now_utc: datetime | None = None,
) -> str:
    """Determine the latest collegiate season string from games or reference date.

    If games are provided and contain at least one valid season, returns the
    latest season among them (sorted in reverse chronological order).
    Otherwise, computes the collegiate season based on the reference timestamp
    (defaults to current UTC time).

    Args:
        games: Optional sequence of domain Game objects.
        now_utc: Optional reference datetime.

    Returns:
        Season string formatted as 'YYYY-YYYY' (e.g., '2026-2027').
    """
    if games:
        return _extract_available_seasons(games)[0]

    ref_time = now_utc if now_utc is not None else datetime.now(UTC)
    if ref_time.tzinfo is None:
        ref_time = ref_time.replace(tzinfo=UTC)
    else:
        ref_time = ref_time.astimezone(UTC)

    if ref_time.month >= AUGUST_MONTH_CUTOFF:
        return f"{ref_time.year}-{ref_time.year + 1}"

    return f"{ref_time.year - 1}-{ref_time.year}"


def _match_opponent(game: Game, opponent_query: str | None, primary_team: str) -> bool:
    """Check whether game opponent matches query filter."""
    if not opponent_query:
        return True

    clean_query = opponent_query.strip().lower()
    opp_name = game.opponent_of(primary_team).name.lower()
    return clean_query in opp_name


def _match_status(game: Game, status_query: str | None) -> bool:
    """Check whether game result or status matches query filter."""
    if not status_query:
        return True

    sq = status_query.strip().upper()
    rv = game.result.value.upper()
    rn = game.result.name.upper()
    if sq in (rv, rn):
        return True

    if sq in {"FINAL", "COMPLETED"}:
        return game.result in FINAL_RESULTS

    return sq in STATUS_ALIASES.get(rv, set()) or sq in STATUS_ALIASES.get(rn, set())


def _match_season(game: Game, season_query: str | None) -> bool:
    """Check whether game season matches query filter."""
    if not season_query:
        return True

    return resolve_game_season(game) == season_query.strip()


def _match_home_only(game: Game, *, home_only: bool, primary_team: str) -> bool:
    """Check whether game meets home match requirement."""
    if not home_only:
        return True

    return game.is_home_game(primary_team)


def _match_future_only(
    game: Game,
    *,
    future_only: bool,
    now_utc: datetime | None,
) -> bool:
    """Check if game meets future-only filter."""
    if not future_only:
        return True

    ref_time = now_utc if now_utc is not None else datetime.now(UTC)
    return game.start_time.astimezone(UTC) >= ref_time


def _game_matches_filters(
    game: Game,
    *,
    season: str | None,
    opponent: str | None,
    home_only: bool,
    status: str | None,
    future_only: bool = False,
    primary_team: str,
    now_utc: datetime | None = None,
) -> bool:
    """Check if a single game satisfies all applied query filters."""
    if not _match_season(game, season):
        return False

    if not _match_opponent(game, opponent, primary_team):
        return False

    if not _match_home_only(game, home_only=home_only, primary_team=primary_team):
        return False

    if not _match_future_only(game, future_only=future_only, now_utc=now_utc):
        return False

    return _match_status(game, status)


def _resolve_filter_season(
    season: str | None,
    games: Sequence[Game],
    now_utc: datetime | None,
) -> str | None:
    """Resolve user season filter string to concrete collegiate season or None."""
    if not season:
        return None

    clean = season.strip()
    if clean.lower() == "all":
        return None

    if clean.lower() in ("latest", "current"):
        return resolve_latest_season(games, now_utc=now_utc)

    return clean


def filter_games(  # noqa: PLR0913 # pylint: disable=too-many-arguments
    games: Sequence[Game],
    *,
    season: str | None = None,
    opponent: str | None = None,
    home_only: bool = False,
    status: str | None = None,
    future_only: bool = False,
    include_past: bool | None = None,
    primary_team: str = DEFAULT_ECU_TEAM_NAME,
    now_utc: datetime | None = None,
) -> list[Game]:
    """Filter and sort games based on query parameters.

    Args:
        games: Collection of games to filter.
        season: Optional season filter string (e.g. '2026-2027').
        opponent: Optional opponent substring query.
        home_only: If True, only home matches are included.
        status: Optional match status/result query.
        future_only: If True, only future matches are included.
        include_past: If False, only future matches are included
            (negation of future_only).
        primary_team: Canonical team name.
        now_utc: Optional reference timestamp for future_only filtering.

    Returns:
        Sorted list of matching Game objects in chronological order.
    """
    effective_future_only = (
        not include_past if include_past is not None else future_only
    )
    target_season = _resolve_filter_season(season, games, now_utc)
    matched = [
        g
        for g in games
        if _game_matches_filters(
            g,
            season=target_season,
            opponent=opponent,
            home_only=home_only,
            status=status,
            future_only=effective_future_only,
            primary_team=primary_team,
            now_utc=now_utc,
        )
    ]
    return sorted(matched, key=lambda g: g.start_time)


def _format_coordinates(geo_str: str | None) -> dict[str, float] | None:
    """Parse lat;lon coordinate string into dictionary or None."""
    if not geo_str or ";" not in geo_str:
        return None

    lat_str, lon_str = geo_str.split(";", 1)
    return {"latitude": float(lat_str), "longitude": float(lon_str)}


def _format_json_game(game: Game, primary_team: str) -> dict[str, Any]:
    """Convert a Game into a dictionary formatted for JSON output."""
    is_home = game.is_home_game(primary_team)
    loc_str, geo_str = resolve_venue_details(game.venue)
    start_utc = game.start_time.astimezone(UTC)
    return {
        "game_id": game.game_id,
        "season": resolve_game_season(game),
        "start_time": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "home_team": game.home_team.to_dict(),
        "away_team": game.away_team.to_dict(),
        "opponent": game.opponent_of(primary_team).name,
        "designation": "Home" if is_home else "Away",
        "is_home": is_home,
        "venue": game.venue,
        "location": loc_str,
        "coordinates": _format_coordinates(geo_str),
        "status": game.result.value.capitalize(),
        "result": game.result.value,
        "home_score": game.home_score,
        "away_score": game.away_score,
        "tickets_url": DEFAULT_TICKETS_URL if is_home else None,
    }


def _format_csv_row(game: Game, primary_team: str) -> dict[str, str]:
    """Convert a Game into a dictionary formatted for CSV output."""
    is_home = game.is_home_game(primary_team)
    loc_str, _ = resolve_venue_details(game.venue)
    start_utc = game.start_time.astimezone(UTC)
    home_score_str = "" if game.home_score is None else str(game.home_score)
    away_score_str = "" if game.away_score is None else str(game.away_score)
    tickets = DEFAULT_TICKETS_URL if is_home else ""
    return {
        "game_id": game.game_id,
        "season": resolve_game_season(game),
        "date": start_utc.strftime("%Y-%m-%d"),
        "time_utc": start_utc.strftime("%H:%M:%S"),
        "start_time_iso": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "home_team": game.home_team.name,
        "away_team": game.away_team.name,
        "opponent": game.opponent_of(primary_team).name,
        "designation": "Home" if is_home else "Away",
        "venue": game.venue,
        "location": loc_str,
        "status": game.result.value.capitalize(),
        "home_score": home_score_str,
        "away_score": away_score_str,
        "tickets_url": tickets,
    }


def _resolve_game_scores(
    game: Game,
    *,
    is_home: bool,
) -> tuple[int | None, int | None]:
    """Return primary team score and opponent score."""
    if is_home:
        return game.home_score, game.away_score

    return game.away_score, game.home_score


def _resolve_html_status(
    game: Game,
    *,
    is_home: bool,
) -> tuple[str, str, str | None]:
    """Resolve display status label, CSS badge class, and score text.

    Args:
        game: Domain Game instance.
        is_home: True if primary team is the home team.

    Returns:
        Tuple of (status_label, status_badge_class, score_text).
    """
    meta = STATUS_METADATA.get(game.result)
    if meta is None:
        return "Scheduled", "status-scheduled", None

    label, badge_class, prefix = meta
    if not prefix:
        return label, badge_class, None

    ecu_score, opp_score = _resolve_game_scores(game, is_home=is_home)
    if ecu_score is not None and opp_score is not None:
        return label, badge_class, f"{prefix} {ecu_score}-{opp_score}"

    return label, badge_class, prefix


def _format_html_game(game: Game, primary_team: str) -> dict[str, Any]:
    """Convert a Game into a dictionary formatted for HTML template rendering.

    Args:
        game: Domain Game instance.
        primary_team: Canonical team name for home/away perspective.

    Returns:
        Dictionary formatted with presentation properties for HTML views.
    """
    is_home = game.is_home_game(primary_team)
    opp = game.opponent_of(primary_team)
    loc_str, _ = resolve_venue_details(game.venue)
    query_target = loc_str or game.venue
    map_url = (
        f"https://www.google.com/maps/search/?api=1&query="
        f"{urllib.parse.quote_plus(query_target)}"
    )

    start_eastern = game.start_time.astimezone(EASTERN_TZ)
    date_str = (
        f"{start_eastern.strftime('%a, %b')} {start_eastern.day}, {start_eastern.year}"
    )
    time_str = (
        f"{start_eastern.strftime('%I:%M %p').lstrip('0')} {start_eastern.tzname()}"
    )
    start_iso = game.start_time.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    status_label, status_badge_class, score_text = _resolve_html_status(
        game,
        is_home=is_home,
    )

    return {
        "game_id": game.game_id,
        "season": resolve_game_season(game),
        "date_str": date_str,
        "time_str": time_str,
        "start_time_iso": start_iso,
        "is_home": is_home,
        "designation": "Home" if is_home else "Away",
        "opponent_name": opp.name,
        "opponent_logo_url": opp.logo_url,
        "opponent_initials": opp.initials,
        "opponent_location": f"{opp.city}, {opp.state}",
        "opponent_division": opp.division,
        "opponent_conference": opp.conference,
        "venue": game.venue,
        "location": loc_str,
        "map_url": map_url,
        "status_label": status_label,
        "status_badge_class": status_badge_class,
        "score_text": score_text,
        "tickets_url": DEFAULT_TICKETS_URL if is_home else None,
        "show_now_divider_before": False,
    }


def _is_game_past(game: Game, ref_time: datetime) -> bool:
    """Determine whether a game has completed or occurred in the past."""
    ref_utc = ref_time if ref_time.tzinfo is not None else ref_time.replace(tzinfo=UTC)
    return game.start_time.astimezone(UTC) < ref_utc


def _find_first_future_index(games: Sequence[Game], ref_time: datetime) -> int | None:
    """Find index of the first future game in sorted sequence."""
    for idx, g in enumerate(games):
        if not _is_game_past(g, ref_time):
            return idx

    return None


def _annotate_now_divider(
    formatted_games: list[dict[str, Any]],
    games: Sequence[Game],
    ref_time: datetime,
) -> bool:
    """Annotate formatted games with show_now_divider_before flag.

    Returns:
        True if divider row is present between past and future games.
    """
    first_future = _find_first_future_index(games, ref_time)
    has_divider = bool(first_future and first_future > 0)
    target_idx = first_future if has_divider else None

    for idx, fg in enumerate(formatted_games):
        fg["show_now_divider_before"] = idx == target_idx

    return has_divider


def _build_feed_urls(base_url: str) -> dict[str, str]:
    """Generate absolute or relative URLs for calendar and schedule feeds.

    Args:
        base_url: Optional base URL prefix.

    Returns:
        Dictionary mapping feed names to resolved URLs.
    """
    normalized = base_url.rstrip("/") if base_url else ""
    return {
        "schedule_url": f"{normalized}/schedule",
        "embed_url": f"{normalized}/schedule/embed",
        "ics_url": f"{normalized}/schedule.ics",
        "pdf_url": f"{normalized}/schedule.pdf",
        "csv_url": f"{normalized}/schedule.csv",
        "json_url": f"{normalized}/schedule.json",
        "rss_url": f"{normalized}/schedule.rss",
        "atom_url": f"{normalized}/schedule.atom",
    }


def resolve_pdf_filename(season: str | None, games: Sequence[Game]) -> str:
    """Resolve attachment filename for PDF schedule downloads.

    Args:
        season: Optional season filter string.
        games: Sequence of domain Game objects.

    Returns:
        Formatted filename ending in .pdf.
    """
    if season:
        clean = season.strip()
        if clean.lower() == "all":
            return "ecu_hockey_schedule.pdf"

        if clean.lower() in ("latest", "current"):
            resolved = resolve_latest_season(games).strip().replace(" ", "-")
            return f"ecu_hockey_schedule_{resolved}.pdf"

        clean_season = clean.replace(" ", "-")
        return f"ecu_hockey_schedule_{clean_season}.pdf"

    seasons = _extract_available_seasons(games)
    if len(seasons) == 1:
        clean = seasons[0].strip().replace(" ", "-")
        return f"ecu_hockey_schedule_{clean}.pdf"

    return "ecu_hockey_schedule.pdf"


def _resolve_render_seasons(
    raw_season: object,
    latest_season: str,
) -> tuple[str, str | None, str | None, bool]:
    """Resolve (selected_season, resolved_season, display_season, is_all_seasons)."""
    clean = str(raw_season).strip() if raw_season is not None else "latest"
    if clean.lower() in ("latest", "current"):
        return ("latest", latest_season, latest_season, False)

    if clean.lower() == "all" or not clean:
        return ("all", None, None, True)

    return (clean, clean, clean, False)


def _build_render_context(
    games: Sequence[Game],
    formatted_games: list[dict[str, Any]],
    base_url: str,
    filters: dict[str, str | bool | None],
    *,
    has_now_divider: bool = False,
) -> dict[str, Any]:
    """Build context dictionary for HTML template rendering."""
    raw_opp = filters.get("opponent")
    raw_status = filters.get("status")
    latest_season = resolve_latest_season(games)
    selected_season, resolved_season, display_season, is_all_seasons = (
        _resolve_render_seasons(filters.get("season"), latest_season)
    )

    return {
        "primary_team": str(filters.get("primary_team") or ""),
        "games": formatted_games,
        "total_games": len(formatted_games),
        "available_seasons": _extract_available_seasons(games),
        "latest_season": latest_season,
        "selected_season": selected_season,
        "resolved_season": resolved_season,
        "display_season": display_season,
        "is_all_seasons": is_all_seasons,
        "has_now_divider": has_now_divider,
        "selected_opponent": str(raw_opp or ""),
        "selected_home_only": bool(filters.get("home_only")),
        "selected_status": str(raw_status or "").lower(),
        "is_embed": bool(filters.get("embed")),
        **_build_feed_urls(base_url),
    }


def _resolve_pdf_selected_season(raw_season: object, games: Sequence[Game]) -> str:
    """Resolve selected_season string for PDF render context."""
    if raw_season is None:
        return ""

    clean = str(raw_season).strip()
    if clean.lower() in ("latest", "current"):
        return resolve_latest_season(games)

    if clean.lower() == "all":
        return ""

    return clean


def _resolve_pdf_logo_url(url: str | None) -> str | None:
    """Resolve static or local logo URLs to file URIs for PDF generation."""
    if not url:
        return None

    if url.startswith("/static/"):
        candidate = (STATIC_DIR / url.removeprefix("/static/")).resolve()
        if candidate.is_file():
            return candidate.as_uri()

    return url


def _resolve_pdf_ecu_logo_url(custom_url: str | None = None) -> str | None:
    """Resolve ECU header logo URL for printable PDF documents."""
    if custom_url is not None:
        return _resolve_pdf_logo_url(custom_url)

    if ECU_LOGO_FILE.is_file():
        return ECU_LOGO_FILE.as_uri()

    return None


def _format_pdf_game(game: Game, primary_team: str) -> dict[str, Any]:
    """Format a Game dictionary for PDF template rendering."""
    formatted = _format_html_game(game, primary_team)
    raw_logo = formatted.get("opponent_logo_url")
    formatted["opponent_logo_url"] = _resolve_pdf_logo_url(raw_logo)
    return formatted


def _build_pdf_render_context(
    games: Sequence[Game],
    formatted_games: list[dict[str, Any]],
    filters: dict[str, str | bool | None],
    generated_date: str | None = None,
    ecu_logo_url: str | None = None,
) -> dict[str, Any]:
    """Build context dictionary for printable PDF schedule rendering."""
    if generated_date is None:
        last_mod = CalendarFeedService.get_last_modified(games)
        generated_date = last_mod.astimezone(EASTERN_TZ).strftime("%b %d, %Y")

    resolved_ecu_logo = _resolve_pdf_ecu_logo_url(ecu_logo_url)

    return {
        "primary_team": str(filters.get("primary_team") or ""),
        "games": formatted_games,
        "total_games": len(formatted_games),
        "available_seasons": _extract_available_seasons(games),
        "selected_season": _resolve_pdf_selected_season(filters.get("season"), games),
        "selected_home_only": bool(filters.get("home_only")),
        "generated_date": generated_date,
        "tickets_url": DEFAULT_TICKETS_URL,
        "ecu_logo_url": resolved_ecu_logo,
        "is_pdf": True,
        "is_embed": False,
    }


class ScheduleDataService:
    """Service to produce normalized HTML, JSON, and CSV master schedule feeds."""

    def __init__(
        self,
        primary_team_name: str = DEFAULT_ECU_TEAM_NAME,
        templates_dir: Path | str | None = None,
    ) -> None:
        """Initialize the schedule data service.

        Args:
            primary_team_name: Canonical team name for home/away orientation.
            templates_dir: Optional custom path to Jinja2 templates directory.
        """
        self.primary_team_name = primary_team_name
        resolved_dir = Path(templates_dir) if templates_dir else DEFAULT_TEMPLATES_DIR
        self._jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(resolved_dir)),
            autoescape=jinja2.select_autoescape(["html", "xml"]),
        )

    @property
    def jinja_env(self) -> jinja2.Environment:
        """Return the configured Jinja2 environment instance.

        Returns:
            Jinja2 Environment object.
        """
        return self._jinja_env

    def generate_html_schedule(  # noqa: PLR0913 # pylint: disable=too-many-arguments,too-many-locals
        self,
        games: Sequence[Game],
        *,
        season: str | None = "latest",
        opponent: str | None = None,
        home_only: bool = False,
        status: str | None = None,
        future_only: bool = False,
        include_past: bool | None = None,
        embed: bool = False,
        base_url: str = "",
        now_utc: datetime | None = None,
    ) -> str:
        """Render responsive HTML schedule view or lightweight embed widget.

        Args:
            games: Collection of games.
            season: Optional season filter string ('latest', 'all', or specific season).
                Defaults to 'latest'.
            opponent: Optional opponent substring query.
            home_only: If True, include only home games.
            status: Optional status query.
            future_only: If True, include only future games.
            include_past: If False, include only future games.
            embed: If True, render lightweight iframe widget view.
            base_url: Optional base URL for prefixing links.
            now_utc: Optional reference timestamp for current time.

        Returns:
            Rendered HTML page string.
        """
        effective_season = "latest" if season is None else season
        filtered = filter_games(
            games,
            season=effective_season,
            opponent=opponent,
            home_only=home_only,
            status=status,
            future_only=future_only,
            include_past=include_past,
            primary_team=self.primary_team_name,
            now_utc=now_utc,
        )
        formatted_games = [
            _format_html_game(g, self.primary_team_name) for g in filtered
        ]
        ref_now = now_utc if now_utc is not None else datetime.now(UTC)
        has_now_divider = _annotate_now_divider(
            formatted_games,
            filtered,
            ref_now,
        )
        filters: dict[str, str | bool | None] = {
            "primary_team": self.primary_team_name,
            "season": effective_season,
            "opponent": opponent,
            "home_only": home_only,
            "status": status,
            "embed": embed,
        }
        context = _build_render_context(
            games,
            formatted_games,
            base_url,
            filters,
            has_now_divider=has_now_divider,
        )
        template_name = "embed.html" if embed else "schedule.html"
        template = self._jinja_env.get_template(template_name)
        return template.render(context)

    def generate_pdf_schedule(  # noqa: PLR0913 # pylint: disable=too-many-arguments
        self,
        games: Sequence[Game],
        *,
        season: str | None = None,
        opponent: str | None = None,
        home_only: bool = False,
        status: str | None = None,
        future_only: bool = False,
        include_past: bool | None = None,
        generated_date: str | None = None,
        ecu_logo_url: str | None = None,
    ) -> bytes:
        """Render printable high-contrast PDF schedule grid for parents and coaches.

        Args:
            games: Collection of domain Game instances.
            season: Optional season filter string.
            opponent: Optional opponent substring query.
            home_only: If True, include only home games.
            status: Optional status query.
            future_only: If True, include only future games.
            include_past: If False, include only future games.
            generated_date: Optional explicit date string displayed on document header.
            ecu_logo_url: Optional custom ECU crest logo URL or file path.

        Returns:
            Binary PDF document bytes starting with %PDF-1.
        """
        filtered = filter_games(
            games,
            season=season,
            opponent=opponent,
            home_only=home_only,
            status=status,
            future_only=future_only,
            include_past=include_past,
            primary_team=self.primary_team_name,
        )
        context = _build_pdf_render_context(
            filtered,
            [_format_pdf_game(g, self.primary_team_name) for g in filtered],
            {
                "primary_team": self.primary_team_name,
                "season": season,
                "opponent": opponent,
                "home_only": home_only,
                "status": status,
            },
            generated_date=generated_date,
            ecu_logo_url=ecu_logo_url,
        )
        rendered_html = self._jinja_env.get_template("schedule_pdf.html").render(
            context,
        )
        return cast(
            "bytes",
            weasyprint.HTML(
                string=rendered_html,
                base_url=str(STATIC_DIR.parent),
            ).write_pdf(),
        )

    def generate_json_feed(
        self,
        games: Sequence[Game],
        *,
        season: str | None = None,
        opponent: str | None = None,
        home_only: bool = False,
        status: str | None = None,
        future_only: bool = False,
        include_past: bool | None = None,
    ) -> dict[str, Any]:
        """Generate structured JSON payload for master schedule feed.

        Args:
            games: Collection of games.
            season: Optional season filter string.
            opponent: Optional opponent substring query.
            home_only: If True, include only home games.
            status: Optional status query.
            future_only: If True, include only future games.
            include_past: If False, include only future games.

        Returns:
            Dictionary matching master schedule JSON schema.
        """
        effective_future_only = (
            not include_past if include_past is not None else future_only
        )
        target_season = _resolve_filter_season(season, games, now_utc=None)
        filtered = filter_games(
            games,
            season=season,
            opponent=opponent,
            home_only=home_only,
            status=status,
            future_only=effective_future_only,
            primary_team=self.primary_team_name,
        )
        formatted_games = [
            _format_json_game(g, self.primary_team_name) for g in filtered
        ]
        return {
            "primary_team": self.primary_team_name,
            "season": target_season,
            "total_games": len(formatted_games),
            "filters": {
                "season": season,
                "opponent": opponent,
                "home_only": home_only,
                "status": status,
                "future_only": effective_future_only,
                "include_past": not effective_future_only,
            },
            "games": formatted_games,
        }

    def generate_json_string(
        self,
        games: Sequence[Game],
        *,
        season: str | None = None,
        opponent: str | None = None,
        home_only: bool = False,
        status: str | None = None,
        future_only: bool = False,
        include_past: bool | None = None,
        indent: int | None = 2,
    ) -> str:
        """Generate formatted JSON string representation for master schedule feed.

        Args:
            games: Collection of games.
            season: Optional season filter string.
            opponent: Optional opponent substring query.
            home_only: If True, include only home games.
            status: Optional status query.
            future_only: If True, include only future games.
            include_past: If False, include only future games.
            indent: JSON indentation spaces.

        Returns:
            JSON-encoded string.
        """
        feed = self.generate_json_feed(
            games,
            season=season,
            opponent=opponent,
            home_only=home_only,
            status=status,
            future_only=future_only,
            include_past=include_past,
        )
        return json.dumps(feed, indent=indent)

    def generate_csv_feed(
        self,
        games: Sequence[Game],
        *,
        season: str | None = None,
        opponent: str | None = None,
        home_only: bool = False,
        status: str | None = None,
        future_only: bool = False,
        include_past: bool | None = None,
    ) -> str:
        """Generate formatted CSV string for master schedule feed.

        Args:
            games: Collection of games.
            season: Optional season filter string.
            opponent: Optional opponent substring query.
            home_only: If True, include only home games.
            status: Optional status query.
            future_only: If True, include only future games.
            include_past: If False, include only future games.

        Returns:
            CSV formatted text string.
        """
        filtered = filter_games(
            games,
            season=season,
            opponent=opponent,
            home_only=home_only,
            status=status,
            future_only=future_only,
            include_past=include_past,
            primary_team=self.primary_team_name,
        )
        output = io.StringIO()
        fieldnames = [
            "game_id",
            "season",
            "date",
            "time_utc",
            "start_time_iso",
            "home_team",
            "away_team",
            "opponent",
            "designation",
            "venue",
            "location",
            "status",
            "home_score",
            "away_score",
            "tickets_url",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\r\n")
        writer.writeheader()
        for g in filtered:
            writer.writerow(_format_csv_row(g, self.primary_team_name))

        return output.getvalue()
