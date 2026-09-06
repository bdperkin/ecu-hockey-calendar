"""Tests for ECUHockeyCrawler and Firestore document parsing."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from ecu_hockey_calendar.ingestion.client import ResilientHttpClient
from ecu_hockey_calendar.ingestion.ecuhockey_crawler import (
    DEFAULT_FIRESTORE_URL,
    DEFAULT_TEAM_ID,
    ECUHockeyCrawler,
    _clean_title_opponent,
    _extract_firestore_value,
    _parse_firestore_datetime,
    parse_firestore_game_document,
)
from ecu_hockey_calendar.models import GameResult
from ecu_hockey_calendar.storage import (
    DataSourceModel,
    GameModel,
    GameStatus,
    RawSnapshotModel,
    SyncAuditModel,
    SyncStatus,
    TeamModel,
    create_sync_engine,
    get_sync_session,
    init_db,
)


@pytest.fixture
def sync_memory_engine():
    """Provide an in-memory SQLite sync engine initialized with schema."""
    engine = create_sync_engine("sqlite:///:memory:")
    init_db(engine)
    return engine


def test_extract_firestore_value() -> None:
    """Verify Firestore value extraction across types and edge cases."""
    assert _extract_firestore_value(None) is None
    assert _extract_firestore_value({}) is None
    assert _extract_firestore_value({"stringValue": "hello"}) == "hello"
    assert _extract_firestore_value({"booleanValue": True}) is True
    assert _extract_firestore_value({"integerValue": "42"}) == 42
    assert (
        _extract_firestore_value({"timestampValue": "2026-09-05T00:00:00Z"})
        == "2026-09-05T00:00:00Z"
    )
    assert _extract_firestore_value({"nullValue": None}) is None


def test_clean_title_opponent() -> None:
    """Verify regex extraction of opponent names from game titles."""
    assert _clean_title_opponent("Game vs Alabama D2 on 09/05/2026") == "Alabama D2"
    assert _clean_title_opponent("vs NC State") == "NC State"
    assert _clean_title_opponent("@ UNC Wilmington on Friday") == "UNC Wilmington"
    assert _clean_title_opponent("Standalone Title") == "Standalone Title"


def test_parse_firestore_datetime() -> None:
    """Verify parsing ISO Firestore timestamp string into UTC datetime."""
    assert _parse_firestore_datetime(None) is None
    assert _parse_firestore_datetime("") is None
    assert _parse_firestore_datetime("invalid-date") is None
    dt = _parse_firestore_datetime("2026-09-05T23:00:00Z")
    assert dt == datetime(2026, 9, 5, 23, 0, tzinfo=UTC)


def test_parse_firestore_game_document_valid() -> None:
    """Verify parsing a valid Firestore game document into ParsedGameRecord."""
    doc = {
        "fields": {
            "id": {"stringValue": "game-doc-123"},
            "timeOfGame": {"stringValue": "2026-09-05T23:00:00Z"},
            "title": {"stringValue": "Game vs Alabama D2 on Sep 5"},
            "venue": {"stringValue": "Carolina Ice Zone"},
            "homeGame": {"booleanValue": True},
            "status": {"stringValue": "final"},
            "gameScore": {"stringValue": "5 - 3"},
        },
    }
    rec = parse_firestore_game_document(doc)
    assert rec is not None
    assert rec.game_id == "game-doc-123"
    assert rec.opponent_name == "University of Alabama (D2)"
    assert rec.is_home is True
    assert rec.start_time == datetime(2026, 9, 5, 23, 0, tzinfo=UTC)
    assert rec.venue == "Carolina Ice Zone"
    assert rec.status == GameStatus.FINAL
    assert rec.home_score == 5
    assert rec.away_score == 3
    assert rec.calculate_result() == GameResult.WIN


def test_parse_firestore_game_document_defaults_and_away() -> None:
    """Verify parsing Firestore document with away status and empty title."""
    doc = {
        "fields": {
            "id": {"stringValue": "game-doc-456"},
            "timeOfGame": {"stringValue": "2026-10-10T00:00:00Z"},
            "title": {"stringValue": ""},
            "homeGame": {"booleanValue": False},
        },
    }
    rec = parse_firestore_game_document(doc)
    assert rec is not None
    assert rec.game_id == "game-doc-456"
    assert rec.opponent_name == "Opponent"
    assert rec.is_home is False
    assert rec.venue == "Carolina Ice Zone"
    assert rec.status == GameStatus.SCHEDULED
    assert rec.home_score is None
    assert rec.away_score is None


def test_parse_firestore_game_document_invalid() -> None:
    """Verify None returned for missing fields or malformed dates."""
    # Missing fields dict
    assert parse_firestore_game_document({}) is None
    assert parse_firestore_game_document({"fields": "not-a-dict"}) is None

    # Missing id or timeOfGame
    assert (
        parse_firestore_game_document({"fields": {"id": {"stringValue": "123"}}})
        is None
    )
    assert (
        parse_firestore_game_document(
            {"fields": {"timeOfGame": {"stringValue": "2026-01-01"}}},
        )
        is None
    )

    # Malformed datetime
    bad_date_doc = {
        "fields": {
            "id": {"stringValue": "123"},
            "timeOfGame": {"stringValue": "not-an-iso-date"},
        },
    }
    assert parse_firestore_game_document(bad_date_doc) is None


def test_crawler_defaults_and_init() -> None:
    """Verify ECUHockeyCrawler initializes with default and custom arguments."""
    crawler = ECUHockeyCrawler()
    assert crawler.team_id == DEFAULT_TEAM_ID
    assert crawler.firestore_url == DEFAULT_FIRESTORE_URL

    custom_client = ResilientHttpClient()
    custom_crawler = ECUHockeyCrawler(
        client=custom_client,
        team_id="custom-team",
        firestore_url="https://custom.api/query",
    )
    assert custom_crawler.client is custom_client
    assert custom_crawler.team_id == "custom-team"
    assert custom_crawler.firestore_url == "https://custom.api/query"


def test_fetch_api_games_success() -> None:
    """Verify fetch_api_games queries Firestore and parses records."""
    mock_payload = [
        {
            "document": {
                "fields": {
                    "id": {"stringValue": "g1"},
                    "timeOfGame": {"stringValue": "2026-09-12T23:00:00Z"},
                    "title": {"stringValue": "vs NC State"},
                    "homeGame": {"booleanValue": True},
                },
            },
        },
        {"document": {"fields": {}}},  # Malformed document ignored
        {"no_document": 123},  # Non-document element ignored
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        """Mock HTTP handler for Firestore query."""
        assert request.method == "POST"
        assert "optimx-sports" in str(request.url)
        return httpx.Response(200, json=mock_payload)

    transport = httpx.MockTransport(handler)

    async def _run() -> None:
        """Execute fetch_api_games success test."""
        async with ResilientHttpClient(transport=transport) as client:
            crawler = ECUHockeyCrawler(client=client)
            records, raw_text, content_hash = await crawler.fetch_api_games()
            assert len(records) == 1
            assert records[0].game_id == "g1"
            assert len(content_hash) == 64
            assert "optimx-sports" not in raw_text or "g1" in raw_text

    asyncio.run(_run())


def test_fetch_html_games_success() -> None:
    """Verify fetch_html_games retrieves HTML schedule and parses it."""
    html_content = """
    <html><body>
    <table>
        <tr><th>Date</th><th>Opponent</th><th>Time</th><th>Location</th></tr>
        <tr>
            <td>09/20/2026</td>
            <td>vs Duke</td>
            <td>7:00 PM</td>
            <td>Carolina Ice Zone</td>
        </tr>
    </table>
    </body></html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        """Mock HTTP handler for HTML schedule."""
        del request
        return httpx.Response(200, text=html_content)

    transport = httpx.MockTransport(handler)

    async def _run() -> None:
        """Execute fetch_html_games success test."""
        async with ResilientHttpClient(transport=transport) as client:
            crawler = ECUHockeyCrawler(client=client)
            records, raw_text, content_hash = await crawler.fetch_html_games()
            assert len(records) == 1
            assert records[0].opponent_name == "Duke University"
            assert "09/20/2026" in raw_text
            assert len(content_hash) == 64

    asyncio.run(_run())


def test_fetch_api_games_non_list_response() -> None:
    """Verify fetch_api_games gracefully handles non-list payload."""
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"error": "denied"}),
    )

    async def _run() -> None:
        """Execute non-list response test."""
        async with ResilientHttpClient(transport=transport) as client:
            crawler = ECUHockeyCrawler(client=client)
            records, raw_text, content_hash = await crawler.fetch_api_games()
            assert not records
            assert "error" in raw_text
            assert len(content_hash) == 64

    asyncio.run(_run())


def test_crawl_prefer_api_scenarios() -> None:
    """Verify crawl prefers API and falls back to HTML when API is empty."""
    html_content = """
    <table>
        <tr><th>Date</th><th>Opponent</th><th>Time</th></tr>
        <tr><td>10/01/2026</td><td>vs Liberty</td><td>7:00 PM</td></tr>
    </table>
    """

    # Scenario 1: API returns records
    api_payload = [
        {
            "document": {
                "fields": {
                    "id": {"stringValue": "api-game-1"},
                    "timeOfGame": {"stringValue": "2026-10-01T23:00:00Z"},
                    "title": {"stringValue": "vs Liberty"},
                },
            },
        },
    ]

    transport_api_ok = httpx.MockTransport(
        lambda _: httpx.Response(200, json=api_payload),
    )

    async def _run_api_ok() -> None:
        """Execute API success fallback scenario."""
        async with ResilientHttpClient(transport=transport_api_ok) as client:
            crawler = ECUHockeyCrawler(client=client)
            recs, raw, chash, ctype = await crawler.crawl(prefer_api=True)
            assert len(recs) == 1
            assert recs[0].game_id == "api-game-1"
            assert raw
            assert len(chash) == 64
            assert ctype == "application/json"

    asyncio.run(_run_api_ok())

    # Scenario 2: API returns empty list -> fallback to HTML
    def handler_api_empty(request: httpx.Request) -> httpx.Response:
        """Mock HTTP handler returning empty API list."""
        if request.method == "POST":
            return httpx.Response(200, json=[])

        return httpx.Response(200, text=html_content)

    transport_api_empty = httpx.MockTransport(handler_api_empty)

    async def _run_api_empty() -> None:
        """Execute API empty fallback scenario."""
        async with ResilientHttpClient(transport=transport_api_empty) as client:
            crawler = ECUHockeyCrawler(client=client)
            recs, raw, chash, ctype = await crawler.crawl(prefer_api=True)
            assert len(recs) == 1
            assert recs[0].opponent_name == "Liberty"
            assert raw
            assert len(chash) == 64
            assert ctype == "text/html"

    asyncio.run(_run_api_empty())


def test_crawl_fallback_and_html_direct() -> None:
    """Verify crawl falls back to HTML on API failure or when preferred."""
    html_content = """
    <table>
        <tr><th>Date</th><th>Opponent</th><th>Time</th></tr>
        <tr><td>10/01/2026</td><td>vs Liberty</td><td>7:00 PM</td></tr>
    </table>
    """

    # Scenario 3: API raises error -> fallback to HTML
    def handler_api_fail(request: httpx.Request) -> httpx.Response:
        """Mock HTTP handler returning 500 error."""
        if request.method == "POST":
            return httpx.Response(500, text="Internal Server Error")

        return httpx.Response(200, text=html_content)

    transport_api_fail = httpx.MockTransport(handler_api_fail)

    async def _run_api_fail() -> None:
        """Execute API failure fallback scenario."""
        async with ResilientHttpClient(
            transport=transport_api_fail,
            max_retries=0,
        ) as client:
            crawler = ECUHockeyCrawler(client=client)
            recs, raw, chash, ctype = await crawler.crawl(prefer_api=True)
            assert len(recs) == 1
            assert recs[0].opponent_name == "Liberty"
            assert raw
            assert len(chash) == 64
            assert ctype == "text/html"

    asyncio.run(_run_api_fail())

    # Scenario 4: prefer_api=False -> directly calls fetch_html_games
    transport_html_direct = httpx.MockTransport(
        lambda _: httpx.Response(200, text=html_content),
    )

    async def _run_html_direct() -> None:
        """Execute HTML direct fallback scenario."""
        async with ResilientHttpClient(transport=transport_html_direct) as client:
            crawler = ECUHockeyCrawler(client=client)
            recs, raw, chash, ctype = await crawler.crawl(prefer_api=False)
            assert len(recs) == 1
            assert raw
            assert len(chash) == 64
            assert ctype == "text/html"

    asyncio.run(_run_html_direct())


def test_crawl_and_sync_lifecycle(sync_memory_engine) -> None:
    """Verify full crawl_and_sync lifecycle: data source, snapshot, games, and audit."""
    api_payload: list[dict[str, Any]] = [
        {
            "document": {
                "fields": {
                    "id": {"stringValue": "game-2026-001"},
                    "timeOfGame": {"stringValue": "2026-10-15T23:00:00Z"},
                    "title": {"stringValue": "Game vs NC State on Oct 15"},
                    "venue": {"stringValue": "Carolina Ice Zone"},
                    "homeGame": {"booleanValue": True},
                    "status": {"stringValue": "final"},
                    "gameScore": {"stringValue": "4 - 2"},
                },
            },
        },
        {
            "document": {
                "fields": {
                    "id": {"stringValue": "game-2026-002"},
                    "timeOfGame": {"stringValue": "2026-10-22T23:30:00Z"},
                    "title": {"stringValue": "@ Wake Forest on Oct 22"},
                    "venue": {"stringValue": "Fairgrounds Arena"},
                    "homeGame": {"booleanValue": False},
                    "status": {"stringValue": "scheduled"},
                },
            },
        },
    ]

    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=api_payload))

    async def _run() -> None:
        """Execute crawl_and_sync lifecycle test."""
        async with ResilientHttpClient(transport=transport) as client:
            crawler = ECUHockeyCrawler(client=client)

            # 1. Initial Sync: Creates records
            with get_sync_session(sync_memory_engine) as session:
                audit = await crawler.crawl_and_sync(session, source_code="primary_sot")
                assert audit.status == SyncStatus.SUCCESS.value
                assert audit.games_created == 2
                assert audit.games_updated == 0
                assert audit.duration_ms is not None

                # Verify DataSourceModel created
                source = session.scalar(
                    select(DataSourceModel).where(
                        DataSourceModel.source_code == "primary_sot",
                    ),
                )
                assert source is not None
                assert source.last_scraped_at is not None

                # Verify RawSnapshotModel
                snaps = session.scalars(select(RawSnapshotModel)).all()
                assert len(snaps) == 1
                assert snaps[0].content_type == "application/json"

                # Verify Teams
                teams = session.scalars(select(TeamModel)).all()
                team_names = {t.name for t in teams}
                assert "East Carolina University" in team_names
                assert "NC State University" in team_names
                assert "Wake Forest University" in team_names

                # Verify Games
                games = session.scalars(select(GameModel)).all()
                assert len(games) == 2
                g1 = session.scalar(
                    select(GameModel).where(GameModel.game_id == "game-2026-001"),
                )
                assert g1 is not None
                assert g1.home_score == 4
                assert g1.away_score == 2
                assert g1.result == "W"

            # 2. Subsequent Sync: Updates records
            # Mutate score in payload
            api_payload[0]["document"]["fields"]["gameScore"] = {"stringValue": "5 - 2"}
            with get_sync_session(sync_memory_engine) as session:
                audit2 = await crawler.crawl_and_sync(
                    session,
                    source_code="primary_sot",
                )
                assert audit2.status == SyncStatus.SUCCESS.value
                assert audit2.games_created == 0
                assert audit2.games_updated == 2

                g1_updated = session.scalar(
                    select(GameModel).where(GameModel.game_id == "game-2026-001"),
                )
                assert g1_updated is not None
                assert g1_updated.home_score == 5

    asyncio.run(_run())


def test_crawl_and_sync_error_handling(sync_memory_engine) -> None:
    """Verify crawl_and_sync marks audit status as FAILED when exception occurs."""

    def handler(request: httpx.Request) -> httpx.Response:
        """Mock HTTP handler returning 500 error."""
        del request
        return httpx.Response(500, text="Database Unavailable")

    transport = httpx.MockTransport(handler)

    async def _run() -> None:
        """Execute crawl_and_sync error handling test."""
        async with ResilientHttpClient(transport=transport, max_retries=0) as client:
            crawler = ECUHockeyCrawler(client=client)

            with get_sync_session(sync_memory_engine) as session:
                with pytest.raises(httpx.HTTPStatusError):
                    await crawler.crawl_and_sync(session, source_code="failing_source")

                # Verify audit record marked as FAILED
                audit = session.scalar(select(SyncAuditModel))
                assert audit is not None
                assert audit.status == SyncStatus.FAILURE.value
                assert audit.error_message is not None
                assert "500" in audit.error_message

    asyncio.run(_run())
