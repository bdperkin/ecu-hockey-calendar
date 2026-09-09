"""Database engine and session management for sync and async operations.

This module provides factory functions to configure SQLAlchemy 2.0 engines,
session factories, and transaction context managers for both SQLite and PostgreSQL.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager, contextmanager
from typing import TYPE_CHECKING, Any

import aiosqlite
import psycopg
from sqlalchemy import create_engine as _create_sync_engine
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.ext.asyncio import (
    create_async_engine as _create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from ecu_hockey_calendar.storage.base import Base

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator
    from sqlite3 import Connection as Sqlite3Connection

DEFAULT_SQLITE_PATH = "ecu_hockey.db"
DEFAULT_SYNC_SQLITE_URL = f"sqlite:///{DEFAULT_SQLITE_PATH}"
DEFAULT_ASYNC_SQLITE_URL = f"sqlite+aiosqlite:///{DEFAULT_SQLITE_PATH}"


def get_aiosqlite_driver_version() -> str:
    """Return the installed version of the aiosqlite driver.

    Returns:
        String version identifier of aiosqlite.
    """
    return aiosqlite.__version__


def get_psycopg_driver_version() -> str:
    """Return the installed version of the psycopg driver.

    Returns:
        String version identifier of psycopg.
    """
    return psycopg.__version__


def get_sync_database_url(url: str | None = None) -> str:
    """Resolve the synchronous database connection URL.

    Args:
        url: Explicit URL, or None to load from environment variables.

    Returns:
        Resolved synchronous database URL.
    """
    if url is not None:
        raw = url
    else:
        raw = os.environ.get("DATABASE_URL", DEFAULT_SYNC_SQLITE_URL)

    # Normalize Heroku/Render legacy postgres:// to postgresql+psycopg://
    if raw.startswith("postgres://"):
        return f"postgresql+psycopg://{raw.removeprefix('postgres://')}"

    # Normalize bare postgresql:// without driver to postgresql+psycopg://
    if raw.startswith("postgresql://"):
        return f"postgresql+psycopg://{raw.removeprefix('postgresql://')}"

    # If an async sqlite URL was passed to sync, strip +aiosqlite
    if raw.startswith("sqlite+aiosqlite://"):
        return f"sqlite://{raw.removeprefix('sqlite+aiosqlite://')}"

    return raw


def _convert_to_async_url(raw: str) -> str:
    """Convert synchronous database URL scheme to asynchronous equivalent.

    Args:
        raw: Raw database connection URL.

    Returns:
        Converted asynchronous database URL.
    """
    if raw.startswith("postgres://"):
        raw = f"postgresql://{raw.removeprefix('postgres://')}"

    if raw.startswith("sqlite:///"):
        return f"sqlite+aiosqlite:///{raw.removeprefix('sqlite:///')}"

    if raw.startswith("postgresql://"):
        return f"postgresql+asyncpg://{raw.removeprefix('postgresql://')}"

    return raw


def get_async_database_url(url: str | None = None) -> str:
    """Resolve the asynchronous database connection URL.

    Args:
        url: Explicit URL, or None to load from environment variables.

    Returns:
        Resolved asynchronous database URL.
    """
    if url is not None:
        return _convert_to_async_url(url)

    raw = os.environ.get("ASYNC_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not raw:
        return DEFAULT_ASYNC_SQLITE_URL

    return _convert_to_async_url(raw)


def _enable_sqlite_foreign_keys(
    dbapi_conn: Sqlite3Connection,
    _connection_record: object,
) -> None:
    """Enable SQLite foreign key constraints on connection.

    Args:
        dbapi_conn: Underlying sqlite3 database connection.
        _connection_record: SQLAlchemy connection record (unused).
    """
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.close()


def _is_in_memory_sqlite(url: str) -> bool:
    """Check if database URL refers to an in-memory SQLite database.

    Args:
        url: Database connection string.

    Returns:
        True if the database is in-memory SQLite, otherwise False.
    """
    return (
        url in {"sqlite://", "sqlite:///:memory:", "sqlite+aiosqlite://"}
        or ":memory:" in url
    )


def _configure_sqlite_memory_kwargs(kwargs: dict[str, Any]) -> None:
    """Apply static pool and threading settings for in-memory SQLite.

    Args:
        kwargs: Mutable dictionary of engine keyword arguments.
    """
    kwargs.setdefault("poolclass", StaticPool)
    connect_args = kwargs.get("connect_args")
    if not isinstance(connect_args, dict):
        connect_args = {}
        kwargs["connect_args"] = connect_args

    connect_args.setdefault("check_same_thread", False)


def create_sync_engine(
    url: str | None = None,
    *,
    echo: bool = False,
    **kwargs: object,
) -> Engine:
    """Create a synchronous SQLAlchemy engine.

    Args:
        url: Optional database connection URL.
        echo: Whether to log generated SQL statements.
        **kwargs: Additional keyword arguments forwarded to create_engine.

    Returns:
        Configured SQLAlchemy Engine.
    """
    resolved_url = get_sync_database_url(url)
    engine_kwargs = dict(kwargs)

    is_sqlite = resolved_url.startswith("sqlite:")
    if is_sqlite and _is_in_memory_sqlite(resolved_url):
        _configure_sqlite_memory_kwargs(engine_kwargs)

    engine = _create_sync_engine(resolved_url, echo=echo, **engine_kwargs)

    if is_sqlite:
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)

    return engine


def create_async_engine(
    url: str | None = None,
    *,
    echo: bool = False,
    **kwargs: object,
) -> AsyncEngine:
    """Create an asynchronous SQLAlchemy engine.

    Args:
        url: Optional database connection URL.
        echo: Whether to log generated SQL statements.
        **kwargs: Additional keyword arguments forwarded to create_async_engine.

    Returns:
        Configured SQLAlchemy AsyncEngine.
    """
    resolved_url = get_async_database_url(url)
    engine_kwargs = dict(kwargs)

    is_sqlite = "sqlite" in resolved_url
    if is_sqlite and _is_in_memory_sqlite(resolved_url):
        _configure_sqlite_memory_kwargs(engine_kwargs)

    engine = _create_async_engine(resolved_url, echo=echo, **engine_kwargs)

    if is_sqlite:
        event.listen(
            engine.sync_engine,
            "connect",
            _enable_sqlite_foreign_keys,
        )

    return engine


def get_sync_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a synchronous Session factory bound to an engine.

    Args:
        engine: The SQLAlchemy Engine to bind sessions to.

    Returns:
        A configured sessionmaker producing Session instances.
    """
    return sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )


def get_async_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Create an asynchronous Session factory bound to an async engine.

    Args:
        engine: The SQLAlchemy AsyncEngine to bind sessions to.

    Returns:
        A configured async_sessionmaker producing AsyncSession instances.
    """
    return async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )


@contextmanager
def get_sync_session(
    engine_or_factory: Engine | sessionmaker[Session] | None = None,
) -> Iterator[Session]:
    """Provide a transactional synchronous database session scope.

    Args:
        engine_or_factory: Optional Engine or sessionmaker instance.

    Yields:
        An active SQLAlchemy Session instance.
    """
    factory: sessionmaker[Session]
    if isinstance(engine_or_factory, Engine):
        factory = get_sync_session_factory(engine_or_factory)
    elif engine_or_factory is not None:
        factory = engine_or_factory
    else:
        factory = get_sync_session_factory(create_sync_engine())

    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@asynccontextmanager
async def get_async_session(
    engine_or_factory: AsyncEngine | async_sessionmaker[AsyncSession] | None = None,
) -> AsyncIterator[AsyncSession]:
    """Provide a transactional asynchronous database session scope.

    Args:
        engine_or_factory: Optional AsyncEngine or async_sessionmaker instance.

    Yields:
        An active SQLAlchemy AsyncSession instance.
    """
    factory: async_sessionmaker[AsyncSession]
    if isinstance(engine_or_factory, AsyncEngine):
        factory = get_async_session_factory(engine_or_factory)
    elif engine_or_factory is not None:
        factory = engine_or_factory
    else:
        factory = get_async_session_factory(create_async_engine())

    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


def init_db(engine: Engine) -> None:
    """Create all relational database tables synchronously.

    Args:
        engine: The SQLAlchemy Engine to execute DDL against.
    """
    Base.metadata.create_all(bind=engine)


def drop_db(engine: Engine) -> None:
    """Drop all relational database tables synchronously.

    Args:
        engine: The SQLAlchemy Engine to execute DDL against.
    """
    Base.metadata.drop_all(bind=engine)


async def async_init_db(engine: AsyncEngine) -> None:
    """Create all relational database tables asynchronously.

    Args:
        engine: The SQLAlchemy AsyncEngine to execute DDL against.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def async_drop_db(engine: AsyncEngine) -> None:
    """Drop all relational database tables asynchronously.

    Args:
        engine: The SQLAlchemy AsyncEngine to execute DDL against.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


__all__ = [
    "DEFAULT_ASYNC_SQLITE_URL",
    "DEFAULT_SQLITE_PATH",
    "DEFAULT_SYNC_SQLITE_URL",
    "async_drop_db",
    "async_init_db",
    "create_async_engine",
    "create_sync_engine",
    "drop_db",
    "get_aiosqlite_driver_version",
    "get_async_database_url",
    "get_async_session",
    "get_async_session_factory",
    "get_psycopg_driver_version",
    "get_sync_database_url",
    "get_sync_session",
    "get_sync_session_factory",
    "init_db",
]
