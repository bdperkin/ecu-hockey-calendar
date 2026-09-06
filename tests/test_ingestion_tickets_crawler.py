"""Unit tests for the ECU Hockey ticketing crawler and database synchronization."""

# pylint: disable=protected-access

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ecu_hockey_calendar.ingestion.client import ResilientHttpClient
from ecu_hockey_calendar.ingestion.tickets_crawler import (
    DEFAULT_FIRESTORE_URL,
    DEFAULT_TEAM_ID,
    DEFAULT_TICKETS_PAGE_URL,
    TicketsCrawler,
)
from ecu_hockey_calendar.ingestion.tickets_parser import ParsedTicketRecord
from ecu_hockey_calendar.storage.base import Base
from ecu_hockey_calendar.storage.models import (
    DataSourceModel,
    DataSourceType,
    GameModel,
    RawSnapshotModel,
    SyncAuditModel,
    SyncStatus,
    TeamModel,
)

if TYPE_CHECKING:
    from collections.abc import Generator

SAMPLE_HTML_PAGE = """
<div class="tickets">
    <div class="ticket-card" id="t-1">
        <h3>ECU vs NC State - Military Appreciation</h3>
        <time>Oct 18, 2026 7:00 PM</time>
        <span class="venue">The Factory</span>
        <div class="price">$10.00</div>
        <a href="https://www.etix.com/checkout/1">Buy Tickets</a>
    </div>
</div>
"""

SAMPLE_FIRESTORE_RESPONSE = [
    {
        "document": {
            "name": (
                "projects/optimx-sports/databases/(default)/documents/tickets/lnjlh6od"
            ),
            "fields": {
                "id": {"stringValue": "lnjlh6od"},
                "title": {"stringValue": "ECU vs Duke - Senior Night"},
                "eventVenue": {"stringValue": "Wake Forest Ice"},
                "timeOfEvent": {"timestampValue": "2026-10-24T23:00:00Z"},
                "shortDescription": {"stringValue": "Senior Night"},
                "priceDescription": {"stringValue": "$15"},
                "inStock": {"booleanValue": True},
                "published": {"booleanValue": True},
                "deleted": {"booleanValue": False},
            },
        },
    },
]


@pytest.fixture
def sync_session() -> Generator[Session, None, None]:
    """In-memory SQLite database session for unit tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_tickets_crawler_initialization() -> None:
    """Verify default and customized initialization values."""
    crawler = TicketsCrawler()
    assert crawler.team_id == DEFAULT_TEAM_ID
    assert crawler.firestore_url == DEFAULT_FIRESTORE_URL
    assert crawler.tickets_url == DEFAULT_TICKETS_PAGE_URL

    custom_client = ResilientHttpClient()
    custom_crawler = TicketsCrawler(
        http_client=custom_client,
        team_id="custom-team",
        firestore_url="https://custom.firestore/query",
        tickets_url="https://custom.tickets/events",
    )
    assert custom_crawler.client is custom_client
    assert custom_crawler.team_id == "custom-team"
    assert custom_crawler.firestore_url == "https://custom.firestore/query"
    assert custom_crawler.tickets_url == "https://custom.tickets/events"


@pytest.mark.anyio
async def test_fetch_firestore_tickets() -> None:
    """Verify fetching and parsing tickets from the Firestore API."""
    mock_client = AsyncMock(spec=ResilientHttpClient)
    mock_client.post_json.return_value = (
        SAMPLE_FIRESTORE_RESPONSE,
        "dummy_hash_json",
    )

    crawler = TicketsCrawler(http_client=mock_client)
    records, raw_text, c_hash = await crawler.fetch_firestore_tickets()

    assert len(records) == 1
    assert records[0].ticket_id == "lnjlh6od"
    assert records[0].opponent_name == "Duke University"
    assert c_hash == "dummy_hash_json"
    assert "lnjlh6od" in raw_text
    mock_client.post_json.assert_awaited_once()


@pytest.mark.anyio
async def test_fetch_html_tickets() -> None:
    """Verify fetching and parsing tickets from HTML sales page."""
    mock_client = AsyncMock(spec=ResilientHttpClient)
    mock_client.fetch_text.return_value = (SAMPLE_HTML_PAGE, "dummy_hash_html")

    crawler = TicketsCrawler(http_client=mock_client)
    records, raw_text, c_hash = await crawler.fetch_html_tickets()

    assert len(records) == 1
    assert records[0].ticket_id == "t-1"
    assert records[0].opponent_name == "NC State University"
    assert c_hash == "dummy_hash_html"
    assert raw_text == SAMPLE_HTML_PAGE
    mock_client.fetch_text.assert_awaited_once_with(DEFAULT_TICKETS_PAGE_URL)


@pytest.mark.anyio
async def test_crawl_fallback_behavior() -> None:
    """Verify primary Firestore API usage with fallback to HTML."""
    mock_client = AsyncMock(spec=ResilientHttpClient)
    mock_client.post_json.return_value = (
        SAMPLE_FIRESTORE_RESPONSE,
        "hash_firestore",
    )
    mock_client.fetch_text.return_value = (SAMPLE_HTML_PAGE, "hash_html")

    crawler = TicketsCrawler(http_client=mock_client)

    # 1. Primary API succeeds
    recs, _raw, _c_hash, c_type = await crawler.crawl(try_firestore=True)
    assert len(recs) == 1
    assert recs[0].opponent_name == "Duke University"
    assert c_type == "application/json"

    # 2. Primary API raises network error -> falls back to HTML
    mock_client.post_json.side_effect = httpx.ConnectError("Network down")
    recs_fb, _raw_fb, _c_hash_fb, c_type_fb = await crawler.crawl(
        try_firestore=True,
    )
    assert len(recs_fb) == 1
    assert recs_fb[0].opponent_name == "NC State University"
    assert c_type_fb == "text/html"

    # 3. try_firestore=False skips API directly
    mock_client.post_json.reset_mock()
    recs_no_api, _, _, c_type_no_api = await crawler.crawl(try_firestore=False)
    assert len(recs_no_api) == 1
    assert c_type_no_api == "text/html"
    mock_client.post_json.assert_not_called()


@pytest.mark.anyio
async def test_crawl_and_sync_success(sync_session: Session) -> None:
    """Verify database synchronization creating snapshots, sources, and games."""
    mock_client = AsyncMock(spec=ResilientHttpClient)
    mock_client.post_json.return_value = (
        SAMPLE_FIRESTORE_RESPONSE,
        "hash_sync_1",
    )

    crawler = TicketsCrawler(http_client=mock_client)
    audit = await crawler.crawl_and_sync(sync_session)

    assert audit.status == SyncStatus.SUCCESS.value
    assert audit.games_created == 1
    assert audit.games_updated == 0

    # Verify DataSource created
    source = sync_session.scalar(
        select(DataSourceModel).where(
            DataSourceModel.source_code == "tickets_ecuhockey",
        ),
    )
    assert source is not None
    assert source.source_type == DataSourceType.TICKETS.value

    # Verify RawSnapshot created
    snapshot = sync_session.scalar(
        select(RawSnapshotModel).where(
            RawSnapshotModel.source_id == source.id,
        ),
    )
    assert snapshot is not None
    assert snapshot.content_type == "application/json"

    # Verify GameModel created
    game = sync_session.scalar(select(GameModel))
    assert game is not None
    assert game.venue == "Wake Forest Ice"

    # Verify second crawl updates instead of creating
    audit2 = await crawler.crawl_and_sync(sync_session)
    assert audit2.status == SyncStatus.SUCCESS.value
    assert audit2.games_created == 0
    assert audit2.games_updated == 1


@pytest.mark.anyio
async def test_crawl_and_sync_enrich_existing_game_venue(
    sync_session: Session,
) -> None:
    """Verify ticket with known venue enriches existing game with venue 'TBD'."""
    # Pre-insert existing game with venue TBD
    ecu = TeamModel(
        name="East Carolina University",
        city="Greenville",
        state="NC",
    )
    duke = TeamModel(name="Duke University", city="Durham", state="NC")
    sync_session.add_all([ecu, duke])
    sync_session.flush()

    dt = datetime(2026, 10, 24, 23, 0, tzinfo=UTC)
    game = GameModel(
        game_id="20261024-duke-university",
        home_team_id=ecu.id,
        away_team_id=duke.id,
        start_time=dt,
        venue="TBD",
        season="2026-2027",
    )
    sync_session.add(game)
    sync_session.commit()

    mock_client = AsyncMock(spec=ResilientHttpClient)
    mock_client.post_json.return_value = (
        SAMPLE_FIRESTORE_RESPONSE,
        "hash_enrich",
    )

    crawler = TicketsCrawler(http_client=mock_client)
    audit = await crawler.crawl_and_sync(sync_session)
    assert audit.status == SyncStatus.SUCCESS.value
    assert audit.games_updated == 1

    sync_session.refresh(game)
    assert game.venue == "Wake Forest Ice"


@pytest.mark.anyio
async def test_crawl_and_sync_failure_audit(sync_session: Session) -> None:
    """Verify that exceptions mark SyncAuditModel as FAILURE and roll back."""
    mock_client = AsyncMock(spec=ResilientHttpClient)
    mock_client.post_json.side_effect = RuntimeError("Fatal parsing error")
    mock_client.fetch_text.side_effect = RuntimeError("Fatal scraping error")

    crawler = TicketsCrawler(http_client=mock_client)

    with pytest.raises(RuntimeError, match="Fatal parsing error"):
        await crawler.crawl_and_sync(sync_session)

    # Verify failed audit record
    audit = sync_session.scalar(select(SyncAuditModel))
    assert audit is not None
    assert audit.status == SyncStatus.FAILURE.value
    assert "Fatal parsing error" in (audit.error_message or "")


@pytest.mark.anyio
async def test_crawl_empty_firestore_falls_back_to_html() -> None:
    """Verify that an empty list from Firestore triggers HTML fallback."""
    mock_client = AsyncMock(spec=ResilientHttpClient)
    mock_client.post_json.return_value = ([], "empty_hash")
    mock_client.fetch_text.return_value = (SAMPLE_HTML_PAGE, "html_hash")

    crawler = TicketsCrawler(http_client=mock_client)
    recs, _raw, c_hash, c_type = await crawler.crawl(try_firestore=True)

    assert len(recs) == 1
    assert c_type == "text/html"
    assert c_hash == "html_hash"


@pytest.mark.anyio
async def test_crawl_and_sync_ticket_filtering_and_existing_venue(
    sync_session: Session,
) -> None:
    """Verify filtering of away games, blank opponents, and no start time."""
    ecu = TeamModel(name="East Carolina University", city="Greenville", state="NC")
    duke = TeamModel(name="Duke University", city="Durham", state="NC")
    sync_session.add_all([ecu, duke])
    sync_session.flush()

    dt = datetime(2026, 10, 24, 23, 0, tzinfo=UTC)
    existing_game = GameModel(
        game_id="ecu-home-duke-university-20261024",
        home_team_id=ecu.id,
        away_team_id=duke.id,
        start_time=dt,
        venue="Fort Liberty Ice",
        season="2026-2027",
    )
    sync_session.add(existing_game)
    sync_session.commit()

    records = [
        # 1. Non-home game (should be skipped)
        ParsedTicketRecord(
            ticket_id="away-1",
            title="UNCW vs ECU",
            opponent_name="UNC Wilmington",
            is_home_game=False,
            start_time=dt,
        ),
        # 2. Blank opponent (should be skipped)
        ParsedTicketRecord(
            ticket_id="no-opp",
            title="General Admission",
            opponent_name=None,
            is_home_game=True,
            start_time=dt,
        ),
        # 3. Missing start_time (to_parsed_game_record returns None -> False)
        ParsedTicketRecord(
            ticket_id="no-time",
            title="Season Pass",
            opponent_name="Duke University",
            is_home_game=True,
            start_time=None,
        ),
        # 4. Matching existing game with non-TBD venue (should not overwrite)
        ParsedTicketRecord(
            ticket_id="duke-tkt",
            title="ECU vs Duke",
            opponent_name="Duke University",
            is_home_game=True,
            start_time=dt,
            venue="Wake Forest Ice",
        ),
    ]

    crawler = TicketsCrawler()
    created, updated = crawler._persist_records(
        sync_session,
        records,
        ecu.id,
        "2026-2027",
    )

    assert created == 0
    # Both records[2] (returns False) and records[3] (returns False)
    # contribute to updated
    assert updated == 2
    sync_session.refresh(existing_game)
    assert existing_game.venue == "Fort Liberty Ice"
