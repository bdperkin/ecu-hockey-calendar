"""East Carolina University - Men's Ice Hockey Team - Calendar.

A modern Python package for managing and exporting ECU Ice Hockey
team schedules, game dates, venues, and calendar formats.
"""

from importlib.metadata import PackageNotFoundError, version

from ecu_hockey_calendar.calendar import ECUHockeyCalendar
from ecu_hockey_calendar.models import Game, GameResult, Schedule, Team

try:
    __version__ = version("ecu-hockey-calendar")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.1.0.dev0"

__all__ = [
    "ECUHockeyCalendar",
    "Game",
    "GameResult",
    "Schedule",
    "Team",
    "__version__",
]
