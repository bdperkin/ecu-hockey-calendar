"""Tests for database engine configuration and session management."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ecu_hockey_calendar.storage import (
    DEFAULT_ASYNC_SQLITE_URL,
    DEFAULT_SYNC_SQLITE_URL,
    GameModel,
    TeamModel,
    async_drop_db,
    async_init_db,
    create_async_engine,
    create_sync_engine,
    drop_db,
    get_aiosqlite_driver_version,
    get_async_database_url,
    get_async_session,
    get_async_session_factory,
    get_sync_database_url,
    get_sync_session,
    get_sync_session_factory,
    init_db,
)


def test_get_aiosqlite_driver_version() -> None:
    """Verify driver version query returns a non-empty string."""
    ver = get_aiosqlite_driver_version()
    assert isinstance(ver, str)
    assert len(ver) > 0


def test_get_sync_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify synchronous database URL resolution under various environments."""
    # Explicit URL passed
    assert get_sync_database_url("sqlite:///custom.db") == "sqlite:///custom.db"

    # Default fallback
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert get_sync_database_url() == DEFAULT_SYNC_SQLITE_URL

    # Environment variable set
    monkeypatch.setenv("DATABASE_URL", "sqlite:///env.db")
    assert get_sync_database_url() == "sqlite:///env.db"

    # Legacy postgres:// normalization
    monkeypatch.setenv("DATABASE_URL", "postgres://localhost/test_db")
    assert get_sync_database_url() == "postgresql://localhost/test_db"

    # Async sqlite URL stripped for sync engine
    assert get_sync_database_url("sqlite+aiosqlite:///file.db") == "sqlite:///file.db"


def test_get_async_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify asynchronous database URL resolution under various environments."""
    # Explicit URL passed
    assert (
        get_async_database_url("sqlite+aiosqlite:///custom.db")
        == "sqlite+aiosqlite:///custom.db"
    )

    # Both env vars absent
    monkeypatch.delenv("ASYNC_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert get_async_database_url() == DEFAULT_ASYNC_SQLITE_URL

    # ASYNC_DATABASE_URL takes precedence
    monkeypatch.setenv("ASYNC_DATABASE_URL", "sqlite+aiosqlite:///async.db")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///sync.db")
    assert get_async_database_url() == "sqlite+aiosqlite:///async.db"

    # Fallback to DATABASE_URL conversion: sqlite
    monkeypatch.delenv("ASYNC_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///sync_convert.db")
    assert get_async_database_url() == "sqlite+aiosqlite:///sync_convert.db"

    # Fallback to DATABASE_URL conversion: postgresql
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test_db")
    assert get_async_database_url() == "postgresql+asyncpg://localhost/test_db"

    # Fallback to legacy postgres:// conversion
    monkeypatch.setenv("DATABASE_URL", "postgres://localhost/test_db")
    assert get_async_database_url() == "postgresql+asyncpg://localhost/test_db"


def test_sync_engine_foreign_keys_and_memory(tmp_path: Path) -> None:
    """Verify SQLite foreign key enforcement and in-memory StaticPool configuration."""
    # In-memory engine
    mem_engine = create_sync_engine("sqlite:///:memory:")
    init_db(mem_engine)

    # Inserting a game with invalid foreign key should fail
    with pytest.raises(IntegrityError), get_sync_session(mem_engine) as session:
        bad_game = GameModel(
            game_id="G-BAD-FK",
            home_team_id=999,
            away_team_id=998,
            start_time=datetime(2026, 11, 1, 19, 0, tzinfo=UTC),
            venue="Arena",
        )
        session.add(bad_game)

    drop_db(mem_engine)
    mem_engine.dispose()

    # File-based engine
    db_file = tmp_path / "test_file.db"
    file_engine = create_sync_engine(f"sqlite:///{db_file}")
    init_db(file_engine)

    with get_sync_session(file_engine) as session:
        t = TeamModel(name="Test Team", city="City", state="ST")
        session.add(t)

    with get_sync_session(file_engine) as session:
        res = session.scalars(select(TeamModel)).all()
        assert len(res) == 1

    drop_db(file_engine)
    file_engine.dispose()

    # Verify custom dict and non-dict connect_args branches
    eng_dict = create_sync_engine("sqlite:///:memory:", connect_args={"timeout": 5})
    eng_dict.dispose()
    eng_non_dict = create_sync_engine("sqlite:///:memory:", connect_args=None)
    eng_non_dict.dispose()


def test_async_engine_lifecycle_and_foreign_keys(tmp_path: Path) -> None:
    """Verify AsyncEngine creation and SQLite foreign key enforcement."""

    async def _run() -> None:
        """Execute async engine lifecycle test logic."""
        async_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await async_init_db(async_engine)

        async with get_async_session(async_engine) as session:
            team = TeamModel(name="ECU Pirates", city="Greenville", state="NC")
            session.add(team)

        async with get_async_session(async_engine) as session:
            result = await session.scalars(select(TeamModel))
            saved_team = result.one()
            assert saved_team.name == "ECU Pirates"

        # Verify foreign key constraint failure
        with pytest.raises(IntegrityError):
            async with get_async_session(async_engine) as session:
                bad_game = GameModel(
                    game_id="G-ASYNC-BAD",
                    home_team_id=999,
                    away_team_id=998,
                    start_time=datetime(2026, 11, 1, 19, 0, tzinfo=UTC),
                    venue="Arena",
                )
                session.add(bad_game)

        await async_drop_db(async_engine)
        await async_engine.dispose()

        # File-based async engine test
        db_file = tmp_path / "async_file.db"
        file_engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
        await async_init_db(file_engine)
        await async_drop_db(file_engine)
        await file_engine.dispose()

    asyncio.run(_run())


def test_create_engine_non_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify create_sync_engine and create_async_engine handling of non-SQLite URLs."""
    sync_calls = []

    def mock_sync_create(url, **kwargs):
        """Mock sync create_engine."""
        sync_calls.append((url, kwargs))
        return "mock_sync"

    monkeypatch.setattr(
        "ecu_hockey_calendar.storage.engine._create_sync_engine",
        mock_sync_create,
    )
    res_sync = create_sync_engine("postgresql://localhost/test_db")
    assert res_sync == "mock_sync"
    assert "poolclass" not in sync_calls[0][1]

    async_calls = []

    def mock_async_create(url, **kwargs):
        """Mock async create_async_engine."""
        async_calls.append((url, kwargs))
        return "mock_async"

    monkeypatch.setattr(
        "ecu_hockey_calendar.storage.engine._create_async_engine",
        mock_async_create,
    )
    res_async = create_async_engine(
        "postgresql+asyncpg://localhost/test_db",
    )
    assert res_async == "mock_async"
    assert "poolclass" not in async_calls[0][1]


def test_sync_session_context_manager_variants() -> None:
    """Verify get_sync_session with engine, sessionmaker, and default engine."""
    engine = create_sync_engine("sqlite:///:memory:")
    init_db(engine)
    factory = get_sync_session_factory(engine)

    # With sessionmaker
    with get_sync_session(factory) as session:
        session.add(TeamModel(name="Team A", city="A", state="NC"))

    # With Engine
    with get_sync_session(engine) as session:
        res = session.scalars(select(TeamModel)).all()
        assert len(res) == 1

    # Exception rollback
    with pytest.raises(RuntimeError), get_sync_session(engine) as session:
        session.add(TeamModel(name="Team B", city="B", state="NC"))
        raise RuntimeError("Simulated failure")

    with get_sync_session(engine) as session:
        names = [t.name for t in session.scalars(select(TeamModel)).all()]
        assert "Team B" not in names

    drop_db(engine)
    engine.dispose()


def test_async_session_context_manager_variants() -> None:
    """Verify get_async_session with engine, sessionmaker, and exception rollback."""

    async def _run() -> None:
        """Execute async session context manager test logic."""
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await async_init_db(engine)
        factory = get_async_session_factory(engine)

        # With async_sessionmaker
        async with get_async_session(factory) as session:
            session.add(TeamModel(name="Async Team A", city="A", state="NC"))

        # With AsyncEngine
        async with get_async_session(engine) as session:
            result = await session.scalars(select(TeamModel))
            assert len(result.all()) == 1

        # Exception rollback
        with pytest.raises(RuntimeError):
            async with get_async_session(engine) as session:
                session.add(TeamModel(name="Async Team B", city="B", state="NC"))
                raise RuntimeError("Async simulated failure")

        async with get_async_session(engine) as session:
            result = await session.scalars(select(TeamModel))
            names = [t.name for t in result.all()]
            assert "Async Team B" not in names

        await async_drop_db(engine)
        await engine.dispose()

    asyncio.run(_run())


def test_sync_session_default_engine(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify get_sync_session with None argument creates engine using DATABASE_URL."""
    db_file = tmp_path / "default_sync.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")

    with get_sync_session() as session:
        assert isinstance(session.bind, Engine)
        init_db(session.bind)
        session.add(TeamModel(name="Default Team", city="City", state="ST"))

    with get_sync_session() as session:
        res = session.scalars(select(TeamModel)).all()
        assert len(res) == 1
        assert isinstance(session.bind, Engine)
        drop_db(session.bind)
        session.bind.dispose()


def test_async_session_default_engine(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify get_async_session with None argument creates engine."""

    async def _run() -> None:
        """Execute async session default engine test logic."""
        db_file = tmp_path / "default_async.db"
        monkeypatch.setenv("ASYNC_DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")

        async with get_async_session() as session:
            assert isinstance(session.bind, AsyncEngine)
            await async_init_db(session.bind)
            session.add(TeamModel(name="Default Async Team", city="City", state="ST"))

        async with get_async_session() as session:
            result = await session.scalars(select(TeamModel))
            assert len(result.all()) == 1
            assert isinstance(session.bind, AsyncEngine)
            await async_drop_db(session.bind)
            await session.bind.dispose()

    asyncio.run(_run())
