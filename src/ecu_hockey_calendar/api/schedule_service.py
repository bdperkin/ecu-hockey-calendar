"""Schedule data serialization and query filtering service for JSON and CSV feeds."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC
from typing import TYPE_CHECKING, Any

from ecu_hockey_calendar.api.service import (
    DEFAULT_ECU_TEAM_NAME,
    DEFAULT_TICKETS_URL,
    resolve_venue_details,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ecu_hockey_calendar.models import Game

AUGUST_MONTH_CUTOFF = 8


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

    aliases: dict[str, set[str]] = {
        "W": {"WIN", "WINS"},
        "L": {"LOSS", "LOSSES"},
        "T": {"TIE", "TIES"},
        "OTL": {"OVERTIME_LOSS", "OT_LOSS"},
        "CANCELLED": {"CANCELED"},
    }
    return sq in aliases.get(rv, set()) or sq in aliases.get(rn, set())


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


class ScheduleDataService:
    """Service to produce normalized JSON and CSV master schedule data feeds."""

    def __init__(self, primary_team_name: str = DEFAULT_ECU_TEAM_NAME) -> None:
        """Initialize the schedule data service.

        Args:
            primary_team_name: Canonical team name for home/away orientation.
        """
        self.primary_team_name = primary_team_name

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
