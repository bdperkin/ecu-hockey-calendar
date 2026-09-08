"""API route modules for ECU Hockey Calendar and Data Service."""

from __future__ import annotations

from ecu_hockey_calendar.api.routes.calendar import router as calendar_router

__all__ = ["calendar_router"]
