"""Unit tests for ACHA Hockey crawler and database synchronization."""

# pylint: disable=protected-access

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ecu_hockey_calendar.ingestion.achahockey_crawler import (
    DEFAULT_ACHA_SEASON,
    ACHAHockeyCrawler,
    _dedupe_records,
    _resolve_crawl_targets,
    _resolve_page_season,
    _resolve_target_season_id,
)
from ecu_hockey_calendar.ingestion.achahockey_parser import (
    CLIENT_CODE,
    DEFAULT_ACHA_PORTAL_URL,
    DEFAULT_APP_KEY,
    DEFAULT_BASE_URL,
    ECU_TEAM_ID,
    KNOWN_SEASONS,
)
from ecu_hockey_calendar.ingestion.client import ResilientHttpClient
from ecu_hockey_calendar.ingestion.html_parser import ParsedGameRecord
from ecu_hockey_calendar.storage.base import Base
from ecu_hockey_calendar.storage.models import (
    DataSourceModel,
    DataSourceType,
    GameModel,
    RawSnapshotModel,
    SyncAuditModel,
    SyncStatus,
)

if TYPE_CHECKING:
    from collections.abc import Generator

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "achahockey"


def _read_fixture_str(filename: str) -> str:
    """Load JSON fixture string from tests/fixtures/achahockey."""
    filepath = FIXTURES_DIR / filename
    return filepath.read_text(encoding="utf-8")


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """In-memory SQLite database session fixture."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session

    engine.dispose()


class TestACHAHockeyCrawlerBasics:
    """Test initialization, helpers, and data structure conversion."""

    def test_crawler_initialization(self) -> None:
        """Verify default and customized initialization."""
        crawler = ACHAHockeyCrawler()
        assert crawler.base_url == DEFAULT_BASE_URL
        assert crawler.portal_url == DEFAULT_ACHA_PORTAL_URL
        assert crawler.team_id == ECU_TEAM_ID
        assert crawler.app_key == DEFAULT_APP_KEY
        assert crawler.client_code == CLIENT_CODE
        assert isinstance(crawler.client, ResilientHttpClient)

        mock_obs = MagicMock()
        mock_client = ResilientHttpClient(observer=mock_obs)
        custom_crawler = ACHAHockeyCrawler(
            client=mock_client,
            base_url="https://custom.feed/index.php",
            portal_url="https://custom.org",
            team_id="999",
            app_key="custom-key",
            client_code="custom-acha",
            observer=mock_obs,
        )
        assert custom_crawler.client is mock_client
        assert custom_crawler.base_url == "https://custom.feed/index.php"
        assert custom_crawler.portal_url == "https://custom.org"
        assert custom_crawler.team_id == "999"
        assert custom_crawler.app_key == "custom-key"
        assert custom_crawler.client_code == "custom-acha"

    def test_crawler_client_observer_assignment(self) -> None:
        """Verify client observer is assigned if missing on existing client."""
        client = ResilientHttpClient()
        obs = MagicMock()
        crawler = ACHAHockeyCrawler(client=client, observer=obs)
        assert crawler.client.observer is obs

    def test_dedupe_records(self) -> None:
        """Verify deduplication preserves encounter order and strips duplicates."""
        now = datetime.now(UTC)
        r1 = ParsedGameRecord(
            game_id="game-1",
            opponent_name="UNC Charlotte",
            is_home=True,
            start_time=now,
            venue="Extreme Ice",
        )
        r2 = ParsedGameRecord(
            game_id="game-2",
            opponent_name="Alabama",
            is_home=False,
            start_time=now,
            venue="Pelham",
        )
        r1_dup = ParsedGameRecord(
            game_id="game-1",
            opponent_name="UNC Charlotte Dup",
            is_home=True,
            start_time=now,
            venue="Extreme Ice Dup",
        )

        deduped = _dedupe_records([r1, r2, r1_dup])
        assert len(deduped) == 2
        assert deduped[0].opponent_name == "UNC Charlotte"
        assert deduped[1].opponent_name == "Alabama"

    def test_resolve_page_season(self) -> None:
        """Verify season resolution with record metadata or fallback."""
        now = datetime.now(UTC)
        r_meta = ParsedGameRecord(
            game_id="g1",
            opponent_name="Alabama",
            is_home=True,
            start_time=now,
            venue="V1",
            metadata={"season": "2025-2026"},
        )
        assert _resolve_page_season(r_meta) == "2025-2026"

        r_empty = ParsedGameRecord(
            game_id="g2",
            opponent_name="Alabama",
            is_home=True,
            start_time=now,
            venue="V2",
        )
        assert _resolve_page_season(r_empty) == DEFAULT_ACHA_SEASON

    def test_resolve_target_season_id(self) -> None:
        """Verify matching season query against label and ID."""
        available = {"2026-2027": "73", "2025-2026": "60"}
        assert _resolve_target_season_id("2026-2027", available) == (
            "2026-2027",
            "73",
        )
        assert _resolve_target_season_id("60", available) == ("2025-2026", "60")
        assert _resolve_target_season_id("unknown", available) is None

    def test_resolve_crawl_targets(self) -> None:
        """Verify season target resolution with None or explicit filter list."""
        available = {"2026-2027": "73", "2025-2026": "60"}
        assert _resolve_crawl_targets(None, available) == available

        filtered = _resolve_crawl_targets(["2026-2027", "unknown"], available)
        assert filtered == {"2026-2027": "73"}

    def test_to_source_records(self) -> None:
        """Verify conversion from ParsedGameRecord to SourceGameRecord."""
        now = datetime.now(UTC)
        r_win = ParsedGameRecord(
            game_id="g1",
            opponent_name="Duke",
            is_home=True,
            start_time=now,
            venue="Carolina Ice Zone",
            home_score=5,
            away_score=2,
            metadata={"season": "2026-2027"},
        )
        r_sched = ParsedGameRecord(
            game_id="g2",
            opponent_name="UNCW",
            is_home=False,
            start_time=now,
            venue="Wilmington",
        )

        src_recs = ACHAHockeyCrawler.to_source_records([r_win, r_sched])
        assert len(src_recs) == 2
        assert src_recs[0].source_type == DataSourceType.LEAGUE
        assert src_recs[0].source_code == "achahockey"
        assert src_recs[0].result is not None
        assert src_recs[0].result.value == "W"
        assert src_recs[1].result is None


class TestACHAHockeyCrawlerAsync:
    """Test asynchronous crawling and discovery routines with mocked HTTP client."""

    @pytest.mark.anyio
    async def test_discover_seasons_success(self) -> None:
        """Verify successful dynamic season discovery."""
        seasons_json = _read_fixture_str("seasons.json")
        client = ResilientHttpClient()
        client.fetch_text = AsyncMock(return_value=(seasons_json, "a" * 64))  # type: ignore[method-assign]
        obs = MagicMock()

        crawler = ACHAHockeyCrawler(client=client, observer=obs)
        discovered = await crawler.discover_seasons()

        assert "2026-2027" in discovered
        assert discovered["2026-2027"] == "73"
        obs.on_scrape.assert_called_once()

    @pytest.mark.anyio
    async def test_discover_seasons_failure_fallback(self) -> None:
        """Verify fallback to KNOWN_SEASONS when discovery fails."""
        client = ResilientHttpClient()
        client.fetch_text = AsyncMock(side_effect=RuntimeError("Network error"))  # type: ignore[method-assign]
        obs = MagicMock()

        crawler = ACHAHockeyCrawler(client=client, observer=obs)
        fallback = await crawler.discover_seasons()

        assert fallback == KNOWN_SEASONS
        obs.on_scrape.assert_called_once()

    @pytest.mark.anyio
    async def test_fetch_schedule_for_season(self) -> None:
        """Verify schedule fetching for a specific season ID."""
        sched_json = _read_fixture_str("season_73.json")
        client = ResilientHttpClient()
        client.fetch_text = AsyncMock(return_value=(sched_json, "a" * 64))  # type: ignore[method-assign]
        obs = MagicMock()

        crawler = ACHAHockeyCrawler(client=client, observer=obs)
        records, payload, content_hash = await crawler.fetch_schedule_for_season(
            "73",
            season_hint="2026-2027",
        )

        assert len(records) == 6
        assert "34694" in payload
        assert len(content_hash) == 64
        obs.on_scrape.assert_called_once()

    @pytest.mark.anyio
    async def test_crawl_target_seasons(self) -> None:
        """Verify crawling multiple target seasons."""
        sched_73 = _read_fixture_str("season_73.json")
        client = ResilientHttpClient()
        client.fetch_text = AsyncMock(return_value=(sched_73, "a" * 64))  # type: ignore[method-assign]

        crawler = ACHAHockeyCrawler(client=client)
        records, payload, chash, ctype = await crawler.crawl(
            seasons=["2026-2027"],
            discover_future=False,
        )

        assert len(records) == 6
        assert ctype == "application/json"
        assert len(chash) == 64
        payload_data = json.loads(payload)
        assert len(payload_data) == 1
        assert payload_data[0]["season"] == "2026-2027"

    @pytest.mark.anyio
    async def test_crawl_and_sync_persistence(self, db_session: Session) -> None:
        """Verify database persistence of snapshot and game entities."""
        sched_73 = _read_fixture_str("season_73.json")
        client = ResilientHttpClient()
        client.fetch_text = AsyncMock(return_value=(sched_73, "a" * 64))  # type: ignore[method-assign]

        crawler = ACHAHockeyCrawler(client=client)
        audit = await crawler.crawl_and_sync(
            db_session,
            source_code="league_achahockey",
            seasons=["2026-2027"],
            discover_future=False,
        )

        assert audit.status == SyncStatus.SUCCESS.value
        assert audit.games_created == 6
        assert audit.games_updated == 0

        source = db_session.scalar(
            select(DataSourceModel).where(
                DataSourceModel.source_code == "league_achahockey",
            ),
        )
        assert source is not None
        assert source.name == "ACHA Master League Portal"
        assert source.last_scraped_at is not None

        snapshots = db_session.scalars(select(RawSnapshotModel)).all()
        assert len(snapshots) == 1

        games = db_session.scalars(select(GameModel)).all()
        assert len(games) == 6

        # Repeat crawl to test update branch
        audit_update = await crawler.crawl_and_sync(
            db_session,
            source_code="league_achahockey",
            seasons=["2026-2027"],
            discover_future=False,
        )
        assert audit_update.status == SyncStatus.SUCCESS.value
        assert audit_update.games_created == 0
        assert audit_update.games_updated == 6

    @pytest.mark.anyio
    async def test_crawl_and_sync_failure_audit(
        self,
        db_session: Session,
    ) -> None:
        """Verify audit failure logging when crawl raises an unhandled error."""
        client = ResilientHttpClient()
        client.fetch_text = AsyncMock(side_effect=RuntimeError("Sync error"))  # type: ignore[method-assign]

        crawler = ACHAHockeyCrawler(client=client)
        with pytest.raises(RuntimeError, match="Sync error"):
            await crawler.crawl_and_sync(
                db_session,
                source_code="league_achahockey",
                seasons=["2026-2027"],
                discover_future=False,
            )

        failed_audit = db_session.scalar(select(SyncAuditModel))
        assert failed_audit is not None
        assert failed_audit.status == SyncStatus.FAILURE.value
        assert "Sync error" in (failed_audit.error_message or "")
