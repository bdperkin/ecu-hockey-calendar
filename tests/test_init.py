"""Tests for package initialization and version exposure."""

import ecu_hockey_calendar


def test_package_exports() -> None:
    """Verify that expected top-level classes and symbols are exported."""
    assert hasattr(ecu_hockey_calendar, "ECUHockeyCalendar")
    assert hasattr(ecu_hockey_calendar, "Game")
    assert hasattr(ecu_hockey_calendar, "GameResult")
    assert hasattr(ecu_hockey_calendar, "Schedule")
    assert hasattr(ecu_hockey_calendar, "Team")
    assert hasattr(ecu_hockey_calendar, "__version__")
    assert isinstance(ecu_hockey_calendar.__version__, str)
    assert hasattr(ecu_hockey_calendar, "FALLBACK_VERSION")
    assert ecu_hockey_calendar.FALLBACK_VERSION == "0.0.0+unknown"
    assert hasattr(ecu_hockey_calendar, "get_version")
    assert callable(ecu_hockey_calendar.get_version)
