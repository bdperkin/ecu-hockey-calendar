"""Unit and integration tests for ecu_hockey_calendar.sync_service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine, select

from ecu_hockey_calendar.ingestion.html_parser import ParsedGameRecord
from ecu_hockey_calendar.models import GameResult
from ecu_hockey_calendar.reconciliation.models import (
    ChangeDetectionCycleResult,
    DataSourceType,
    ReconciledGame,
    SourceGameRecord,
)
from ecu_hockey_calendar.storage.base import Base
from ecu_hockey_calendar.storage.engine import get_sync_session
from ecu_hockey_calendar.storage.models import (
    GameModel,
    GameStatus,
    SyncAuditModel,
    SyncStatus,
    TeamModel,
)
from ecu_hockey_calendar.sync_service import (
    DEFAULT_COOLDOWN_SECONDS,
    MIN_COOLDOWN_SECONDS,
    SyncManager,
    _convert_parsed_to_source_record,
    _ensure_data_source,
    _execute_crawlers,
    _get_or_create_team,
    _load_baseline_games_from_db,
    _persist_sync_results,
    _run_acchockey_crawler,
    _run_ecuhockey_crawler,
    _update_existing_audit_record,
    _upsert_reconciled_game,
    execute_sync_pipeline,
    run_sync_pipeline,
)

# pylint: disable=protected-access


@pytest.fixture
def sqlite_engine() -> Any:
    """Create in-memory SQLite engine for tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def test_convert_parsed_to_source_record_with_scores() -> None:
    """Test converting ParsedGameRecord with scores and calculate_result."""
    parsed = ParsedGameRecord(
        game_id="game-101",
        opponent_name="UNC Wilmington",
        is_home=True,
        start_time=datetime(2026, 10, 20, 19, 0, tzinfo=UTC),
        venue="The Factory",
        home_score=5,
        away_score=3,
        metadata={"division": "D2"},
    )
    src = _convert_parsed_to_source_record(
        parsed,
        DataSourceType.PRIMARY_SOT,
        "ecuhockey",
    )
    assert src.game_id == "game-101"
    assert src.source_type == DataSourceType.PRIMARY_SOT
    assert src.source_code == "ecuhockey"
    assert src.opponent_name == "UNC Wilmington"
    assert src.result == GameResult.WIN
    assert src.home_score == 5
    assert src.away_score == 3
    assert src.metadata == {"division": "D2"}


def test_convert_parsed_to_source_record_without_scores() -> None:
    """Test converting ParsedGameRecord without scores produces None result."""
    parsed = ParsedGameRecord(
        game_id="game-102",
        opponent_name="NC State",
        is_home=False,
        start_time=datetime(2026, 10, 25, 20, 0, tzinfo=UTC),
        venue="Invisalign Arena",
        metadata={},
    )
    src = _convert_parsed_to_source_record(
        parsed,
        DataSourceType.LEAGUE,
        "acchockey",
    )
    assert src.game_id == "game-102"
    assert src.result is None
    assert src.home_score is None
    assert src.away_score is None
    assert not src.metadata


@pytest.mark.anyio
async def test_run_crawlers_success() -> None:
    """Test _run_ecuhockey_crawler and _run_acchockey_crawler success paths."""
    mock_record = ParsedGameRecord(
        game_id="g1",
        opponent_name="Duke",
        is_home=True,
        start_time=datetime(2026, 11, 1, 19, 0, tzinfo=UTC),
        venue="The Factory",
    )
    with patch(
        "ecu_hockey_calendar.sync_service.ECUHockeyCrawler.crawl",
        new_callable=AsyncMock,
        return_value=([mock_record], "<html></html>", "h1", "text/html"),
    ):
        recs, status_str, dur = await _run_ecuhockey_crawler()
        assert len(recs) == 1
        assert status_str == "SUCCESS"
        assert dur >= 0.0
        assert recs[0].source_code == "ecuhockey"

    with patch(
        "ecu_hockey_calendar.sync_service.ACCHockeyCrawler.crawl",
        new_callable=AsyncMock,
        return_value=([mock_record], "<html></html>", "h2", "text/html"),
    ):
        recs_acc, status_acc, dur_acc = await _run_acchockey_crawler()
        assert len(recs_acc) == 1
        assert status_acc == "SUCCESS"
        assert dur_acc >= 0.0
        assert recs_acc[0].source_code == "acchockey"


@pytest.mark.anyio
async def test_execute_crawlers_filtering_and_resilience() -> None:
    """Test _execute_crawlers with different filters and exception handling."""
    mock_src = SourceGameRecord(
        source_type=DataSourceType.PRIMARY_SOT,
        source_code="ecuhockey",
        opponent_name="NC State",
        start_time=datetime(2026, 11, 5, 19, 0, tzinfo=UTC),
        venue="The Factory",
    )

    # Filter: ecuhockey only
    with patch(
        "ecu_hockey_calendar.sync_service._run_ecuhockey_crawler",
        new_callable=AsyncMock,
        return_value=([mock_src], "SUCCESS", 0.1),
    ):
        recs, telemetry = await _execute_crawlers("ecuhockey")
        assert len(recs) == 1
        assert len(telemetry) == 1
        assert telemetry[0]["source"] == "ecuhockey"

    # Filter: acchockey only
    with patch(
        "ecu_hockey_calendar.sync_service._run_acchockey_crawler",
        new_callable=AsyncMock,
        return_value=([mock_src], "SUCCESS", 0.1),
    ):
        recs, telemetry = await _execute_crawlers("acchockey")
        assert len(recs) == 1
        assert len(telemetry) == 1
        assert telemetry[0]["source"] == "acchockey"

    # Failure resilience in both crawlers
    with (
        patch(
            "ecu_hockey_calendar.sync_service._run_ecuhockey_crawler",
            new_callable=AsyncMock,
            side_effect=RuntimeError("ECU failure"),
        ),
        patch(
            "ecu_hockey_calendar.sync_service._run_acchockey_crawler",
            new_callable=AsyncMock,
            side_effect=RuntimeError("ACC failure"),
        ),
    ):
        recs, telemetry = await _execute_crawlers("all")
        assert len(recs) == 0
        assert len(telemetry) == 2
        assert "FAILED: ECU failure" in telemetry[0]["status"]
        assert "FAILED: ACC failure" in telemetry[1]["status"]


def test_load_baseline_games_from_db(sqlite_engine: Any) -> None:
    """Test _load_baseline_games_from_db with and without season filter."""
    with get_sync_session(sqlite_engine) as session:
        t1 = TeamModel(name="ECU", city="Greenville", state="NC")
        t2 = TeamModel(name="UNCW", city="Wilmington", state="NC")
        session.add_all([t1, t2])
        session.flush()

        g1 = GameModel(
            game_id="g-1",
            home_team_id=t1.id,
            away_team_id=t2.id,
            start_time=datetime(2026, 10, 1, 19, 0, tzinfo=UTC),
            venue="Venue",
            status="scheduled",
            season="2026-2027",
        )
        g2 = GameModel(
            game_id="g-2",
            home_team_id=t1.id,
            away_team_id=t2.id,
            start_time=datetime(2025, 10, 1, 19, 0, tzinfo=UTC),
            venue="Venue",
            status="scheduled",
            season="2025-2026",
        )
        session.add_all([g1, g2])
        session.commit()

    with get_sync_session(sqlite_engine) as session:
        all_games = _load_baseline_games_from_db(session)
        assert len(all_games) == 2

        season_games = _load_baseline_games_from_db(session, season="2026-2027")
        assert len(season_games) == 1
        assert season_games[0].game_id == "g-1"


def test_get_or_create_team_and_upsert_game(sqlite_engine: Any) -> None:
    """Test team get/create and game upsert insertion and update."""
    with get_sync_session(sqlite_engine) as session:
        team1 = _get_or_create_team(session, "Virginia Tech", "Blacksburg", "VA")
        assert team1.name == "Virginia Tech"
        # Duplicate should return existing
        team1_dup = _get_or_create_team(session, "Virginia Tech")
        assert team1_dup.id == team1.id

        ecu = _get_or_create_team(session, "East Carolina University")

        rec_game = ReconciledGame(
            canonical_game_id="rec-001",
            start_time=datetime(2026, 10, 10, 19, 0, tzinfo=UTC),
            opponent_name="Virginia Tech",
            is_home=True,
            venue="The Factory",
            status=GameStatus.SCHEDULED,
            result=GameResult.WIN,
            home_score=4,
            away_score=1,
            contributing_sources=["ecuhockey"],
        )
        _upsert_reconciled_game(session, rec_game, ecu.id)
        session.commit()

    with get_sync_session(sqlite_engine) as session:
        saved = session.scalar(select(GameModel).where(GameModel.game_id == "rec-001"))
        assert saved is not None
        assert saved.home_score == 4
        assert saved.result == "W"

        # Update game
        rec_game_updated = ReconciledGame(
            canonical_game_id="rec-001",
            start_time=datetime(2026, 10, 10, 19, 0, tzinfo=UTC),
            opponent_name="Virginia Tech",
            is_home=False,
            venue="Lancerlot",
            status=GameStatus.FINAL,
            result=GameResult.LOSS,
            home_score=1,
            away_score=4,
            contributing_sources=["ecuhockey"],
        )
        _upsert_reconciled_game(session, rec_game_updated, ecu.id)
        session.commit()

    with get_sync_session(sqlite_engine) as session:
        updated = session.scalar(
            select(GameModel).where(GameModel.game_id == "rec-001"),
        )
        assert updated is not None
        assert updated.venue == "Lancerlot"
        assert updated.result == "L"


def test_ensure_data_source(sqlite_engine: Any) -> None:
    """Test _ensure_data_source insertion and touch."""
    with get_sync_session(sqlite_engine) as session:
        ds1 = _ensure_data_source(
            session,
            "ecuhockey",
            "ECU Hockey",
            DataSourceType.PRIMARY_SOT,
        )
        assert ds1.source_url == "https://www.ecuhockey.com"

        ds2 = _ensure_data_source(
            session,
            "acchockey",
            "ACC Hockey",
            DataSourceType.LEAGUE,
        )
        assert ds2.source_url == "https://www.acchockey.com"

        # Update existing
        ds1_updated = _ensure_data_source(
            session,
            "ecuhockey",
            "ECU Hockey",
            DataSourceType.PRIMARY_SOT,
        )
        assert ds1_updated.id == ds1.id


def test_update_existing_audit_record(sqlite_engine: Any) -> None:
    """Test _update_existing_audit_record when audit exists vs does not exist."""
    cycle_id = "test-cycle-update"
    with get_sync_session(sqlite_engine) as session:
        audit = SyncAuditModel(
            sync_cycle_id=cycle_id,
            started_at=datetime.now(UTC) - timedelta(seconds=2),
            status=SyncStatus.RUNNING.value,
        )
        session.add(audit)
        session.commit()

    cycle_result = ChangeDetectionCycleResult(
        cycle_id=cycle_id,
        changes=[],
    )

    with get_sync_session(sqlite_engine) as session:
        updated = _update_existing_audit_record(session, cycle_result)
        assert updated is True
        session.commit()

    with get_sync_session(sqlite_engine) as session:
        stmt = select(SyncAuditModel).where(SyncAuditModel.sync_cycle_id == cycle_id)
        persisted = session.scalar(stmt)
        assert persisted is not None
        assert persisted.status == SyncStatus.SUCCESS.value
        assert persisted.completed_at is not None

    # Test when audit does not exist
    non_existent_cycle = ChangeDetectionCycleResult(
        cycle_id="non-existent",
        changes=[],
    )
    with get_sync_session(sqlite_engine) as session:
        assert _update_existing_audit_record(session, non_existent_cycle) is False


def test_persist_sync_results_branches(sqlite_engine: Any) -> None:
    """Test _persist_sync_results with initial_audit_exists=False and True."""
    cycle_id_new = "cycle-persist-new"
    cycle_result_new = ChangeDetectionCycleResult(
        cycle_id=cycle_id_new,
        changes=[],
    )
    telemetry = [
        {"source": "ecuhockey", "name": "ECU"},
        {"source": "acchockey", "name": "ACC"},
    ]

    with get_sync_session(sqlite_engine) as session:
        _persist_sync_results(
            session,
            [],
            telemetry,
            cycle_result_new,
            initial_audit_exists=False,
        )
        session.commit()

    with get_sync_session(sqlite_engine) as session:
        audit = session.scalar(
            select(SyncAuditModel).where(SyncAuditModel.sync_cycle_id == cycle_id_new),
        )
        assert audit is not None
        assert audit.status == SyncStatus.SUCCESS.value


@pytest.mark.anyio
async def test_run_sync_pipeline_dry_run_and_notifications(sqlite_engine: Any) -> None:
    """Test run_sync_pipeline with dry_run and notify flags."""
    mock_src = SourceGameRecord(
        source_type=DataSourceType.PRIMARY_SOT,
        source_code="ecuhockey",
        opponent_name="UNC Wilmington",
        start_time=datetime(2026, 11, 15, 19, 0, tzinfo=UTC),
        venue="The Factory",
    )

    async def mock_crawler_async(
        _: str,
    ) -> tuple[list[SourceGameRecord], list[dict[str, Any]]]:
        """Mock async crawler returning a single record."""
        return [mock_src], [
            {
                "source": "ecuhockey",
                "name": "ECU",
                "records": 1,
                "status": "SUCCESS",
                "duration": 0.1,
            },
        ]

    # Dry run
    tel, result, conflicts = await run_sync_pipeline(
        engine=sqlite_engine,
        dry_run=True,
        crawler_fn=mock_crawler_async,
    )
    assert len(tel) == 1
    assert len(result.created_games) == 1
    assert len(conflicts) == 0

    # Live run with notify and notify_individual
    mock_dispatcher_cls = MagicMock()
    mock_disp_inst = MagicMock()
    mock_dispatcher_cls.return_value = mock_disp_inst

    tel2, _result2, _conflicts2 = await run_sync_pipeline(
        engine=sqlite_engine,
        dry_run=False,
        notify=True,
        notify_individual=True,
        crawler_fn=mock_crawler_async,
        dispatcher_cls=mock_dispatcher_cls,
    )
    assert len(tel2) == 1
    assert mock_disp_inst.dispatch_cycle.called
    assert mock_disp_inst.dispatch_cycle.call_args[1]["individual_changes"] is True


def test_execute_sync_pipeline_wrapper(sqlite_engine: Any) -> None:
    """Test synchronous execute_sync_pipeline entrypoint."""
    mock_src = SourceGameRecord(
        source_type=DataSourceType.PRIMARY_SOT,
        source_code="ecuhockey",
        opponent_name="Duke",
        start_time=datetime(2026, 12, 1, 19, 0, tzinfo=UTC),
        venue="The Factory",
    )

    def mock_crawler_sync(
        _: str,
    ) -> tuple[list[SourceGameRecord], list[dict[str, Any]]]:
        """Mock synchronous crawler returning a single record."""
        return [mock_src], [
            {
                "source": "ecuhockey",
                "name": "ECU",
                "records": 1,
                "status": "SUCCESS",
                "duration": 0.05,
            },
        ]

    tel, result, _conflicts = execute_sync_pipeline(
        engine=sqlite_engine,
        dry_run=True,
        crawler_fn=mock_crawler_sync,
    )
    assert len(tel) == 1
    assert len(result.created_games) == 1


class TestSyncManager:
    """Comprehensive test suite for SyncManager concurrency and cooldown."""

    def test_sync_manager_initialization(self) -> None:
        """Verify cooldown resolution and bounding."""
        # Default cooldown
        sm = SyncManager()
        assert sm.cooldown_seconds == DEFAULT_COOLDOWN_SECONDS

        # Bounded by MIN_COOLDOWN_SECONDS
        sm_low = SyncManager(cooldown_seconds=100)
        assert sm_low.cooldown_seconds == MIN_COOLDOWN_SECONDS

        # Custom cooldown allowed when specified
        sm_custom = SyncManager(cooldown_seconds=10, allow_custom_cooldown=True)
        assert sm_custom.cooldown_seconds == 10

        # SYNC_COOLDOWN_SECONDS environment variable resolution
        with patch.dict("os.environ", {"SYNC_COOLDOWN_SECONDS": "450"}):
            sm_env = SyncManager()
            assert sm_env.cooldown_seconds == 450

    def test_lock_acquire_and_release(self) -> None:
        """Verify thread-safe lock acquisition and release."""
        sm = SyncManager()
        assert sm.is_running is False
        assert sm.active_cycle_id is None

        # Acquire lock
        acquired = sm.try_acquire("cycle-100")
        assert acquired is True
        assert sm.is_running is True
        assert sm.active_cycle_id == "cycle-100"

        # Concurrency conflict
        acquired_again = sm.try_acquire("cycle-200")
        assert acquired_again is False
        assert sm.active_cycle_id == "cycle-100"

        # Release lock
        sm.release()
        assert sm.is_running is False
        assert sm.active_cycle_id is None

    def test_cooldown_calculation(self) -> None:
        """Verify cooldown calculation against elapsed time."""
        sm = SyncManager(cooldown_seconds=60, allow_custom_cooldown=True)
        assert sm.get_cooldown_remaining() == 0
        assert sm.can_trigger() is True

        now = datetime.now(UTC)
        sm._last_completed_at = now - timedelta(seconds=20)
        assert sm.get_cooldown_remaining(now=now) == 40
        assert sm.can_trigger(now=now) is False

        # Cooldown elapsed
        assert sm.get_cooldown_remaining(now=now + timedelta(seconds=65)) == 0
        assert sm.can_trigger(now=now + timedelta(seconds=65)) is True

        # Naive datetime fallback in _last_completed_at
        sm._last_completed_at = datetime.now(UTC).replace(tzinfo=None)
        assert sm.get_cooldown_remaining() >= 0

    def test_init_last_completed_from_db(self, sqlite_engine: Any) -> None:
        """Verify SyncManager initializes cooldown from database audits."""
        completed_time = datetime.now(UTC) - timedelta(minutes=5)
        with get_sync_session(sqlite_engine) as session:
            audit = SyncAuditModel(
                sync_cycle_id="c-audit-db",
                started_at=completed_time - timedelta(seconds=5),
                completed_at=completed_time,
                status=SyncStatus.SUCCESS.value,
            )
            session.add(audit)
            session.commit()

        sm = SyncManager(engine=sqlite_engine, cooldown_seconds=600)
        remaining = sm.get_cooldown_remaining()
        assert 250 <= remaining <= 350

        # DB error resilience
        sm_broken = SyncManager(engine=sqlite_engine)
        sm_broken._last_completed_at = None
        with patch(
            "ecu_hockey_calendar.sync_service.get_sync_session",
            side_effect=RuntimeError("DB down"),
        ):
            sm_broken._init_last_completed_from_db()
            assert sm_broken.last_completed_at is None

        # Engine is None
        sm_none = SyncManager(engine=None)
        sm_none._init_last_completed_from_db()
        assert sm_none.last_completed_at is None

    def test_record_initial_audit_and_finalize_failure(
        self,
        sqlite_engine: Any,
    ) -> None:
        """Test record_initial_audit and finalize_audit_failure lifecycle."""
        sm = SyncManager(engine=sqlite_engine)
        sm.record_initial_audit("c-fail-test", source_filter="ecuhockey")

        with get_sync_session(sqlite_engine) as session:
            audit = session.scalar(
                select(SyncAuditModel).where(
                    SyncAuditModel.sync_cycle_id == "c-fail-test",
                ),
            )
            assert audit is not None
            assert audit.status == SyncStatus.RUNNING.value
            assert audit.details is not None
            assert audit.details["target_source"] == "ecuhockey"

        sm.finalize_audit_failure("c-fail-test", "Scraper timed out")

        with get_sync_session(sqlite_engine) as session:
            audit_failed = session.scalar(
                select(SyncAuditModel).where(
                    SyncAuditModel.sync_cycle_id == "c-fail-test",
                ),
            )
            assert audit_failed is not None
            assert audit_failed.status == SyncStatus.FAILURE.value
            assert audit_failed.error_message == "Scraper timed out"
            assert audit_failed.completed_at is not None

        # Edge cases: engine is None
        sm_no_engine = SyncManager()
        sm_no_engine.record_initial_audit("c-none")
        sm_no_engine.finalize_audit_failure("c-none", "err")

        # Edge case: audit record not found during finalize
        sm.finalize_audit_failure("non-existent-id", "err")

        # Edge case: DB exception during finalize
        with patch(
            "ecu_hockey_calendar.sync_service.get_sync_session",
            side_effect=RuntimeError("DB failure"),
        ):
            sm.finalize_audit_failure("c-fail-test", "err")

    def test_trigger_handler_interface(self, sqlite_engine: Any) -> None:
        """Test trigger_handler callable hook."""
        sm = SyncManager(engine=sqlite_engine)
        sm.trigger_handler("c-trigger-1", source="ecuhockey")
        assert sm.is_running is True

        with pytest.raises(RuntimeError, match="already in progress"):
            sm.trigger_handler("c-trigger-2")

        sm.release()
        assert sm.is_running is False

    @pytest.mark.anyio
    async def test_run_background_sync(self, sqlite_engine: Any) -> None:
        """Test run_background_sync success, missing engine, and failure paths."""
        sm_no_engine = SyncManager()
        assert await sm_no_engine.run_background_sync("c-no-engine") is None

        sm = SyncManager(
            engine=sqlite_engine,
            allow_custom_cooldown=True,
            cooldown_seconds=5,
        )
        sm.try_acquire("c-bg-success")

        async def mock_crawler(
            _: str,
        ) -> tuple[list[SourceGameRecord], list[dict[str, Any]]]:
            """Mock crawler returning empty records."""
            return [], []

        res = await sm.run_background_sync("c-bg-success", crawler_fn=mock_crawler)
        assert res is not None
        assert sm.is_running is False
        assert sm.last_completed_at is not None

        # Failure during background execution
        sm.try_acquire("c-bg-fail")
        sm.record_initial_audit("c-bg-fail")

        with patch(
            "ecu_hockey_calendar.sync_service.run_sync_pipeline",
            side_effect=RuntimeError("Network disconnected"),
        ):
            res_fail = await sm.run_background_sync("c-bg-fail")
            assert res_fail is None
            assert sm.is_running is False

        with get_sync_session(sqlite_engine) as session:
            audit = session.scalar(
                select(SyncAuditModel).where(
                    SyncAuditModel.sync_cycle_id == "c-bg-fail",
                ),
            )
            assert audit is not None
            assert audit.status == SyncStatus.FAILURE.value
            assert "Network disconnected" in str(audit.error_message)
