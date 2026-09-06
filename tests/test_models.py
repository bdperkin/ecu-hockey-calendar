"""Tests for the data models in ecu_hockey_calendar.models."""

from datetime import UTC, datetime

import pytest

from ecu_hockey_calendar.models import Game, GameResult, Schedule, Team


def test_team_creation_and_to_dict(ecu_team: Team) -> None:
    """Test successful Team initialization and serialization to dictionary."""
    assert ecu_team.name == "East Carolina University"
    assert ecu_team.city == "Greenville"
    assert ecu_team.state == "NC"
    assert ecu_team.division == "ACHA M2"
    assert ecu_team.conference == "ACCHL"

    data = ecu_team.to_dict()
    assert data["name"] == "East Carolina University"
    assert data["city"] == "Greenville"


@pytest.mark.parametrize(
    ("name", "city", "state"),
    [
        ("", "City", "ST"),
        ("   ", "City", "ST"),
        ("Team", "", "ST"),
        ("Team", "   ", "ST"),
        ("Team", "City", ""),
        ("Team", "City", "   "),
    ],
)
def test_team_validation_errors(name: str, city: str, state: str) -> None:
    """Test validation errors when required Team string attributes are empty."""
    with pytest.raises(ValueError, match="cannot be empty"):
        Team(name=name, city=city, state=state)


def test_game_creation_and_properties(
    sample_game: Game,
    ecu_team: Team,
    unc_team: Team,
) -> None:
    """Test Game attributes, helper methods, and serialization."""
    assert sample_game.game_id == "GAME-001"
    assert sample_game.is_home_game("East Carolina University")
    assert not sample_game.is_home_game("UNC Chapel Hill")
    assert sample_game.opponent_of("East Carolina University") == unc_team
    assert sample_game.opponent_of("UNC Chapel Hill") == ecu_team

    with pytest.raises(ValueError, match="is not participating in this game"):
        sample_game.opponent_of("NC State")

    data = sample_game.to_dict()
    assert data["game_id"] == "GAME-001"
    assert data["result"] == GameResult.SCHEDULED.value


@pytest.mark.parametrize(
    ("game_id", "venue"),
    [
        ("", "Venue"),
        ("   ", "Venue"),
        ("ID-1", ""),
        ("ID-1", "   "),
    ],
)
def test_game_validation_errors(
    game_id: str,
    venue: str,
    ecu_team: Team,
    unc_team: Team,
) -> None:
    """Test Game raises ValueError when mandatory fields are empty."""
    with pytest.raises(ValueError, match="cannot be empty"):
        Game(
            game_id=game_id,
            home_team=ecu_team,
            away_team=unc_team,
            start_time=datetime(2026, 10, 15, 19, 0, tzinfo=UTC),
            venue=venue,
        )


def test_game_identical_teams_raises(ecu_team: Team) -> None:
    """Test Game raises ValueError if home and away teams are identical."""
    with pytest.raises(ValueError, match="Home and away teams cannot be identical"):
        Game(
            game_id="ID-1",
            home_team=ecu_team,
            away_team=ecu_team,
            start_time=datetime(2026, 10, 15, 19, 0, tzinfo=UTC),
            venue="Arena",
        )


def test_schedule_management(sample_game: Game, unc_team: Team, ecu_team: Team) -> None:
    """Test Schedule game addition, ordering, duplicate detection, and queries."""
    schedule = Schedule(season="2026-2027")
    assert schedule.total_games == 0
    assert schedule.season == "2026-2027"

    schedule.add_game(sample_game)
    assert schedule.total_games == 1

    # Attempt duplicate addition
    with pytest.raises(ValueError, match="already exists in schedule"):
        schedule.add_game(sample_game)

    earlier_game = Game(
        game_id="GAME-000",
        home_team=unc_team,
        away_team=ecu_team,
        start_time=datetime(2026, 10, 1, 20, 0, tzinfo=UTC),
        venue="Orange County Sportsplex",
    )
    schedule.add_game(earlier_game)
    assert schedule.total_games == 2
    # Ensure sorting by start_time
    assert schedule.games[0].game_id == "GAME-000"
    assert schedule.games[1].game_id == "GAME-001"

    # Filters
    assert len(schedule.filter_by_opponent("UNC")) == 2
    assert len(schedule.filter_by_opponent("Duke")) == 0
    assert len(schedule.filter_home_games("East Carolina University")) == 1
    assert len(schedule.filter_away_games("East Carolina University")) == 1

    # Serialization
    sched_dict = schedule.to_dict()
    assert sched_dict["season"] == "2026-2027"
    assert sched_dict["total_games"] == 2
    assert len(sched_dict["games"]) == 2


def test_schedule_empty_season_raises() -> None:
    """Test Schedule raises ValueError if season string is empty."""
    with pytest.raises(ValueError, match="Season cannot be empty"):
        Schedule(season="  ")
