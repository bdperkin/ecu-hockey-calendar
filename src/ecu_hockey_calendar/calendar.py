"""Calendar management and export functionality for ECU Men's Ice Hockey.

This module provides the ECUHockeyCalendar service to manage game fixtures,
track team events, and export schedules into multiple interoperable formats
including iCalendar (RFC 5545), CSV, and JSON.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from ecu_hockey_calendar.models import Game, GameResult, Schedule, Team

if TYPE_CHECKING:
    from datetime import datetime

ECU_DEFAULT_TEAM = Team(
    name="East Carolina University",
    city="Greenville",
    state="NC",
    division="ACHA M2",
    conference="ACCHL",
)


class ECUHockeyCalendar:
    """Manages ECU Ice Hockey schedules and provides calendar export services.

    Attributes:
        season: The season label (e.g., '2026-2027').
        team: The primary ECU hockey Team model instance.
        schedule: The associated season Schedule collection.
    """

    def __init__(
        self,
        season: str = "2026-2027",
        team: Team | None = None,
    ) -> None:
        """Initialize the ECU Hockey Calendar.

        Args:
            season: The academic or competitive hockey season string.
            team: Optional custom primary Team; defaults to ECU Ice Hockey.
        """
        self.season = season
        self.team = team if team is not None else ECU_DEFAULT_TEAM
        self.schedule = Schedule(season=season)

    def add_match(
        self,
        opponent: Team,
        start_time: datetime,
        venue: str,
        *,
        is_home: bool = True,
        game_id: str | None = None,
        duration_hours: float = 2.5,
    ) -> Game:
        """Schedule a new match against an opponent.

        Args:
            opponent: The opposing Team object.
            start_time: Scheduled puck drop datetime.
            venue: Location or ice arena name.
            is_home: True if ECU is the home team, False if traveling away.
            game_id: Optional custom unique identifier for the game.
            duration_hours: Estimated game duration in hours.

        Returns:
            The created and registered Game instance.

        Raises:
            ValueError: If duration_hours is less than or equal to 0.
        """
        if duration_hours <= 0:
            msg = "Duration hours must be greater than zero."
            raise ValueError(msg)

        gid = (
            game_id
            if game_id is not None
            else f"ECU-{self.season}-{self.schedule.total_games + 1:02d}"
        )
        home_team = self.team if is_home else opponent
        away_team = opponent if is_home else self.team

        game = Game(
            game_id=gid,
            home_team=home_team,
            away_team=away_team,
            start_time=start_time,
            venue=venue,
            result=GameResult.SCHEDULED,
        )
        self.schedule.add_game(game)
        return game

    def export_ics(self, prod_id: str = "-//ECU Ice Hockey//Calendar//EN") -> str:
        """Generate standard RFC 5545 iCalendar data for all scheduled games.

        Args:
            prod_id: Product identifier for the iCalendar header.

        Returns:
            A string containing valid iCalendar (ICS) formatted data.
        """
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            f"PRODID:{prod_id}",
            "CALSCALE:GREGORIAN",
            f"X-WR-CALNAME:ECU Men's Ice Hockey ({self.season})",
        ]

        for game in self.schedule.games:
            dtstart = game.start_time.strftime("%Y%m%dT%H%M%SZ")
            dtend = (game.start_time + timedelta(hours=2.5)).strftime("%Y%m%dT%H%M%SZ")
            summary = (
                f"ECU Hockey vs {game.away_team.name}"
                if game.is_home_game(self.team.name)
                else f"ECU Hockey at {game.home_team.name}"
            )
            opponent = game.opponent_of(self.team.name)
            description = f"ECU Hockey {self.season} match against {opponent.name}."

            lines.extend(
                [
                    "BEGIN:VEVENT",
                    f"UID:{game.game_id}@ecu-hockey-calendar",
                    f"DTSTAMP:{dtstart}",
                    f"DTSTART:{dtstart}",
                    f"DTEND:{dtend}",
                    f"SUMMARY:{summary}",
                    f"LOCATION:{game.venue}",
                    f"DESCRIPTION:{description}",
                    "STATUS:CONFIRMED",
                    "END:VEVENT",
                ]
            )

        lines.append("END:VCALENDAR")
        return "\r\n".join(lines) + "\r\n"

    def export_json(self, indent: int = 2) -> str:
        """Export the complete season schedule as a formatted JSON string.

        Args:
            indent: Number of spaces for JSON indentation.

        Returns:
            A JSON-formatted string representation of the schedule.
        """
        data: dict[str, Any] = {
            "team": self.team.to_dict(),
            "season": self.season,
            "schedule": self.schedule.to_dict(),
        }
        return json.dumps(data, indent=indent)

    def export_csv(self) -> str:
        """Export scheduled games to CSV format.

        Returns:
            A CSV string with headers and game details.
        """
        output = io.StringIO()
        fieldnames = [
            "game_id",
            "date",
            "time",
            "home_team",
            "away_team",
            "venue",
            "is_home",
            "result",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()

        for game in self.schedule.games:
            writer.writerow(
                {
                    "game_id": game.game_id,
                    "date": game.start_time.strftime("%Y-%m-%d"),
                    "time": game.start_time.strftime("%H:%M"),
                    "home_team": game.home_team.name,
                    "away_team": game.away_team.name,
                    "venue": game.venue,
                    "is_home": "Yes" if game.is_home_game(self.team.name) else "No",
                    "result": game.result.value,
                }
            )

        return output.getvalue()
