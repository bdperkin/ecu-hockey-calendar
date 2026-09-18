"""Tests for 'ecu-hockey scrape' and 'crawl' CLI commands.

Covers tiered output modes (minimal, verbose, debug), source filtering,
JSON streaming, database persistence, and error resilience.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner
from rich.console import Console

from ecu_hockey_calendar.cli.main import cli
from ecu_hockey_calendar.cli.scrape import (
    ScrapeResult,
    _json_sanitize,
    _persist_scraped_results,
    _render_scrape_summary,
    _serialize_record,
    scrape_command,
)
from ecu_hockey_calendar.ingestion.html_parser import ParsedGameRecord
from ecu_hockey_calendar.ingestion.instagram_parser import ParsedInstagramPost
from ecu_hockey_calendar.ingestion.opponent_parser import OpponentFixture
from ecu_hockey_calendar.ingestion.tickets_parser import ParsedTicketRecord
from ecu_hockey_calendar.storage.engine import create_sync_engine
from ecu_hockey_calendar.storage.models import GameStatus

if TYPE_CHECKING:
    from pathlib import Path


def _sample_game_record(game_id: str = "test-game-1") -> ParsedGameRecord:
    """Helper to create dummy ParsedGameRecord."""
    return ParsedGameRecord(
        game_id=game_id,
        opponent_name="Test Opponent",
        is_home=True,
        start_time=datetime(2026, 10, 10, 19, 0, tzinfo=UTC),
        venue="Test Arena",
        status=GameStatus.SCHEDULED,
        home_score=None,
        away_score=None,
    )


def test_scrape_result_to_dict() -> None:
    """Verify ScrapeResult dictionary representation."""
    res = ScrapeResult(
        source_code="test",
        name="Test Source",
        status="SUCCESS",
        records=[1, 2, 3],
        duration=1.23,
        error_message=None,
    )
    d = res.to_dict()
    assert d["source_code"] == "test"
    assert d["name"] == "Test Source"
    assert d["status"] == "SUCCESS"
    assert d["record_count"] == 3
    assert d["duration"] == 1.23
    assert d["error_message"] is None


def test_json_sanitize_and_serialize_record() -> None:
    """Verify JSON sanitization handles nested dataclasses, datetimes, and enums."""

    class DummyEnum(Enum):
        """Test enumeration for serialization testing."""

        ACTIVE = "active"

    @dataclass
    class DummyItem:
        """Test dataclass for serialization testing."""

        created_at: datetime
        status: DummyEnum

    item = DummyItem(
        created_at=datetime(2026, 9, 18, 12, 0, tzinfo=UTC),
        status=DummyEnum.ACTIVE,
    )
    serialized = _serialize_record(item)
    assert isinstance(serialized, dict)
    assert serialized["created_at"] == "2026-09-18T12:00:00+00:00"
    assert serialized["status"] == "active"

    # Test dict with custom to_dict method
    class CustomObj:
        """Test custom object with to_dict method."""

        def to_dict(self) -> dict[str, str]:
            """Return custom dictionary representation."""
            return {"key": "val"}

    assert _serialize_record(CustomObj()) == {"key": "val"}
    assert _serialize_record({"raw": "dict"}) == {"raw": "dict"}
    assert _serialize_record("plain string") == "plain string"
    assert _json_sanitize([DummyEnum.ACTIVE]) == ["active"]


def test_scrape_minimal_output_default() -> None:
    """Verify default execution produces concise summary without verbose logs."""
    runner = CliRunner()
    rec = _sample_game_record()

    with (
        patch(
            "ecu_hockey_calendar.cli.scrape.ECUHockeyCrawler.crawl",
            new_callable=AsyncMock,
            return_value=([rec], "html", "hash", "text/html"),
        ),
        patch(
            "ecu_hockey_calendar.cli.scrape.ACCHockeyCrawler.crawl",
            new_callable=AsyncMock,
            return_value=([rec], "html", "hash", "text/html"),
        ),
        patch(
            "ecu_hockey_calendar.cli.scrape.InstagramCrawler.fetch_posts",
            new_callable=AsyncMock,
            return_value=([], "", "", "none"),
        ),
        patch(
            "ecu_hockey_calendar.cli.scrape.TicketsCrawler.crawl",
            new_callable=AsyncMock,
            return_value=([], "", "", "none"),
        ),
    ):
        result = runner.invoke(cli, ["scrape"])
        assert result.exit_code == 0
        assert "SCHEDULE INGESTION SCRAPER" in result.output
        assert "MINIMAL" in result.output
        assert "ECU Hockey Official" in result.output
        assert "ACC Hockey League" in result.output
        # In minimal mode, no URL scrape lines or HTTP wire logs should appear
        assert "SCRAPE " not in result.output
        assert "DEBUG [http]" not in result.output


def test_crawl_alias() -> None:
    """Verify 'crawl' alias routes to scrape command."""
    runner = CliRunner()
    rec = _sample_game_record()

    with patch(
        "ecu_hockey_calendar.cli.scrape.ECUHockeyCrawler.crawl",
        new_callable=AsyncMock,
        return_value=([rec], "html", "hash", "text/html"),
    ):
        result = runner.invoke(cli, ["crawl", "-s", "ecuhockey"])
        assert result.exit_code == 0
        assert "SCHEDULE INGESTION SCRAPER" in result.output
        assert "ECU Hockey Official" in result.output


def test_scrape_verbose_mode() -> None:
    """Verify -v and --verbose flags stream URL and discovery telemetry."""
    runner = CliRunner()
    rec = _sample_game_record()

    with patch(
        "ecu_hockey_calendar.cli.scrape.ECUHockeyCrawler.crawl",
        new_callable=AsyncMock,
        return_value=([rec], "html", "hash", "text/html"),
    ):
        result = runner.invoke(cli, ["scrape", "-s", "ecuhockey", "-v"])
        assert result.exit_code == 0
        assert "VERBOSE" in result.output
        assert "ECU Hockey Official" in result.output

    # Test global -v flag
    with patch(
        "ecu_hockey_calendar.cli.scrape.ECUHockeyCrawler.crawl",
        new_callable=AsyncMock,
        return_value=([rec], "html", "hash", "text/html"),
    ):
        result_global = runner.invoke(cli, ["-v", "scrape", "-s", "ecuhockey"])
        assert result_global.exit_code == 0
        assert "VERBOSE" in result_global.output


def test_scrape_debug_mode() -> None:
    """Verify --debug flag displays debug banner and wire telemetry."""
    runner = CliRunner()
    rec = _sample_game_record()

    with patch(
        "ecu_hockey_calendar.cli.scrape.ECUHockeyCrawler.crawl",
        new_callable=AsyncMock,
        return_value=([rec], "html", "hash", "text/html"),
    ):
        result = runner.invoke(cli, ["scrape", "-s", "ecuhockey", "--debug"])
        assert result.exit_code == 0
        assert "DEBUG" in result.output

    # Test global --debug flag
    with patch(
        "ecu_hockey_calendar.cli.scrape.ECUHockeyCrawler.crawl",
        new_callable=AsyncMock,
        return_value=([rec], "html", "hash", "text/html"),
    ):
        result_global = runner.invoke(cli, ["--debug", "scrape", "-s", "ecuhockey"])
        assert result_global.exit_code == 0
        assert "DEBUG" in result_global.output


def test_scrape_source_filters() -> None:
    """Verify each individual source filter executes the appropriate crawler."""
    runner = CliRunner()
    rec = _sample_game_record()

    # acchockey
    with patch(
        "ecu_hockey_calendar.cli.scrape.ACCHockeyCrawler.crawl",
        new_callable=AsyncMock,
        return_value=([rec], "html", "hash", "text/html"),
    ):
        res = runner.invoke(cli, ["scrape", "-s", "acchockey"])
        assert res.exit_code == 0
        assert "ACC Hockey League" in res.output

    # instagram / social
    dummy_post = ParsedInstagramPost(
        post_id="p1",
        shortcode="p1",
        caption="Game Day",
        url="https://instagram.com/p/1",
        published_at=datetime(2026, 10, 10, tzinfo=UTC),
    )
    with patch(
        "ecu_hockey_calendar.cli.scrape.InstagramCrawler.fetch_posts",
        new_callable=AsyncMock,
        return_value=([dummy_post], "{}", "hash", "application/json"),
    ):
        res = runner.invoke(cli, ["scrape", "-s", "social"])
        assert res.exit_code == 0
        assert "ECU Hockey Instagram" in res.output

    # tickets
    dummy_ticket = ParsedTicketRecord(
        ticket_id="t1",
        title="ECU vs UNC",
        start_time=datetime(2026, 10, 10, tzinfo=UTC),
    )
    with patch(
        "ecu_hockey_calendar.cli.scrape.TicketsCrawler.crawl",
        new_callable=AsyncMock,
        return_value=([dummy_ticket], "{}", "hash", "application/json"),
    ):
        res = runner.invoke(cli, ["scrape", "-s", "tickets"])
        assert res.exit_code == 0
        assert "ECU Hockey Tickets" in res.output

    # opponent
    dummy_fixture = OpponentFixture(
        opponent_name="UNC",
        summary="ECU vs UNC",
        start_time=datetime(2026, 10, 10, tzinfo=UTC),
        venue="Raleigh",
        is_opponent_home=True,
    )
    with patch(
        "ecu_hockey_calendar.cli.scrape.OpponentCrawler.fetch_opponent_schedule",
        new_callable=AsyncMock,
        return_value=([dummy_fixture], "{}", "hash", "application/json"),
    ):
        res = runner.invoke(cli, ["scrape", "-s", "opponent"])
        assert res.exit_code == 0
        assert "Opponent Schedule Feeds" in res.output


def test_scrape_subseasons_filter() -> None:
    """Verify --subseasons crawls specified historical subseason endpoints."""
    runner = CliRunner()
    rec = _sample_game_record()

    with patch(
        "ecu_hockey_calendar.cli.scrape.ACCHockeyCrawler.crawl",
        new_callable=AsyncMock,
        return_value=([rec], "html", "hash", "text/html"),
    ) as mock_crawl:
        res = runner.invoke(
            cli,
            [
                "scrape",
                "-s",
                "acchockey",
                "--subseasons",
                "950924,https://www.acchockey.com/sched/custom",
            ],
        )
        assert res.exit_code == 0
        assert mock_crawl.call_count == 2
        calls = [c.kwargs.get("url") for c in mock_crawl.call_args_list]
        assert any("subseason=950924" in url for url in calls if url)
        assert "https://www.acchockey.com/sched/custom" in calls


def test_scrape_json_output() -> None:
    """Verify --json produces valid parseable JSON without banner or table noise."""
    runner = CliRunner()
    rec = _sample_game_record()

    with patch(
        "ecu_hockey_calendar.cli.scrape.ECUHockeyCrawler.crawl",
        new_callable=AsyncMock,
        return_value=([rec], "html", "hash", "text/html"),
    ):
        res = runner.invoke(cli, ["scrape", "-s", "ecuhockey", "--json"])
        assert res.exit_code == 0
        data = json.loads(res.output)
        assert "sources" in data
        assert "total_records" in data
        assert data["total_records"] == 1
        assert "ecuhockey" in data["records"]
        assert data["records"]["ecuhockey"][0]["game_id"] == "test-game-1"


def test_scrape_save_to_database(tmp_path: Path) -> None:
    """Verify --save persists crawled fixtures into database."""
    db_file = tmp_path / "scrape_save.db"
    db_url = f"sqlite:///{db_file}"
    runner = CliRunner()
    rec = _sample_game_record()

    with (
        patch(
            "ecu_hockey_calendar.cli.scrape.ECUHockeyCrawler.crawl",
            new_callable=AsyncMock,
            return_value=([rec], "html", "hash", "text/html"),
        ),
        patch(
            "ecu_hockey_calendar.cli.scrape.ECUHockeyCrawler.crawl_and_sync",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_sync,
    ):
        res = runner.invoke(
            cli,
            ["scrape", "-s", "ecuhockey", "--save", "--db-url", db_url],
        )
        assert res.exit_code == 0
        assert "Persisted scraped fixtures to database" in res.output
        mock_sync.assert_called_once()


def test_scrape_error_handling() -> None:
    """Verify crawler exceptions are captured and reported without aborting CLI."""
    runner = CliRunner()

    with patch(
        "ecu_hockey_calendar.cli.scrape.ECUHockeyCrawler.crawl",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Connection timeout to upstream host"),
    ):
        res = runner.invoke(cli, ["scrape", "-s", "ecuhockey"])
        assert res.exit_code == 0
        assert "ERROR" in res.output
        assert "Connection timeout to upstream host" in res.output


def test_render_scrape_summary_with_errors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify _render_scrape_summary formats warning when an error is present."""
    buf = io.StringIO()
    console = Console(file=buf, color_system=None)
    results = [
        ScrapeResult("s1", "Source 1", "SUCCESS", [1, 2], 1.0),
        ScrapeResult("s2", "Source 2", "ERROR", [], 0.5, error_message="Fatal crash"),
    ]
    _render_scrape_summary(results, console)
    out = buf.getvalue()
    assert "Source 1" in out
    assert "Source 2" in out
    captured = capsys.readouterr()
    assert "Fatal crash" in captured.err


def test_persist_scraped_results_all_sources(tmp_path: Path) -> None:
    """Verify _persist_scraped_results persists records across all crawler types."""
    db_file = tmp_path / "persist_all.db"
    db_url = f"sqlite:///{db_file}"
    engine = create_sync_engine(db_url)

    results = [
        ScrapeResult(
            "ecuhockey",
            "ECU Hockey",
            "SUCCESS",
            [_sample_game_record("g1")],
            1.0,
        ),
        ScrapeResult(
            "acchockey",
            "ACC Hockey",
            "SUCCESS",
            [_sample_game_record("g2")],
            1.0,
        ),
        ScrapeResult("tickets", "Tickets", "SUCCESS", [1], 1.0),
        ScrapeResult("instagram", "Instagram", "SUCCESS", [1], 1.0),
        ScrapeResult("opponent", "Opponent", "SUCCESS", [1], 1.0),
        ScrapeResult("unrecognized", "Unrecognized", "SUCCESS", [1], 1.0),
        ScrapeResult("empty", "Empty", "EMPTY", [], 1.0),
    ]

    with (
        patch(
            "ecu_hockey_calendar.cli.scrape.ECUHockeyCrawler.crawl_and_sync",
            new_callable=AsyncMock,
        ) as m_ecu,
        patch(
            "ecu_hockey_calendar.cli.scrape.ACCHockeyCrawler.crawl_and_sync",
            new_callable=AsyncMock,
        ) as m_acc,
        patch(
            "ecu_hockey_calendar.cli.scrape.TicketsCrawler.crawl_and_sync",
            new_callable=AsyncMock,
        ) as m_tix,
        patch(
            "ecu_hockey_calendar.cli.scrape.InstagramCrawler.sync",
            new_callable=AsyncMock,
        ) as m_ig,
        patch(
            "ecu_hockey_calendar.cli.scrape.OpponentCrawler.sync",
            new_callable=AsyncMock,
        ) as m_opp,
    ):
        _persist_scraped_results(engine, results, season="2026-2027")
        assert m_ecu.call_count == 1
        assert m_acc.call_count == 1
        assert m_tix.call_count == 1
        assert m_ig.call_count == 1
        assert m_opp.call_count == 1


def test_scrape_source_exception_branches() -> None:
    """Verify exception branches in each individual crawler are handled."""
    runner = CliRunner()

    with patch(
        "ecu_hockey_calendar.cli.scrape.ACCHockeyCrawler.crawl",
        new_callable=AsyncMock,
        side_effect=RuntimeError("ACCHL network error"),
    ):
        res = runner.invoke(cli, ["scrape", "-s", "acchockey"])
        assert res.exit_code == 0
        assert "ERROR" in res.output
        assert "ACCHL network error" in res.output

    with patch(
        "ecu_hockey_calendar.cli.scrape.InstagramCrawler.fetch_posts",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Instagram API error"),
    ):
        res = runner.invoke(cli, ["scrape", "-s", "social"])
        assert res.exit_code == 0
        assert "ERROR" in res.output
        assert "Instagram API error" in res.output

    with patch(
        "ecu_hockey_calendar.cli.scrape.OpponentCrawler.fetch_opponent_schedule",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Opponent crawler error"),
    ):
        res = runner.invoke(cli, ["scrape", "-s", "opponent"])
        assert res.exit_code == 0
        assert "ERROR" in res.output
        assert "Opponent crawler error" in res.output

    with patch(
        "ecu_hockey_calendar.cli.scrape.TicketsCrawler.crawl",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Tickets feed error"),
    ):
        res = runner.invoke(cli, ["scrape", "-s", "tickets"])
        assert res.exit_code == 0
        assert "ERROR" in res.output
        assert "Tickets feed error" in res.output


def test_scrape_save_with_json(tmp_path: Path) -> None:
    """Verify --save when --json is enabled does not print standard success messages."""
    db_file = tmp_path / "scrape_save_json.db"
    db_url = f"sqlite:///{db_file}"
    runner = CliRunner()
    rec = _sample_game_record()

    with (
        patch(
            "ecu_hockey_calendar.cli.scrape.ECUHockeyCrawler.crawl",
            new_callable=AsyncMock,
            return_value=([rec], "html", "hash", "text/html"),
        ),
        patch(
            "ecu_hockey_calendar.cli.scrape.ECUHockeyCrawler.crawl_and_sync",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        res = runner.invoke(
            cli,
            ["scrape", "-s", "ecuhockey", "--save", "--db-url", db_url, "--json"],
        )
        assert res.exit_code == 0
        data = json.loads(res.output)
        assert data["total_records"] == 1
        assert "Persisted scraped fixtures to database" not in res.output


def test_scrape_command_with_non_dict_context_obj() -> None:
    """Verify scrape_command handles non-dict ctx.obj gracefully."""
    runner = CliRunner()
    rec = _sample_game_record()

    with patch(
        "ecu_hockey_calendar.cli.scrape.ECUHockeyCrawler.crawl",
        new_callable=AsyncMock,
        return_value=([rec], "html", "hash", "text/html"),
    ):
        result = runner.invoke(scrape_command, ["-s", "ecuhockey"], obj="not-a-dict")
        assert result.exit_code == 0
        assert "ECU Hockey Official" in result.output


def test_scrape_with_opponents_config_flag(tmp_path: Path) -> None:
    """Verify scrape command accepts -O / --opponents-config flag."""
    runner = CliRunner()
    custom_yaml = tmp_path / "opponents.yaml"
    custom_yaml.write_text(
        """opponents:
    -
        canonical_name: "UNC Chapel Hill"
        feed_url: "https://unc.edu/feed.ics"
        feed_type: "ical"
""",
        encoding="utf-8",
    )
    dummy_fixture = OpponentFixture(
        opponent_name="UNC Chapel Hill",
        summary="ECU vs UNC",
        start_time=datetime(2026, 10, 20, 19, 0, tzinfo=UTC),
        venue="Orange County Sportsplex",
        is_opponent_home=True,
    )
    with patch(
        "ecu_hockey_calendar.cli.scrape.OpponentCrawler.fetch_opponent_schedule",
        new_callable=AsyncMock,
        return_value=([dummy_fixture], "{}", "hash", "application/json"),
    ):
        res = runner.invoke(
            scrape_command,
            ["-O", str(custom_yaml), "-s", "opponent"],
        )
        assert res.exit_code == 0
        assert "Opponent Schedule Feeds" in res.output


def test_scrape_with_missing_opponents_config(tmp_path: Path) -> None:
    """Verify scrape command aborts cleanly when opponent config is missing."""
    runner = CliRunner()
    missing = tmp_path / "missing_opponents.yaml"
    res = runner.invoke(
        scrape_command,
        ["-O", str(missing), "-s", "opponent"],
    )
    assert res.exit_code != 0
    assert "Opponent configuration file not found" in res.output


def test_scrape_with_invalid_opponents_config(tmp_path: Path) -> None:
    """Verify scrape command aborts cleanly on invalid YAML opponent config."""
    runner = CliRunner()
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("opponents: [broken", encoding="utf-8")
    res = runner.invoke(
        scrape_command,
        ["-O", str(bad_yaml), "-s", "opponent"],
    )
    assert res.exit_code != 0
    assert "Invalid opponent configuration" in res.output


def test_crawl_alias_with_opponents_config(tmp_path: Path) -> None:
    """Verify crawl alias accepts -O / --opponents-config flag."""
    runner = CliRunner()
    custom_yaml = tmp_path / "opponents.yaml"
    custom_yaml.write_text(
        """opponents:
    -
        canonical_name: "UNC Chapel Hill"
        feed_url: "https://unc.edu/feed.ics"
        feed_type: "ical"
""",
        encoding="utf-8",
    )
    dummy_fixture = OpponentFixture(
        opponent_name="UNC Chapel Hill",
        summary="ECU vs UNC",
        start_time=datetime(2026, 10, 20, 19, 0, tzinfo=UTC),
        venue="Orange County Sportsplex",
        is_opponent_home=True,
    )
    with patch(
        "ecu_hockey_calendar.cli.scrape.OpponentCrawler.fetch_opponent_schedule",
        new_callable=AsyncMock,
        return_value=([dummy_fixture], "{}", "hash", "application/json"),
    ):
        res = runner.invoke(
            cli,
            ["crawl", "-O", str(custom_yaml), "-s", "opponent"],
        )
        assert res.exit_code == 0
        assert "Opponent Schedule Feeds" in res.output


def test_scrape_root_cli_context_inheritance(tmp_path: Path) -> None:
    """Verify root cli -O option is passed down to scrape command via ctx.obj."""
    runner = CliRunner()
    custom_yaml = tmp_path / "root_opponents.yaml"
    custom_yaml.write_text(
        """opponents:
    -
        canonical_name: "UNC Chapel Hill"
        feed_url: "https://unc.edu/feed.ics"
        feed_type: "ical"
""",
        encoding="utf-8",
    )
    dummy_fixture = OpponentFixture(
        opponent_name="UNC Chapel Hill",
        summary="ECU vs UNC",
        start_time=datetime(2026, 10, 20, 19, 0, tzinfo=UTC),
        venue="Orange County Sportsplex",
        is_opponent_home=True,
    )
    with patch(
        "ecu_hockey_calendar.cli.scrape.OpponentCrawler.fetch_opponent_schedule",
        new_callable=AsyncMock,
        return_value=([dummy_fixture], "{}", "hash", "application/json"),
    ):
        res = runner.invoke(
            cli,
            ["-O", str(custom_yaml), "scrape", "-s", "opponent"],
        )
        assert res.exit_code == 0
        assert "Opponent Schedule Feeds" in res.output


def test_scrape_with_envvar_opponents_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify scrape command respects OPPONENTS_CONFIG environment variable."""
    runner = CliRunner()
    custom_yaml = tmp_path / "env_opponents.yaml"
    custom_yaml.write_text(
        """opponents:
    -
        canonical_name: "UNC Chapel Hill"
        feed_url: "https://unc.edu/feed.ics"
        feed_type: "ical"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPPONENTS_CONFIG", str(custom_yaml))
    dummy_fixture = OpponentFixture(
        opponent_name="UNC Chapel Hill",
        summary="ECU vs UNC",
        start_time=datetime(2026, 10, 20, 19, 0, tzinfo=UTC),
        venue="Orange County Sportsplex",
        is_opponent_home=True,
    )
    with patch(
        "ecu_hockey_calendar.cli.scrape.OpponentCrawler.fetch_opponent_schedule",
        new_callable=AsyncMock,
        return_value=([dummy_fixture], "{}", "hash", "application/json"),
    ):
        res = runner.invoke(
            scrape_command,
            ["-s", "opponent"],
        )
        assert res.exit_code == 0
        assert "Opponent Schedule Feeds" in res.output
