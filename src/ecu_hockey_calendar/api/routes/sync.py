"""Synchronization telemetry and diagnostics route handlers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, select

from ecu_hockey_calendar.api.auth import verify_admin_token
from ecu_hockey_calendar.api.routes.health import DEFAULT_SCRAPERS
from ecu_hockey_calendar.storage.engine import get_sync_session
from ecu_hockey_calendar.storage.models import (
    DataSourceModel,
    SyncAuditModel,
    SyncStatus,
)
from ecu_hockey_calendar.storage.service import get_sync_audit_history

if TYPE_CHECKING:
    from sqlalchemy import Engine
    from sqlalchemy.orm import Session

sync_router = APIRouter(prefix="/api/v1/sync", tags=["Diagnostics", "Sync"])


def _format_audit_record(audit: SyncAuditModel | None) -> dict[str, Any]:
    """Format a SyncAuditModel instance into structured telemetry dictionary."""
    if audit is None:
        return {
            "sync_cycle_id": None,
            "status": "never_run",
            "started_at": None,
            "completed_at": None,
            "duration_ms": None,
            "games_created": 0,
            "games_updated": 0,
            "games_deleted": 0,
            "conflicts_detected": 0,
            "error_message": None,
        }

    return {
        "sync_cycle_id": audit.sync_cycle_id,
        "status": audit.status,
        "started_at": audit.started_at.isoformat() if audit.started_at else None,
        "completed_at": (
            audit.completed_at.isoformat() if audit.completed_at else None
        ),
        "duration_ms": audit.duration_ms,
        "games_created": audit.games_created,
        "games_updated": audit.games_updated,
        "games_deleted": audit.games_deleted,
        "conflicts_detected": audit.conflicts_detected,
        "error_message": audit.error_message,
    }


def _query_sources_telemetry(engine: Engine) -> list[dict[str, Any]]:
    """Retrieve registered data source statuses from database."""
    with get_sync_session(engine) as session:
        stmt = select(DataSourceModel).order_by(DataSourceModel.priority_order)
        sources = session.scalars(stmt).all()
        if not sources:
            return list(DEFAULT_SCRAPERS)

        return [
            {
                "source_code": s.source_code,
                "name": s.name,
                "source_type": s.source_type,
                "is_active": s.is_active,
                "last_scraped_at": (
                    s.last_scraped_at.isoformat() if s.last_scraped_at else None
                ),
            }
            for s in sources
        ]


def _get_last_success_timestamp(session: Session) -> str | None:
    """Retrieve timestamp string of latest successful sync cycle."""
    stmt = (
        select(SyncAuditModel.completed_at)
        .where(SyncAuditModel.status.in_([SyncStatus.SUCCESS.value, "COMPLETED"]))
        .order_by(SyncAuditModel.started_at.desc())
        .limit(1)
    )
    last_success_dt = session.scalar(stmt)
    if last_success_dt is None:
        return None

    return last_success_dt.isoformat()


def _determine_sync_status(audit: SyncAuditModel | None) -> str:
    """Determine whether the sync engine is actively running."""
    if audit is None:
        return "idle"

    if audit.status == SyncStatus.RUNNING.value:
        return "syncing"

    return "idle"


def _extract_db_sync_telemetry(engine: Engine) -> dict[str, Any]:
    """Query synchronization audit statistics from the database."""
    with get_sync_session(engine) as session:
        audits = get_sync_audit_history(session, limit=1)
        latest_audit = audits[0] if audits else None
        count_val = session.scalar(select(func.count(SyncAuditModel.id)))  # pylint: disable=not-callable
        total_count = int(count_val) if count_val is not None else 0

        return {
            "current_status": _determine_sync_status(latest_audit),
            "last_sync": _format_audit_record(latest_audit),
            "last_success_at": _get_last_success_timestamp(session),
            "total_sync_cycles": total_count,
            "sources": _query_sources_telemetry(engine),
        }


@sync_router.get(
    "/status",
    summary="Synchronization Status and Telemetry",
    description=(
        "Retrieve telemetry for the latest sync cycle, elapsed duration, "
        "individual source status, and detected change counts."
    ),
    response_model=None,
)
def get_sync_status(request: Request) -> dict[str, Any]:
    """Retrieve synchronization telemetry, metrics, and source health.

    Args:
        request: Incoming HTTP request.

    Returns:
        Structured sync telemetry payload.
    """
    override = getattr(request.app.state, "sync_status_override", None)
    if override is not None:
        return dict(override)

    engine: Engine | None = getattr(request.app.state, "db_engine", None)
    if engine is None:
        return {
            "current_status": "idle",
            "last_sync": _format_audit_record(None),
            "last_success_at": None,
            "total_sync_cycles": 0,
            "sources": list(DEFAULT_SCRAPERS),
        }

    return _extract_db_sync_telemetry(engine)


@sync_router.post(
    "/trigger",
    summary="Trigger Synchronization Cycle",
    description=(
        "Administrative endpoint to trigger an on-demand schedule crawl and "
        "reconciliation cycle. Requires administrator authentication."
    ),
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_admin_token)],
)
def trigger_sync_cycle(
    request: Request,
    *,
    source: Annotated[
        str | None,
        Query(
            description=(
                "Optional specific source code to synchronize (e.g. 'ecuhockey'). "
                "Defaults to all active sources."
            ),
        ),
    ] = None,
) -> dict[str, Any]:
    """Trigger an on-demand schedule synchronization cycle.

    Args:
        request: Incoming FastAPI HTTP request.
        source: Optional source code to restrict sync.

    Returns:
        Response payload acknowledging sync task initiation.
    """
    cycle_id = f"sync-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"

    handler = getattr(request.app.state, "sync_trigger_handler", None)
    if callable(handler):
        handler(cycle_id, source=source)

    return {
        "status": "accepted",
        "sync_cycle_id": cycle_id,
        "target_source": source or "all",
        "timestamp": datetime.now(UTC).isoformat(),
        "message": "Synchronization cycle triggered successfully.",
    }
