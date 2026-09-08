"""Service health check, liveness, and readiness probe route handlers."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select, text

from ecu_hockey_calendar.storage.engine import get_sync_session
from ecu_hockey_calendar.storage.models import DataSourceModel

if TYPE_CHECKING:
    from sqlalchemy import Engine

logger = logging.getLogger(__name__)

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


@health_router.get(
    "/health",
    summary="Service Liveness and Readiness Probe",
    description=(
        "Comprehensive health probe reporting overall service status, relational "
        "database connectivity, and ingestion scraper telemetry."
    ),
    responses={
        200: {"description": "Service is healthy and ready to process traffic."},
        503: {"description": "Service is unhealthy or dependencies are unreachable."},
    },
)
def get_health_probe(request: Request, response: Response) -> dict[str, Any]:
    """Inspect and report service health, database state, and scraper metrics.

    Args:
        request: Incoming HTTP request.
        response: FastAPI response object to set status codes.

    Returns:
        Structured health check payload.
    """
    engine: Engine | None = getattr(request.app.state, "db_engine", None)
    db_result = _probe_database(engine)
    scrapers_result = _probe_scrapers(request)

    is_unhealthy = db_result.get("status") == "unhealthy"
    overall_status = "unhealthy" if is_unhealthy else "healthy"

    if is_unhealthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        response.status_code = status.HTTP_200_OK

    start_time: datetime | None = getattr(request.app.state, "start_time", None)
    version = getattr(request.app, "version", "unknown")

    return {
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


@health_router.head(
    "/health",
    summary="Health Check Headers",
    description="Inspect health check status code without response payload.",
)
def head_health_probe(request: Request, response: Response) -> Response:
    """Handle HEAD probe requests for health check endpoint.

    Args:
        request: Incoming HTTP request.
        response: FastAPI response object.

    Returns:
        Empty response with appropriate status code.
    """
    res_dict = get_health_probe(request, response)
    st_code = (
        status.HTTP_503_SERVICE_UNAVAILABLE
        if res_dict.get("status") == "unhealthy"
        else status.HTTP_200_OK
    )
    return Response(status_code=st_code)
