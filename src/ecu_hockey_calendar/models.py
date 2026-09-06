"""Data models for ECU Ice Hockey games, teams, and schedules.

This module defines domain classes representing hockey teams, game events,
and complete season schedules with support for validation and serialization.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime


class GameResult(StrEnum):
    """Enumeration of possible hockey game outcomes."""

    WIN = "W"
    LOSS = "L"
    TIE = "T"
    OVERTIME_LOSS = "OTL"
    SCHEDULED = "SCHEDULED"


@dataclass(frozen=True, slots=True)
class Team:
    """Represents a collegiate ice hockey team.

    Attributes:
        name: The full name of the hockey team or university.
        city: The team's home city.
        state: The two-letter state abbreviation or region code.
        division: The league competition division (e.g., ACHA M2, ACHA M3).
        conference: The conference name (e.g., ACCHL).
    """

    name: str
    city: str
    state: str
    division: str = "ACHA M2"
    conference: str = "ACCHL"

    def __post_init__(self) -> None:
        """Validate team attributes after initialization.

        Raises:
            ValueError: If team name, city, or state is empty.
        """
        if not self.name.strip():
            msg = "Team name cannot be empty."
            raise ValueError(msg)
        if not self.city.strip():
            msg = "Team city cannot be empty."
            raise ValueError(msg)
        if not self.state.strip():
            msg = "Team state cannot be empty."
            raise ValueError(msg)

    def to_dict(self) -> dict[str, str]:
        """Convert the team instance into a plain dictionary representation.

        Returns:
            A dictionary containing all team attributes.
        """
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Game:
    """Represents an individual hockey game event.

    Attributes:
        game_id: Unique identifier for the game.
        home_team: The hosting Team object.
        away_team: The visiting Team object.
        start_time: Scheduled game puck drop datetime.
        venue: Arena or rink name where the game is played.
        result: Outcome of the game if completed, or SCHEDULED.
        home_score: Final home team score if completed.
        away_score: Final away team score if completed.
    """

    game_id: str
    home_team: Team
    away_team: Team
    start_time: datetime
    venue: str
    result: GameResult = GameResult.SCHEDULED
    home_score: int | None = None
    away_score: int | None = None

    def __post_init__(self) -> None:
        """Validate game properties after initialization.

        Raises:
            ValueError: If game_id or venue is empty, or if teams are identical.
        """
        if not self.game_id.strip():
            msg = "Game ID cannot be empty."
            raise ValueError(msg)
        if not self.venue.strip():
            msg = "Venue cannot be empty."
            raise ValueError(msg)
        if self.home_team == self.away_team:
            msg = "Home and away teams cannot be identical."
            raise ValueError(msg)

    def is_home_game(self, team_name: str) -> bool:
        """Check if a specific team is the home team for this game.

        Args:
            team_name: The name of the team to evaluate.

        Returns:
            True if the specified team is the host team, otherwise False.
        """
        return self.home_team.name.casefold() == team_name.casefold()

    def opponent_of(self, team_name: str) -> Team:
        """Retrieve the opposing team given a reference team name.

        Args:
            team_name: The name of the reference team.

        Returns:
            The opposing Team instance.

        Raises:
            ValueError: If the reference team is neither home nor away.
        """
        if self.is_home_game(team_name):
            return self.away_team
        if self.away_team.name.casefold() == team_name.casefold():
            return self.home_team
        msg = f"Team '{team_name}' is not participating in this game."
        raise ValueError(msg)

    def to_dict(self) -> dict[str, Any]:
        """Convert game information to a serialized dictionary.

        Returns:
            A dictionary containing serialized game data.
        """
        return {
            "game_id": self.game_id,
            "home_team": self.home_team.to_dict(),
            "away_team": self.away_team.to_dict(),
            "start_time": self.start_time.isoformat(),
            "venue": self.venue,
            "result": self.result.value,
            "home_score": self.home_score,
            "away_score": self.away_score,
        }


@dataclass(slots=True)
class Schedule:
    """Manages an ordered list of games for an athletic hockey season.

    Attributes:
        season: The season label (e.g., '2026-2027').
        games: A list of Game objects included in the season schedule.
    """

    season: str
    games: list[Game] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate schedule attributes.

        Raises:
            ValueError: If the season identifier is empty.
        """
        if not self.season.strip():
            msg = "Season cannot be empty."
            raise ValueError(msg)

    def add_game(self, game: Game) -> None:
        """Add a game to the schedule in chronological order.

        Args:
            game: The Game instance to add to the schedule.

        Raises:
            ValueError: If a game with the same game_id is already present.
        """
        if any(existing.game_id == game.game_id for existing in self.games):
            msg = f"Game with ID '{game.game_id}' already exists in schedule."
            raise ValueError(msg)
        self.games.append(game)
        self.games.sort(key=lambda g: g.start_time)

    def filter_by_opponent(self, opponent_name: str) -> list[Game]:
        """Return all games played against a specific opponent.

        Args:
            opponent_name: The name or partial substring of the opponent.

        Returns:
            A list of matching Game objects.
        """
        normalized = opponent_name.casefold()
        return [
            g
            for g in self.games
            if normalized in g.home_team.name.casefold()
            or normalized in g.away_team.name.casefold()
        ]

    def filter_home_games(self, team_name: str) -> list[Game]:
        """Return all games hosted by the specified team.

        Args:
            team_name: The name of the team hosting the game.

        Returns:
            A list of home games for the specified team.
        """
        return [g for g in self.games if g.is_home_game(team_name)]

    def filter_away_games(self, team_name: str) -> list[Game]:
        """Return all away games for the specified team.

        Args:
            team_name: The name of the team visiting.

        Returns:
            A list of away games for the specified team.
        """
        normalized = team_name.casefold()
        return [g for g in self.games if g.away_team.name.casefold() == normalized]

    @property
    def total_games(self) -> int:
        """Return total number of games currently scheduled.

        Returns:
            Integer count of games in the schedule.
        """
        return len(self.games)

    def to_dict(self) -> dict[str, Any]:
        """Serialize schedule to a dictionary.

        Returns:
            Dictionary containing season information and game lists.
        """
        return {
            "season": self.season,
            "total_games": self.total_games,
            "games": [g.to_dict() for g in self.games],
        }
