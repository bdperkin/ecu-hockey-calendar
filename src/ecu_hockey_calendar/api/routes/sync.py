"""Synchronization telemetry and diagnostics route handlers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    status,
)
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
from ecu_hockey_calendar.sync_service import (
    DEFAULT_COOLDOWN_SECONDS,
    SyncManager,
)

if TYPE_CHECKING:
    from collections.abc import Callable

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


def _determine_sync_status(
    audit: SyncAuditModel | None,
    *,
    is_running: bool = False,
) -> str:
    """Determine whether the sync engine is actively running."""
    if is_running:
        return "syncing"

    if audit is not None and audit.status == SyncStatus.RUNNING.value:
        return "syncing"

    return "idle"


def _build_manager_telemetry(sync_manager: SyncManager | None) -> dict[str, Any]:
    """Extract operational telemetry status flags from SyncManager."""
    if sync_manager is None:
        return {
            "sync_trigger_enabled": False,
            "can_trigger": False,
            "cooldown_remaining_seconds": 0,
            "cooldown_total_seconds": DEFAULT_COOLDOWN_SECONDS,
            "is_running": False,
        }

    return {
        "sync_trigger_enabled": True,
        "can_trigger": sync_manager.can_trigger(),
        "cooldown_remaining_seconds": sync_manager.get_cooldown_remaining(),
        "cooldown_total_seconds": sync_manager.cooldown_seconds,
        "is_running": sync_manager.is_running,
    }


def _build_empty_db_telemetry(manager_meta: dict[str, Any]) -> dict[str, Any]:
    """Build fallback telemetry payload when database engine is uninitialized."""
    return {
        "current_status": "syncing" if manager_meta["is_running"] else "idle",
        "last_sync": _format_audit_record(None),
        "last_success_at": None,
        "total_sync_cycles": 0,
        "sources": list(DEFAULT_SCRAPERS),
        "sync_trigger_enabled": manager_meta["sync_trigger_enabled"],
        "can_trigger": manager_meta["can_trigger"],
        "cooldown_remaining_seconds": manager_meta["cooldown_remaining_seconds"],
        "cooldown_total_seconds": manager_meta["cooldown_total_seconds"],
    }


def _extract_db_sync_telemetry(
    engine: Engine,
    sync_manager: SyncManager | None = None,
) -> dict[str, Any]:
    """Query synchronization audit statistics from the database."""
    manager_meta = _build_manager_telemetry(sync_manager)
    with get_sync_session(engine) as session:
        audits = get_sync_audit_history(session, limit=1)
        latest_audit = audits[0] if audits else None
        count_val = session.scalar(select(func.count(SyncAuditModel.id)))  # pylint: disable=not-callable
        total_count = int(count_val) if count_val is not None else 0

        return {
            "current_status": _determine_sync_status(
                latest_audit,
                is_running=manager_meta["is_running"],
            ),
            "last_sync": _format_audit_record(latest_audit),
            "last_success_at": _get_last_success_timestamp(session),
            "total_sync_cycles": total_count,
            "sources": _query_sources_telemetry(engine),
            "sync_trigger_enabled": manager_meta["sync_trigger_enabled"],
            "can_trigger": manager_meta["can_trigger"],
            "cooldown_remaining_seconds": manager_meta["cooldown_remaining_seconds"],
            "cooldown_total_seconds": manager_meta["cooldown_total_seconds"],
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

    sync_manager: SyncManager | None = getattr(request.app.state, "sync_manager", None)
    engine: Engine | None = getattr(request.app.state, "db_engine", None)
    if engine is None:
        return _build_empty_db_telemetry(_build_manager_telemetry(sync_manager))

    return _extract_db_sync_telemetry(engine, sync_manager=sync_manager)


def _build_accepted_sync_response(cycle_id: str, source: str | None) -> dict[str, Any]:
    """Construct 202 Accepted response payload for triggered sync cycle."""
    return {
        "status": "accepted",
        "sync_cycle_id": cycle_id,
        "target_source": source or "all",
        "timestamp": datetime.now(UTC).isoformat(),
        "message": "Synchronization cycle triggered successfully.",
    }


def _ensure_manager_engine(sync_manager: SyncManager, request: Request) -> None:
    """Attach database engine to sync manager if not already configured."""
    app_engine = getattr(request.app.state, "db_engine", None)
    if sync_manager.engine is None and app_engine is not None:
        sync_manager.engine = app_engine


def _validate_sync_readiness(sync_manager: SyncManager) -> None:
    """Validate that sync manager is not currently running or in cooldown."""
    if sync_manager.is_running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A synchronization cycle is already in progress.",
        )

    remaining = sync_manager.get_cooldown_remaining()
    if remaining > 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Synchronization trigger is in cooldown. Please wait "
                f"{remaining} seconds before retrying."
            ),
            headers={"Retry-After": str(remaining)},
        )


def _dispatch_manager_cycle(
    sync_manager: SyncManager,
    request: Request,
    background_tasks: BackgroundTasks,
    source: str | None,
) -> dict[str, Any]:
    """Execute sync trigger using in-process SyncManager."""
    _ensure_manager_engine(sync_manager, request)
    _validate_sync_readiness(sync_manager)

    cycle_id = f"sync-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
    if not sync_manager.try_acquire(cycle_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A synchronization cycle is already in progress.",
        )

    sync_manager.record_initial_audit(cycle_id, source_filter=source or "all")
    background_tasks.add_task(
        sync_manager.run_background_sync,
        cycle_id,
        source=source,
    )
    return _build_accepted_sync_response(cycle_id, source)


def _dispatch_custom_handler(
    handler: Callable[..., Any],
    source: str | None,
) -> dict[str, Any]:
    """Execute custom sync trigger handler registered on application state."""
    cycle_id = f"sync-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
    try:
        handler(cycle_id, source=source)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return _build_accepted_sync_response(cycle_id, source)


@sync_router.post(
    "/trigger",
    summary="Trigger Synchronization Cycle",
    description=(
        "Administrative endpoint to trigger an on-demand schedule crawl and "
        "reconciliation cycle. Requires administrator authentication. Returns "
        "409 Conflict if already running, 429 Too Many Requests if in cooldown, "
        "or 501 Not Implemented if on-demand execution is not configured."
    ),
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        status.HTTP_202_ACCEPTED: {
            "description": "Synchronization cycle triggered successfully.",
        },
        status.HTTP_409_CONFLICT: {
            "description": "A synchronization cycle is already in progress.",
        },
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "description": "Synchronization trigger cooldown is active.",
        },
        status.HTTP_501_NOT_IMPLEMENTED: {
            "description": (
                "On-demand synchronization trigger is not implemented or "
                "configured in this deployment environment."
            ),
        },
    },
    dependencies=[Depends(verify_admin_token)],
)
def trigger_sync_cycle(
    request: Request,
    background_tasks: BackgroundTasks,
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
        background_tasks: FastAPI background tasks collector.
        source: Optional source code to restrict sync.

    Returns:
        Response payload acknowledging sync task initiation.

    Raises:
        HTTPException: 409 Conflict if a cycle is already executing.
        HTTPException: 429 Too Many Requests if trigger is in cooldown.
        HTTPException: 501 Not Implemented if no sync trigger handler is registered.
    """
    sync_manager: SyncManager | None = getattr(request.app.state, "sync_manager", None)
    if sync_manager is not None:
        return _dispatch_manager_cycle(sync_manager, request, background_tasks, source)

    handler = getattr(request.app.state, "sync_trigger_handler", None)
    if callable(handler):
        return _dispatch_custom_handler(handler, source)

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            "On-demand synchronization trigger is not implemented or "
            "configured in this deployment environment. Scheduled "
            "synchronization runs via external cron."
        ),
    )
