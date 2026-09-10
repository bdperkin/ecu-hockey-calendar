"""Tests for the 'ecu-hockey notify' CLI command.

Verifies custom webhook alert broadcasting, severity resolution, channel
filtering, error handling, and Rich output formatting.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from ecu_hockey_calendar.cli.main import cli
from ecu_hockey_calendar.cli.notify import SEVERITY_MAP
from ecu_hockey_calendar.notifications.models import (
    DispatchResult,
    MultiChannelDispatchSummary,
    NotificationChannel,
    NotificationSeverity,
)


def test_severity_map_coverage() -> None:
    """Verify all expected severity levels are defined in SEVERITY_MAP."""
    assert SEVERITY_MAP["info"] == NotificationSeverity.INFO
    assert SEVERITY_MAP["success"] == NotificationSeverity.SUCCESS
    assert SEVERITY_MAP["warning"] == NotificationSeverity.WARNING
    assert SEVERITY_MAP["alert"] == NotificationSeverity.ALERT
    assert SEVERITY_MAP["error"] == NotificationSeverity.ALERT


def test_notify_command_no_channels_configured() -> None:
    """Verify notify exits cleanly with a warning when no webhook channels exist."""
    runner = CliRunner()
    with patch(
        "ecu_hockey_calendar.cli.notify.NotificationDispatcher.dispatch",
    ) as mock_dispatch:
        mock_dispatch.return_value = MultiChannelDispatchSummary(
            results=[],
            cycle_id=None,
            message_title="Test",
        )
        result = runner.invoke(
            cli,
            ["notify", "-m", "Test alert message"],
        )
        assert result.exit_code == 0
        assert "No active notification channels configured" in result.output


def test_notify_command_success_all_options() -> None:
    """Verify notify succeeds with all options, flags, and multiple channels."""
    runner = CliRunner()
    discord_res = DispatchResult(
        channel=NotificationChannel.DISCORD,
        success=True,
        attempts=1,
        status_code=204,
    )
    slack_res = DispatchResult(
        channel=NotificationChannel.SLACK,
        success=True,
        attempts=1,
        status_code=200,
    )

    with patch(
        "ecu_hockey_calendar.cli.notify.NotificationDispatcher.dispatch",
    ) as mock_dispatch:
        mock_dispatch.return_value = MultiChannelDispatchSummary(
            results=[discord_res, slack_res],
            cycle_id="test-cycle",
            message_title="Custom Alert Title",
        )

        result = runner.invoke(
            cli,
            [
                "notify",
                "-m",
                "Game schedule was updated",
                "-t",
                "Custom Alert Title",
                "-s",
                "alert",
                "-d",
                "Venue changed to Raleigh Center Ice",
                "--url",
                "https://github.com/bdperkin/ecu-hockey-calendar/actions/runs/123",
                "-c",
                "discord",
                "-c",
                "slack",
            ],
        )

        assert result.exit_code == 0
        assert "NOTIFICATION DISPATCH" in result.output
        assert "Notification Dispatch Telemetry" in result.output
        assert "Discord" in result.output
        assert "Slack" in result.output
        assert "Delivered" in result.output
        assert "Notification successfully dispatched" in result.output

        # Verify dispatched message properties
        call_args = mock_dispatch.call_args
        msg = call_args[0][0]
        assert msg.title == "Custom Alert Title"
        assert msg.summary == "Game schedule was updated"
        assert msg.details == "Venue changed to Raleigh Center Ice"
        assert msg.severity == NotificationSeverity.ALERT
        assert msg.event_url == (
            "https://github.com/bdperkin/ecu-hockey-calendar/actions/runs/123"
        )
        assert call_args[1]["channels"] == {
            NotificationChannel.DISCORD,
            NotificationChannel.SLACK,
        }


def test_notify_command_severities() -> None:
    """Verify various severity inputs map to appropriate NotificationSeverity."""
    runner = CliRunner()
    for sev_name, expected_sev in [
        ("success", NotificationSeverity.SUCCESS),
        ("warning", NotificationSeverity.WARNING),
        ("error", NotificationSeverity.ALERT),
        ("info", NotificationSeverity.INFO),
    ]:
        with patch(
            "ecu_hockey_calendar.cli.notify.NotificationDispatcher.dispatch",
        ) as mock_dispatch:
            mock_dispatch.return_value = MultiChannelDispatchSummary(
                results=[
                    DispatchResult(
                        channel=NotificationChannel.TELEGRAM,
                        success=True,
                        attempts=1,
                    ),
                ],
                cycle_id=None,
                message_title="Title",
            )
            result = runner.invoke(
                cli,
                ["notify", "-m", f"Testing severity {sev_name}", "-s", sev_name],
            )
            assert result.exit_code == 0
            call_msg = mock_dispatch.call_args[0][0]
            assert call_msg.severity == expected_sev


def test_notify_command_failure_raises_click_exception() -> None:
    """Verify notify exits with error code when dispatch fails on any channel."""
    runner = CliRunner()
    failed_res = DispatchResult(
        channel=NotificationChannel.DISCORD,
        success=False,
        attempts=3,
        status_code=500,
        error_message="HTTP 500 Server Error",
    )

    with patch(
        "ecu_hockey_calendar.cli.notify.NotificationDispatcher.dispatch",
    ) as mock_dispatch:
        mock_dispatch.return_value = MultiChannelDispatchSummary(
            results=[failed_res],
            cycle_id="err-cycle",
            message_title="Failed",
        )
        result = runner.invoke(
            cli,
            ["notify", "-m", "Failure test"],
        )
        assert result.exit_code != 0
        assert "Failed to dispatch notification to channels: discord" in result.output


def test_sync_command_with_notify_individual() -> None:
    """Verify sync --notify --notify-individual passes individual_changes."""
    runner = CliRunner()
    with (
        patch("ecu_hockey_calendar.cli.sync.create_sync_engine") as mock_engine,
        patch("ecu_hockey_calendar.cli.sync.Base.metadata.create_all"),
        patch(
            "ecu_hockey_calendar.cli.sync._execute_crawlers",
        ) as mock_crawlers,
        patch("ecu_hockey_calendar.cli.sync.get_sync_session"),
        patch(
            "ecu_hockey_calendar.cli.sync._load_baseline_games_from_db",
            return_value=[],
        ),
        patch(
            "ecu_hockey_calendar.cli.sync.NotificationDispatcher",
        ) as mock_disp_cls,
    ):
        mock_engine.return_value = MagicMock()
        mock_crawlers.return_value = (
            [],
            [
                {
                    "source": "ecuhockey",
                    "name": "ECU Hockey",
                    "records": 0,
                    "status": "SUCCESS",
                    "duration": 0.1,
                },
            ],
        )
        mock_dispatcher_inst = MagicMock()
        mock_disp_cls.return_value = mock_dispatcher_inst

        result = runner.invoke(
            cli,
            ["sync", "--notify", "--notify-individual"],
        )
        assert result.exit_code == 0
        assert mock_dispatcher_inst.dispatch_cycle.called
        call_kwargs = mock_dispatcher_inst.dispatch_cycle.call_args[1]
        assert call_kwargs["individual_changes"] is True
