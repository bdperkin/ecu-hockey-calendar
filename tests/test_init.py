"""Tests for package initialization and version exposure."""

import ecu_hockey_calendar
import ecu_hockey_calendar.api


def test_package_exports() -> None:
    """Verify that expected top-level classes and symbols are exported."""
    assert hasattr(ecu_hockey_calendar, "ECUHockeyCalendar")
    assert hasattr(ecu_hockey_calendar, "Game")
    assert hasattr(ecu_hockey_calendar, "GameResult")
    assert hasattr(ecu_hockey_calendar, "Schedule")
    assert hasattr(ecu_hockey_calendar, "SyndicationConfig")
    assert hasattr(ecu_hockey_calendar, "SyndicationFeedService")
    assert hasattr(ecu_hockey_calendar, "Team")
    assert hasattr(ecu_hockey_calendar, "__version__")
    assert isinstance(ecu_hockey_calendar.__version__, str)
    assert hasattr(ecu_hockey_calendar, "FALLBACK_VERSION")
    assert ecu_hockey_calendar.FALLBACK_VERSION == "0.0.0+unknown"
    assert hasattr(ecu_hockey_calendar, "get_version")
    assert callable(ecu_hockey_calendar.get_version)


def test_api_package_create_app() -> None:
    """Verify that api package exports working create_app factory."""
    assert hasattr(ecu_hockey_calendar.api, "create_app")
    app = ecu_hockey_calendar.api.create_app()
    assert app is not None
    assert app.title == "ECU Men's Ice Hockey Calendar & Data API"
