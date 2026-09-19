"""Tests for CLI remote API operations across all operational subcommands.

Validates that 'status', 'conflicts', 'export', and 'sync' interact with remote
HTTP API endpoints when --api-url is provided, with full coverage for both
success and failure paths.
"""

# pylint: disable=too-many-lines

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from ecu_hockey_calendar.api.client import (
    RemoteApiAuthError,
    RemoteApiError,
    RemoteSyncAudit,
)
from ecu_hockey_calendar.cli.main import cli
from ecu_hockey_calendar.cli.production import DEFAULT_PROD_API_URL
from ecu_hockey_calendar.models import Game, GameResult, Team
from ecu_hockey_calendar.storage.models import SyncStatus

if TYPE_CHECKING:
    from pathlib import Path

TOKEN_FLAG = "--" + "token"
MOCK_TOKEN = "mock-cli-token"


@pytest.fixture
def runner() -> CliRunner:
    """Provide a Click test runner fixture."""
    return CliRunner()


@pytest.fixture
def sample_game() -> Game:
    """Provide a sample domain Game fixture."""
    return Game(
        game_id="game-1",
        home_team=Team(name="East Carolina University", city="Greenville", state="NC"),
        away_team=Team(name="UNC Chapel Hill", city="Chapel Hill", state="NC"),
        start_time=datetime(2026, 10, 15, 20, 0, tzinfo=UTC),
        venue="The Factory Ice House",
        result=GameResult.SCHEDULED,
    )


class TestCliRemoteStatus:
    """Tests for 'ecu-hockey status --api-url' remote command execution."""

    def test_status_remote_success_subcommand_flag(
        self,
        runner: CliRunner,
        sample_game: Game,
    ) -> None:
        """Verify status command fetches remote telemetry and renders output."""
        audit = RemoteSyncAudit(
            sync_cycle_id="sync-123",
            status=SyncStatus.SUCCESS,
            started_at=datetime(2026, 9, 14, 8, 0, tzinfo=UTC),
            duration_ms=450,
        )
        telemetry = {
            "total_cycles": 5,
            "last_success_at": datetime(2026, 9, 14, 8, 0, tzinfo=UTC),
            "latest_audit": audit,
            "status": "idle",
        }
        sources = [
            {
                "source_code": "ecuhockey",
                "name": "Official Team Site",
                "source_type": "primary_sot",
                "is_active": True,
                "last_scraped_at": datetime(2026, 9, 14, 8, 0, tzinfo=UTC),
            },
        ]

        mock_client = MagicMock()
        mock_client.get_status_data.return_value = (telemetry, sources, [sample_game])

        with patch(
            "ecu_hockey_calendar.cli.status.RemoteApiClient",
            return_value=mock_client,
        ) as mock_cls:
            result = runner.invoke(
                cli,
                [
                    "status",
                    "--api-url",
                    "https://ecu-hockey-api.onrender.com",
                    TOKEN_FLAG,
                    MOCK_TOKEN,
                    "--season",
                    "2026-2027",
                ],
            )
            assert result.exit_code == 0
            mock_cls.assert_called_once_with(
                "https://ecu-hockey-api.onrender.com",
                token=MOCK_TOKEN,
            )
            mock_client.get_status_data.assert_called_once_with(season="2026-2027")
            assert "SYSTEM STATUS & SCHEDULE DIAGNOSTICS" in result.output
            assert "Remote API (https://ecu-hockey-api.onrender.com)" in result.output
            assert "Official Team Site" in result.output
            assert "Schedule Overview" in result.output

    def test_status_remote_success_root_flag(
        self,
        runner: CliRunner,
    ) -> None:
        """Verify status honors --api-url and token option passed before subcommand."""
        mock_client = MagicMock()
        mock_client.get_status_data.return_value = (
            {
                "total_cycles": 1,
                "last_success_at": None,
                "latest_audit": None,
                "status": "idle",
            },
            [],
            [],
        )

        with patch(
            "ecu_hockey_calendar.cli.status.RemoteApiClient",
            return_value=mock_client,
        ) as mock_cls:
            result = runner.invoke(
                cli,
                [
                    "--api-url",
                    "https://remote.api",
                    TOKEN_FLAG,
                    MOCK_TOKEN,
                    "status",
                ],
            )
            assert result.exit_code == 0
            mock_cls.assert_called_once_with("https://remote.api", token=MOCK_TOKEN)

    def test_status_remote_error(self, runner: CliRunner) -> None:
        """Verify RemoteApiError in status command produces click exception."""
        mock_client = MagicMock()
        mock_client.get_status_data.side_effect = RemoteApiError("Connection failed")

        with patch(
            "ecu_hockey_calendar.cli.status.RemoteApiClient",
            return_value=mock_client,
        ):
            result = runner.invoke(
                cli,
                ["status", "--api-url", "https://remote.api"],
            )
            assert result.exit_code != 0
            assert "Failed to query status from remote API" in result.output


class TestCliRemoteConflicts:
    """Tests for 'ecu-hockey conflicts --api-url' remote command execution."""

    def test_conflicts_remote_clean(self, runner: CliRunner) -> None:
        """Verify clean conflict status display when no discrepancies exist."""
        mock_client = MagicMock()
        mock_client.get_conflicts.return_value = {"conflicts": []}

        with patch(
            "ecu_hockey_calendar.cli.conflicts.RemoteApiClient",
            return_value=mock_client,
        ) as mock_cls:
            result = runner.invoke(
                cli,
                [
                    "conflicts",
                    "--api-url",
                    "https://remote.api",
                    TOKEN_FLAG,
                    MOCK_TOKEN,
                ],
            )
            assert result.exit_code == 0
            mock_cls.assert_called_once_with("https://remote.api", token=MOCK_TOKEN)
            assert "Target: Remote API (https://remote.api)" in result.output
            assert "Conflict Status Clean" in result.output
            assert (
                "No active schedule conflicts or discrepancies found" in result.output
            )

    def test_conflicts_remote_with_items_and_filters(self, runner: CliRunner) -> None:
        """Verify conflict rendering and filter arguments passing."""
        mock_client = MagicMock()
        mock_client.get_conflicts.return_value = {
            "conflicts": [
                {
                    "conflict_id": "c-1",
                    "game_id": "g-1",
                    "field": "start_time",
                    "severity": "CRITICAL",
                    "requires_review": True,
                    "summary": "Start time mismatch",
                    "candidates": [
                        {"source_code": "ecuhockey", "value": "20:00"},
                        {"source_code": "acchockey", "value": "21:00"},
                    ],
                },
            ],
        }

        with patch(
            "ecu_hockey_calendar.cli.conflicts.RemoteApiClient",
            return_value=mock_client,
        ):
            result = runner.invoke(
                cli,
                [
                    "--api-url",
                    "https://remote.api",
                    "conflicts",
                    "--severity",
                    "CRITICAL",
                    "--game-id",
                    "g-1",
                    "--field",
                    "start_time",
                    "--review-only",
                ],
            )
            assert result.exit_code == 0
            mock_client.get_conflicts.assert_called_once_with(
                severity="CRITICAL",
                game_id="g-1",
                field_name="start_time",
                review_only=True,
                limit=None,
                offset=0,
            )
            assert "Target: Remote API (https://remote.api)" in result.output
            assert "start_time" in result.output
            assert "CRITICAL" in result.output
            assert "Start time" in result.output

    def test_conflicts_remote_auth_error(self, runner: CliRunner) -> None:
        """Verify RemoteApiAuthError produces clear token advice."""
        mock_client = MagicMock()
        mock_client.get_conflicts.side_effect = RemoteApiAuthError("Unauthorized (401)")

        with patch(
            "ecu_hockey_calendar.cli.conflicts.RemoteApiClient",
            return_value=mock_client,
        ):
            result = runner.invoke(
                cli,
                ["conflicts", "--api-url", "https://remote.api"],
            )
            assert result.exit_code != 0
            assert "Target: Remote API (https://remote.api)" in result.output
            assert "Authentication required" in result.output
            assert "ECU_HOCKEY_ADMIN_TOKEN" in result.output

    def test_conflicts_remote_generic_error(self, runner: CliRunner) -> None:
        """Verify generic RemoteApiError produces click exception."""
        mock_client = MagicMock()
        mock_client.get_conflicts.side_effect = RemoteApiError("Gateway timeout")

        with patch(
            "ecu_hockey_calendar.cli.conflicts.RemoteApiClient",
            return_value=mock_client,
        ):
            result = runner.invoke(
                cli,
                ["conflicts", "--api-url", "https://remote.api"],
            )
            assert result.exit_code != 0
            assert "Target: Remote API (https://remote.api)" in result.output
            assert "Failed to query conflicts from remote API" in result.output

    def test_conflicts_remote_pagination_and_json(self, runner: CliRunner) -> None:
        """Verify remote conflicts pagination parameters and JSON output formatting."""
        mock_client = MagicMock()
        mock_client.get_conflicts.return_value = {
            "total_conflicts": 10,
            "filtered_count": 1,
            "limit": 2,
            "offset": 4,
            "conflicts": [
                {
                    "conflict_id": "c-1",
                    "game_id": "g-1",
                    "field": "start_time",
                    "severity": "CRITICAL",
                    "requires_review": True,
                    "summary": "Start time mismatch",
                    "recorded_at": "2026-10-01T12:00:00Z",
                },
            ],
        }

        with patch(
            "ecu_hockey_calendar.cli.conflicts.RemoteApiClient",
            return_value=mock_client,
        ):
            res_json = runner.invoke(
                cli,
                [
                    "conflicts",
                    "--api-url",
                    "https://remote.api",
                    "--limit",
                    "2",
                    "--offset",
                    "4",
                    "--json",
                ],
            )
            assert res_json.exit_code == 0
            assert '"total_conflicts": 10' in res_json.output
            mock_client.get_conflicts.assert_called_with(
                severity=None,
                game_id=None,
                field_name=None,
                review_only=False,
                limit=2,
                offset=4,
            )

            res_table = runner.invoke(
                cli,
                [
                    "conflicts",
                    "--api-url",
                    "https://remote.api",
                    "--limit",
                    "2",
                    "--offset",
                    "4",
                ],
            )
            assert res_table.exit_code == 0
            assert "1 of 10 (offset: 4)" in res_table.output

    def test_conflicts_remote_requires_review(self, runner: CliRunner) -> None:
        """Verify --requires-review flag passes review_only=True to remote client."""
        mock_client = MagicMock()
        mock_client.get_conflicts.return_value = {"conflicts": [], "total_conflicts": 0}

        with patch(
            "ecu_hockey_calendar.cli.conflicts.RemoteApiClient",
            return_value=mock_client,
        ):
            result = runner.invoke(
                cli,
                ["conflicts", "--api-url", "https://remote.api", "--requires-review"],
            )
            assert result.exit_code == 0
            mock_client.get_conflicts.assert_called_with(
                severity=None,
                game_id=None,
                field_name=None,
                review_only=True,
                limit=None,
                offset=0,
            )

    def test_conflicts_remote_resolve_accept_source(self, runner: CliRunner) -> None:
        """Verify remote resolve command with --accept-source."""
        mock_client = MagicMock()
        mock_client.resolve_conflict.return_value = {
            "status": "resolved",
            "conflict_id": "conf-123",
            "game_id": "game-456",
            "field": "start_time",
            "value": "19:00",
            "accepted_source": "ECU Hockey",
            "resolved_by": "admin",
        }

        with patch(
            "ecu_hockey_calendar.cli.conflicts.RemoteApiClient",
            return_value=mock_client,
        ) as mock_cls:
            result = runner.invoke(
                cli,
                [
                    "conflicts",
                    "resolve",
                    "conf-123",
                    "--accept-source",
                    "ECU Hockey",
                    "--api-url",
                    "https://remote.api",
                    TOKEN_FLAG,
                    MOCK_TOKEN,
                ],
            )
            assert result.exit_code == 0
            mock_cls.assert_called_once_with("https://remote.api", token=MOCK_TOKEN)
            mock_client.resolve_conflict.assert_called_once_with(
                "conf-123",
                field=None,
                value=None,
                accept_source="ECU Hockey",
                notes=None,
                resolved_by="admin",
            )
            assert "Conflict Resolved Successfully!" in result.output
            assert "conf-123" in result.output
            assert "ECU Hockey" in result.output

    def test_conflicts_remote_resolve_explicit_field_value_and_json(
        self,
        runner: CliRunner,
    ) -> None:
        """Verify remote resolve command with --field, --value, and JSON."""
        mock_client = MagicMock()
        mock_client.resolve_conflict.return_value = {
            "status": "resolved",
            "conflict_id": "conf-789",
            "game_id": "game-999",
            "field": "venue",
            "value": "New Arena",
            "accepted_source": None,
            "resolved_by": "lead_editor",
            "notes": "Verified by coaching staff",
        }

        with patch(
            "ecu_hockey_calendar.cli.conflicts.RemoteApiClient",
            return_value=mock_client,
        ):
            result = runner.invoke(
                cli,
                [
                    "conflicts",
                    "resolve",
                    "conf-789",
                    "--field",
                    "venue",
                    "--value",
                    "New Arena",
                    "--notes",
                    "Verified by coaching staff",
                    "--resolved-by",
                    "lead_editor",
                    "--json",
                    "--api-url",
                    "https://remote.api",
                ],
            )
            assert result.exit_code == 0
            mock_client.resolve_conflict.assert_called_once_with(
                "conf-789",
                field="venue",
                value="New Arena",
                accept_source=None,
                notes="Verified by coaching staff",
                resolved_by="lead_editor",
            )
            assert '"status": "resolved"' in result.output
            assert '"venue"' in result.output
            assert '"New Arena"' in result.output

    def test_conflicts_remote_resolve_prod_flag(self, runner: CliRunner) -> None:
        """Verify remote resolve command targeting production using --prod."""
        mock_client = MagicMock()
        mock_client.resolve_conflict.return_value = {
            "status": "resolved",
            "conflict_id": "conf-111",
            "game_id": "g-1",
            "field": "start_time",
            "value": "20:00",
            "accepted_source": "achahockey",
            "resolved_by": "admin",
        }

        with patch(
            "ecu_hockey_calendar.cli.conflicts.RemoteApiClient",
            return_value=mock_client,
        ) as mock_cls:
            result = runner.invoke(
                cli,
                [
                    "conflicts",
                    "resolve",
                    "conf-111",
                    "--accept-source",
                    "achahockey",
                    "--prod",
                    TOKEN_FLAG,
                    MOCK_TOKEN,
                ],
            )
            assert result.exit_code == 0
            mock_cls.assert_called_once_with(DEFAULT_PROD_API_URL, token=MOCK_TOKEN)
            assert "Conflict Resolved Successfully!" in result.output

    def test_conflicts_remote_resolve_root_prod_flag(self, runner: CliRunner) -> None:
        """Verify remote resolve command targeting production using root --prod."""
        mock_client = MagicMock()
        mock_client.resolve_conflict.return_value = {
            "status": "resolved",
            "conflict_id": "conf-222",
            "game_id": "g-2",
            "field": "date",
            "value": "2026-10-01",
            "accepted_source": "achahockey",
            "resolved_by": "admin",
        }

        with patch(
            "ecu_hockey_calendar.cli.conflicts.RemoteApiClient",
            return_value=mock_client,
        ) as mock_cls:
            result = runner.invoke(
                cli,
                [
                    "--prod",
                    TOKEN_FLAG,
                    MOCK_TOKEN,
                    "conflicts",
                    "resolve",
                    "conf-222",
                    "--accept-source",
                    "achahockey",
                ],
            )
            assert result.exit_code == 0
            mock_cls.assert_called_once_with(DEFAULT_PROD_API_URL, token=MOCK_TOKEN)

    def test_conflicts_remote_resolve_auth_error(self, runner: CliRunner) -> None:
        """Verify handling of authentication error during remote conflict resolution."""
        mock_client = MagicMock()
        mock_client.resolve_conflict.side_effect = RemoteApiAuthError(
            "Unauthorized (401)",
        )

        with patch(
            "ecu_hockey_calendar.cli.conflicts.RemoteApiClient",
            return_value=mock_client,
        ):
            result = runner.invoke(
                cli,
                [
                    "conflicts",
                    "resolve",
                    "conf-123",
                    "--accept-source",
                    "ECU Hockey",
                    "--api-url",
                    "https://remote.api",
                ],
            )
            assert result.exit_code != 0
            assert "Authentication required" in result.output
            assert (
                "Authentication failed for remote conflict resolution." in result.output
            )

    def test_conflicts_remote_resolve_generic_error(self, runner: CliRunner) -> None:
        """Verify handling of generic remote error during conflict resolution."""
        mock_client = MagicMock()
        mock_client.resolve_conflict.side_effect = RemoteApiError(
            "Remote gateway error",
        )

        with patch(
            "ecu_hockey_calendar.cli.conflicts.RemoteApiClient",
            return_value=mock_client,
        ):
            result = runner.invoke(
                cli,
                [
                    "conflicts",
                    "resolve",
                    "conf-123",
                    "--accept-source",
                    "ECU Hockey",
                    "--api-url",
                    "https://remote.api",
                ],
            )
            assert result.exit_code != 0
            assert (
                "Failed to resolve conflict on remote API: Remote gateway error"
                in result.output
            )


class TestCliRemoteExport:
    """Tests for 'ecu-hockey export --api-url' remote command execution."""

    def test_export_remote_stdout_text(
        self,
        runner: CliRunner,
        sample_game: Game,
    ) -> None:
        """Verify exporting text schedule to stdout via remote API."""
        mock_client = MagicMock()
        mock_client.fetch_export.return_value = '{"games": []}'
        mock_client.get_games.return_value = [sample_game]

        with patch(
            "ecu_hockey_calendar.cli.export.RemoteApiClient",
            return_value=mock_client,
        ) as mock_cls:
            result = runner.invoke(
                cli,
                [
                    "--api-url",
                    "https://remote.api",
                    "export",
                    "-f",
                    "json",
                    "--season",
                    "2026-2027",
                    "--home-only",
                ],
            )
            assert result.exit_code == 0
            mock_cls.assert_called_once_with("https://remote.api", token=None)
            mock_client.fetch_export.assert_called_once_with(
                "json",
                season="2026-2027",
                opponent=None,
                home_only=True,
                future_only=False,
                status=None,
                embed=False,
            )
            assert '{"games": []}' in result.output

    def test_export_remote_file_pdf(
        self,
        runner: CliRunner,
        tmp_path: Path,
        sample_game: Game,
    ) -> None:
        """Verify exporting binary PDF schedule to file via remote API."""
        out_file = tmp_path / "schedule.pdf"
        mock_client = MagicMock()
        mock_client.fetch_export.return_value = b"%PDF-1.4 sample binary"
        mock_client.get_games.return_value = [sample_game]

        with patch(
            "ecu_hockey_calendar.cli.export.RemoteApiClient",
            return_value=mock_client,
        ) as mock_cls:
            result = runner.invoke(
                cli,
                [
                    "export",
                    "--api-url",
                    "https://remote.api",
                    TOKEN_FLAG,
                    MOCK_TOKEN,
                    "-f",
                    "pdf",
                    "-o",
                    str(out_file),
                ],
            )
            assert result.exit_code == 0
            mock_cls.assert_called_once_with("https://remote.api", token=MOCK_TOKEN)
            assert out_file.exists()
            assert out_file.read_bytes() == b"%PDF-1.4 sample binary"
            assert "Export Successful" in result.output
            assert "PDF" in result.output

    def test_export_remote_embed_html(
        self,
        runner: CliRunner,
        tmp_path: Path,
        sample_game: Game,
    ) -> None:
        """Verify exporting embed widget HTML view via remote API."""
        out_file = tmp_path / "widget.html"
        mock_client = MagicMock()
        mock_client.fetch_export.return_value = (
            "<iframe src='/schedule/embed'></iframe>"
        )
        mock_client.get_games.return_value = [sample_game]

        with patch(
            "ecu_hockey_calendar.cli.export.RemoteApiClient",
            return_value=mock_client,
        ):
            result = runner.invoke(
                cli,
                [
                    "export",
                    "--api-url",
                    "https://remote.api",
                    "--embed",
                    "-f",
                    "html",
                    "-o",
                    str(out_file),
                ],
            )
            assert result.exit_code == 0
            assert out_file.read_text(encoding="utf-8").startswith("<iframe")
            assert "HTML (EMBED)" in result.output

    def test_export_remote_error(self, runner: CliRunner) -> None:
        """Verify RemoteApiError in export produces click exception."""
        mock_client = MagicMock()
        mock_client.fetch_export.side_effect = RemoteApiError("Not found")

        with patch(
            "ecu_hockey_calendar.cli.export.RemoteApiClient",
            return_value=mock_client,
        ):
            result = runner.invoke(
                cli,
                ["export", "--api-url", "https://remote.api", "-f", "ics"],
            )
            assert result.exit_code != 0
            assert "Failed to export schedule from remote API" in result.output


class TestCliRemoteSync:
    """Tests for 'ecu-hockey sync --api-url' remote command execution."""

    def test_sync_remote_success_all_sources(self, runner: CliRunner) -> None:
        """Verify sync command triggers remote pipeline for all sources."""
        mock_client = MagicMock()
        mock_client.trigger_sync.return_value = {
            "status": "accepted",
            "message": "Cycle dispatched",
        }

        with patch(
            "ecu_hockey_calendar.cli.sync.RemoteApiClient",
            return_value=mock_client,
        ) as mock_cls:
            result = runner.invoke(
                cli,
                [
                    "--api-url",
                    "https://remote.api",
                    TOKEN_FLAG,
                    MOCK_TOKEN,
                    "sync",
                ],
            )
            assert result.exit_code == 0
            mock_cls.assert_called_once_with("https://remote.api", token=MOCK_TOKEN)
            mock_client.trigger_sync.assert_called_once_with(source=None)
            assert "SCHEDULE SYNCHRONIZATION & RECONCILIATION" in result.output
            assert "Remote API (https://remote.api)" in result.output
            assert (
                "Remote synchronization dispatched successfully: Cycle dispatched"
                in result.output
            )

    def test_sync_remote_success_specific_source_fallback_status(
        self,
        runner: CliRunner,
    ) -> None:
        """Verify sync with specific source and fallback status message."""
        mock_client = MagicMock()
        mock_client.trigger_sync.return_value = {"status": "in_progress"}

        with patch(
            "ecu_hockey_calendar.cli.sync.RemoteApiClient",
            return_value=mock_client,
        ):
            result = runner.invoke(
                cli,
                ["sync", "--api-url", "https://remote.api", "--source", "ecuhockey"],
            )
            assert result.exit_code == 0
            mock_client.trigger_sync.assert_called_once_with(source="ecuhockey")
            assert (
                "Remote synchronization dispatched successfully: in_progress"
                in result.output
            )

    def test_sync_remote_subcommand_token(self, runner: CliRunner) -> None:
        """Verify sync with token option passed directly at subcommand level."""
        mock_client = MagicMock()
        mock_client.trigger_sync.return_value = {"status": "ok"}

        with patch(
            "ecu_hockey_calendar.cli.sync.RemoteApiClient",
            return_value=mock_client,
        ) as mock_cls:
            result = runner.invoke(
                cli,
                ["sync", "--api-url", "https://remote.api", TOKEN_FLAG, MOCK_TOKEN],
            )
            assert result.exit_code == 0
            mock_cls.assert_called_once_with("https://remote.api", token=MOCK_TOKEN)

    def test_sync_remote_unsupported_501(self, runner: CliRunner) -> None:
        """Verify sync gracefully renders warning when remote is unsupported (501)."""
        mock_client = MagicMock()
        mock_client.trigger_sync.return_value = {
            "status": "unsupported",
            "status_code": 501,
            "message": (
                "On-demand synchronization trigger is not implemented. Runs via cron."
            ),
        }

        with patch(
            "ecu_hockey_calendar.cli.sync.RemoteApiClient",
            return_value=mock_client,
        ):
            result = runner.invoke(
                cli,
                ["sync", "--api-url", "https://remote.api"],
            )
            assert result.exit_code == 0
            assert "Runs via cron" in result.output

    def test_sync_remote_auth_error(self, runner: CliRunner) -> None:
        """Verify RemoteApiAuthError produces clear token advice on sync."""
        mock_client = MagicMock()
        mock_client.trigger_sync.side_effect = RemoteApiAuthError("Unauthorized (401)")

        with patch(
            "ecu_hockey_calendar.cli.sync.RemoteApiClient",
            return_value=mock_client,
        ):
            result = runner.invoke(
                cli,
                ["sync", "--api-url", "https://remote.api"],
            )
            assert result.exit_code != 0
            assert "Authentication required" in result.output
            assert "ECU_HOCKEY_ADMIN_TOKEN" in result.output

    def test_sync_remote_generic_error(self, runner: CliRunner) -> None:
        """Verify RemoteApiError produces click exception on sync."""
        mock_client = MagicMock()
        mock_client.trigger_sync.side_effect = RemoteApiError("Connection refused")

        with patch(
            "ecu_hockey_calendar.cli.sync.RemoteApiClient",
            return_value=mock_client,
        ):
            result = runner.invoke(
                cli,
                ["sync", "--api-url", "https://remote.api"],
            )
            assert result.exit_code != 0
            assert "Failed to trigger synchronization on remote API" in result.output


class TestCliRemoteHealth:
    """Tests for 'ecu-hockey health --api-url' remote command execution."""

    def test_health_remote_success(self, runner: CliRunner) -> None:
        """Verify health command fetches remote health data and renders panel."""
        mock_client = MagicMock()
        mock_client.get_health.return_value = {
            "status": "healthy",
            "version": "0.9.0",
            "uptime_seconds": 3600.0,
            "components": {
                "database": {"connected": True, "dialect": "postgresql"},
                "scrapers": {
                    "status": "operational",
                    "sources": [
                        {
                            "source_code": "ecuhockey",
                            "name": "ECU Hockey",
                            "source_type": "primary",
                            "is_active": True,
                            "last_scraped_at": "2026-10-01T12:00:00Z",
                        },
                    ],
                },
            },
        }

        with patch(
            "ecu_hockey_calendar.cli.health.RemoteApiClient",
            return_value=mock_client,
        ):
            result = runner.invoke(cli, ["health", "--api-url", "https://remote.api"])
            assert result.exit_code == 0
            assert "HEALTHY" in result.output
            assert "Connected (postgresql)" in result.output
            assert "ecuhockey" in result.output

    def test_health_remote_json(self, runner: CliRunner) -> None:
        """Verify health --json outputs pure structured JSON."""
        mock_client = MagicMock()
        mock_client.get_health.return_value = {
            "status": "healthy",
            "version": "0.9.0",
            "components": {"database": {"connected": True}},
        }

        with patch(
            "ecu_hockey_calendar.cli.health.RemoteApiClient",
            return_value=mock_client,
        ):
            result = runner.invoke(
                cli,
                ["health", "--api-url", "https://remote.api", "--json"],
            )
            assert result.exit_code == 0
            assert '"status": "healthy"' in result.output

    def test_health_remote_unhealthy(self, runner: CliRunner) -> None:
        """Verify unhealthy remote response exits with status code 1."""
        mock_client = MagicMock()
        mock_client.get_health.return_value = {
            "status": "unhealthy",
            "version": "0.9.0",
            "components": {
                "database": {"connected": False, "dialect": "sqlite"},
                "scrapers": {"status": "degraded", "sources": []},
            },
        }

        with patch(
            "ecu_hockey_calendar.cli.health.RemoteApiClient",
            return_value=mock_client,
        ):
            result = runner.invoke(cli, ["health", "--api-url", "https://remote.api"])
            assert result.exit_code == 1
            assert "UNHEALTHY" in result.output

    def test_health_remote_error(self, runner: CliRunner) -> None:
        """Verify RemoteApiError in health command produces click exception."""
        mock_client = MagicMock()
        mock_client.get_health.side_effect = RemoteApiError("Connection failed")

        with patch(
            "ecu_hockey_calendar.cli.health.RemoteApiClient",
            return_value=mock_client,
        ):
            result = runner.invoke(cli, ["health", "--api-url", "https://remote.api"])
            assert result.exit_code != 0
            assert "Failed to fetch health diagnostics from remote API" in result.output


class TestCliRemoteSyncStatus:
    """Tests for 'ecu-hockey sync status --api-url' remote command execution."""

    def test_sync_status_remote_success(self, runner: CliRunner) -> None:
        """Verify sync status fetches remote telemetry and renders display."""
        mock_client = MagicMock()
        mock_client.get_sync_status.return_value = {
            "current_status": "idle",
            "total_syncs": 5,
            "last_successful_sync": "2026-10-01T12:00:00Z",
            "last_sync": {
                "sync_cycle_id": "cycle-99",
                "status": "SUCCESS",
                "started_at": "2026-10-01T11:55:00Z",
                "duration_ms": 1200,
                "games_created": 2,
                "games_updated": 1,
                "games_deleted": 0,
                "conflicts_detected": 0,
            },
            "sources": [
                {
                    "source_code": "ecuhockey",
                    "name": "ECU Hockey",
                    "source_type": "primary",
                    "is_active": True,
                    "last_scraped_at": "2026-10-01T12:00:00Z",
                },
            ],
        }

        with patch(
            "ecu_hockey_calendar.cli.sync.RemoteApiClient",
            return_value=mock_client,
        ):
            result = runner.invoke(
                cli,
                ["sync", "status", "--api-url", "https://remote.api"],
            )
            assert result.exit_code == 0
            assert "cycle-99" in result.output
            assert "Remote API (https://remote.api)" in result.output
            assert "ecuhockey" in result.output

    def test_sync_status_remote_json(self, runner: CliRunner) -> None:
        """Verify sync status --json outputs raw remote payload."""
        mock_client = MagicMock()
        mock_client.get_sync_status.return_value = {
            "current_status": "idle",
            "total_syncs": 5,
        }

        with patch(
            "ecu_hockey_calendar.cli.sync.RemoteApiClient",
            return_value=mock_client,
        ):
            result = runner.invoke(
                cli,
                ["sync", "status", "--api-url", "https://remote.api", "--json"],
            )
            assert result.exit_code == 0
            assert '"current_status": "idle"' in result.output

    def test_sync_status_remote_error(self, runner: CliRunner) -> None:
        """Verify RemoteApiError in sync status produces click exception."""
        mock_client = MagicMock()
        mock_client.get_sync_status.side_effect = RemoteApiError("Timeout")

        with patch(
            "ecu_hockey_calendar.cli.sync.RemoteApiClient",
            return_value=mock_client,
        ):
            result = runner.invoke(
                cli,
                ["sync", "status", "--api-url", "https://remote.api"],
            )
            assert result.exit_code != 0
            assert "Failed to query sync status from remote API" in result.output
