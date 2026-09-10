"""East Carolina University - Men's Ice Hockey Team - Calendar.

A modern Python package for managing and exporting ECU Ice Hockey
team schedules, game dates, venues, and calendar formats.
"""

from ecu_hockey_calendar.calendar import ECUHockeyCalendar
from ecu_hockey_calendar.models import Game, GameResult, Schedule, Team
from ecu_hockey_calendar.version import (
    FALLBACK_VERSION,
    __version__,
    get_version,
)

__all__ = [
    "FALLBACK_VERSION",
    "ECUHockeyCalendar",
    "Game",
    "GameResult",
    "Schedule",
    "Team",
    "__version__",
    "get_version",
]
