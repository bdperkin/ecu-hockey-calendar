"""Tests for storage service change persistence and temporal querying."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ecu_hockey_calendar.reconciliation.models import (
    ChangeDetectionCycleResult,
    FieldDiff,
    GameChangeRecord,
    GameStateTransition,
)
from ecu_hockey_calendar.storage import (
    DataSourceModel,
    SyncStatus,
    async_get_changes_since,
    async_get_latest_game_snapshot,
    async_get_sync_audit_history,
    async_init_db,
    async_record_change_cycle,
    create_async_engine,
    create_sync_engine,
    get_async_session,
    get_changes_since,
    get_latest_game_snapshot,
    get_sync_audit_history,
    get_sync_session,
    init_db,
    record_change_cycle,
)


@pytest.fixture
def sync_engine():
    """Create in-memory sync engine initialized with schema."""
    engine = create_sync_engine("sqlite:///:memory:")
    init_db(engine)
    return engine


@pytest.fixture
async def async_engine():
    """Create in-memory async engine initialized with schema."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await async_init_db(engine)
    return engine


def _sample_cycle_result() -> ChangeDetectionCycleResult:
    """Construct a sample ChangeDetectionCycleResult with multiple transitions."""
    t0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    t1 = datetime(2026, 10, 1, 12, 1, tzinfo=UTC)

    diff = FieldDiff(
        field_name="venue",
        old_value="TBD",
        new_value="Carolina Ice Palace",
        human_description="Venue changed from 'TBD' to 'Carolina Ice Palace'",
    )

    c1 = GameChangeRecord(
        canonical_game_id="game-1",
        state_transition=GameStateTransition.CREATED,
        field_diffs=[],
        previous_snapshot=None,
        current_snapshot={"canonical_game_id": "game-1", "opponent": "NC State"},
        detected_conflicts=[],
        human_summary="New game scheduled vs NC State",
        recorded_at=t0,
    )

    c2 = GameChangeRecord(
        canonical_game_id="game-2",
        state_transition=GameStateTransition.UPDATED,
        field_diffs=[diff],
        previous_snapshot={"canonical_game_id": "game-2", "venue": "TBD"},
        current_snapshot={
            "canonical_game_id": "game-2",
            "venue": "Carolina Ice Palace",
        },
        detected_conflicts=[],
        human_summary=diff.human_description,
        recorded_at=t0 + timedelta(seconds=10),
    )

    c3 = GameChangeRecord(
        canonical_game_id="game-3",
        state_transition=GameStateTransition.DELETED,
        field_diffs=[],
        previous_snapshot={"canonical_game_id": "game-3", "opponent": "Duke"},
        current_snapshot=None,
        detected_conflicts=[],
        human_summary="Game vs Duke removed from schedule",
        recorded_at=t0 + timedelta(seconds=20),
    )

    c4 = GameChangeRecord(
        canonical_game_id="game-4",
        state_transition=GameStateTransition.UNCHANGED,
        field_diffs=[],
        previous_snapshot={"canonical_game_id": "game-4"},
        current_snapshot={"canonical_game_id": "game-4"},
        detected_conflicts=[],
        human_summary="No changes",
        recorded_at=t0 + timedelta(seconds=30),
    )

    return ChangeDetectionCycleResult(
        cycle_id="cycle-sync-001",
        changes=[c1, c2, c3, c4],
        started_at=t0,
        completed_at=t1,
    )


def test_record_change_cycle_and_query_sync(sync_engine) -> None:
    """Verify synchronous recording and querying of change cycle results."""
    cycle_res = _sample_cycle_result()

    with get_sync_session(sync_engine) as session:
        ds = DataSourceModel(
            source_code="test_src",
            name="Test Source",
            source_url="https://test.local",
            source_type="league",
        )
        session.add(ds)
        session.flush()

        audit = record_change_cycle(
            session,
            cycle_res,
            source_id=ds.id,
            sync_status=SyncStatus.SUCCESS,
        )
        assert audit.id is not None
        assert audit.games_created == 1
        assert audit.games_updated == 1
        assert audit.games_deleted == 1
        assert audit.conflicts_detected == 0
        assert audit.duration_ms == 60000

        # Query all changes since before t0
        since = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
        changes = get_changes_since(session, since)
        # c4 (UNCHANGED) should not be persisted in game_changes
        assert len(changes) == 3
        assert [c.canonical_game_id for c in changes] == ["game-1", "game-2", "game-3"]

        # Filter by canonical_game_id
        g2_changes = get_changes_since(session, since, canonical_game_id="game-2")
        assert len(g2_changes) == 1
        assert g2_changes[0].change_type == "UPDATED"

        # Filter by change_types using Enum
        updated_changes = get_changes_since(
            session,
            since,
            change_types=[GameStateTransition.UPDATED],
        )
        assert len(updated_changes) == 1
        assert updated_changes[0].canonical_game_id == "game-2"

        # Filter by change_types using lowercase string
        deleted_changes = get_changes_since(
            session,
            since,
            change_types=["deleted"],
        )
        assert len(deleted_changes) == 1
        assert deleted_changes[0].canonical_game_id == "game-3"

        # Order descending with limit
        desc_changes = get_changes_since(
            session,
            since,
            order_desc=True,
            limit=2,
        )
        assert len(desc_changes) == 2
        assert desc_changes[0].canonical_game_id == "game-3"
        assert desc_changes[1].canonical_game_id == "game-2"

        # Query latest snapshot
        snap = get_latest_game_snapshot(session, "game-2")
        assert snap is not None
        assert snap["venue"] == "Carolina Ice Palace"

        no_snap = get_latest_game_snapshot(session, "nonexistent-game")
        assert no_snap is None

        # Query sync audit history
        audits = get_sync_audit_history(session, since=since, limit=10)
        assert len(audits) == 1
        assert audits[0].sync_cycle_id == "cycle-sync-001"

        audits_no_since = get_sync_audit_history(session, limit=10)
        assert len(audits_no_since) == 1


@pytest.mark.anyio
async def test_record_change_cycle_and_query_async(async_engine) -> None:
    """Verify asynchronous recording and querying of change cycle results."""
    cycle_res = _sample_cycle_result()

    async with get_async_session(async_engine) as session:
        audit = await async_record_change_cycle(
            session,
            cycle_res,
            sync_status=SyncStatus.FAILURE,
            error_message="Simulated warning",
        )
        assert audit.id is not None
        assert audit.status == "FAILURE"
        assert audit.error_message == "Simulated warning"

        since = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
        changes = await async_get_changes_since(session, since)
        assert len(changes) == 3

        # Async filter by game id
        g1 = await async_get_changes_since(session, since, canonical_game_id="game-1")
        assert len(g1) == 1
        assert g1[0].change_type == "CREATED"

        # Async filter by change types
        g_up = await async_get_changes_since(
            session,
            since,
            change_types=[GameStateTransition.UPDATED],
        )
        assert len(g_up) == 1
        assert g_up[0].canonical_game_id == "game-2"

        # Async order descending with limit
        g_desc = await async_get_changes_since(
            session,
            since,
            order_desc=True,
            limit=2,
        )
        assert len(g_desc) == 2
        assert g_desc[0].canonical_game_id == "game-3"

        # Async query latest snapshot
        snap = await async_get_latest_game_snapshot(session, "game-1")
        assert snap is not None
        assert snap["opponent"] == "NC State"

        no_snap = await async_get_latest_game_snapshot(session, "unknown")
        assert no_snap is None

        # Async query sync audit history
        history = await async_get_sync_audit_history(session, since=since)
        assert len(history) == 1
        assert history[0].sync_cycle_id == "cycle-sync-001"

        history_no_since = await async_get_sync_audit_history(session)
        assert len(history_no_since) == 1
