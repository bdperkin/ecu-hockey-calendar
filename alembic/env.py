"""Alembic database migration configuration."""

from __future__ import annotations

import os
from logging.config import fileConfig
from typing import TYPE_CHECKING

from alembic import context
from sqlalchemy import engine_from_config, pool

from ecu_hockey_calendar.storage.base import Base
from ecu_hockey_calendar.storage.engine import get_sync_database_url
from ecu_hockey_calendar.storage.models import (  # noqa: F401
    DataSourceModel,
    GameModel,
    RawSnapshotModel,
    SyncAuditModel,
    TeamModel,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    """Retrieve database URL from environment or configuration.

    Returns:
        The resolved database connection string.
    """
    configured_url = config.get_main_option("sqlalchemy.url")
    return get_sync_database_url(os.environ.get("DATABASE_URL", configured_url))


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode without an active connection.

    Configures the context with just a URL and executes migrations
    emitting SQL directly.
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Execute migrations on an established database connection.

    Args:
        connection: Active SQLAlchemy database connection.
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode with a live database engine.

    Creates an Engine or reuses an existing connection passed through
    the config attributes dictionary.
    """
    connectable = config.attributes.get("connection", None)

    if connectable is None:
        configuration = config.get_section(config.config_ini_section, {})
        configuration["sqlalchemy.url"] = get_url()
        engine = engine_from_config(
            configuration,
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

        with engine.connect() as connection:
            do_run_migrations(connection)
    else:
        do_run_migrations(connectable)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
