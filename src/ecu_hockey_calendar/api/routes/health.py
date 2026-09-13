"""Service health check, liveness, and readiness probe route handlers."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select, text

from ecu_hockey_calendar.api.negotiation import negotiate_response
from ecu_hockey_calendar.storage.engine import get_sync_session
from ecu_hockey_calendar.storage.models import DataSourceModel

if TYPE_CHECKING:
    from sqlalchemy import Engine

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_SCRAPERS",
    "enrich_source_records",
    "format_relative_time",
    "format_uptime",
    "get_health_probe",
    "head_health_probe",
]

health_router = APIRouter(tags=["Health"])

DEFAULT_SCRAPERS: list[dict[str, Any]] = [
    {
        "source_code": "ecuhockey",
        "name": "ECU Club Hockey Official Schedule",
        "source_type": "primary_sot",
        "is_active": True,
        "last_scraped_at": None,
    },
    {
        "source_code": "acchockey",
        "name": "ACCHL Master League Portal",
        "source_type": "league",
        "is_active": True,
        "last_scraped_at": None,
    },
    {
        "source_code": "tickets",
        "name": "ECU Hockey Etix Ticket Portal",
        "source_type": "tickets",
        "is_active": True,
        "last_scraped_at": None,
    },
    {
        "source_code": "instagram",
        "name": "ECU Hockey Instagram Feed",
        "source_type": "social",
        "is_active": True,
        "last_scraped_at": None,
    },
]


def _probe_database(engine: Engine | None) -> dict[str, Any]:
    """Execute ping check against relational database storage.

    Args:
        engine: Active SQLAlchemy Engine instance or None.

    Returns:
        Status dictionary for the database health component.
    """
    if engine is None:
        return {
            "status": "not_configured",
            "connected": False,
            "message": "Database engine not initialized (in-memory mode)",
        }

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 # pylint: disable=broad-exception-caught
        logger.warning("Database connectivity probe failed: %s", exc)
        return {
            "status": "unhealthy",
            "connected": False,
            "error": "Database connectivity probe failed",
        }

    return {
        "status": "connected",
        "connected": True,
        "dialect": engine.dialect.name,
    }


def _format_source_record(source: DataSourceModel) -> dict[str, Any]:
    """Serialize a single data source model to dictionary format."""
    return {
        "source_code": source.source_code,
        "name": source.name,
        "source_type": source.source_type,
        "is_active": source.is_active,
        "last_scraped_at": (
            source.last_scraped_at.isoformat() if source.last_scraped_at else None
        ),
    }


def _fetch_active_sources(engine: Engine) -> list[dict[str, Any]]:
    """Retrieve active data source models from database."""
    with get_sync_session(engine) as session:
        stmt = select(DataSourceModel).order_by(DataSourceModel.priority_order)
        sources = session.scalars(stmt).all()
        if not sources:
            return DEFAULT_SCRAPERS

        return [_format_source_record(s) for s in sources]


def _probe_scrapers(request: Request) -> dict[str, Any]:
    """Retrieve data source scraper status and activity records.

    Args:
        request: Incoming FastAPI HTTP request.

    Returns:
        Dictionary containing overall scraper status and source items.
    """
    override = getattr(request.app.state, "scraper_health_override", None)
    if override is not None:
        return dict(override)

    engine: Engine | None = getattr(request.app.state, "db_engine", None)
    if engine is None:
        return {"status": "operational", "sources": DEFAULT_SCRAPERS}

    try:
        return {"status": "operational", "sources": _fetch_active_sources(engine)}
    except Exception as exc:  # noqa: BLE001 # pylint: disable=broad-exception-caught
        logger.warning("Scraper health check probe failed: %s", exc)
        return {
            "status": "degraded",
            "sources": DEFAULT_SCRAPERS,
            "error": "Data source probe failed",
        }


def _calculate_uptime(start_time: datetime | None) -> float:
    """Calculate elapsed uptime in seconds from start time."""
    if start_time is None:
        return 0.0

    return max(0.0, (datetime.now(UTC) - start_time).total_seconds())


SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400


def format_uptime(seconds: float) -> str:
    """Format elapsed uptime seconds into a human-readable duration string.

    Args:
        seconds: Elapsed uptime in seconds.

    Returns:
        Human-readable duration string (e.g. '15h 46m 20s').
    """
    total_sec = int(max(0.0, seconds))
    if total_sec < SECONDS_PER_MINUTE:
        return f"{total_sec}s"

    if total_sec < SECONDS_PER_HOUR:
        mins, secs = divmod(total_sec, SECONDS_PER_MINUTE)
        return f"{mins}m {secs}s"

    if total_sec < SECONDS_PER_DAY:
        hours, remainder = divmod(total_sec, SECONDS_PER_HOUR)
        mins, secs = divmod(remainder, SECONDS_PER_MINUTE)
        return f"{hours}h {mins}m {secs}s"

    days, remainder = divmod(total_sec, SECONDS_PER_DAY)
    hours, remainder = divmod(remainder, SECONDS_PER_HOUR)
    mins, secs = divmod(remainder, SECONDS_PER_MINUTE)
    return f"{days}d {hours}h {mins}m {secs}s"


def _pluralize(value: int, unit: str) -> str:
    """Return pluralized string unit, e.g. '1 minute' or '5 minutes'."""
    suffix = "s" if value != 1 else ""
    return f"{value} {unit}{suffix} ago"


def _calculate_relative_age(delta_sec: float) -> str:
    """Calculate relative age string from elapsed seconds."""
    if delta_sec < SECONDS_PER_MINUTE:
        return "just now"

    if delta_sec < SECONDS_PER_HOUR:
        return _pluralize(int(delta_sec // SECONDS_PER_MINUTE), "minute")

    if delta_sec < SECONDS_PER_DAY:
        return _pluralize(int(delta_sec // SECONDS_PER_HOUR), "hour")

    return _pluralize(int(delta_sec // SECONDS_PER_DAY), "day")


def format_relative_time(
    dt_str: str | None,
    now: datetime | None = None,
) -> tuple[str, str]:
    """Format an ISO timestamp into human-readable and relative representations.

    Args:
        dt_str: ISO format timestamp string or None.
        now: Optional current datetime reference for testing.

    Returns:
        Tuple of (formatted_timestamp, relative_age).
    """
    if not dt_str:
        return "Never", "Never"

    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
    except ValueError:
        return "Invalid", "Invalid"

    formatted_ts = dt.strftime("%b %d, %Y, %I:%M %p UTC")
    current_time = now or datetime.now(UTC)
    delta_sec = max(0.0, (current_time - dt).total_seconds())

    relative_age = _calculate_relative_age(delta_sec)
    return formatted_ts, relative_age


def enrich_source_records(
    sources: list[dict[str, Any]],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Enrich data source records with formatted and relative timestamps.

    Args:
        sources: List of raw data source dictionaries.
        now: Optional current datetime reference for testing.

    Returns:
        List of enriched source dictionaries for template rendering.
    """
    enriched: list[dict[str, Any]] = []
    for src in sources:
        item = dict(src)
        formatted_ts, relative_age = format_relative_time(
            src.get("last_scraped_at"),
            now=now,
        )
        item["last_scraped_formatted"] = formatted_ts
        item["last_scraped_relative"] = relative_age
        enriched.append(item)

    return enriched


def _determine_display_status(
    overall_status: str,
    scrapers_status: str,
) -> str:
    """Determine visual status label for overall health banner."""
    if overall_status == "unhealthy":
        return "unhealthy"

    if overall_status == "degraded" or scrapers_status == "degraded":
        return "degraded"

    return "healthy"


def _build_health_data(request: Request) -> tuple[dict[str, Any], int]:
    """Inspect and compile service health, database state, and scraper metrics.

    Args:
        request: Incoming FastAPI HTTP request.

    Returns:
        Tuple of (health_payload_dict, http_status_code).
    """
    engine: Engine | None = getattr(request.app.state, "db_engine", None)
    db_result = _probe_database(engine)
    scrapers_result = _probe_scrapers(request)

    is_unhealthy = db_result.get("status") == "unhealthy"
    overall_status = "unhealthy" if is_unhealthy else "healthy"

    status_code = (
        status.HTTP_503_SERVICE_UNAVAILABLE if is_unhealthy else status.HTTP_200_OK
    )

    start_time: datetime | None = getattr(request.app.state, "start_time", None)
    version = getattr(request.app, "version", "unknown")

    payload: dict[str, Any] = {
        "status": overall_status,
        "service": "ecu-hockey-calendar-api",
        "version": version,
        "timestamp": datetime.now(UTC).isoformat(),
        "uptime_seconds": round(_calculate_uptime(start_time), 3),
        "components": {
            "database": db_result,
            "scrapers": scrapers_result,
        },
    }
    return payload, status_code


@health_router.get(
    "/health",
    summary="Service Liveness and Readiness Probe",
    description=(
        "Comprehensive health probe reporting overall service status, relational "
        "database connectivity, and ingestion scraper telemetry."
    ),
    responses={
        200: {
            "description": "Service is healthy and ready to process traffic.",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "status": {"type": "string"},
                            "service": {"type": "string"},
                            "version": {"type": "string"},
                            "timestamp": {"type": "string"},
                            "uptime_seconds": {"type": "number"},
                            "components": {"type": "object"},
                        },
                        "required": [
                            "status",
                            "service",
                            "version",
                            "timestamp",
                            "uptime_seconds",
                            "components",
                        ],
                    },
                },
                "text/html": {
                    "schema": {"type": "string"},
                },
            },
        },
        503: {
            "description": "Service is unhealthy or dependencies are unreachable.",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "status": {"type": "string"},
                            "service": {"type": "string"},
                            "version": {"type": "string"},
                            "timestamp": {"type": "string"},
                            "uptime_seconds": {"type": "number"},
                            "components": {"type": "object"},
                        },
                        "required": [
                            "status",
                            "service",
                            "version",
                            "timestamp",
                            "uptime_seconds",
                            "components",
                        ],
                    },
                },
                "text/html": {
                    "schema": {"type": "string"},
                },
            },
        },
    },
)
def get_health_probe(
    request: Request,
    response: Response,
) -> Response:
    """Inspect and report service health, database state, and scraper metrics.

    Args:
        request: Incoming HTTP request.
        response: FastAPI response object to set status codes.

    Returns:
        Content-negotiated HTML dashboard or JSON response.
    """
    payload, status_code = _build_health_data(request)
    response.status_code = status_code

    uptime_sec = payload["uptime_seconds"]
    formatted_uptime = format_uptime(uptime_sec)

    scrapers_comp = payload["components"]["scrapers"]
    sources = scrapers_comp.get("sources", [])
    enriched_sources = enrich_source_records(sources)

    display_status = _determine_display_status(
        payload["status"],
        scrapers_comp.get("status", "operational"),
    )

    context: dict[str, Any] = {
        "active_tab": "health",
        "display_status": display_status,
        "formatted_uptime": formatted_uptime,
        "sources": enriched_sources,
        "active_scrapers_count": sum(1 for s in sources if s.get("is_active")),
        "total_scrapers_count": len(sources),
    }

    return negotiate_response(
        request,
        payload,
        "health.html",
        context=context,
        status_code=status_code,
    )


@health_router.head(
    "/health",
    summary="Health Check Headers",
    description="Inspect health check status code without response payload.",
)
def head_health_probe(
    request: Request,
    response: Response,
) -> Response:
    """Handle HEAD probe requests for health check endpoint.

    Args:
        request: Incoming HTTP request.
        response: FastAPI response object.

    Returns:
        Empty response with appropriate status code.
    """
    _payload, status_code = _build_health_data(request)
    response.status_code = status_code
    return Response(status_code=status_code)
