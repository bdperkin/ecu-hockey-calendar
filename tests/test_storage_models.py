"""Tests for SQLAlchemy storage models and ORM entities."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ecu_hockey_calendar.models import Game, GameResult, Team
from ecu_hockey_calendar.storage import (
    DataSourceModel,
    DataSourceORM,
    DataSourceType,
    GameChangeModel,
    GameChangeORM,
    GameModel,
    GameORM,
    GameStatus,
    RawSnapshotModel,
    RawSnapshotORM,
    SyncAuditModel,
    SyncAuditORM,
    SyncStatus,
    TeamModel,
    TeamORM,
    create_sync_engine,
    get_sync_session,
    init_db,
)


@pytest.fixture
def sync_memory_engine():
    """Provide an in-memory SQLite sync engine initialized with schema."""
    engine = create_sync_engine("sqlite:///:memory:")
    init_db(engine)
    return engine


def test_model_aliases() -> None:
    """Verify ORM alias classes match their Model counterparts."""
    assert TeamORM is TeamModel
    assert GameORM is GameModel
    assert DataSourceORM is DataSourceModel
    assert RawSnapshotORM is RawSnapshotModel
    assert SyncAuditORM is SyncAuditModel
    assert GameChangeORM is GameChangeModel


def test_enum_values() -> None:
    """Verify string enum members."""
    assert DataSourceType.PRIMARY_SOT == "primary_sot"
    assert DataSourceType.LEAGUE == "league"
    assert DataSourceType.TICKETS == "tickets"
    assert DataSourceType.SOCIAL == "social"
    assert DataSourceType.OPPONENT == "opponent"

    assert SyncStatus.RUNNING == "RUNNING"
    assert SyncStatus.SUCCESS == "SUCCESS"
    assert SyncStatus.FAILURE == "FAILURE"
    assert SyncStatus.PARTIAL == "PARTIAL"

    assert GameStatus.SCHEDULED == "SCHEDULED"
    assert GameStatus.IN_PROGRESS == "IN_PROGRESS"
    assert GameStatus.FINAL == "FINAL"
    assert GameStatus.POSTPONED == "POSTPONED"
    assert GameStatus.CANCELLED == "CANCELLED"


def test_team_model_lifecycle(sync_memory_engine, ecu_team: Team) -> None:
    """Verify TeamModel creation, conversion, serialization, and persistence."""
    with get_sync_session(sync_memory_engine) as session:
        team_orm = TeamModel.from_domain(
            ecu_team,
            logo_url="https://example.com/logo.png",
            website="https://ecuhockey.com",
        )
        session.add(team_orm)
        session.flush()

        assert team_orm.id is not None
        assert team_orm.name == "East Carolina University"
        assert team_orm.city == "Greenville"
        assert team_orm.state == "NC"
        assert team_orm.division == "ACHA M2"
        assert team_orm.conference == "ACCHL"
        assert team_orm.logo_url == "https://example.com/logo.png"
        assert team_orm.website == "https://ecuhockey.com"
        assert team_orm.created_at is not None
        assert team_orm.updated_at is not None

        # Domain conversion
        domain = team_orm.to_domain()
        assert domain == ecu_team

        # Dictionary serialization
        d = team_orm.to_dict()
        assert d["name"] == "East Carolina University"
        assert d["city"] == "Greenville"
        assert d["id"] == team_orm.id
        assert d["created_at"] is not None

    # Verify query
    with get_sync_session(sync_memory_engine) as session:
        queried = session.scalars(
            select(TeamModel).where(TeamModel.name == "East Carolina University"),
        ).one()
        assert queried.city == "Greenville"


def test_team_unique_name_constraint(sync_memory_engine) -> None:
    """Verify unique constraint on team name."""
    with (
        pytest.raises(IntegrityError),
        get_sync_session(sync_memory_engine) as session,
    ):
        t1 = TeamModel(name="ECU", city="Greenville", state="NC")
        t2 = TeamModel(name="ECU", city="Other City", state="NC")
        session.add_all([t1, t2])
        session.flush()


def test_game_model_lifecycle(
    sync_memory_engine,
    ecu_team: Team,
    unc_team: Team,
    sample_game: Game,
) -> None:
    """Verify GameModel persistence, domain conversions, and serialization."""
    with get_sync_session(sync_memory_engine) as session:
        home = TeamModel.from_domain(ecu_team)
        away = TeamModel.from_domain(unc_team)
        session.add_all([home, away])
        session.flush()

        game_orm = GameModel.from_domain(
            sample_game,
            home_team_id=home.id,
            away_team_id=away.id,
            season="2026-2027",
            status=GameStatus.FINAL.value,
            end_time=datetime(2026, 10, 15, 21, 30, tzinfo=UTC),
        )
        game_orm.result = "W"
        game_orm.home_score = 5
        game_orm.away_score = 2
        session.add(game_orm)
        session.flush()

        assert game_orm.id is not None
        assert game_orm.game_id == "GAME-001"
        assert game_orm.home_team.name == "East Carolina University"
        assert game_orm.away_team.name == "UNC Chapel Hill"
        assert len(home.home_games) == 1
        assert len(away.away_games) == 1

        # Domain round-trip
        domain_game = game_orm.to_domain()
        assert domain_game.game_id == "GAME-001"
        assert domain_game.result == GameResult.WIN
        assert domain_game.home_score == 5
        assert domain_game.away_score == 2

        # Serialization
        data = game_orm.to_dict()
        assert data["game_id"] == "GAME-001"
        assert data["home_team_id"] == home.id
        assert data["home_score"] == 5
        assert data["status"] == GameStatus.FINAL.value
        assert data["end_time"] is not None


def test_game_to_domain_fallback(
    sync_memory_engine,
    ecu_team: Team,
    unc_team: Team,
) -> None:
    """Verify GameModel.to_domain fallback behavior for unknown results."""
    with get_sync_session(sync_memory_engine) as session:
        home = TeamModel.from_domain(ecu_team)
        away = TeamModel.from_domain(unc_team)
        session.add_all([home, away])
        session.flush()

        # Unknown result string falls back to SCHEDULED
        g1 = GameModel(
            game_id="G-FALLBACK",
            home_team_id=home.id,
            away_team_id=away.id,
            start_time=datetime(2026, 11, 1, 19, 0, tzinfo=UTC),
            venue="Ice Arena",
            result="UNKNOWN_VALUE",
        )
        session.add(g1)
        session.flush()
        assert g1.to_domain().result == GameResult.SCHEDULED

        # None result defaults to SCHEDULED
        g2 = GameModel(
            game_id="G-NONE",
            home_team_id=home.id,
            away_team_id=away.id,
            start_time=datetime(2026, 11, 2, 19, 0, tzinfo=UTC),
            venue="Ice Arena",
            result=None,
        )
        session.add(g2)
        session.flush()
        assert g2.to_domain().result == GameResult.SCHEDULED


def test_data_source_and_snapshot_lifecycle(sync_memory_engine) -> None:
    """Verify DataSourceModel and RawSnapshotModel relationships and serialization."""
    with get_sync_session(sync_memory_engine) as session:
        source = DataSourceModel(
            source_code="PRIMARY_SOT",
            name="Official ECU Schedule",
            source_url="https://www.ecuhockey.com/schedule/upcoming",
            source_type=DataSourceType.PRIMARY_SOT.value,
            priority_order=1,
            is_active=True,
            last_scraped_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        )
        session.add(source)
        session.flush()

        snapshot = RawSnapshotModel(
            source_id=source.id,
            url="https://www.ecuhockey.com/schedule/upcoming",
            content_hash="abc123hash",
            content_type="text/html",
            payload="<html><body>Schedule Content</body></html>",
        )
        session.add(snapshot)
        session.flush()

        assert source.id is not None
        assert snapshot.id is not None
        assert len(source.snapshots) == 1
        assert source.snapshots[0].content_hash == "abc123hash"
        assert snapshot.source.name == "Official ECU Schedule"

        s_dict = source.to_dict()
        assert s_dict["source_code"] == "PRIMARY_SOT"
        assert s_dict["last_scraped_at"] is not None

        snap_dict = snapshot.to_dict()
        assert snap_dict["content_hash"] == "abc123hash"
        assert snap_dict["captured_at"] is not None


def test_sync_audit_lifecycle(sync_memory_engine) -> None:
    """Verify SyncAuditModel persistence, foreign keys, and serialization."""
    with get_sync_session(sync_memory_engine) as session:
        source = DataSourceModel(
            source_code="LEAGUE",
            name="ACC Hockey League",
            source_url="https://www.acchockey.com/page/show/9602441-east-carolina",
            source_type=DataSourceType.LEAGUE.value,
        )
        session.add(source)
        session.flush()

        audit = SyncAuditModel(
            source_id=source.id,
            sync_cycle_id="cycle-20260905-001",
            started_at=datetime(2026, 9, 5, 20, 0, tzinfo=UTC),
            completed_at=datetime(2026, 9, 5, 20, 0, 5, tzinfo=UTC),
            duration_ms=5000,
            status=SyncStatus.SUCCESS.value,
            games_created=2,
            games_updated=1,
            games_deleted=0,
            conflicts_detected=0,
            error_message=None,
            details={"updated_game_ids": ["GAME-001"]},
        )
        session.add(audit)
        session.flush()

        assert audit.id is not None
        assert audit.source is not None
        assert audit.source.name == "ACC Hockey League"
        assert len(source.sync_audits) == 1

        d = audit.to_dict()
        assert d["sync_cycle_id"] == "cycle-20260905-001"
        assert d["status"] == "SUCCESS"
        assert d["duration_ms"] == 5000
        assert d["details"] == {"updated_game_ids": ["GAME-001"]}


def test_team_cascade_delete_games(
    sync_memory_engine,
    ecu_team: Team,
    unc_team: Team,
) -> None:
    """Verify deleting a team cascades to remove associated games."""
    with get_sync_session(sync_memory_engine) as session:
        home = TeamModel.from_domain(ecu_team)
        away = TeamModel.from_domain(unc_team)
        session.add_all([home, away])
        session.flush()

        game = GameModel(
            game_id="G-CASCADE-TEST",
            home_team_id=home.id,
            away_team_id=away.id,
            start_time=datetime(2026, 12, 1, 19, 0, tzinfo=UTC),
            venue="Arena",
        )
        session.add(game)
        session.flush()

        assert (
            session.scalar(
                select(GameModel).where(GameModel.game_id == "G-CASCADE-TEST"),
            )
            is not None
        )

        # Delete the home team
        session.delete(home)
        session.flush()

        # Game should be removed
        assert (
            session.scalar(
                select(GameModel).where(GameModel.game_id == "G-CASCADE-TEST"),
            )
            is None
        )


def test_game_change_model_lifecycle(sync_memory_engine) -> None:
    """Verify GameChangeModel creation, serialization, relationship, and cascade."""
    with get_sync_session(sync_memory_engine) as session:
        audit = SyncAuditModel(
            sync_cycle_id="cycle-123",
            status=SyncStatus.SUCCESS.value,
        )
        session.add(audit)
        session.flush()

        change = GameChangeModel(
            sync_cycle_id="cycle-123",
            sync_audit_id=audit.id,
            canonical_game_id="game-20261010-unc-home",
            change_type="UPDATED",
            summary="Start time moved from 7:00 PM to 8:30 PM",
            field_diffs=[
                {
                    "field_name": "start_time",
                    "old_value": "2026-10-10T19:00:00+00:00",
                    "new_value": "2026-10-10T20:30:00+00:00",
                    "human_description": "Start time moved from 7:00 PM to 8:30 PM",
                },
            ],
            snapshot_before={"canonical_game_id": "game-20261010-unc-home"},
            snapshot_after={"canonical_game_id": "game-20261010-unc-home"},
        )
        session.add(change)
        session.flush()

        assert change.id is not None
        assert change.sync_audit is audit
        assert audit.game_changes == [change]
        assert change.recorded_at is not None

        d = change.to_dict()
        assert d["id"] == change.id
        assert d["sync_cycle_id"] == "cycle-123"
        assert d["sync_audit_id"] == audit.id
        assert d["canonical_game_id"] == "game-20261010-unc-home"
        assert d["change_type"] == "UPDATED"
        assert d["summary"] == "Start time moved from 7:00 PM to 8:30 PM"
        assert len(d["field_diffs"]) == 1
        assert d["snapshot_before"] == {"canonical_game_id": "game-20261010-unc-home"}
        assert d["snapshot_after"] == {"canonical_game_id": "game-20261010-unc-home"}
        assert d["recorded_at"] is not None

        # Deleting audit should cascade delete game_changes
        session.delete(audit)
        session.flush()

        assert (
            session.scalar(
                select(GameChangeModel).where(GameChangeModel.id == change.id),
            )
            is None
        )
