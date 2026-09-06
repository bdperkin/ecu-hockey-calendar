"""Unit tests for the ACCHL league schedule crawler and database synchronization."""

# pylint: disable=protected-access

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ecu_hockey_calendar.ingestion.acchockey_crawler import (
    DEFAULT_ACCHL_SCHEDULE_URL,
    ACCHockeyCrawler,
    _dedupe_records,
    _resolve_page_season,
)
from ecu_hockey_calendar.ingestion.client import ResilientHttpClient
from ecu_hockey_calendar.ingestion.html_parser import ParsedGameRecord
from ecu_hockey_calendar.storage.base import Base
from ecu_hockey_calendar.storage.models import (
    DataSourceType,
    GameModel,
    GameStatus,
    RawSnapshotModel,
    SyncAuditModel,
    SyncStatus,
)

if TYPE_CHECKING:
    from collections.abc import Generator

HTML_LANDING_PAGE = """
<!DOCTYPE html>
<html>
<head><title>East Carolina Hockey</title></head>
<body>
    <div class="contentTabs">
        <a href="/schedule/team_instance/10282704?subseason=950924">Schedule</a>
    </div>
</body>
</html>
"""

HTML_SCHEDULE_PAGE = """
<!DOCTYPE html>
<html>
<head><title>Schedule 2025-2026</title></head>
<body>
    <table class="statTable">
        <tr id="game_list_row_101" class="completed">
            <td>ME-1</td>
            <td>Sat Oct 4</td>
            <td><div class="scheduleListScore">5-2</div></td>
            <td><a class="teamName">Elon</a></td>
            <td>Hillsborough, NC</td>
            <td>TBD</td>
        </tr>
    </table>
</body>
</html>
"""

HTML_PAGE_PAGINATED = """
<!DOCTYPE html>
<html>
<head><title>Schedule 2025-2026</title></head>
<body>
    <table class="statTable">
        <tr id="game_list_row_102" class="completed">
            <td>ME-2</td>
            <td>Sat Oct 18</td>
            <td><div class="scheduleListScore">4-1</div></td>
            <td><a class="teamName">Charlotte</a></td>
            <td>Charlotte, NC</td>
            <td>TBD</td>
        </tr>
    </table>
    <div class="pagination">
        <a class="next_page" href="/schedule/team_instance/10282704?page=2">Next</a>
    </div>
</body>
</html>
"""

HTML_SUBSEASON_DROPDOWN = """
<!DOCTYPE html>
<html>
<head><title>Schedule 2025-2026</title></head>
<body>
    <table class="statTable">
        <tr id="game_list_row_103" class="completed">
            <td>ME-3</td>
            <td>Fri Oct 24</td>
            <td><div class="scheduleListScore">3-2</div></td>
            <td><a class="teamName">App State</a></td>
            <td>Fayetteville, NC</td>
            <td>TBD</td>
        </tr>
    </table>
    <select>
        <option value="/schedule/team_instance/99999?subseason=88888">2024-2025</option>
    </select>
</body>
</html>
"""


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """In-memory SQLite database session fixture."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session

    engine.dispose()


def test_crawler_initialization() -> None:
    """Verify default and customized initialization."""
    default_crawler = ACCHockeyCrawler()
    assert default_crawler.schedule_url == DEFAULT_ACCHL_SCHEDULE_URL
    assert default_crawler.base_url == "https://www.acchockey.com"
    assert isinstance(default_crawler.client, ResilientHttpClient)

    custom_client = ResilientHttpClient()
    custom_crawler = ACCHockeyCrawler(
        client=custom_client,
        base_url="https://custom.example.com",
        schedule_url="https://custom.example.com/sched",
    )
    assert custom_crawler.client is custom_client
    assert custom_crawler.base_url == "https://custom.example.com"
    assert custom_crawler.schedule_url == "https://custom.example.com/sched"


def test_dedupe_records() -> None:
    """Verify deduplication preserves first encounter order."""
    now = datetime.now(UTC)
    r1 = ParsedGameRecord(
        game_id="game-1",
        opponent_name="Elon",
        is_home=True,
        start_time=now,
        venue="Venue 1",
    )
    r2 = ParsedGameRecord(
        game_id="game-2",
        opponent_name="Charlotte",
        is_home=False,
        start_time=now,
        venue="Venue 2",
    )
    r1_dup = ParsedGameRecord(
        game_id="game-1",
        opponent_name="Elon Duplicate",
        is_home=True,
        start_time=now,
        venue="Venue 1 Dup",
    )

    deduped = _dedupe_records([r1, r2, r1_dup])
    assert len(deduped) == 2
    assert deduped[0].opponent_name == "Elon"
    assert deduped[1].opponent_name == "Charlotte"


def test_resolve_page_season() -> None:
    """Verify season string resolution with metadata and fallback."""
    now = datetime.now(UTC)
    r_meta = ParsedGameRecord(
        game_id="g1",
        opponent_name="Elon",
        is_home=True,
        start_time=now,
        venue="V1",
        metadata={"season": "2024-2025"},
    )
    assert _resolve_page_season(r_meta) == "2024-2025"

    r_none = ParsedGameRecord(
        game_id="g2",
        opponent_name="Charlotte",
        is_home=True,
        start_time=now,
        venue="V2",
    )
    assert _resolve_page_season(r_none, "2026-2027") == "2026-2027"


@pytest.mark.anyio
async def test_fetch_landing_or_schedule() -> None:
    """Verify schedule retrieval from direct table and landing page redirect."""
    client = ResilientHttpClient()
    crawler = ACCHockeyCrawler(client=client)

    # 1. Page with statTable directly
    client.fetch_text = AsyncMock(return_value=(HTML_SCHEDULE_PAGE, "hash1"))  # type: ignore[method-assign]
    _html1, recs = await crawler._fetch_landing_or_schedule("https://example.com/sched")
    assert len(recs) == 1
    assert recs[0].opponent_name == "Elon University"

    # 2. Landing page that links to schedule
    client.fetch_text = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            (HTML_LANDING_PAGE, "hash_landing"),
            (HTML_SCHEDULE_PAGE, "hash_sched"),
        ],
    )
    html2, recs2 = await crawler._fetch_landing_or_schedule(
        "https://example.com/landing",
    )
    assert len(recs2) == 1
    assert HTML_LANDING_PAGE in html2
    assert HTML_SCHEDULE_PAGE in html2

    # 3. Landing page without schedule links
    client.fetch_text = AsyncMock(return_value=("<div>Empty</div>", "hash_empty"))  # type: ignore[method-assign]
    _html3, recs3 = await crawler._fetch_landing_or_schedule(
        "https://example.com/empty",
    )
    assert len(recs3) == 0


@pytest.mark.anyio
async def test_crawl_pagination_and_subseasons() -> None:
    """Verify traversal of pagination links and subseason dropdowns."""
    client = ResilientHttpClient()
    crawler = ACCHockeyCrawler(client=client)

    # Pagination test
    client.fetch_text = AsyncMock(return_value=(HTML_SCHEDULE_PAGE, "h1"))  # type: ignore[method-assign]
    visited_pages: set[str] = {"https://www.acchockey.com/initial"}
    recs, chunks = await crawler._crawl_pagination(
        HTML_PAGE_PAGINATED,
        visited_pages,
        max_pages=5,
    )
    assert len(recs) == 1
    assert len(chunks) == 1
    assert len(visited_pages) == 2

    # Max pages limit hit
    recs_limit, _ = await crawler._crawl_pagination(
        HTML_PAGE_PAGINATED,
        visited_pages,
        max_pages=2,
    )
    assert len(recs_limit) == 0

    # Already visited pagination link skipped
    recs_skipped, _ = await crawler._crawl_pagination(
        HTML_PAGE_PAGINATED,
        visited_pages,
        max_pages=10,
    )
    assert len(recs_skipped) == 0

    # Subseason test
    crawler._fetch_landing_or_schedule = AsyncMock(  # type: ignore[method-assign]
        return_value=(HTML_SCHEDULE_PAGE, recs),
    )
    visited_subs: set[str] = {"https://www.acchockey.com/initial"}
    sub_recs, sub_chunks = await crawler._crawl_subseasons(
        HTML_SUBSEASON_DROPDOWN,
        visited_subs,
        max_pages=5,
    )
    assert len(sub_recs) == 1
    assert len(sub_chunks) == 1
    assert len(visited_subs) == 2

    # Max pages limit hit for subseasons
    sub_limit, _ = await crawler._crawl_subseasons(
        HTML_SUBSEASON_DROPDOWN,
        visited_subs,
        max_pages=2,
    )
    assert len(sub_limit) == 0

    # Already visited subseason link skipped
    sub_skip, _ = await crawler._crawl_subseasons(
        HTML_SUBSEASON_DROPDOWN,
        visited_subs,
        max_pages=10,
    )
    assert len(sub_skip) == 0


@pytest.mark.anyio
async def test_fetch_schedule_and_crawl() -> None:
    """Verify aggregate fetch_schedule and crawl method outputs."""
    client = ResilientHttpClient()
    crawler = ACCHockeyCrawler(client=client)

    crawler._fetch_landing_or_schedule = AsyncMock(  # type: ignore[method-assign]
        return_value=(HTML_SCHEDULE_PAGE, []),
    )
    crawler._crawl_pagination = AsyncMock(  # type: ignore[method-assign]
        return_value=([], []),
    )
    crawler._crawl_subseasons = AsyncMock(  # type: ignore[method-assign]
        return_value=([], []),
    )

    recs, _raw_payload, content_hash, content_type = await crawler.crawl(
        include_subseasons=True,
    )
    assert isinstance(recs, list)
    assert content_type == "text/html"
    assert len(content_hash) == 64


def test_finalize_audit() -> None:
    """Verify SyncAuditModel timestamp, duration, and error updating."""
    started_at = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
    audit = SyncAuditModel(
        source_id=1,
        sync_cycle_id="sync-test",
        started_at=started_at,
        status=SyncStatus.RUNNING.value,
    )
    ACCHockeyCrawler._finalize_audit(
        audit,
        started_at,
        SyncStatus.SUCCESS,
    )
    assert audit.status == SyncStatus.SUCCESS.value
    assert audit.completed_at is not None
    assert audit.duration_ms is not None
    assert audit.duration_ms >= 0

    ACCHockeyCrawler._finalize_audit(
        audit,
        started_at,
        SyncStatus.FAILURE,
        error_message="Network failure",
    )
    assert audit.status == SyncStatus.FAILURE.value
    assert audit.error_message == "Network failure"


def test_get_or_create_source_and_team(db_session: Session) -> None:
    """Verify database helpers for DataSource and Team models."""
    crawler = ACCHockeyCrawler()
    source1 = crawler._get_or_create_source(db_session, "league_acchockey")
    assert source1.source_code == "league_acchockey"
    assert source1.source_type == DataSourceType.LEAGUE.value
    assert source1.priority_order == 2

    # Calling again returns same model
    source2 = crawler._get_or_create_source(db_session, "league_acchockey")
    assert source2.id == source1.id

    team1 = crawler._get_or_create_team(db_session, "Elon University")
    assert team1.name == "Elon University"

    team2 = crawler._get_or_create_team(db_session, "Elon University")
    assert team2.id == team1.id


def test_upsert_game_and_persist_records(db_session: Session) -> None:
    """Verify game model creation and updates during sync."""
    crawler = ACCHockeyCrawler()
    ecu = crawler._get_or_create_team(db_session, "East Carolina University")

    now = datetime(2025, 10, 4, 19, 0, tzinfo=UTC)
    rec = ParsedGameRecord(
        game_id="ecu-away-elon-20251004",
        opponent_name="Elon University",
        is_home=False,
        start_time=now,
        venue="Hillsborough, NC",
        status=GameStatus.SCHEDULED,
        league_game_id="ME-1",
        metadata={"season": "2025-2026"},
    )

    created, updated = crawler._persist_records(db_session, [rec], ecu.id)
    assert created == 1
    assert updated == 0

    game = db_session.scalar(select(GameModel).where(GameModel.game_id == rec.game_id))
    assert game is not None
    assert game.status == GameStatus.SCHEDULED.value

    # Update with final score
    rec_final = ParsedGameRecord(
        game_id="ecu-away-elon-20251004",
        opponent_name="Elon University",
        is_home=False,
        start_time=now,
        venue="Hillsborough, NC",
        status=GameStatus.FINAL,
        home_score=5,
        away_score=2,
        league_game_id="ME-1",
        metadata={"season": "2025-2026"},
    )
    created2, updated2 = crawler._persist_records(db_session, [rec_final], ecu.id)
    assert created2 == 0
    assert updated2 == 1

    db_session.refresh(game)
    assert game.status == GameStatus.FINAL.value
    assert game.home_score == 5
    assert game.away_score == 2


@pytest.mark.anyio
async def test_crawl_and_sync_success(db_session: Session) -> None:
    """Verify complete end-to-end sync cycle into relational storage."""
    client = ResilientHttpClient()
    client.fetch_text = AsyncMock(return_value=(HTML_SCHEDULE_PAGE, "hash_test"))  # type: ignore[method-assign]
    crawler = ACCHockeyCrawler(client=client)

    audit = await crawler.crawl_and_sync(db_session)
    assert audit.status == SyncStatus.SUCCESS.value
    assert audit.games_created == 1
    assert audit.games_updated == 0

    # Verify RawSnapshotModel persisted
    snapshot = db_session.scalar(
        select(RawSnapshotModel).where(RawSnapshotModel.source_id == audit.source_id),
    )
    assert snapshot is not None
    assert snapshot.content_type == "text/html"

    # Verify GameModel persisted
    game = db_session.scalar(select(GameModel))
    assert game is not None
    assert game.home_score == 5
    assert game.away_score == 2


@pytest.mark.anyio
async def test_crawl_and_sync_failure(db_session: Session) -> None:
    """Verify error audit recording and re-raising on crawl failure."""
    crawler = ACCHockeyCrawler()
    crawler.crawl = AsyncMock(side_effect=RuntimeError("Simulated network drop"))  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="Simulated network drop"):
        await crawler.crawl_and_sync(db_session)

    # Verify audit failure recorded
    audit = db_session.scalar(select(SyncAuditModel).order_by(SyncAuditModel.id.desc()))
    assert audit is not None
    assert audit.status == SyncStatus.FAILURE.value
    assert "Simulated network drop" in str(audit.error_message)
