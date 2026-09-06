"""Unit tests for the opponent schedule crawler and reverse verification pipeline."""

# pylint: disable=protected-access,too-many-lines,too-many-locals

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ecu_hockey_calendar.ingestion.client import ResilientHttpClient
from ecu_hockey_calendar.ingestion.instagram_crawler import SessionCache
from ecu_hockey_calendar.ingestion.opponent_crawler import (
    OpponentCrawler,
    _parse_cached_opponent_feed,
)
from ecu_hockey_calendar.ingestion.opponent_parser import (
    OpponentDirectory,
    OpponentEndpointConfig,
    OpponentFeedType,
    VerificationStatus,
)
from ecu_hockey_calendar.models import Game, Team
from ecu_hockey_calendar.storage.base import Base
from ecu_hockey_calendar.storage.models import (
    DataSourceType,
    GameModel,
    RawSnapshotModel,
    SyncAuditModel,
    SyncStatus,
    TeamModel,
)

if TYPE_CHECKING:
    from collections.abc import Generator

SAMPLE_ICAL_SCHEDULE = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:game-unc-1
DTSTART:20261018T233000Z
SUMMARY:UNC Tar Heels vs. East Carolina University
LOCATION:Orange County Sportsplex
STATUS:CONFIRMED
END:VEVENT
END:VCALENDAR"""

SAMPLE_JSON_SCHEDULE = {
    "schedule": [
        {
            "id": "vt-game-1",
            "date": "2026-10-18",
            "time": "7:30 PM",
            "opponent": "East Carolina University",
            "venue": "Lancerlot Sports Complex",
            "home_away": "home",
            "status": "scheduled",
        },
    ],
}

SAMPLE_HTML_SCHEDULE = """
<table>
    <tr><td>Date</td><td>Opponent</td><td>Time</td><td>Location</td></tr>
    <tr>
        <td>2026-10-18</td>
        <td>East Carolina University</td>
        <td>7:30 PM</td>
        <td>The Factory Ice House</td>
    </tr>
</table>
"""


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Provide clean isolated in-memory SQLite database session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session

    engine.dispose()


@pytest.fixture
def mock_directory() -> OpponentDirectory:
    """Create directory with representative collegiate opponents."""
    directory = OpponentDirectory()
    directory.register(
        OpponentEndpointConfig(
            canonical_name="UNC Chapel Hill",
            feed_url="https://tarheelhockey.com/schedule.ics",
            feed_type=OpponentFeedType.ICAL,
            home_venue="Orange County Sportsplex",
            aliases=("unc", "north carolina"),
        ),
    )
    directory.register(
        OpponentEndpointConfig(
            canonical_name="Virginia Tech",
            feed_url="https://hokieshockey.com/api/schedule.json",
            feed_type=OpponentFeedType.JSON,
            home_venue="Lancerlot Sports Complex",
            aliases=("vt", "hokies"),
        ),
    )
    directory.register(
        OpponentEndpointConfig(
            canonical_name="NC State University",
            feed_url="https://ncstatehockey.com/schedule.html",
            feed_type=OpponentFeedType.HTML,
            home_venue="The Factory Ice House",
            aliases=("nc state", "pack"),
        ),
    )
    return directory


def test_parse_cached_opponent_feed() -> None:
    """Test parsing cached payloads across iCal, JSON, and HTML."""
    fixtures_ical = _parse_cached_opponent_feed(
        SAMPLE_ICAL_SCHEDULE,
        OpponentFeedType.ICAL,
        "UNC Chapel Hill",
    )
    assert len(fixtures_ical) == 1
    assert fixtures_ical[0].opponent_name == "UNC Chapel Hill"

    fixtures_json = _parse_cached_opponent_feed(
        '{"schedule": [{"date": "2026-10-18", "opponent": "ECU"}]}',
        OpponentFeedType.JSON,
        "Virginia Tech",
    )
    assert len(fixtures_json) == 1
    assert fixtures_json[0].opponent_name == "Virginia Tech"

    # Bad JSON handling
    assert not _parse_cached_opponent_feed(
        "INVALID_JSON",
        OpponentFeedType.JSON,
        "Virginia Tech",
    )

    fixtures_html = _parse_cached_opponent_feed(
        SAMPLE_HTML_SCHEDULE,
        OpponentFeedType.HTML,
        "NC State University",
    )
    assert len(fixtures_html) == 1
    assert fixtures_html[0].opponent_name == "NC State University"


@pytest.mark.anyio
async def test_opponent_crawler_init_defaults() -> None:
    """Test OpponentCrawler initialization with default collaborators."""
    crawler = OpponentCrawler()
    assert crawler.client is not None
    assert crawler.directory is not None
    assert crawler.cache is not None
    assert crawler.rate_limiter is not None
    await crawler.client.close()


@pytest.mark.anyio
async def test_fetch_opponent_schedule_ical(mock_directory: OpponentDirectory) -> None:
    """Test fetching and parsing iCal schedule feeds."""
    mock_client = AsyncMock(spec=ResilientHttpClient)
    mock_client.fetch_text.return_value = (SAMPLE_ICAL_SCHEDULE, "hash-ical")

    crawler = OpponentCrawler(
        http_client=mock_client,
        directory=mock_directory,
    )

    fixtures, payload, chash, ctype = await crawler.fetch_opponent_schedule("unc")
    assert len(fixtures) == 1
    assert payload == SAMPLE_ICAL_SCHEDULE
    assert chash == "hash-ical"
    assert ctype == "text/calendar"

    # Verify cached return on subsequent call
    cached_fix, _, _, _ = await crawler.fetch_opponent_schedule("unc", use_cache=True)
    assert len(cached_fix) == 1
    mock_client.fetch_text.assert_called_once()


@pytest.mark.anyio
async def test_fetch_opponent_schedule_json(mock_directory: OpponentDirectory) -> None:
    """Test fetching and parsing JSON schedule feeds."""
    mock_client = AsyncMock(spec=ResilientHttpClient)
    mock_client.fetch_json.return_value = (SAMPLE_JSON_SCHEDULE, "hash-json")

    crawler = OpponentCrawler(
        http_client=mock_client,
        directory=mock_directory,
    )

    fixtures, payload, chash, ctype = await crawler.fetch_opponent_schedule("vt")
    assert len(fixtures) == 1
    assert "vt-game-1" in payload
    assert chash == "hash-json"
    assert ctype == "application/json"


@pytest.mark.anyio
async def test_fetch_opponent_schedule_html(mock_directory: OpponentDirectory) -> None:
    """Test fetching and parsing HTML schedule tables."""
    mock_client = AsyncMock(spec=ResilientHttpClient)
    mock_client.fetch_text.return_value = (SAMPLE_HTML_SCHEDULE, "hash-html")

    crawler = OpponentCrawler(
        http_client=mock_client,
        directory=mock_directory,
    )

    fixtures, payload, chash, ctype = await crawler.fetch_opponent_schedule(
        "NC State University",
    )
    assert len(fixtures) == 1
    assert payload == SAMPLE_HTML_SCHEDULE
    assert chash == "hash-html"
    assert ctype == "text/html"


@pytest.mark.anyio
async def test_fetch_opponent_schedule_not_in_directory(
    mock_directory: OpponentDirectory,
) -> None:
    """Test requesting schedule for an unregistered opponent."""
    crawler = OpponentCrawler(directory=mock_directory)
    fixtures, payload, chash, ctype = await crawler.fetch_opponent_schedule(
        "Unknown Institution",
    )
    assert not fixtures
    assert payload == ""
    assert chash == ""
    assert ctype == "none"
    await crawler.client.close()


@pytest.mark.anyio
async def test_fetch_with_fallback_error_handling(
    mock_directory: OpponentDirectory,
) -> None:
    """Test error handling and stale cache fallback during network errors."""
    mock_client = AsyncMock(spec=ResilientHttpClient)
    mock_client.fetch_text.side_effect = httpx.ConnectError("Connection failed")

    cache = SessionCache()
    crawler = OpponentCrawler(
        http_client=mock_client,
        directory=mock_directory,
        session_cache=cache,
    )

    # Initial failure with no cache returns empty
    fixtures, payload, _, ctype = await crawler.fetch_opponent_schedule("unc")
    assert not fixtures
    assert payload == ""
    assert ctype == "none"

    # Preload cache with stale entry
    cache.set(
        "opp:UNC Chapel Hill",
        SAMPLE_ICAL_SCHEDULE,
        "hash-stale",
        "text/calendar",
        ttl=-10.0,  # Expired
    )

    # Network failure should now fall back to stale cache
    (
        fixtures_stale,
        payload_stale,
        chash_stale,
        _,
    ) = await crawler.fetch_opponent_schedule("unc", use_cache=False)
    assert len(fixtures_stale) == 1
    assert payload_stale == SAMPLE_ICAL_SCHEDULE
    assert chash_stale == "hash-stale"


@pytest.mark.anyio
async def test_reverse_check_game_success(mock_directory: OpponentDirectory) -> None:
    """Test reverse check verification when opponent feed matches game."""
    mock_client = AsyncMock(spec=ResilientHttpClient)
    mock_client.fetch_text.return_value = (SAMPLE_ICAL_SCHEDULE, "hash-ical")

    crawler = OpponentCrawler(
        http_client=mock_client,
        directory=mock_directory,
    )

    dt = datetime(2026, 10, 18, 23, 30, tzinfo=UTC)
    ecu_team = Team(name="East Carolina University", city="Greenville", state="NC")
    unc_team = Team(name="UNC Chapel Hill", city="Chapel Hill", state="NC")

    # Game where ECU is away at UNC
    game = Game(
        game_id="game-rev-1",
        home_team=unc_team,
        away_team=ecu_team,
        start_time=dt,
        venue="Orange County Sportsplex",
    )

    res = await crawler.reverse_check_game(game)
    assert res.verification_status == VerificationStatus.VERIFIED
    assert res.confidence_score >= 0.75
    assert res.matched_fixture is not None
    assert res.home_away_aligned is True


@pytest.mark.anyio
async def test_reverse_check_game_opponent_name_resolution(
    mock_directory: OpponentDirectory,
) -> None:
    """Test opponent team resolution when ECU is home team."""
    mock_client = AsyncMock(spec=ResilientHttpClient)
    mock_client.fetch_text.return_value = (SAMPLE_ICAL_SCHEDULE, "hash-ical")

    crawler = OpponentCrawler(
        http_client=mock_client,
        directory=mock_directory,
    )

    dt = datetime(2026, 10, 18, 23, 30, tzinfo=UTC)
    ecu_team = Team(name="East Carolina University", city="Greenville", state="NC")
    unc_team = Team(name="UNC Chapel Hill", city="Chapel Hill", state="NC")

    # Game where ECU is home
    game = Game(
        game_id="game-rev-2",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=dt,
        venue="Carolina Ice Palace",
    )

    res = await crawler.reverse_check_game(game)
    # Both claim home (UNC schedule summary has UNC vs ECU), so discrepancy detected
    assert res.verification_status == VerificationStatus.DISCREPANCY
    assert res.home_away_aligned is False


@pytest.mark.anyio
async def test_reverse_check_game_unavailable(
    mock_directory: OpponentDirectory,
) -> None:
    """Test reverse checking when opponent is not in directory or schedule empty."""
    crawler = OpponentCrawler(directory=mock_directory)

    dt = datetime(2026, 10, 18, 23, 30, tzinfo=UTC)
    ecu_team = Team(name="East Carolina University", city="Greenville", state="NC")
    duke_team = Team(name="Duke University", city="Durham", state="NC")

    # Duke is not registered in mock_directory
    game = Game(
        game_id="game-rev-3",
        home_team=ecu_team,
        away_team=duke_team,
        start_time=dt,
        venue="Orange County Sportsplex",
    )

    res = await crawler.reverse_check_game(game)
    assert res.verification_status == VerificationStatus.UNAVAILABLE
    assert res.confidence_score == 0.0
    assert "No opponent directory config registered" in (res.notes or "")

    # Opponent in directory but fetch yields no fixtures
    unc_game = Game(
        game_id="game-rev-4",
        home_team=ecu_team,
        away_team=Team(name="UNC Chapel Hill", city="Chapel Hill", state="NC"),
        start_time=dt,
        venue="Orange County Sportsplex",
    )
    with patch.object(
        crawler,
        "fetch_opponent_schedule",
        AsyncMock(return_value=([], "", "", "none")),
    ):
        res_empty = await crawler.reverse_check_game(unc_game)
        assert res_empty.verification_status == VerificationStatus.UNAVAILABLE
        assert "feed returned no fixtures" in (res_empty.notes or "")

    await crawler.client.close()


@pytest.mark.anyio
async def test_reverse_check_all_games(mock_directory: OpponentDirectory) -> None:
    """Test batch reverse check for multiple games."""
    mock_client = AsyncMock(spec=ResilientHttpClient)
    mock_client.fetch_text.return_value = (SAMPLE_ICAL_SCHEDULE, "hash-ical")

    crawler = OpponentCrawler(
        http_client=mock_client,
        directory=mock_directory,
    )

    dt = datetime(2026, 10, 18, 23, 30, tzinfo=UTC)
    ecu = Team(name="East Carolina University", city="Greenville", state="NC")
    unc = Team(name="UNC Chapel Hill", city="Chapel Hill", state="NC")

    g1 = Game("g-1", unc, ecu, dt, "Orange County Sportsplex")
    g2 = Game("g-2", ecu, unc, dt, "Carolina Ice Palace")

    results = await crawler.reverse_check_all_games([g1, g2])
    assert len(results) == 2
    assert "g-1" in results
    assert "g-2" in results
    assert results["g-1"].verification_status == VerificationStatus.VERIFIED


def test_get_or_create_source_and_record_snapshot(
    db_session: Session,
) -> None:
    """Test creating and retrieving DataSourceModel and persisting RawSnapshotModel."""
    crawler = OpponentCrawler()
    src1 = crawler._get_or_create_source(db_session)
    assert src1.source_type == DataSourceType.OPPONENT.value
    assert src1.source_code == "opponent"

    # Subsequent call returns same entity
    src2 = crawler._get_or_create_source(db_session)
    assert src1.id == src2.id

    # Snapshot recording
    snap = crawler._record_snapshot(
        db_session,
        src1,
        url="https://example.com/feed.ics",
        payload=SAMPLE_ICAL_SCHEDULE,
        content_hash="hash-123",
        content_type="text/calendar",
    )
    assert snap is not None
    assert snap.source_id == src1.id
    assert snap.content_hash == "hash-123"

    # Empty payload or hash returns None
    assert (
        crawler._record_snapshot(
            db_session,
            src1,
            url="url",
            payload="",
            content_hash="hash",
            content_type="type",
        )
        is None
    )
    assert (
        crawler._record_snapshot(
            db_session,
            src1,
            url="url",
            payload="payload",
            content_hash="",
            content_type="type",
        )
        is None
    )


@pytest.mark.anyio
async def test_sync_successful_workflow(
    db_session: Session,
    mock_directory: OpponentDirectory,
) -> None:
    """Test full crawler sync persistence cycle with games and snapshots."""
    mock_client = AsyncMock(spec=ResilientHttpClient)
    mock_client.fetch_text.return_value = (SAMPLE_ICAL_SCHEDULE, "hash-ical")

    crawler = OpponentCrawler(
        http_client=mock_client,
        directory=mock_directory,
    )

    # Seed database with teams and games
    ecu_team = TeamModel(name="East Carolina University", city="Greenville", state="NC")
    unc_team = TeamModel(name="UNC Chapel Hill", city="Chapel Hill", state="NC")
    db_session.add_all([ecu_team, unc_team])
    db_session.flush()

    dt = datetime(2026, 10, 18, 23, 30, tzinfo=UTC)
    game_orm = GameModel(
        game_id="sync-game-1",
        home_team_id=unc_team.id,
        away_team_id=ecu_team.id,
        start_time=dt,
        venue="Orange County Sportsplex",
        season="2026-2027",
    )
    db_session.add(game_orm)
    db_session.flush()

    verified, discrepancies, audit = await crawler.sync(
        db_session,
        games=[game_orm],
        season="2026-2027",
    )

    assert verified == 1
    assert discrepancies == 0
    assert audit.status == SyncStatus.SUCCESS.value
    assert audit.games_updated == 1
    assert audit.conflicts_detected == 0
    assert audit.details is not None
    assert audit.details["verified"] == 1

    # Verify snapshot persistence
    snapshots = list(db_session.scalars(select(RawSnapshotModel)))
    assert len(snapshots) == 1
    assert snapshots[0].content_hash == "hash-ical"


@pytest.mark.anyio
async def test_sync_empty_games_partial_status(
    db_session: Session,
    mock_directory: OpponentDirectory,
) -> None:
    """Test sync with no games returns PARTIAL audit status."""
    crawler = OpponentCrawler(directory=mock_directory)

    verified, discrepancies, audit = await crawler.sync(
        db_session,
        games=[],
    )
    assert verified == 0
    assert discrepancies == 0
    assert audit.status == SyncStatus.PARTIAL.value
    assert audit.error_message == "No games provided or found for verification"
    await crawler.client.close()


@pytest.mark.anyio
async def test_sync_exception_failure(
    db_session: Session,
    mock_directory: OpponentDirectory,
) -> None:
    """Test sync lifecycle when an unexpected error occurs during crawl."""
    crawler = OpponentCrawler(directory=mock_directory)

    ecu_team = TeamModel(name="East Carolina University", city="Greenville", state="NC")
    unc_team = TeamModel(name="UNC Chapel Hill", city="Chapel Hill", state="NC")
    db_session.add_all([ecu_team, unc_team])
    db_session.flush()

    dt = datetime(2026, 10, 18, 23, 30, tzinfo=UTC)
    game_orm = GameModel(
        game_id="sync-game-err",
        home_team_id=unc_team.id,
        away_team_id=ecu_team.id,
        start_time=dt,
        venue="Orange County Sportsplex",
        season="2026-2027",
    )
    db_session.add(game_orm)
    db_session.flush()

    with (
        patch.object(
            crawler,
            "_process_game_verifications",
            AsyncMock(side_effect=RuntimeError("Verification crash")),
        ),
        pytest.raises(RuntimeError, match="Verification crash"),
    ):
        await crawler.sync(db_session, games=[game_orm])

    audit = db_session.scalar(select(SyncAuditModel))
    assert audit is not None
    assert audit.status == SyncStatus.FAILURE.value
    assert "Verification crash" in (audit.error_message or "")
    await crawler.client.close()


@pytest.mark.anyio
async def test_sync_default_query_and_discrepancies(
    db_session: Session,
    mock_directory: OpponentDirectory,
) -> None:
    """Test sync querying DB by season with games, discrepancies, and unknown teams."""
    mock_client = AsyncMock(spec=ResilientHttpClient)
    mock_client.fetch_text.return_value = (SAMPLE_ICAL_SCHEDULE, "hash-ical")

    crawler = OpponentCrawler(
        http_client=mock_client,
        directory=mock_directory,
    )

    ecu_team = TeamModel(name="East Carolina University", city="Greenville", state="NC")
    unc_team = TeamModel(name="UNC Chapel Hill", city="Chapel Hill", state="NC")
    duke_team = TeamModel(name="Duke University", city="Durham", state="NC")
    db_session.add_all([ecu_team, unc_team, duke_team])
    db_session.flush()

    dt = datetime(2026, 10, 18, 23, 30, tzinfo=UTC)

    # Game 1: Matches UNC feed -> VERIFIED
    g1 = GameModel(
        game_id="sync-g1",
        home_team_id=unc_team.id,
        away_team_id=ecu_team.id,
        start_time=dt,
        venue="Orange County Sportsplex",
        season="2026-2027",
    )
    # Game 2: Same opponent UNC, but home/away conflict -> DISCREPANCY
    g2 = GameModel(
        game_id="sync-g2",
        home_team_id=ecu_team.id,
        away_team_id=unc_team.id,
        start_time=dt,
        venue="Carolina Ice Palace",
        season="2026-2027",
    )
    # Game 3: Duke (not in mock_directory) -> UNAVAILABLE
    g3 = GameModel(
        game_id="sync-g3",
        home_team_id=ecu_team.id,
        away_team_id=duke_team.id,
        start_time=dt,
        venue="Carolina Ice Palace",
        season="2026-2027",
    )
    db_session.add_all([g1, g2, g3])
    db_session.flush()

    # Call sync with games=None so it queries the DB
    verified, discrepancies, audit = await crawler.sync(
        db_session,
        season="2026-2027",
    )

    assert verified == 1
    assert discrepancies == 1
    assert audit.games_updated == 1
    assert audit.conflicts_detected == 1
    assert audit.status == SyncStatus.SUCCESS.value
    assert audit.details is not None
    assert audit.details["total_games_checked"] == 3
