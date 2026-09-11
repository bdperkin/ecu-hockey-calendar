"""Schedule data serialization and query filtering service for feeds."""

from __future__ import annotations

import csv
import io
import json
import urllib.parse
from datetime import UTC
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


def _game_matches_filters(
    game: Game,
    *,
    season: str | None,
    opponent: str | None,
    home_only: bool,
    status: str | None,
    primary_team: str,
) -> bool:
    """Check if a single game satisfies all applied query filters."""
    if not _match_season(game, season):
        return False

    if not _match_opponent(game, opponent, primary_team):
        return False

    if not _match_home_only(game, home_only=home_only, primary_team=primary_team):
        return False

    return _match_status(game, status)


def filter_games(
    games: Sequence[Game],
    *,
    season: str | None = None,
    opponent: str | None = None,
    home_only: bool = False,
    status: str | None = None,
    primary_team: str = DEFAULT_ECU_TEAM_NAME,
) -> list[Game]:
    """Filter and sort games based on query parameters.

    Args:
        games: Collection of games to filter.
        season: Optional season filter string (e.g. '2026-2027').
        opponent: Optional opponent substring query.
        home_only: If True, only home matches are included.
        status: Optional match status/result query.
        primary_team: Canonical team name.

    Returns:
        Sorted list of matching Game objects in chronological order.
    """
    matched = [
        g
        for g in games
        if _game_matches_filters(
            g,
            season=season,
            opponent=opponent,
            home_only=home_only,
            status=status,
            primary_team=primary_team,
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
    }


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
        "ics_url": f"{normalized}/calendar.ics",
        "pdf_url": f"{normalized}/schedule.pdf",
        "csv_url": f"{normalized}/api/schedule.csv",
        "json_url": f"{normalized}/api/schedule.json",
    }


def _extract_available_seasons(games: Sequence[Game]) -> list[str]:
    """Extract sorted distinct collegiate seasons from games."""
    return sorted({resolve_game_season(g) for g in games}, reverse=True)


def resolve_pdf_filename(season: str | None, games: Sequence[Game]) -> str:
    """Resolve attachment filename for PDF schedule downloads.

    Args:
        season: Optional season filter string.
        games: Sequence of domain Game objects.

    Returns:
        Formatted filename ending in .pdf.
    """
    if season:
        clean = season.strip().replace(" ", "-")
        return f"ecu_hockey_schedule_{clean}.pdf"

    seasons = _extract_available_seasons(games)
    if len(seasons) == 1:
        clean = seasons[0].strip().replace(" ", "-")
        return f"ecu_hockey_schedule_{clean}.pdf"

    return "ecu_hockey_schedule.pdf"


def _build_render_context(
    games: Sequence[Game],
    formatted_games: list[dict[str, Any]],
    base_url: str,
    filters: dict[str, str | bool | None],
) -> dict[str, Any]:
    """Build context dictionary for HTML template rendering."""
    raw_season = filters.get("season")
    raw_opp = filters.get("opponent")
    raw_status = filters.get("status")
    return {
        "primary_team": str(filters.get("primary_team") or ""),
        "games": formatted_games,
        "total_games": len(formatted_games),
        "available_seasons": _extract_available_seasons(games),
        "selected_season": str(raw_season) if raw_season else "",
        "selected_opponent": str(raw_opp) if raw_opp else "",
        "selected_home_only": bool(filters.get("home_only")),
        "selected_status": str(raw_status).lower() if raw_status else "",
        "is_embed": bool(filters.get("embed")),
        **_build_feed_urls(base_url),
    }


def _build_pdf_render_context(
    games: Sequence[Game],
    formatted_games: list[dict[str, Any]],
    filters: dict[str, str | bool | None],
    generated_date: str | None = None,
) -> dict[str, Any]:
    """Build context dictionary for printable PDF schedule rendering."""
    raw_season = filters.get("season")
    if generated_date is None:
        last_mod = CalendarFeedService.get_last_modified(games)
        generated_date = last_mod.astimezone(EASTERN_TZ).strftime("%b %d, %Y")

    return {
        "primary_team": str(filters.get("primary_team") or ""),
        "games": formatted_games,
        "total_games": len(formatted_games),
        "available_seasons": _extract_available_seasons(games),
        "selected_season": str(raw_season) if raw_season else "",
        "selected_home_only": bool(filters.get("home_only")),
        "generated_date": generated_date,
        "tickets_url": DEFAULT_TICKETS_URL,
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

    def generate_html_schedule(
        self,
        games: Sequence[Game],
        *,
        season: str | None = None,
        opponent: str | None = None,
        home_only: bool = False,
        status: str | None = None,
        embed: bool = False,
        base_url: str = "",
    ) -> str:
        """Render responsive HTML schedule view or lightweight embed widget.

        Args:
            games: Collection of games.
            season: Optional season filter string.
            opponent: Optional opponent substring query.
            home_only: If True, include only home games.
            status: Optional status query.
            embed: If True, render lightweight iframe widget view.
            base_url: Optional base URL for prefixing links.

        Returns:
            Rendered HTML page string.
        """
        filtered = filter_games(
            games,
            season=season,
            opponent=opponent,
            home_only=home_only,
            status=status,
            primary_team=self.primary_team_name,
        )
        formatted_games = [
            _format_html_game(g, self.primary_team_name) for g in filtered
        ]
        filters: dict[str, str | bool | None] = {
            "primary_team": self.primary_team_name,
            "season": season,
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
        )
        template_name = "embed.html" if embed else "schedule.html"
        template = self._jinja_env.get_template(template_name)
        return template.render(context)

    def generate_pdf_schedule(
        self,
        games: Sequence[Game],
        *,
        season: str | None = None,
        opponent: str | None = None,
        home_only: bool = False,
        status: str | None = None,
        generated_date: str | None = None,
    ) -> bytes:
        """Render printable high-contrast PDF schedule grid for parents and coaches.

        Args:
            games: Collection of domain Game instances.
            season: Optional season filter string.
            opponent: Optional opponent substring query.
            home_only: If True, include only home games.
            status: Optional status query.
            generated_date: Optional explicit date string displayed on document header.

        Returns:
            Binary PDF document bytes starting with %PDF-1.
        """
        filtered = filter_games(
            games,
            season=season,
            opponent=opponent,
            home_only=home_only,
            status=status,
            primary_team=self.primary_team_name,
        )
        formatted_games = [
            _format_html_game(g, self.primary_team_name) for g in filtered
        ]
        filters: dict[str, str | bool | None] = {
            "primary_team": self.primary_team_name,
            "season": season,
            "opponent": opponent,
            "home_only": home_only,
            "status": status,
        }
        context = _build_pdf_render_context(
            filtered,
            formatted_games,
            filters,
            generated_date=generated_date,
        )
        template = self._jinja_env.get_template("schedule_pdf.html")
        rendered_html = template.render(context)
        return cast("bytes", weasyprint.HTML(string=rendered_html).write_pdf())

    def generate_json_feed(
        self,
        games: Sequence[Game],
        *,
        season: str | None = None,
        opponent: str | None = None,
        home_only: bool = False,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Generate structured JSON payload for master schedule feed.

        Args:
            games: Collection of games.
            season: Optional season filter string.
            opponent: Optional opponent substring query.
            home_only: If True, include only home games.
            status: Optional status query.

        Returns:
            Dictionary matching master schedule JSON schema.
        """
        filtered = filter_games(
            games,
            season=season,
            opponent=opponent,
            home_only=home_only,
            status=status,
            primary_team=self.primary_team_name,
        )
        formatted_games = [
            _format_json_game(g, self.primary_team_name) for g in filtered
        ]
        return {
            "primary_team": self.primary_team_name,
            "season": season,
            "total_games": len(formatted_games),
            "filters": {
                "season": season,
                "opponent": opponent,
                "home_only": home_only,
                "status": status,
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
        indent: int | None = 2,
    ) -> str:
        """Generate formatted JSON string representation for master schedule feed.

        Args:
            games: Collection of games.
            season: Optional season filter string.
            opponent: Optional opponent substring query.
            home_only: If True, include only home games.
            status: Optional status query.
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
    ) -> str:
        """Generate formatted CSV string for master schedule feed.

        Args:
            games: Collection of games.
            season: Optional season filter string.
            opponent: Optional opponent substring query.
            home_only: If True, include only home games.
            status: Optional status query.

        Returns:
            CSV formatted text string.
        """
        filtered = filter_games(
            games,
            season=season,
            opponent=opponent,
            home_only=home_only,
            status=status,
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
