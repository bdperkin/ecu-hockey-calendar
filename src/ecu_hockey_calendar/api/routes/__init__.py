"""API route modules for ECU Hockey Calendar and Data Service."""

from __future__ import annotations

from ecu_hockey_calendar.api.routes.calendar import router as calendar_router
from ecu_hockey_calendar.api.routes.conflicts import conflicts_router
from ecu_hockey_calendar.api.routes.health import health_router
from ecu_hockey_calendar.api.routes.schedule import schedule_router
from ecu_hockey_calendar.api.routes.sync import sync_router
from ecu_hockey_calendar.api.routes.web import web_router

__all__ = [
    "calendar_router",
    "conflicts_router",
    "health_router",
    "schedule_router",
    "sync_router",
    "web_router",
]
