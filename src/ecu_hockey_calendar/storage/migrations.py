"""Alembic database migration runner utilities.

This module provides programmatic interfaces to execute Alembic schema migrations
both for CLI tools, production deployments, and automated testing environments.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from alembic import command
from alembic.config import Config

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection


def _resolve_alembic_ini_path(config_path: str | Path | None) -> Path:
    """Resolve the filesystem path to alembic.ini configuration file.

    Args:
        config_path: Optional custom path to alembic.ini.

    Returns:
        Resolved Path to alembic.ini.
    """
    if config_path is not None:
        return Path(config_path).resolve()

    candidate = Path.cwd() / "alembic.ini"
    if candidate.is_file():
        return candidate

    package_root = Path(__file__).resolve().parent.parent.parent.parent
    return package_root / "alembic.ini"


def get_alembic_config(
    database_url: str | None = None,
    config_path: str | Path | None = None,
) -> Config:
    """Create an Alembic Config object pointing to the repository migration environment.

    Args:
        database_url: Optional database connection URL override.
        config_path: Optional path to alembic.ini configuration file.

    Returns:
        Configured Alembic Config object.
    """
    resolved_config = _resolve_alembic_ini_path(config_path)
    cfg = Config(str(resolved_config))

    script_loc = cfg.get_main_option("script_location")
    if script_loc and not Path(script_loc).is_absolute():
        cfg.set_main_option(
            "script_location",
            str(resolved_config.parent / script_loc),
        )

    if database_url is not None:
        cfg.set_main_option("sqlalchemy.url", database_url)

    return cfg


def run_migrations_upgrade(
    target_revision: str = "head",
    database_url: str | None = None,
    connection: Connection | None = None,
    config_path: str | Path | None = None,
) -> None:
    """Run Alembic migrations upgrade to target revision.

    Args:
        target_revision: Target Alembic revision identifier (defaults to 'head').
        database_url: Optional database connection URL.
        connection: Optional live SQLAlchemy connection to reuse.
        config_path: Optional custom path to alembic.ini.
    """
    cfg = get_alembic_config(database_url=database_url, config_path=config_path)
    if connection is not None:
        cfg.attributes["connection"] = connection

    command.upgrade(cfg, target_revision)


def run_migrations_downgrade(
    target_revision: str = "base",
    database_url: str | None = None,
    connection: Connection | None = None,
    config_path: str | Path | None = None,
) -> None:
    """Run Alembic migrations downgrade to target revision.

    Args:
        target_revision: Target Alembic revision identifier (defaults to 'base').
        database_url: Optional database connection URL.
        connection: Optional live SQLAlchemy connection to reuse.
        config_path: Optional custom path to alembic.ini.
    """
    cfg = get_alembic_config(database_url=database_url, config_path=config_path)
    if connection is not None:
        cfg.attributes["connection"] = connection

    command.downgrade(cfg, target_revision)


__all__ = [
    "get_alembic_config",
    "run_migrations_downgrade",
    "run_migrations_upgrade",
]
