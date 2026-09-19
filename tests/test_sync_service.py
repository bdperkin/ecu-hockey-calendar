# pylint: disable=too-many-lines
"""Unit and integration tests for ecu_hockey_calendar.sync_service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine, select

from ecu_hockey_calendar.ingestion.html_parser import ParsedGameRecord
from ecu_hockey_calendar.ingestion.opponent_parser import (
    OpponentEndpointConfig,
    OpponentFeedType,
    OpponentFixture,
)
from ecu_hockey_calendar.models import GameResult
from ecu_hockey_calendar.reconciliation.models import (
    ChangeDetectionCycleResult,
    DataSourceType,
    GameChangeRecord,
    GameStateTransition,
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
    _collect_stale_game_ids,
    _convert_opponent_fixture_to_source_record,
    _convert_parsed_to_source_record,
    _ensure_crawl_data_sources,
    _ensure_data_source,
    _execute_crawlers,
    _get_or_create_team,
    _load_baseline_games_from_db,
    _persist_sync_results,
    _prune_stale_fixtures,
    _resolve_data_source_type,
    _run_acchockey_crawler,
    _run_achahockey_crawler,
    _run_ecuhockey_crawler,
    _run_instagram_crawler,
    _run_opponent_crawler,
    _should_skip_pruning,
    _stale_ids_from_baseline,
    _stale_ids_from_deleted,
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
    ) as mock_acc_crawl:
        recs_acc, status_acc, dur_acc = await _run_acchockey_crawler()
        mock_acc_crawl.assert_called_once_with(include_subseasons=True)
        assert len(recs_acc) == 1
        assert status_acc == "SUCCESS"
        assert dur_acc >= 0.0
        assert recs_acc[0].source_code == "acchockey"

    with patch(
        "ecu_hockey_calendar.sync_service.ACHAHockeyCrawler.crawl",
        new_callable=AsyncMock,
        return_value=([mock_record], '{"data": []}', "h3", "application/json"),
    ) as mock_acha_crawl:
        recs_acha, status_acha, dur_acha = await _run_achahockey_crawler()
        mock_acha_crawl.assert_called_once_with()
        assert len(recs_acha) == 1
        assert status_acha == "SUCCESS"
        assert dur_acha >= 0.0
        assert recs_acha[0].source_code == "achahockey"


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

    # Filter: achahockey only
    with patch(
        "ecu_hockey_calendar.sync_service._run_achahockey_crawler",
        new_callable=AsyncMock,
        return_value=([mock_src], "SUCCESS", 0.1),
    ):
        recs, telemetry = await _execute_crawlers("achahockey")
        assert len(recs) == 1
        assert len(telemetry) == 1
        assert telemetry[0]["source"] == "achahockey"

    # Filter: instagram only
    with patch(
        "ecu_hockey_calendar.sync_service._run_instagram_crawler",
        new_callable=AsyncMock,
        return_value=([mock_src], "SUCCESS", 0.1),
    ):
        recs, telemetry = await _execute_crawlers("instagram")
        assert len(recs) == 1
        assert len(telemetry) == 1
        assert telemetry[0]["source"] == "instagram"

    # Filter: social alias
    with patch(
        "ecu_hockey_calendar.sync_service._run_instagram_crawler",
        new_callable=AsyncMock,
        return_value=([mock_src], "SUCCESS", 0.1),
    ):
        recs, telemetry = await _execute_crawlers("social")
        assert len(recs) == 1
        assert len(telemetry) == 1
        assert telemetry[0]["source"] == "instagram"

    # Filter: opponent only
    mock_custom_dir = MagicMock()
    with patch(
        "ecu_hockey_calendar.sync_service._run_opponent_crawler",
        new_callable=AsyncMock,
        return_value=([mock_src], "SUCCESS", 0.1),
    ) as mock_run_opp:
        recs, telemetry = await _execute_crawlers(
            "opponent",
            opponent_directory=mock_custom_dir,
        )
        assert len(recs) == 1
        assert len(telemetry) == 1
        assert telemetry[0]["source"] == "opponent"
        mock_run_opp.assert_called_once_with(
            directory=mock_custom_dir,
            observer=None,
        )

    # Failure resilience in all crawlers
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
        patch(
            "ecu_hockey_calendar.sync_service._run_achahockey_crawler",
            new_callable=AsyncMock,
            side_effect=RuntimeError("ACHA failure"),
        ),
        patch(
            "ecu_hockey_calendar.sync_service._run_instagram_crawler",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Instagram failure"),
        ),
    ):
        recs, telemetry = await _execute_crawlers("all")
        assert len(recs) == 0
        assert len(telemetry) == 4
        assert "FAILED: ECU failure" in telemetry[0]["status"]
        assert "FAILED: ACC failure" in telemetry[1]["status"]
        assert "FAILED: ACHA failure" in telemetry[2]["status"]
        assert "FAILED: Instagram failure" in telemetry[3]["status"]

    # Failure resilience in opponent crawler
    with patch(
        "ecu_hockey_calendar.sync_service._run_opponent_crawler",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Opponent network down"),
    ):
        recs_opp, tel_opp = await _execute_crawlers("opponent")
        assert len(recs_opp) == 0
        assert len(tel_opp) == 1
        assert "FAILED: Opponent network down" in tel_opp[0]["status"]


def test_convert_opponent_fixture_to_source_record() -> None:
    """Test converting OpponentFixture into SourceGameRecord."""
    fix_home = OpponentFixture(
        opponent_name="UNC Chapel Hill",
        summary="ECU vs UNC",
        start_time=datetime(2026, 10, 20, 19, 0, tzinfo=UTC),
        venue="Orange County Sportsplex",
        is_opponent_home=False,
        status=GameStatus.SCHEDULED,
        raw_details={"division": "M2"},
    )
    src_home = _convert_opponent_fixture_to_source_record(fix_home, "UNC Chapel Hill")
    assert src_home.source_type == DataSourceType.OPPONENT
    assert src_home.source_code == "opponent"
    assert src_home.opponent_name == "UNC Chapel Hill"
    assert src_home.is_home is True
    assert src_home.venue == "Orange County Sportsplex"
    assert src_home.metadata == {"division": "M2"}

    # Opponent is home -> ECU is away, fallback canonical_name when opponent_name empty
    fix_away = OpponentFixture(
        opponent_name="",
        summary="ECU at Duke",
        start_time=datetime(2026, 11, 1, 20, 0, tzinfo=UTC),
        venue="WCC",
        is_opponent_home=True,
    )
    src_away = _convert_opponent_fixture_to_source_record(fix_away, "Duke University")
    assert src_away.is_home is False
    assert src_away.opponent_name == "Duke University"
    assert not src_away.metadata


@pytest.mark.anyio
async def test_run_instagram_crawler_success() -> None:
    """Test _run_instagram_crawler parses posts and skips non-game posts."""
    mock_post_game = MagicMock()
    mock_parsed_rec = ParsedGameRecord(
        game_id="ig-1",
        opponent_name="UNC Wilmington",
        is_home=True,
        start_time=datetime(2026, 10, 25, 19, 0, tzinfo=UTC),
        venue="The Factory",
    )
    mock_post_game.to_parsed_game_record.return_value = mock_parsed_rec

    mock_post_nongame = MagicMock()
    mock_post_nongame.to_parsed_game_record.return_value = None

    with patch(
        "ecu_hockey_calendar.sync_service.InstagramCrawler.fetch_posts",
        new_callable=AsyncMock,
        return_value=([mock_post_game, mock_post_nongame], "{}", "hash", "json"),
    ):
        recs, status_str, dur = await _run_instagram_crawler(access_token="test_token")
        assert len(recs) == 1
        assert status_str == "SUCCESS"
        assert dur >= 0.0
        assert recs[0].source_type == DataSourceType.SOCIAL
        assert recs[0].source_code == "instagram"
        assert recs[0].opponent_name == "UNC Wilmington"


@pytest.mark.anyio
async def test_run_opponent_crawler_success() -> None:
    """Test _run_opponent_crawler fetches and filters opponent schedules."""
    mock_dir = MagicMock()
    cfg = OpponentEndpointConfig(
        canonical_name="UNC Chapel Hill",
        feed_url="https://example.com/ical",
        feed_type=OpponentFeedType.ICAL,
    )
    mock_dir.list_endpoints.return_value = [cfg]

    mock_fix_ecu = OpponentFixture(
        opponent_name="UNC Chapel Hill",
        summary="ECU vs UNC",
        start_time=datetime(2026, 10, 20, 19, 0, tzinfo=UTC),
        venue="Sportsplex",
        is_opponent_home=True,
    )

    with (
        patch(
            "ecu_hockey_calendar.sync_service.OpponentCrawler.fetch_opponent_schedule",
            new_callable=AsyncMock,
            return_value=([mock_fix_ecu], "ical", "hash", "text/calendar"),
        ),
        patch(
            "ecu_hockey_calendar.sync_service.filter_ecu_fixtures",
            return_value=[mock_fix_ecu],
        ),
    ):
        recs, status_str, dur = await _run_opponent_crawler(directory=mock_dir)
        assert len(recs) == 1
        assert status_str == "SUCCESS"
        assert dur >= 0.0
        assert recs[0].source_type == DataSourceType.OPPONENT
        assert recs[0].source_code == "opponent"


def test_resolve_data_source_type() -> None:
    """Test _resolve_data_source_type mapping helper."""
    assert _resolve_data_source_type("ecuhockey") == DataSourceType.PRIMARY_SOT
    assert _resolve_data_source_type("acchockey") == DataSourceType.LEAGUE
    assert _resolve_data_source_type("achahockey") == DataSourceType.LEAGUE
    assert _resolve_data_source_type("instagram") == DataSourceType.SOCIAL
    assert _resolve_data_source_type("social") == DataSourceType.SOCIAL
    assert _resolve_data_source_type("opponent") == DataSourceType.OPPONENT
    assert _resolve_data_source_type("tickets") == DataSourceType.TICKETS
    assert _resolve_data_source_type("unknown") == DataSourceType.PRIMARY_SOT


def test_ensure_data_source_custom_urls(sqlite_engine: Any) -> None:
    """Test _ensure_data_source sets appropriate default URLs."""
    with get_sync_session(sqlite_engine) as session:
        src_ig = _ensure_data_source(
            session,
            "instagram",
            "Instagram",
            DataSourceType.SOCIAL,
        )
        assert src_ig.source_url == "https://www.instagram.com/ecuhockey"

        src_opp = _ensure_data_source(
            session,
            "opponent",
            "Opponent",
            DataSourceType.OPPONENT,
        )
        assert src_opp.source_url == "https://github.com/bdperkin/ecu-hockey-calendar"

        src_other = _ensure_data_source(
            session,
            "custom",
            "Custom",
            DataSourceType.PRIMARY_SOT,
        )
        assert src_other.source_url == ""

        # Test _ensure_crawl_data_sources with multiple sources
        _ensure_crawl_data_sources(
            session,
            [
                {"source": "ecuhockey", "name": "ECU"},
                {"source": "instagram", "name": "Instagram"},
                {"source": "opponent", "name": "Opponents"},
            ],
        )


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

        ds3 = _ensure_data_source(
            session,
            "achahockey",
            "ACHA Hockey",
            DataSourceType.LEAGUE,
        )
        assert ds3.source_url == "https://www.achahockey.org"

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

    # Test initial_audit_exists=True where update succeeds
    cycle_id_existing = "cycle-persist-existing"
    with get_sync_session(sqlite_engine) as session:
        audit_running = SyncAuditModel(
            sync_cycle_id=cycle_id_existing,
            started_at=datetime.now(UTC),
            status=SyncStatus.RUNNING.value,
        )
        session.add(audit_running)
        session.commit()

    cycle_result_existing = ChangeDetectionCycleResult(
        cycle_id=cycle_id_existing,
        changes=[],
    )
    with get_sync_session(sqlite_engine) as session:
        _persist_sync_results(
            session,
            [],
            telemetry,
            cycle_result_existing,
            initial_audit_exists=True,
        )
        session.commit()

    with get_sync_session(sqlite_engine) as session:
        audit_done = session.scalar(
            select(SyncAuditModel).where(
                SyncAuditModel.sync_cycle_id == cycle_id_existing,
            ),
        )
        assert audit_done is not None
        assert audit_done.status == SyncStatus.SUCCESS.value


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


@pytest.mark.anyio
async def test_run_sync_pipeline_verify_opponents(sqlite_engine: Any) -> None:
    """Test run_sync_pipeline with verify_opponents in live and dry-run modes."""
    mock_src = SourceGameRecord(
        source_type=DataSourceType.PRIMARY_SOT,
        source_code="ecuhockey",
        opponent_name="UNC Chapel Hill",
        start_time=datetime(2026, 11, 20, 19, 0, tzinfo=UTC),
        venue="The Factory",
    )

    async def mock_crawler(
        _: str,
    ) -> tuple[list[SourceGameRecord], list[dict[str, Any]]]:
        return [mock_src], [
            {
                "source": "ecuhockey",
                "name": "ECU",
                "records": 1,
                "status": "SUCCESS",
                "duration": 0.1,
            },
        ]

    mock_opp_crawler = MagicMock()
    mock_opp_crawler.sync = AsyncMock(return_value=(1, 0, MagicMock()))
    mock_opp_crawler.reverse_check_all_games = AsyncMock(return_value={})
    mock_opp_cls = MagicMock(return_value=mock_opp_crawler)

    # Live run with verify_opponents=True
    mock_dir = MagicMock()
    await run_sync_pipeline(
        engine=sqlite_engine,
        dry_run=False,
        verify_opponents=True,
        crawler_fn=mock_crawler,
        opponent_crawler_cls=mock_opp_cls,
        opponent_directory=mock_dir,
    )
    assert mock_opp_crawler.sync.called
    assert mock_opp_cls.call_args[1]["directory"] is mock_dir

    # Dry run with verify_opponents=True
    await run_sync_pipeline(
        engine=sqlite_engine,
        dry_run=True,
        verify_opponents=True,
        crawler_fn=mock_crawler,
        opponent_crawler_cls=mock_opp_cls,
    )
    assert mock_opp_crawler.reverse_check_all_games.called


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

        # DB has no completed audits
        sm_empty = SyncManager(engine=sqlite_engine)
        sm_empty._last_completed_at = None
        with get_sync_session(sqlite_engine) as session:
            for rec in session.scalars(select(SyncAuditModel)).all():
                session.delete(rec)

            session.commit()

        sm_empty._init_last_completed_from_db()
        assert sm_empty._last_completed_at is None

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


def test_stale_ids_helpers() -> None:
    """Verify helpers for computing stale IDs from baseline and deleted records."""
    dt = datetime(2026, 9, 20, 1, 30, tzinfo=UTC)
    gm1 = GameModel(game_id="game-1", start_time=dt, venue="Ice 1", season="2026-2027")
    gm2 = GameModel(game_id="game-2", start_time=dt, venue="Ice 2", season="2026-2027")
    reconciled_ids = {"game-1"}

    assert _stale_ids_from_baseline(reconciled_ids, [gm1, gm2]) == ["game-2"]

    rec_del = GameChangeRecord(
        canonical_game_id="game-2",
        state_transition=GameStateTransition.DELETED,
        field_diffs=[],
        previous_snapshot={},
        current_snapshot=None,
        detected_conflicts=[],
        human_summary="Deleted game",
        recorded_at=dt,
    )
    rec_kept = GameChangeRecord(
        canonical_game_id="game-1",
        state_transition=GameStateTransition.UNCHANGED,
        field_diffs=[],
        previous_snapshot={},
        current_snapshot={},
        detected_conflicts=[],
        human_summary="Kept game",
        recorded_at=dt,
    )
    assert _stale_ids_from_deleted(reconciled_ids, [rec_del, rec_kept]) == ["game-2"]

    # _collect_stale_game_ids branches
    assert _collect_stale_game_ids(reconciled_ids, [gm1, gm2], None) == ["game-2"]
    assert _collect_stale_game_ids(reconciled_ids, None, [rec_del]) == ["game-2"]
    assert _collect_stale_game_ids(reconciled_ids, None, None) == []


def test_should_skip_pruning() -> None:
    """Verify pruning is only skipped during partial crawl cycles."""
    assert _should_skip_pruning("ecuhockey") is True
    assert _should_skip_pruning("instagram") is True
    assert _should_skip_pruning("all") is False
    assert _should_skip_pruning("ALL") is False
    assert _should_skip_pruning("") is False
    assert _should_skip_pruning("  ") is False


def test_prune_stale_fixtures(sqlite_engine: Any) -> None:
    """Verify database pruning removes stale game fixtures."""
    dt = datetime(2026, 9, 20, 1, 30, tzinfo=UTC)
    with get_sync_session(sqlite_engine) as session:
        t1 = _get_or_create_team(session, "East Carolina University")
        t2 = _get_or_create_team(session, "UNC Charlotte")

        g1 = GameModel(
            game_id="game-vs-charlotte-0919",
            home_team_id=t2.id,
            away_team_id=t1.id,
            start_time=dt,
            venue="Extreme Ice Center",
            season="2026-2027",
        )
        g_stale = GameModel(
            game_id="ecu-away-charlotte-duplicate",
            home_team_id=t2.id,
            away_team_id=t1.id,
            start_time=dt,
            venue="Extreme Ice Center",
            season="2026-2027",
        )
        session.add_all([g1, g_stale])
        session.commit()

    rg = ReconciledGame(
        canonical_game_id="game-vs-charlotte-0919",
        opponent_name="UNC Charlotte",
        start_time=dt,
        venue="Extreme Ice Center",
        is_home=False,
    )

    # 1. Skip if source_filter != 'all'
    with get_sync_session(sqlite_engine) as session:
        pruned = _prune_stale_fixtures(
            session,
            [rg],
            baseline_games=[g1, g_stale],
            source_filter="ecuhockey",
        )
        assert pruned == []

    # 2. No stale IDs
    with get_sync_session(sqlite_engine) as session:
        pruned = _prune_stale_fixtures(
            session,
            [rg],
            baseline_games=[g1],
            source_filter="all",
        )
        assert pruned == []

    # 3. Prune stale fixture via baseline_games
    with get_sync_session(sqlite_engine) as session:
        pruned = _prune_stale_fixtures(
            session,
            [rg],
            baseline_games=[g1, g_stale],
            source_filter="all",
        )
        session.commit()
        assert pruned == ["ecu-away-charlotte-duplicate"]

    with get_sync_session(sqlite_engine) as session:
        remaining = session.scalars(select(GameModel.game_id)).all()
        assert "game-vs-charlotte-0919" in remaining
        assert "ecu-away-charlotte-duplicate" not in remaining


def test_prune_stale_fixtures_via_deleted_records(sqlite_engine: Any) -> None:
    """Verify pruning works via deleted_records when baseline_games is None."""
    dt = datetime(2026, 9, 20, 1, 30, tzinfo=UTC)
    with get_sync_session(sqlite_engine) as session:
        t1 = _get_or_create_team(session, "East Carolina University")
        t2 = _get_or_create_team(session, "UNC Charlotte")

        g_stale = GameModel(
            game_id="ecu-away-charlotte-stale-2",
            home_team_id=t2.id,
            away_team_id=t1.id,
            start_time=dt,
            venue="Extreme Ice Center",
            season="2026-2027",
        )
        session.add(g_stale)
        session.commit()

    rec_del = GameChangeRecord(
        canonical_game_id="ecu-away-charlotte-stale-2",
        state_transition=GameStateTransition.DELETED,
        field_diffs=[],
        previous_snapshot={},
        current_snapshot=None,
        detected_conflicts=[],
        human_summary="Deleted game",
        recorded_at=dt,
    )
    rg = ReconciledGame(
        canonical_game_id="game-vs-charlotte-0919",
        opponent_name="UNC Charlotte",
        start_time=dt,
        venue="Extreme Ice Center",
        is_home=False,
    )

    with get_sync_session(sqlite_engine) as session:
        pruned = _prune_stale_fixtures(
            session,
            [rg],
            baseline_games=None,
            deleted_records=[rec_del],
            source_filter="all",
        )
        session.commit()
        assert pruned == ["ecu-away-charlotte-stale-2"]

    with get_sync_session(sqlite_engine) as session:
        remaining = session.scalars(
            select(GameModel).where(GameModel.game_id == "ecu-away-charlotte-stale-2"),
        ).first()
        assert remaining is None


@pytest.mark.anyio
async def test_run_sync_pipeline_prunes_synthetic_duplicate(sqlite_engine: Any) -> None:
    """Verify pipeline purges pre-existing synthetic duplicate games."""
    dt = datetime(2026, 9, 20, 1, 30, tzinfo=UTC)
    with get_sync_session(sqlite_engine) as session:
        t_ecu = _get_or_create_team(session, "East Carolina University")
        t_uncc = _get_or_create_team(session, "UNC Charlotte")

        old_duplicate = GameModel(
            game_id="ecu-away-university-of-north-carolina-charlotte-20260920",
            home_team_id=t_uncc.id,
            away_team_id=t_ecu.id,
            start_time=dt,
            venue="Extreme Ice Center, Charlotte, NC",
            season="2026-2027",
        )
        session.add(old_duplicate)
        session.commit()

    async def mock_crawler(
        _: str,
    ) -> tuple[list[SourceGameRecord], list[dict[str, Any]]]:
        rec = SourceGameRecord(
            source_type=DataSourceType.PRIMARY_SOT,
            source_code="ecuhockey",
            game_id="game-vs-charlotte-on-09192026-mrxgmz79",
            start_time=dt,
            opponent_name="UNC Charlotte",
            venue="Extreme Ice Center",
            is_home=False,
        )
        return [rec], [{"source": "ecuhockey", "name": "ECU Official"}]

    _, change_res, _ = await run_sync_pipeline(
        engine=sqlite_engine,
        source_filter="all",
        crawler_fn=mock_crawler,
    )

    assert change_res is not None

    with get_sync_session(sqlite_engine) as session:
        games = session.scalars(select(GameModel)).all()
        game_ids = [g.game_id for g in games]
        assert "game-vs-charlotte-on-09192026-mrxgmz79" in game_ids
        assert (
            "ecu-away-university-of-north-carolina-charlotte-20260920" not in game_ids
        )
