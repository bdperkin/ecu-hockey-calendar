"""Persistence and querying services for schedule change detection and audits.

This module provides transaction-safe operations to record synchronization
audit cycles, log atomic game state transitions and field diffs, and query
recent changes across temporal windows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from ecu_hockey_calendar.storage.models import (
    GameChangeModel,
    SyncAuditModel,
    SyncStatus,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import Session

    from ecu_hockey_calendar.reconciliation.models import (
        ChangeDetectionCycleResult,
        GameStateTransition,
    )


def _build_sync_audit_entity(
    cycle_result: ChangeDetectionCycleResult,
    source_id: int | None,
    sync_status: SyncStatus,
    error_message: str | None,
) -> SyncAuditModel:
    """Construct a SyncAuditModel from change detection cycle results."""
    duration = int(
        (cycle_result.completed_at - cycle_result.started_at).total_seconds() * 1000,
    )
    return SyncAuditModel(
        source_id=source_id,
        sync_cycle_id=cycle_result.cycle_id,
        started_at=cycle_result.started_at,
        completed_at=cycle_result.completed_at,
        duration_ms=max(0, duration),
        status=sync_status.value,
        games_created=len(cycle_result.created_games),
        games_updated=len(cycle_result.updated_games),
        games_deleted=len(cycle_result.deleted_games),
        conflicts_detected=len(cycle_result.conflict_games),
        error_message=error_message,
        details=cycle_result.to_dict(),
    )


def _build_game_change_entities(
    cycle_result: ChangeDetectionCycleResult,
    audit: SyncAuditModel,
) -> list[GameChangeModel]:
    """Construct GameChangeModel entities for all non-trivial state changes."""
    change_models: list[GameChangeModel] = []
    for change in cycle_result.changes:
        st_val = getattr(
            change.state_transition,
            "value",
            str(change.state_transition),
        )
        if st_val == "UNCHANGED":
            continue

        change_models.append(
            GameChangeModel(
                sync_cycle_id=cycle_result.cycle_id,
                sync_audit=audit,
                canonical_game_id=change.canonical_game_id,
                change_type=st_val,
                summary=change.human_summary[:512],
                field_diffs=[d.to_dict() for d in change.field_diffs],
                snapshot_before=change.previous_snapshot,
                snapshot_after=change.current_snapshot,
                recorded_at=change.recorded_at,
            ),
        )

    return change_models


def _normalize_change_type_values(
    change_types: Sequence[GameStateTransition | str] | None,
) -> list[str] | None:
    """Normalize transition filter values to list of uppercase strings."""
    if not change_types:
        return None

    normalized: list[str] = []
    for ct in change_types:
        val = getattr(ct, "value", str(ct))
        normalized.append(val.upper())

    return normalized


def record_change_cycle(
    session: Session,
    cycle_result: ChangeDetectionCycleResult,
    *,
    source_id: int | None = None,
    sync_status: SyncStatus = SyncStatus.SUCCESS,
    error_message: str | None = None,
) -> SyncAuditModel:
    """Record sync audit metrics and granular game changes synchronously.

    Args:
        session: Active synchronous SQLAlchemy session.
        cycle_result: ChangeDetectionCycleResult containing changes.
        source_id: Optional data source identifier.
        sync_status: Final status of the synchronization cycle.
        error_message: Optional error message if the cycle encountered errors.

    Returns:
        The persisted SyncAuditModel entity with associated changes.
    """
    audit = _build_sync_audit_entity(
        cycle_result,
        source_id,
        sync_status,
        error_message,
    )
    session.add(audit)

    change_entities = _build_game_change_entities(cycle_result, audit)
    session.add_all(change_entities)
    session.flush()

    return audit


async def async_record_change_cycle(
    session: AsyncSession,
    cycle_result: ChangeDetectionCycleResult,
    *,
    source_id: int | None = None,
    sync_status: SyncStatus = SyncStatus.SUCCESS,
    error_message: str | None = None,
) -> SyncAuditModel:
    """Record sync audit metrics and granular game changes asynchronously.

    Args:
        session: Active asynchronous SQLAlchemy session.
        cycle_result: ChangeDetectionCycleResult containing changes.
        source_id: Optional data source identifier.
        sync_status: Final status of the synchronization cycle.
        error_message: Optional error message if the cycle encountered errors.

    Returns:
        The persisted SyncAuditModel entity with associated changes.
    """
    audit = _build_sync_audit_entity(
        cycle_result,
        source_id,
        sync_status,
        error_message,
    )
    session.add(audit)

    change_entities = _build_game_change_entities(cycle_result, audit)
    session.add_all(change_entities)
    await session.flush()

    return audit


def get_changes_since(
    session: Session,
    since: datetime,
    *,
    canonical_game_id: str | None = None,
    change_types: Sequence[GameStateTransition | str] | None = None,
    order_desc: bool = False,
    limit: int | None = None,
) -> list[GameChangeModel]:
    """Retrieve schedule game changes recorded on or after a given timestamp.

    Args:
        session: Active synchronous SQLAlchemy session.
        since: Earliest recorded_at cutoff timestamp (timezone-aware).
        canonical_game_id: Optional filter for a specific game identifier.
        change_types: Optional filter for specific transition classifications.
        order_desc: If True, order newest first; otherwise oldest first.
        limit: Optional maximum number of change records to retrieve.

    Returns:
        List of matching GameChangeModel entities.
    """
    stmt = select(GameChangeModel).where(GameChangeModel.recorded_at >= since)

    if canonical_game_id:
        stmt = stmt.where(GameChangeModel.canonical_game_id == canonical_game_id)

    norm_types = _normalize_change_type_values(change_types)
    if norm_types:
        stmt = stmt.where(GameChangeModel.change_type.in_(norm_types))

    if order_desc:
        stmt = stmt.order_by(GameChangeModel.recorded_at.desc())
    else:
        stmt = stmt.order_by(GameChangeModel.recorded_at.asc())

    if limit is not None:
        stmt = stmt.limit(limit)

    return list(session.scalars(stmt).all())


async def async_get_changes_since(
    session: AsyncSession,
    since: datetime,
    *,
    canonical_game_id: str | None = None,
    change_types: Sequence[GameStateTransition | str] | None = None,
    order_desc: bool = False,
    limit: int | None = None,
) -> list[GameChangeModel]:
    """Retrieve schedule game changes after a timestamp asynchronously.

    Args:
        session: Active asynchronous SQLAlchemy session.
        since: Earliest recorded_at cutoff timestamp (timezone-aware).
        canonical_game_id: Optional filter for a specific game identifier.
        change_types: Optional filter for specific transition classifications.
        order_desc: If True, order newest first; otherwise oldest first.
        limit: Optional maximum number of change records to retrieve.

    Returns:
        List of matching GameChangeModel entities.
    """
    stmt = select(GameChangeModel).where(GameChangeModel.recorded_at >= since)

    if canonical_game_id:
        stmt = stmt.where(GameChangeModel.canonical_game_id == canonical_game_id)

    norm_types = _normalize_change_type_values(change_types)
    if norm_types:
        stmt = stmt.where(GameChangeModel.change_type.in_(norm_types))

    if order_desc:
        stmt = stmt.order_by(GameChangeModel.recorded_at.desc())
    else:
        stmt = stmt.order_by(GameChangeModel.recorded_at.asc())

    if limit is not None:
        stmt = stmt.limit(limit)

    res = await session.scalars(stmt)
    return list(res.all())


def get_sync_audit_history(
    session: Session,
    *,
    since: datetime | None = None,
    limit: int = 50,
) -> list[SyncAuditModel]:
    """Retrieve synchronization audit logs in descending chronological order.

    Args:
        session: Active synchronous SQLAlchemy session.
        since: Optional cutoff timestamp filter.
        limit: Maximum number of audit records to return.

    Returns:
        List of SyncAuditModel entities.
    """
    stmt = select(SyncAuditModel)
    if since is not None:
        stmt = stmt.where(SyncAuditModel.started_at >= since)

    stmt = stmt.order_by(SyncAuditModel.started_at.desc()).limit(limit)
    return list(session.scalars(stmt).all())


async def async_get_sync_audit_history(
    session: AsyncSession,
    *,
    since: datetime | None = None,
    limit: int = 50,
) -> list[SyncAuditModel]:
    """Retrieve sync audit logs asynchronously in descending chronological order.

    Args:
        session: Active asynchronous SQLAlchemy session.
        since: Optional cutoff timestamp filter.
        limit: Maximum number of audit records to return.

    Returns:
        List of SyncAuditModel entities.
    """
    stmt = select(SyncAuditModel)
    if since is not None:
        stmt = stmt.where(SyncAuditModel.started_at >= since)

    stmt = stmt.order_by(SyncAuditModel.started_at.desc()).limit(limit)
    res = await session.scalars(stmt)
    return list(res.all())


def get_latest_game_snapshot(
    session: Session,
    canonical_game_id: str,
) -> dict[str, Any] | None:
    """Retrieve the most recent historical snapshot for a game.

    Args:
        session: Active synchronous SQLAlchemy session.
        canonical_game_id: Canonical identifier of the target game.

    Returns:
        Dictionary snapshot after the change, or None if not found.
    """
    stmt = (
        select(GameChangeModel)
        .where(
            GameChangeModel.canonical_game_id == canonical_game_id,
            GameChangeModel.snapshot_after.is_not(None),
        )
        .order_by(GameChangeModel.recorded_at.desc())
        .limit(1)
    )
    change = session.scalar(stmt)
    return change.snapshot_after if change else None


async def async_get_latest_game_snapshot(
    session: AsyncSession,
    canonical_game_id: str,
) -> dict[str, Any] | None:
    """Retrieve the most recent historical snapshot for a game asynchronously.

    Args:
        session: Active asynchronous SQLAlchemy session.
        canonical_game_id: Canonical identifier of the target game.

    Returns:
        Dictionary snapshot after the change, or None if not found.
    """
    stmt = (
        select(GameChangeModel)
        .where(
            GameChangeModel.canonical_game_id == canonical_game_id,
            GameChangeModel.snapshot_after.is_not(None),
        )
        .order_by(GameChangeModel.recorded_at.desc())
        .limit(1)
    )
    res = await session.scalars(stmt)
    change = res.first()
    return change.snapshot_after if change else None


__all__ = [
    "async_get_changes_since",
    "async_get_latest_game_snapshot",
    "async_get_sync_audit_history",
    "async_record_change_cycle",
    "get_changes_since",
    "get_latest_game_snapshot",
    "get_sync_audit_history",
    "record_change_cycle",
]
