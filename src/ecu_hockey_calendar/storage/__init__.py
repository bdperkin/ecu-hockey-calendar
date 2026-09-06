"""Storage and persistence package for ECU Hockey Calendar.

This package provides relational ORM models, sync and async database engines,
session management, and schema migration utilities.
"""

from __future__ import annotations

from ecu_hockey_calendar.storage.base import NAMING_CONVENTION, Base
from ecu_hockey_calendar.storage.engine import (
    DEFAULT_ASYNC_SQLITE_URL,
    DEFAULT_SQLITE_PATH,
    DEFAULT_SYNC_SQLITE_URL,
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
from ecu_hockey_calendar.storage.migrations import (
    get_alembic_config,
    run_migrations_downgrade,
    run_migrations_upgrade,
)
from ecu_hockey_calendar.storage.models import (
    DataSourceModel,
    DataSourceORM,
    DataSourceType,
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
)

__all__ = [
    "DEFAULT_ASYNC_SQLITE_URL",
    "DEFAULT_SQLITE_PATH",
    "DEFAULT_SYNC_SQLITE_URL",
    "NAMING_CONVENTION",
    "Base",
    "DataSourceModel",
    "DataSourceORM",
    "DataSourceType",
    "GameModel",
    "GameORM",
    "GameStatus",
    "RawSnapshotModel",
    "RawSnapshotORM",
    "SyncAuditModel",
    "SyncAuditORM",
    "SyncStatus",
    "TeamModel",
    "TeamORM",
    "async_drop_db",
    "async_init_db",
    "create_async_engine",
    "create_sync_engine",
    "drop_db",
    "get_aiosqlite_driver_version",
    "get_alembic_config",
    "get_async_database_url",
    "get_async_session",
    "get_async_session_factory",
    "get_sync_database_url",
    "get_sync_session",
    "get_sync_session_factory",
    "init_db",
    "run_migrations_downgrade",
    "run_migrations_upgrade",
]
