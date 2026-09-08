"""Tests for Alembic database migration pipeline and runner utilities."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import inspect, text

from ecu_hockey_calendar.storage import (
    create_sync_engine,
    get_alembic_config,
    run_migrations_downgrade,
    run_migrations_upgrade,
)


def test_get_alembic_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify Alembic Config creation and path resolution."""
    # Default resolution from current working directory
    cfg = get_alembic_config()
    assert cfg.config_file_name is not None
    assert Path(cfg.config_file_name).name == "alembic.ini"

    # Resolution when alembic.ini is not in current working directory
    non_repo_dir = tmp_path / "somewhere_else"
    non_repo_dir.mkdir()
    monkeypatch.chdir(non_repo_dir)

    cfg_fallback = get_alembic_config()
    assert cfg_fallback.config_file_name is not None
    assert Path(cfg_fallback.config_file_name).name == "alembic.ini"

    # Explicit config path and database URL with absolute script_location
    custom_ini = tmp_path / "custom_alembic.ini"
    abs_script = Path(__file__).resolve().parent.parent / "alembic"
    custom_ini.write_text(
        f"[alembic]\n"
        f"script_location = {abs_script}\n"
        f"path_separator = os\n"
        f"sqlalchemy.url = sqlite:///temp.db\n",
    )
    custom_cfg = get_alembic_config(
        database_url="sqlite:///override.db",
        config_path=custom_ini,
    )
    assert custom_cfg.get_main_option("sqlalchemy.url") == "sqlite:///override.db"
    assert custom_cfg.get_main_option("script_location") == str(abs_script)


def test_migrations_upgrade_and_downgrade_with_connection() -> None:
    """Verify programmatic migration upgrade and downgrade reusing a live connection."""
    engine = create_sync_engine("sqlite:///:memory:")

    with engine.connect() as conn:
        # Upgrade to head
        run_migrations_upgrade(target_revision="head", connection=conn)

        # Inspect created tables
        inspector = inspect(conn)
        tables = set(inspector.get_table_names())
        expected_tables = {
            "teams",
            "games",
            "data_sources",
            "raw_snapshots",
            "sync_audits",
            "game_changes",
            "alembic_version",
        }
        assert expected_tables.issubset(tables)

        # Insert record into migrated schema
        conn.execute(
            text(
                "INSERT INTO teams (name, city, state, division, conference) "
                "VALUES ('ECU', 'Greenville', 'NC', 'ACHA M2', 'ACCHL')",
            ),
        )
        result = conn.execute(text("SELECT name FROM teams")).scalar()
        assert result == "ECU"

        # Downgrade to base
        run_migrations_downgrade(target_revision="base", connection=conn)

        inspector_after = inspect(conn)
        tables_after = set(inspector_after.get_table_names())
        assert "teams" not in tables_after
        assert "games" not in tables_after
        assert "data_sources" not in tables_after
        assert "game_changes" not in tables_after

    engine.dispose()


def test_migrations_upgrade_and_downgrade_with_url(tmp_path: Path) -> None:
    """Verify programmatic migration upgrade and downgrade using database URL."""
    db_file = tmp_path / "migrated.db"
    db_url = f"sqlite:///{db_file}"

    run_migrations_upgrade(target_revision="head", database_url=db_url)

    engine = create_sync_engine(db_url)
    with engine.connect() as conn:
        inspector = inspect(conn)
        assert "teams" in inspector.get_table_names()

    engine.dispose()

    run_migrations_downgrade(target_revision="base", database_url=db_url)

    engine2 = create_sync_engine(db_url)
    with engine2.connect() as conn:
        inspector = inspect(conn)
        assert "teams" not in inspector.get_table_names()

    engine2.dispose()


def test_migrations_offline(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify Alembic offline migration execution output."""
    cfg = get_alembic_config(database_url="sqlite:///dummy.db")
    command.upgrade(cfg, "head", sql=True)

    captured = capsys.readouterr()
    assert "CREATE TABLE teams" in captured.out
    assert "CREATE TABLE games" in captured.out
    assert "CREATE TABLE data_sources" in captured.out
