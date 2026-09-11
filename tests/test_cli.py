# pylint: disable=too-many-lines
"""Tests for the ECU Hockey command-line interface (ecu-hockey).

Covers root CLI group, subcommands (sync, status, export, conflicts, serve),
error handling, rich formatting, and options.
"""

from __future__ import annotations

import io
import os
import runpy
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import click
import pytest
from click.testing import CliRunner
from rich.console import Console
from sqlalchemy import select

from ecu_hockey_calendar.cli.conflicts import _matches_filter, conflicts_command
from ecu_hockey_calendar.cli.console import (
    create_table,
    format_severity_badge,
    format_status_badge,
    get_console,
    print_banner,
    print_error,
    print_panel,
    print_success,
    print_warning,
)
from ecu_hockey_calendar.cli.export import _detect_format, export_command
from ecu_hockey_calendar.cli.main import cli, main
from ecu_hockey_calendar.cli.serve import serve_command
from ecu_hockey_calendar.cli.status import (
    _compute_schedule_stats,
    _render_next_game_panel,
    status_command,
)
from ecu_hockey_calendar.cli.sync import (
    _convert_parsed_to_source_record,
    _ensure_data_source,
    sync_command,
)
from ecu_hockey_calendar.ingestion.html_parser import ParsedGameRecord
from ecu_hockey_calendar.models import Game, GameResult, Team
from ecu_hockey_calendar.reconciliation.models import (
    DataSourceType,
)
from ecu_hockey_calendar.storage.base import Base
from ecu_hockey_calendar.storage.engine import create_sync_engine, get_sync_session
from ecu_hockey_calendar.storage.models import (
    DataSourceModel,
    GameChangeModel,
    GameModel,
    GameStatus,
    SyncAuditModel,
    TeamModel,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def runner() -> CliRunner:
    """Provide a Click test runner fixture."""
    return CliRunner()


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    """Provide a file-backed SQLite database URL fixture."""
    db_file = tmp_path / "test_cli.db"
    url = f"sqlite:///{db_file}"
    engine = create_sync_engine(url)
    Base.metadata.create_all(engine)
    return url


class TestConsoleHelpers:
    """Tests for CLI rich console utilities and formatting."""

    def test_get_console(self) -> None:
        """Verify get_console returns Console instance."""
        con = get_console()
        assert isinstance(con, Console)

    def test_print_banner(self) -> None:
        """Verify banner rendering with and without subtitle."""
        buf = io.StringIO()
        custom = Console(file=buf, force_terminal=False, color_system=None)
        print_banner("TEST TITLE", subtitle="Test Subtitle", custom_console=custom)
        output = buf.getvalue()
        assert "ECU MEN'S ICE HOCKEY" in output
        assert "TEST TITLE" in output
        assert "Test Subtitle" in output

        buf2 = io.StringIO()
        custom2 = Console(file=buf2, force_terminal=False, color_system=None)
        print_banner("NO SUBTITLE", custom_console=custom2)
        assert "NO SUBTITLE" in buf2.getvalue()

    def test_format_severity_badge(self) -> None:
        """Verify severity badge colorization."""
        crit = format_severity_badge("CRITICAL")
        assert "CRITICAL" in crit.plain

        high = format_severity_badge("HIGH")
        assert "HIGH" in high.plain

        med = format_severity_badge("MEDIUM")
        assert "MEDIUM" in med.plain

        low = format_severity_badge("LOW")
        assert "LOW" in low.plain

        other = format_severity_badge("UNKNOWN")
        assert "UNKNOWN" in other.plain

    def test_format_status_badge(self) -> None:
        """Verify status badge styling across states."""
        for status_val in ("SUCCESS", "FINAL", "CONFIRMED", "ACTIVE"):
            assert status_val in format_status_badge(status_val).plain

        for status_val in ("FAILURE", "CANCELLED", "ERROR"):
            assert status_val in format_status_badge(status_val).plain

        for status_val in ("PARTIAL", "POSTPONED", "SYNCING", "IN_PROGRESS"):
            assert status_val in format_status_badge(status_val).plain

        for status_val in ("SCHEDULED", "IDLE"):
            assert status_val in format_status_badge(status_val).plain

        assert "CUSTOM" in format_status_badge("CUSTOM").plain

    def test_create_table(self) -> None:
        """Verify Rich table creation and column assignment."""
        table = create_table("Test Table", [("Col A", "cyan"), ("Col B", "bold")])
        assert table.title == "Test Table"
        assert len(table.columns) == 2

    def test_print_messages(self) -> None:
        """Verify print_success, print_warning, print_error, and print_panel."""
        buf = io.StringIO()
        custom = Console(file=buf, force_terminal=False, color_system=None)

        print_success("Operation completed", custom_console=custom)
        assert "Operation completed" in buf.getvalue()

        print_warning("Check warning", custom_console=custom)
        assert "Check warning" in buf.getvalue()

        print_error("Fatal error", custom_console=custom)
        assert "Fatal error" in buf.getvalue()

        print_panel("Panel body", title="Panel Title", custom_console=custom)
        assert "Panel body" in buf.getvalue()


class TestCliRoot:
    """Tests for the root ecu-hockey CLI group and entrypoint."""

    def test_cli_help(self, runner: CliRunner) -> None:
        """Verify root CLI help displays subcommands."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "sync" in result.output
        assert "status" in result.output
        assert "export" in result.output
        assert "conflicts" in result.output
        assert "serve" in result.output

    def test_cli_version(self, runner: CliRunner) -> None:
        """Verify root CLI displays version information."""
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "ecu-hockey" in result.output

    def test_main_function_success(self) -> None:
        """Verify main() entrypoint with valid arguments returns 0."""
        with patch("ecu_hockey_calendar.cli.main.cli.main") as mock_cli:
            mock_cli.return_value = 0
            code = main(["--version"])
            assert code == 0

    def test_main_function_click_exception(self) -> None:
        """Verify main() handles ClickException gracefully."""
        with patch(
            "ecu_hockey_calendar.cli.main.cli.main",
            side_effect=click.ClickException("Failed"),
        ):
            code = main(["status"])
            assert code == 1

    def test_main_function_exit_exception(self) -> None:
        """Verify main() handles click.exceptions.Exit."""
        with patch(
            "ecu_hockey_calendar.cli.main.cli.main",
            side_effect=click.exceptions.Exit(2),
        ):
            code = main(["export"])
            assert code == 2

    def test_main_function_system_exit(self) -> None:
        """Verify main() handles SystemExit."""
        with patch("ecu_hockey_calendar.cli.main.cli.main", side_effect=SystemExit(0)):
            code = main(["--help"])
            assert code == 0

    def test_cli_main_module(self) -> None:
        """Verify python -m ecu_hockey_calendar.cli execution."""
        with (
            patch("sys.exit") as mock_exit,
            patch("ecu_hockey_calendar.cli.main.main", return_value=0),
        ):
            runpy.run_module("ecu_hockey_calendar.cli.__main__", run_name="__main__")
            mock_exit.assert_called_once_with(0)


class TestStatusCommand:
    """Tests for 'ecu-hockey status' command."""

    def test_status_empty_db(self, runner: CliRunner, db_url: str) -> None:
        """Verify status command on an unpopulated database."""
        result = runner.invoke(status_command, ["--db-url", db_url])
        assert result.exit_code == 0
        assert "SYSTEM STATUS & SCHEDULE DIAGNOSTICS" in result.output
        assert "Never Run" in result.output
        assert "Registered Data Sources" in result.output

    def test_status_populated_db(self, runner: CliRunner, db_url: str) -> None:
        """Verify status command on a populated database."""
        engine = create_sync_engine(db_url)
        with get_sync_session(engine) as session:
            # Add team
            ecu = TeamModel(
                name="East Carolina University",
                city="Greenville",
                state="NC",
            )
            unc = TeamModel(name="UNC Chapel Hill", city="Chapel Hill", state="NC")
            session.add_all([ecu, unc])
            session.flush()

            # Add games
            g1 = GameModel(
                game_id="game-1",
                home_team_id=ecu.id,
                away_team_id=unc.id,
                start_time=datetime(2026, 10, 15, 19, 0, tzinfo=UTC),
                venue="The Factory Ice House",
                status="SCHEDULED",
                season="2026-2027",
            )
            g2 = GameModel(
                game_id="game-2",
                home_team_id=unc.id,
                away_team_id=ecu.id,
                start_time=datetime(2026, 9, 1, 19, 0, tzinfo=UTC),
                venue="Orange County Sportsplex",
                status="FINAL",
                home_score=2,
                away_score=4,
                result="WIN",
                season="2026-2027",
            )
            session.add_all([g1, g2])

            # Add source
            source = DataSourceModel(
                source_code="ecuhockey",
                name="ECU Official",
                source_url="https://www.ecuhockey.com",
                source_type="primary_sot",
                priority_order=1,
                is_active=True,
                last_scraped_at=datetime(2026, 9, 8, 12, 0, tzinfo=UTC),
            )
            session.add(source)

            # Add audit
            audit = SyncAuditModel(
                sync_cycle_id="sync-test-123",
                status="SUCCESS",
                started_at=datetime(2026, 9, 8, 12, 0, tzinfo=UTC),
                completed_at=datetime(2026, 9, 8, 12, 1, tzinfo=UTC),
                duration_ms=60000,
                games_created=2,
                games_updated=0,
                games_deleted=0,
                conflicts_detected=0,
            )
            session.add(audit)

        result = runner.invoke(
            status_command,
            ["--db-url", db_url, "--season", "2026-2027"],
        )
        assert result.exit_code == 0
        assert "sync-test-123" in result.output
        assert "SUCCESS" in result.output
        assert "ECU Official" in result.output
        assert "Total Fixtures" in result.output

    def test_status_db_error(self, runner: CliRunner) -> None:
        """Verify status command handles database error."""
        result = runner.invoke(
            status_command,
            ["--db-url", "sqlite:////invalid/path/db.sqlite"],
        )
        assert result.exit_code != 0

    def test_status_upcoming_away_game(self, runner: CliRunner, db_url: str) -> None:
        """Verify status command formatting when next fixture is an away match."""
        engine = create_sync_engine(db_url)
        with get_sync_session(engine) as session:
            ecu = TeamModel(
                name="East Carolina University",
                city="Greenville",
                state="NC",
            )
            ncsu = TeamModel(name="NC State", city="Raleigh", state="NC")
            session.add_all([ecu, ncsu])
            session.flush()

            future_dt = datetime.now(UTC) + timedelta(days=5)
            game = GameModel(
                game_id="game-future-away",
                home_team_id=ncsu.id,
                away_team_id=ecu.id,
                start_time=future_dt,
                venue="Invisalign Arena",
                status="SCHEDULED",
                season="2026-2027",
            )
            session.add(game)

        result = runner.invoke(
            status_command,
            ["--db-url", db_url, "--season", "2026-2027"],
        )
        assert result.exit_code == 0
        assert "AWAY FIXTURE" in result.output
        assert "Tickets:" not in result.output

    def test_status_helpers(self) -> None:
        """Verify status helper functions directly."""
        ecu = Team(name="East Carolina University", city="Greenville", state="NC")
        opp = Team(name="NC State", city="Raleigh", state="NC")
        past_game = Game(
            game_id="g-past",
            home_team=ecu,
            away_team=opp,
            start_time=datetime(2020, 1, 1, 19, 0, tzinfo=UTC),
            venue="Arena",
            result=GameResult.WIN,
        )
        fut_game = Game(
            game_id="g-fut",
            home_team=ecu,
            away_team=opp,
            start_time=datetime(2030, 1, 1, 19, 0, tzinfo=UTC),
            venue="Arena",
            result=GameResult.SCHEDULED,
        )
        cancelled_game = Game(
            game_id="g-can",
            home_team=ecu,
            away_team=opp,
            start_time=datetime(2030, 2, 1, 19, 0, tzinfo=UTC),
            venue="Arena",
            result=GameResult.CANCELLED,
        )
        postponed_game = Game(
            game_id="g-post",
            home_team=ecu,
            away_team=opp,
            start_time=datetime(2030, 3, 1, 19, 0, tzinfo=UTC),
            venue="Arena",
            result=GameResult.POSTPONED,
        )
        loss_game = Game(
            game_id="g-loss",
            home_team=opp,
            away_team=ecu,
            start_time=datetime(2020, 2, 1, 19, 0, tzinfo=UTC),
            venue="Arena",
            result=GameResult.LOSS,
        )
        tie_game = Game(
            game_id="g-tie",
            home_team=ecu,
            away_team=opp,
            start_time=datetime(2020, 3, 1, 19, 0, tzinfo=UTC),
            venue="Arena",
            result=GameResult.TIE,
        )

        stats = _compute_schedule_stats(
            [
                past_game,
                fut_game,
                cancelled_game,
                postponed_game,
                loss_game,
                tie_game,
            ],
        )
        assert stats["total"] == 6
        assert stats["wins"] == 1
        assert stats["losses"] == 1
        assert stats["ties"] == 1
        assert stats["cancelled"] == 1
        assert stats["postponed"] == 1
        assert stats["next_game"] == fut_game

        panel_next = _render_next_game_panel(fut_game)
        assert "NC State" in str(panel_next.renderable)

        panel_none = _render_next_game_panel(None)
        assert "No future games" in str(panel_none.renderable)


class TestExportCommand:
    """Tests for 'ecu-hockey export' command."""

    def test_export_detect_format(self) -> None:
        """Verify format detection from option and file extension."""
        assert _detect_format("json", None) == "json"
        assert _detect_format("html", None) == "html"
        assert _detect_format("pdf", None) == "pdf"
        assert _detect_format(None, "sched.csv") == "csv"
        assert _detect_format(None, "sched.json") == "json"
        assert _detect_format(None, "sched.ics") == "ics"
        assert _detect_format(None, "sched.html") == "html"
        assert _detect_format(None, "sched.pdf") == "pdf"
        assert _detect_format(None, None, embed=True) == "html"
        assert _detect_format(None, "sched.txt") == "ics"

    def test_export_pdf_stdout(self, runner: CliRunner, db_url: str) -> None:
        """Verify export command outputs binary PDF to stdout."""
        result = runner.invoke(export_command, ["-f", "pdf", "--db-url", db_url])
        assert result.exit_code == 0
        assert b"%PDF-1." in result.stdout_bytes

    def test_export_ics_stdout(self, runner: CliRunner, db_url: str) -> None:
        """Verify export command outputs valid iCalendar to stdout."""
        result = runner.invoke(export_command, ["-f", "ics", "--db-url", db_url])
        assert result.exit_code == 0
        assert "BEGIN:VCALENDAR" in result.output
        assert "END:VCALENDAR" in result.output

    def test_export_json_stdout(self, runner: CliRunner, db_url: str) -> None:
        """Verify export command outputs JSON to stdout."""
        result = runner.invoke(export_command, ["-f", "json", "--db-url", db_url])
        assert result.exit_code == 0
        assert '"primary_team": "East Carolina University"' in result.output

    def test_export_csv_stdout(self, runner: CliRunner, db_url: str) -> None:
        """Verify export command outputs CSV to stdout."""
        result = runner.invoke(export_command, ["-f", "csv", "--db-url", db_url])
        assert result.exit_code == 0
        assert "game_id,season,date" in result.output

    def test_export_html_stdout(self, runner: CliRunner, db_url: str) -> None:
        """Verify export command outputs HTML to stdout."""
        result = runner.invoke(export_command, ["-f", "html", "--db-url", db_url])
        assert result.exit_code == 0
        assert "<!DOCTYPE html>" in result.output
        assert "East Carolina University Men's Ice Hockey" in result.output

    def test_export_html_embed_stdout(self, runner: CliRunner, db_url: str) -> None:
        """Verify export command with --embed outputs widget HTML to stdout."""
        result = runner.invoke(
            export_command,
            ["--embed", "-f", "html", "--db-url", db_url],
        )
        assert result.exit_code == 0
        assert "embed-mode" in result.output
        assert '<header class="site-header">' not in result.output

    def test_export_html_to_file(
        self,
        runner: CliRunner,
        db_url: str,
        tmp_path: Path,
    ) -> None:
        """Verify export command auto-detects HTML and writes to file."""
        out_file = tmp_path / "schedule.html"
        result = runner.invoke(
            export_command,
            ["-o", str(out_file), "--db-url", db_url],
        )
        assert result.exit_code == 0
        assert "Export Successful" in result.output
        assert out_file.is_file()
        assert "<!DOCTYPE html>" in out_file.read_text(encoding="utf-8")

    def test_export_html_embed_to_file(
        self,
        runner: CliRunner,
        db_url: str,
        tmp_path: Path,
    ) -> None:
        """Verify export command with --embed writes embed view to file."""
        out_file = tmp_path / "embed_schedule.html"
        result = runner.invoke(
            export_command,
            ["--embed", "-o", str(out_file), "--db-url", db_url],
        )
        assert result.exit_code == 0
        assert "HTML (EMBED)" in result.output
        assert out_file.is_file()
        assert "embed-mode" in out_file.read_text(encoding="utf-8")

    def test_export_to_file(
        self,
        runner: CliRunner,
        db_url: str,
        tmp_path: Path,
    ) -> None:
        """Verify export command writes to specified output file."""
        out_file = tmp_path / "subdir" / "schedule.json"
        result = runner.invoke(
            export_command,
            ["-o", str(out_file), "--db-url", db_url],
        )
        assert result.exit_code == 0
        assert "Export Successful" in result.output
        assert out_file.is_file()
        assert '"primary_team"' in out_file.read_text(encoding="utf-8")

    def test_export_filters(
        self,
        runner: CliRunner,
        db_url: str,
        tmp_path: Path,
    ) -> None:
        """Verify export filtering parameters."""
        out_file = tmp_path / "schedule.csv"
        result = runner.invoke(
            export_command,
            [
                "-o",
                str(out_file),
                "--db-url",
                db_url,
                "--season",
                "2026-2027",
                "--opponent",
                "UNC",
                "--home-only",
                "--status",
                "scheduled",
            ],
        )
        assert result.exit_code == 0
        assert out_file.is_file()

    def test_export_db_error(self, runner: CliRunner) -> None:
        """Verify export handles database failures."""
        result = runner.invoke(
            export_command,
            ["--db-url", "sqlite:////invalid/db.sqlite"],
        )
        assert result.exit_code != 0

    def test_export_os_error(self, runner: CliRunner, db_url: str) -> None:
        """Verify export handles file write failures."""
        with patch("pathlib.Path.write_text", side_effect=OSError("Permission denied")):
            result = runner.invoke(
                export_command,
                ["-o", "/root/forbidden.ics", "--db-url", db_url],
            )
            assert result.exit_code != 0

    def test_export_pdf_to_file(
        self,
        runner: CliRunner,
        db_url: str,
        tmp_path: Path,
    ) -> None:
        """Verify export command auto-detects PDF and writes binary file."""
        out_file = tmp_path / "schedule.pdf"
        result = runner.invoke(
            export_command,
            ["-o", str(out_file), "--home-only", "--db-url", db_url],
        )
        assert result.exit_code == 0
        assert out_file.is_file()
        assert out_file.read_bytes().startswith(b"%PDF-1.")

    def test_export_pdf_os_error(self, runner: CliRunner, db_url: str) -> None:
        """Verify export handles binary file write failures."""
        with patch("pathlib.Path.write_bytes", side_effect=OSError("Disk full")):
            result = runner.invoke(
                export_command,
                ["-f", "pdf", "-o", "/forbidden/schedule.pdf", "--db-url", db_url],
            )
            assert result.exit_code != 0

    def test_export_from_populated_db(self, runner: CliRunner, db_url: str) -> None:
        """Verify export reads from database when games exist."""
        engine = create_sync_engine(db_url)
        with get_sync_session(engine) as session:
            ecu = TeamModel(
                name="East Carolina University",
                city="Greenville",
                state="NC",
            )
            unc = TeamModel(name="UNC Chapel Hill", city="Chapel Hill", state="NC")
            session.add_all([ecu, unc])
            session.flush()
            game = GameModel(
                game_id="game-exp-1",
                home_team_id=ecu.id,
                away_team_id=unc.id,
                start_time=datetime(2026, 11, 10, 19, 0, tzinfo=UTC),
                venue="The Factory Ice House",
                status="SCHEDULED",
                season="2026-2027",
            )
            session.add(game)

        result = runner.invoke(
            export_command,
            ["-f", "json", "--season", "2026-2027", "--db-url", db_url],
        )
        assert result.exit_code == 0
        assert "UNC Chapel Hill" in result.output


class TestConflictsCommand:
    """Tests for 'ecu-hockey conflicts' command."""

    def test_conflicts_clean(self, runner: CliRunner, db_url: str) -> None:
        """Verify conflicts command when no discrepancies exist."""
        result = runner.invoke(conflicts_command, ["--db-url", db_url])
        assert result.exit_code == 0
        assert "Conflict Status Clean" in result.output
        assert "No active schedule conflicts or discrepancies found" in result.output

    def test_conflicts_detected(self, runner: CliRunner, db_url: str) -> None:
        """Verify conflicts table rendering when discrepancies exist."""
        engine = create_sync_engine(db_url)
        with get_sync_session(engine) as session:
            audit = SyncAuditModel(
                sync_cycle_id="sync-test",
                status="SUCCESS",
            )
            session.add(audit)
            session.flush()

            change1 = GameChangeModel(
                sync_cycle_id="sync-test",
                sync_audit_id=audit.id,
                canonical_game_id="game-101",
                change_type="CONFLICT",
                summary="Conflicting venue: factory vs wcc",
                field_diffs=[
                    {
                        "field": "venue",
                        "severity": "HIGH",
                        "requires_review": True,
                        "old_value": "The Factory",
                        "new_value": "Wake Competition Center",
                    },
                ],
                recorded_at=datetime(2026, 9, 8, 12, 0, tzinfo=UTC),
            )
            change2 = GameChangeModel(
                sync_cycle_id="sync-test",
                sync_audit_id=audit.id,
                canonical_game_id="game-102",
                change_type="DISCREPANCY",
                summary="Time discrepancy: 19:00 vs 20:00",
                field_diffs=[
                    {
                        "field": "start_time",
                        "severity": "LOW",
                        "requires_review": False,
                        "old_value": "19:00",
                        "new_value": "20:00",
                    },
                ],
                recorded_at=datetime(2026, 9, 8, 12, 0, tzinfo=UTC),
            )
            change3 = GameChangeModel(
                sync_cycle_id="sync-test",
                sync_audit_id=audit.id,
                canonical_game_id="game-103",
                change_type="CONFLICT",
                summary="Diffs-empty discrepancy",
                field_diffs=[],
                recorded_at=datetime(2026, 9, 8, 12, 0, tzinfo=UTC),
            )
            session.add_all([change1, change2, change3])

        # Test listing all conflicts
        result = runner.invoke(conflicts_command, ["--db-url", db_url])
        assert result.exit_code == 0
        assert "Active Schedule Discrepancies (3 found)" in result.output
        assert "game-101" in result.output
        assert "game-102" in result.output
        assert "game-103" in result.output

        # Test filter by severity
        res_sev = runner.invoke(
            conflicts_command,
            ["--db-url", db_url, "--severity", "HIGH"],
        )
        assert res_sev.exit_code == 0
        assert "game-101" in res_sev.output
        assert "game-102" not in res_sev.output

        # Test filter by game-id
        res_gid = runner.invoke(
            conflicts_command,
            ["--db-url", db_url, "--game-id", "game-102"],
        )
        assert res_gid.exit_code == 0
        assert "game-102" in res_gid.output
        assert "game-101" not in res_gid.output

        # Test filter by field
        res_field = runner.invoke(
            conflicts_command,
            ["--db-url", db_url, "--field", "venue"],
        )
        assert res_field.exit_code == 0
        assert "game-101" in res_field.output
        assert "game-102" not in res_field.output

        # Test filter review-only
        res_rev = runner.invoke(
            conflicts_command,
            ["--db-url", db_url, "--review-only"],
        )
        assert res_rev.exit_code == 0
        assert "game-101" in res_rev.output
        assert "game-102" not in res_rev.output

    def test_conflicts_filter_helper(self) -> None:
        """Verify _matches_filter logic directly."""
        item = {
            "severity": "HIGH",
            "game_id": "g-1",
            "field": "venue",
            "requires_review": True,
        }
        assert _matches_filter(
            item,
            severity="HIGH",
            game_id="g-1",
            field_name="venue",
            review_only=True,
        )
        assert not _matches_filter(
            item,
            severity="LOW",
            game_id="g-1",
            field_name="venue",
            review_only=False,
        )
        assert not _matches_filter(
            item,
            severity="HIGH",
            game_id="g-2",
            field_name="venue",
            review_only=False,
        )
        assert not _matches_filter(
            item,
            severity="HIGH",
            game_id="g-1",
            field_name="date",
            review_only=False,
        )
        item_no_rev = dict(item, requires_review=False)
        assert not _matches_filter(
            item_no_rev,
            severity="HIGH",
            game_id="g-1",
            field_name="venue",
            review_only=True,
        )

    def test_conflicts_db_error(self, runner: CliRunner) -> None:
        """Verify conflicts handles database errors."""
        result = runner.invoke(
            conflicts_command,
            ["--db-url", "sqlite:////invalid/db.sqlite"],
        )
        assert result.exit_code != 0


class TestServeCommand:
    """Tests for 'ecu-hockey serve' command."""

    def test_serve_command_invocation(self, runner: CliRunner) -> None:
        """Verify serve command prints banner and calls run_server."""
        with (
            patch("ecu_hockey_calendar.cli.serve.run_server") as mock_run,
            patch.dict(os.environ, {}, clear=True),
        ):
            result = runner.invoke(
                serve_command,
                [
                    "--host",
                    "0.0.0.0",
                    "--port",
                    "9000",
                    "--reload",
                    "--db-url",
                    "sqlite:///custom.db",
                ],
            )
            assert result.exit_code == 0
            assert "Local Server Running at http://0.0.0.0:9000" in result.output
            assert "http://0.0.0.0:9000/calendar.ics" in result.output
            mock_run.assert_called_once_with(
                host="0.0.0.0",
                port=9000,
                reload=True,
            )

    def test_serve_command_default_no_db_url(self, runner: CliRunner) -> None:
        """Verify serve command with default parameters and no db-url."""
        with (
            patch("ecu_hockey_calendar.cli.serve.run_server") as mock_run,
            patch.dict(os.environ, {}, clear=True),
        ):
            result = runner.invoke(serve_command, [])
            assert result.exit_code == 0
            mock_run.assert_called_once_with(host="127.0.0.1", port=8000, reload=False)

    def test_serve_command_with_migrate_success(self, runner: CliRunner) -> None:
        """Verify serve command with --migrate executes run_migrations_upgrade."""
        with (
            patch("ecu_hockey_calendar.cli.serve.run_server") as mock_run,
            patch(
                "ecu_hockey_calendar.cli.serve.run_migrations_upgrade",
            ) as mock_migrate,
            patch.dict(os.environ, {}, clear=True),
        ):
            result = runner.invoke(
                serve_command,
                ["--migrate", "--db-url", "sqlite:///test.db"],
            )
            assert result.exit_code == 0
            mock_migrate.assert_called_once_with(database_url="sqlite:///test.db")
            mock_run.assert_called_once_with(host="127.0.0.1", port=8000, reload=False)
            assert "Applying database schema migrations" in result.output
            assert "Schema migrations applied successfully." in result.output

    def test_serve_command_with_migrate_failure(self, runner: CliRunner) -> None:
        """Verify serve aborts and does not start server when migration fails."""
        with (
            patch("ecu_hockey_calendar.cli.serve.run_server") as mock_run,
            patch(
                "ecu_hockey_calendar.cli.serve.run_migrations_upgrade",
                side_effect=RuntimeError("Alembic migration failed to connect"),
            ) as mock_migrate,
            patch.dict(os.environ, {}, clear=True),
        ):
            result = runner.invoke(serve_command, ["--migrate"])
            assert result.exit_code != 0
            mock_migrate.assert_called_once_with(database_url=None)
            mock_run.assert_not_called()
            assert "Alembic migration failed to connect" in result.output

    def test_serve_command_auto_migrate_envvar(self, runner: CliRunner) -> None:
        """Verify AUTO_MIGRATE=true environment variable triggers migrations."""
        with (
            patch("ecu_hockey_calendar.cli.serve.run_server") as mock_run,
            patch(
                "ecu_hockey_calendar.cli.serve.run_migrations_upgrade",
            ) as mock_migrate,
            patch.dict(os.environ, {"AUTO_MIGRATE": "true"}, clear=True),
        ):
            result = runner.invoke(serve_command, [])
            assert result.exit_code == 0
            mock_migrate.assert_called_once_with(database_url=None)
            mock_run.assert_called_once()
            assert "Schema migrations applied successfully." in result.output

    def test_serve_command_auto_migrate_disabled_envvar(
        self,
        runner: CliRunner,
    ) -> None:
        """Verify AUTO_MIGRATE=false environment variable skips migrations."""
        with (
            patch("ecu_hockey_calendar.cli.serve.run_server") as mock_run,
            patch(
                "ecu_hockey_calendar.cli.serve.run_migrations_upgrade",
            ) as mock_migrate,
            patch.dict(os.environ, {"AUTO_MIGRATE": "false"}, clear=True),
        ):
            result = runner.invoke(serve_command, [])
            assert result.exit_code == 0
            mock_migrate.assert_not_called()
            mock_run.assert_called_once()


class TestSyncCommand:
    """Tests for 'ecu-hockey sync' command."""

    def test_convert_parsed_record(self) -> None:
        """Verify _convert_parsed_to_source_record converts record fields."""
        rec = ParsedGameRecord(
            game_id="parsed-1",
            opponent_name="Wake Forest",
            is_home=True,
            start_time=datetime(2026, 11, 1, 19, 0, tzinfo=UTC),
            venue="The Factory",
            status=GameStatus.FINAL,
            home_score=5,
            away_score=2,
            metadata={"test_key": "val"},
        )
        src = _convert_parsed_to_source_record(
            rec,
            DataSourceType.PRIMARY_SOT,
            "ecuhockey",
        )
        assert src.game_id == "parsed-1"
        assert src.opponent_name == "Wake Forest"
        assert src.result == GameResult.WIN
        assert src.metadata == {"test_key": "val"}

        # Without score
        rec_no_score = ParsedGameRecord(
            game_id="parsed-2",
            opponent_name="Duke",
            is_home=False,
            start_time=datetime(2026, 11, 2, 19, 0, tzinfo=UTC),
            venue="WCC",
        )
        src2 = _convert_parsed_to_source_record(
            rec_no_score,
            DataSourceType.LEAGUE,
            "acchockey",
        )
        assert src2.result is None

    def test_sync_dry_run(self, runner: CliRunner, db_url: str) -> None:
        """Verify sync with --dry-run does not persist changes to database."""
        mock_rec = ParsedGameRecord(
            game_id="game-dry-1",
            opponent_name="Richmond",
            is_home=True,
            start_time=datetime(2026, 10, 20, 19, 0, tzinfo=UTC),
            venue="The Factory",
        )

        with patch(
            "ecu_hockey_calendar.cli.sync.ECUHockeyCrawler.crawl",
            new_callable=AsyncMock,
            return_value=([mock_rec], "<html></html>", "hash1", "text/html"),
        ):
            result = runner.invoke(
                sync_command,
                ["--dry-run", "--source", "ecuhockey", "--db-url", db_url],
            )
            assert result.exit_code == 0
            assert "DRY RUN" in result.output
            assert (
                "Dry run completed: Changes detected above were NOT committed"
                in result.output
            )

            # Check DB has no games persisted
            engine = create_sync_engine(db_url)
            with get_sync_session(engine) as session:
                games = session.scalars(select(GameModel)).all()
                assert len(games) == 0

    def test_sync_live_run(self, runner: CliRunner, db_url: str) -> None:
        """Verify sync in live mode commits fixtures and audit to database."""
        rec1 = ParsedGameRecord(
            game_id="game-live-1",
            opponent_name="UNC Wilmington",
            is_home=True,
            start_time=datetime(2026, 10, 25, 19, 0, tzinfo=UTC),
            venue="The Factory Ice House",
        )
        rec2 = ParsedGameRecord(
            game_id="game-live-2",
            opponent_name="Virginia Tech",
            is_home=False,
            start_time=datetime(2026, 10, 30, 20, 0, tzinfo=UTC),
            venue="Lancerlot Sports Complex",
        )

        with (
            patch(
                "ecu_hockey_calendar.cli.sync.ECUHockeyCrawler.crawl",
                new_callable=AsyncMock,
                return_value=([rec1], "<html></html>", "hash1", "text/html"),
            ),
            patch(
                "ecu_hockey_calendar.cli.sync.ACCHockeyCrawler.crawl",
                new_callable=AsyncMock,
                return_value=([rec2], "<html></html>", "hash2", "text/html"),
            ),
        ):
            result = runner.invoke(
                sync_command,
                ["--source", "all", "--db-url", db_url],
            )
            assert result.exit_code == 0
            assert "Schedule synchronization completed successfully" in result.output

            # Verify games committed to DB
            engine = create_sync_engine(db_url)
            with get_sync_session(engine) as session:
                games = session.scalars(select(GameModel)).all()
                assert len(games) == 2
                audits = session.scalars(select(SyncAuditModel)).all()
                assert len(audits) == 1
                assert audits[0].status == "SUCCESS"

    def test_sync_crawler_failure_resilience(
        self,
        runner: CliRunner,
        db_url: str,
    ) -> None:
        """Verify sync gracefully handles crawler failure and continues."""
        with (
            patch(
                "ecu_hockey_calendar.cli.sync.ECUHockeyCrawler.crawl",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Connection timeout"),
            ),
            patch(
                "ecu_hockey_calendar.cli.sync.ACCHockeyCrawler.crawl",
                new_callable=AsyncMock,
                return_value=([], "", "hash", "text/html"),
            ),
        ):
            result = runner.invoke(
                sync_command,
                ["--source", "all", "--db-url", db_url],
            )
            assert result.exit_code == 0
            assert "FAILED" in result.output

    def test_sync_with_notifications(self, runner: CliRunner, db_url: str) -> None:
        """Verify --notify triggers notification dispatcher."""
        rec = ParsedGameRecord(
            game_id="game-notify-1",
            opponent_name="Georgetown",
            is_home=True,
            start_time=datetime(2026, 11, 5, 19, 0, tzinfo=UTC),
            venue="The Factory",
        )
        with (
            patch(
                "ecu_hockey_calendar.cli.sync.ECUHockeyCrawler.crawl",
                new_callable=AsyncMock,
                return_value=([rec], "", "", ""),
            ),
            patch(
                "ecu_hockey_calendar.cli.sync.NotificationDispatcher.dispatch_cycle",
            ) as mock_dispatch,
        ):
            result = runner.invoke(
                sync_command,
                ["--source", "ecuhockey", "--notify", "--db-url", db_url],
            )
            assert result.exit_code == 0
            mock_dispatch.assert_called_once()

    def test_sync_fatal_pipeline_error(self, runner: CliRunner) -> None:
        """Verify sync handles fatal pipeline exceptions."""
        result = runner.invoke(
            sync_command,
            ["--db-url", "sqlite:////invalid/fatal/db.sqlite"],
        )
        assert result.exit_code != 0

    def test_sync_update_existing_records_and_season(
        self,
        runner: CliRunner,
        db_url: str,
    ) -> None:
        """Verify sync updates existing records on repeated sync."""
        rec1 = ParsedGameRecord(
            game_id="game-sync-update",
            opponent_name="Liberty University",
            is_home=True,
            start_time=datetime(2026, 11, 1, 19, 0, tzinfo=UTC),
            venue="The Factory",
        )
        with patch(
            "ecu_hockey_calendar.cli.sync.ECUHockeyCrawler.crawl",
            new_callable=AsyncMock,
            return_value=([rec1], "", "", ""),
        ):
            # First sync creates records
            res1 = runner.invoke(
                sync_command,
                ["--source", "ecuhockey", "--season", "2026-2027", "--db-url", db_url],
            )
            assert res1.exit_code == 0

            # Second sync updates records
            res2 = runner.invoke(
                sync_command,
                ["--source", "ecuhockey", "--season", "2026-2027", "--db-url", db_url],
            )
            assert res2.exit_code == 0
            assert "Schedule synchronization completed successfully" in res2.output

    def test_sync_acchockey_source_only_and_failure(
        self,
        runner: CliRunner,
        db_url: str,
    ) -> None:
        """Verify sync with --source acchockey and crawler failure handling."""
        rec = ParsedGameRecord(
            game_id="game-acc-only",
            opponent_name="Duke",
            is_home=False,
            start_time=datetime(2026, 12, 1, 20, 0, tzinfo=UTC),
            venue="Orange County Sportsplex",
        )
        with patch(
            "ecu_hockey_calendar.cli.sync.ACCHockeyCrawler.crawl",
            new_callable=AsyncMock,
            return_value=([rec], "", "", ""),
        ):
            res = runner.invoke(
                sync_command,
                ["--source", "acchockey", "--db-url", db_url],
            )
            assert res.exit_code == 0
            assert "ACC Hockey League" in res.output

        with patch(
            "ecu_hockey_calendar.cli.sync.ACCHockeyCrawler.crawl",
            new_callable=AsyncMock,
            side_effect=ConnectionResetError("Reset by peer"),
        ):
            res_fail = runner.invoke(
                sync_command,
                ["--source", "acchockey", "--db-url", db_url],
            )
            assert res_fail.exit_code == 0
            assert "RESET BY PEER" in res_fail.output

    def test_ensure_data_source_explicit_url(self, db_url: str) -> None:
        """Verify _ensure_data_source retains explicit source_url."""
        engine = create_sync_engine(db_url)
        with get_sync_session(engine) as session:
            src = _ensure_data_source(
                session,
                "custom",
                "Custom Source",
                DataSourceType.PRIMARY_SOT,
                source_url="https://custom.com",
            )
            assert src.source_url == "https://custom.com"
