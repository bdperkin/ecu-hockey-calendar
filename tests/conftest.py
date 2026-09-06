"""Pytest fixtures for ecu-hockey-calendar tests."""

from datetime import UTC, datetime

import pytest

from ecu_hockey_calendar.models import Game, Team


@pytest.fixture
def ecu_team() -> Team:
    """Provide a standard ECU hockey team fixture.

    Returns:
        A populated Team instance for East Carolina University.
    """
    return Team(
        name="East Carolina University",
        city="Greenville",
        state="NC",
        division="ACHA M2",
        conference="ACCHL",
    )


@pytest.fixture
def unc_team() -> Team:
    """Provide an opponent team fixture for UNC Chapel Hill.

    Returns:
        A populated Team instance for UNC.
    """
    return Team(
        name="UNC Chapel Hill",
        city="Chapel Hill",
        state="NC",
        division="ACHA M2",
        conference="ACCHL",
    )


@pytest.fixture
def sample_game(ecu_team: Team, unc_team: Team) -> Game:
    """Provide a sample scheduled game fixture between ECU and UNC.

    Args:
        ecu_team: The host ECU team fixture.
        unc_team: The visiting UNC team fixture.

    Returns:
        A Game object instance.
    """
    return Game(
        game_id="GAME-001",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2026, 10, 15, 19, 0, tzinfo=UTC),
        venue="The Factory Ice House",
    )
