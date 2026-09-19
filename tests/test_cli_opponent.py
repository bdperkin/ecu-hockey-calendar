"""Tests for the 'ecu-hockey opponent' CLI subcommands.

Covers interactive rich output, JSON formatted output, YAML appending,
custom options (--max-pages, --division, --conference, --disabled),
and error handling.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import click
import httpx
import pytest
from click.testing import CliRunner

from ecu_hockey_calendar.cli.main import cli
from ecu_hockey_calendar.cli.opponent import (
    _build_detection_table,
    _format_aliases_display,
    _handle_append_target,
    _handle_discovery_error,
    _present_discovery_result,
    _render_interactive_discovery,
    _run_spider,
)
from ecu_hockey_calendar.ingestion.opponent_config import (
    OpponentDirectory,
    OpponentFeedType,
)
from ecu_hockey_calendar.ingestion.opponent_discovery import (
    ConfidenceLevel,
    DiscoveredOpponent,
)


@pytest.fixture
def sample_discovered_opponent() -> DiscoveredOpponent:
    """Fixture providing a populated DiscoveredOpponent instance."""
    return DiscoveredOpponent(
        canonical_name="NC State University",
        feed_url="https://ncstatehockey.com/calendar.ics",
        feed_type=OpponentFeedType.ICAL,
        home_venue="Invisalign Arena",
        division="ACHA M2",
        conference="ACCHL",
        aliases=("icepack", "pack"),
        website="https://ncstatehockey.com",
        enabled=True,
        confidence_scores={
            "canonical_name": ConfidenceLevel.HIGH,
            "feed_url": ConfidenceLevel.HIGH,
            "feed_type": ConfidenceLevel.HIGH,
            "home_venue": ConfidenceLevel.HIGH,
            "website": ConfidenceLevel.HIGH,
            "aliases": ConfidenceLevel.HIGH,
        },
        pages_crawled=(
            "https://ncstatehockey.com",
            "https://ncstatehockey.com/schedule",
        ),
    )


class TestCliOpponentHelpers:
    """Tests for CLI helper and formatting functions."""

    def test_format_aliases_display(self) -> None:
        """Verify alias formatting for display."""
        assert _format_aliases_display(("a", "b")) == "a, b"
        assert _format_aliases_display(()) == "(none)"

    def test_build_detection_table(
        self,
        sample_discovered_opponent: DiscoveredOpponent,
    ) -> None:
        """Verify detection table creation with all attributes."""
        table = _build_detection_table(sample_discovered_opponent)
        assert table.title is not None
        assert "NC State University" in table.title
        assert len(table.rows) == 9

    def test_render_interactive_discovery(
        self,
        sample_discovered_opponent: DiscoveredOpponent,
    ) -> None:
        """Verify interactive discovery rendering does not error."""
        _render_interactive_discovery(
            sample_discovered_opponent,
            "https://ncstatehockey.com",
        )

    def test_handle_append_target_success(
        self,
        tmp_path: Path,
        sample_discovered_opponent: DiscoveredOpponent,
    ) -> None:
        """Verify appending to target file succeeds."""
        target = tmp_path / "opponents.yaml"
        _handle_append_target(target, sample_discovered_opponent)
        assert target.is_file()
        dir_obj = OpponentDirectory.from_yaml(target)
        assert "NC State University" in dir_obj

    def test_handle_append_target_duplicate_error(
        self,
        tmp_path: Path,
        sample_discovered_opponent: DiscoveredOpponent,
    ) -> None:
        """Verify appending duplicate raises ClickException."""
        target = tmp_path / "opponents.yaml"
        _handle_append_target(target, sample_discovered_opponent)

        with pytest.raises(click.ClickException, match="already exists"):
            _handle_append_target(target, sample_discovered_opponent)

    def test_handle_append_target_os_error(
        self,
        sample_discovered_opponent: DiscoveredOpponent,
    ) -> None:
        """Verify appending with filesystem OSError raises ClickException."""
        with (
            patch(
                "ecu_hockey_calendar.cli.opponent.append_opponent_to_yaml_file",
                side_effect=OSError("Permission denied"),
            ),
            pytest.raises(click.ClickException, match="Permission denied"),
        ):
            _handle_append_target(
                Path("/invalid/path.yaml"),
                sample_discovered_opponent,
            )

    def test_handle_discovery_error_text(self) -> None:
        """Verify _handle_discovery_error in text mode."""
        with pytest.raises(click.ClickException, match="Connection refused"):
            _handle_discovery_error(ValueError("Connection refused"), as_json=False)

    def test_handle_discovery_error_json(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Verify _handle_discovery_error in JSON mode."""
        with pytest.raises(SystemExit) as exc_info:
            _handle_discovery_error(ValueError("Failed request"), as_json=True)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["error"] == "Failed request"

    def test_present_discovery_result_json(
        self,
        capsys: pytest.CaptureFixture[str],
        sample_discovered_opponent: DiscoveredOpponent,
    ) -> None:
        """Verify presenting result as JSON."""
        _present_discovery_result(
            sample_discovered_opponent,
            "https://ncstatehockey.com",
            as_json=True,
            append_to=None,
        )
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["canonical_name"] == "NC State University"
        assert data["feed_type"] == "ical"

    @pytest.mark.anyio
    async def test_run_spider_invokes_discover(self) -> None:
        """Verify _run_spider instantiates spider and calls discover."""
        with patch(
            "ecu_hockey_calendar.cli.opponent.OpponentDiscoverySpider.discover",
            new_callable=AsyncMock,
        ) as mock_discover:
            await _run_spider(
                "https://example.com",
                5,
                "ACHA M2",
                "ACCHL",
                enabled=True,
            )
            mock_discover.assert_awaited_once_with(
                "https://example.com",
                division="ACHA M2",
                conference="ACCHL",
                enabled=True,
            )


class TestCliOpponentCommand:
    """Tests for 'ecu-hockey opponent discover' command execution."""

    def test_discover_empty_url(self) -> None:
        """Verify empty base URL raises UsageError."""
        runner = CliRunner()
        result = runner.invoke(cli, ["opponent", "discover", "   "])
        assert result.exit_code != 0
        assert "Base URL cannot be empty" in result.output

    def test_discover_interactive_success(
        self,
        sample_discovered_opponent: DiscoveredOpponent,
    ) -> None:
        """Verify interactive discovery CLI output."""
        runner = CliRunner()
        with patch(
            "ecu_hockey_calendar.cli.opponent._run_spider",
            new_callable=AsyncMock,
            return_value=sample_discovered_opponent,
        ):
            result = runner.invoke(
                cli,
                ["opponent", "discover", "https://ncstatehockey.com"],
            )

        assert result.exit_code == 0
        assert "OPPONENT DISCOVERY" in result.output
        assert "NC State University" in result.output
        assert "Invisalign Arena" in result.output
        assert "Candidate opponents.yaml Entry" in result.output

    def test_discover_json_success(
        self,
        sample_discovered_opponent: DiscoveredOpponent,
    ) -> None:
        """Verify JSON discovery CLI output."""
        runner = CliRunner()
        with patch(
            "ecu_hockey_calendar.cli.opponent._run_spider",
            new_callable=AsyncMock,
            return_value=sample_discovered_opponent,
        ):
            result = runner.invoke(
                cli,
                ["opponent", "discover", "https://ncstatehockey.com", "--json"],
            )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["canonical_name"] == "NC State University"
        assert data["overall_confidence"] == "HIGH"

    def test_discover_append_to_file(
        self,
        tmp_path: Path,
        sample_discovered_opponent: DiscoveredOpponent,
    ) -> None:
        """Verify appending discovered opponent directly to target YAML."""
        target = tmp_path / "opponents.yaml"
        runner = CliRunner()
        with patch(
            "ecu_hockey_calendar.cli.opponent._run_spider",
            new_callable=AsyncMock,
            return_value=sample_discovered_opponent,
        ):
            result = runner.invoke(
                cli,
                [
                    "opponent",
                    "discover",
                    "https://ncstatehockey.com",
                    "--append-to",
                    str(target),
                ],
            )

        assert result.exit_code == 0
        assert target.is_file()
        dir_obj = OpponentDirectory.from_yaml(target)
        assert "NC State University" in dir_obj

    def test_discover_options_forwarding(
        self,
        sample_discovered_opponent: DiscoveredOpponent,
    ) -> None:
        """Verify CLI options passed to _run_spider."""
        runner = CliRunner()
        with patch(
            "ecu_hockey_calendar.cli.opponent._run_spider",
            new_callable=AsyncMock,
            return_value=sample_discovered_opponent,
        ) as mock_spider:
            result = runner.invoke(
                cli,
                [
                    "opponent",
                    "discover",
                    "https://ncstatehockey.com",
                    "--max-pages",
                    "5",
                    "--division",
                    "ACHA M3",
                    "--conference",
                    "Independent",
                    "--disabled",
                ],
            )

        assert result.exit_code == 0
        mock_spider.assert_awaited_once_with(
            "https://ncstatehockey.com",
            5,
            "ACHA M3",
            "Independent",
            enabled=False,
        )

    def test_discover_spider_failure_interactive(self) -> None:
        """Verify error message displayed on spider failure."""
        runner = CliRunner()
        with patch(
            "ecu_hockey_calendar.cli.opponent._run_spider",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("Network unreachable"),
        ):
            result = runner.invoke(cli, ["opponent", "discover", "https://broken.com"])

        assert result.exit_code != 0
        assert "Discovery failed: Network unreachable" in result.output

    def test_discover_spider_failure_json(self) -> None:
        """Verify JSON error message displayed on spider failure."""
        runner = CliRunner()
        with patch(
            "ecu_hockey_calendar.cli.opponent._run_spider",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("Network unreachable"),
        ):
            result = runner.invoke(
                cli,
                ["opponent", "discover", "https://broken.com", "--json"],
            )

        assert result.exit_code != 0
        data = json.loads(result.output)
        assert "Network unreachable" in data["error"]
