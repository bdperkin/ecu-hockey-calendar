"""Unit tests for the ECU Hockey Instagram crawler, caching, and sync operations."""

# pylint: disable=protected-access,too-many-lines,too-many-locals

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, time
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ecu_hockey_calendar.ingestion.client import ResilientHttpClient
from ecu_hockey_calendar.ingestion.instagram_crawler import (
    DEFAULT_CACHE_TTL_SECONDS,
    DEFAULT_RATE_LIMIT_INTERVAL,
    InstagramCrawler,
    RateLimiter,
    SessionCache,
)
from ecu_hockey_calendar.ingestion.instagram_parser import (
    DEFAULT_GRAPH_API_URL,
    DEFAULT_INSTAGRAM_URL,
    DEFAULT_INSTAGRAM_USERNAME,
    DEFAULT_WEB_PROFILE_URL,
    ParsedInstagramPost,
)
from ecu_hockey_calendar.storage.base import Base
from ecu_hockey_calendar.storage.models import (
    DataSourceModel,
    DataSourceType,
    GameModel,
    GameStatus,
    RawSnapshotModel,
    SyncAuditModel,
    SyncStatus,
    TeamModel,
)

if TYPE_CHECKING:
    from collections.abc import Generator

SAMPLE_GRAPH_API_RESPONSE = {
    "data": [
        {
            "id": "18012345678",
            "caption": (
                "GAMEDAY: ECU vs NC State tonight at 7:30 PM at Carolina Ice Palace!"
            ),
            "media_type": "IMAGE",
            "timestamp": "2026-10-18T16:00:00+0000",
            "permalink": "https://www.instagram.com/p/Cxyz789/",
        },
    ],
}

SAMPLE_WEB_PROFILE_RESPONSE = {
    "data": {
        "user": {
            "edge_owner_to_timeline_media": {
                "edges": [
                    {
                        "node": {
                            "id": "18098765432",
                            "shortcode": "Cabc123",
                            "taken_at_timestamp": 1792944000,
                            "edge_media_to_caption": {
                                "edges": [
                                    {
                                        "node": {
                                            "text": (
                                                "TIME CHANGE: Puck drop against Duke "
                                                "moved to 8:00 PM on Oct 25"
                                            ),
                                        },
                                    },
                                ],
                            },
                        },
                    },
                ],
            },
        },
    },
}

SAMPLE_HTML_RESPONSE = """
<html>
<head>
<meta property="og:description"
    content="ECU vs UNC Wilmington at The Ice Center on Nov 5 at 7pm" />
<script type="application/ld+json">
{
    "@context": "https://schema.org",
    "@type": "SocialMediaPosting",
    "identifier": "html_post_999",
    "articleBody": "ECU vs Wake Forest on Nov 12 at 8pm",
    "url": "https://www.instagram.com/p/Cwake123/"
}
</script>
<script type="application/ld+json">
{
    "@context": "https://schema.org",
    "@type": "SocialMediaPosting",
    "identifier": "html_post_1000",
    "articleBody": "GAMEDAY vs NC State at Carolina Ice Palace",
    "url": "https://www.instagram.com/p/Cncstate/"
}
</script>
</head>
<body></body>
</html>
"""


@pytest.fixture
def sync_session() -> Generator[Session, None, None]:
    """In-memory SQLite database session for unit testing crawler persistence."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.mark.anyio
async def test_rate_limiter_acquire_and_elapsed() -> None:
    """Verify RateLimiter delay enforcement and elapsed calculation."""
    limiter = RateLimiter(min_interval=0.01)
    assert limiter.min_interval == 0.01
    assert limiter.time_since_last_request() > 0

    # First acquire updates timestamp without substantial wait
    await limiter.acquire()
    assert limiter.time_since_last_request() < 1.0

    # Immediate second acquire causes brief sleep
    start = asyncio.get_running_loop().time()
    await limiter.acquire()
    end = asyncio.get_running_loop().time()
    assert (end - start) >= 0.005


def test_session_cache_set_get_ttl_and_clear() -> None:
    """Verify SessionCache operations including stale reads and purging."""
    cache = SessionCache(default_ttl=10.0)
    assert cache.default_ttl == 10.0
    assert not cache.has("missing")
    assert cache.get("missing") is None

    # Set and retrieve valid entry
    cache.set("k1", "payload1", "hash1", "application/json")
    assert cache.has("k1")
    assert cache.get("k1") == ("payload1", "hash1", "application/json")

    # Set entry with negative TTL (already expired)
    cache.set("k_exp", "payload_exp", "hash_exp", "text/html", ttl=-1.0)
    assert not cache.has("k_exp")
    assert cache.get("k_exp", allow_stale=False) is None
    assert cache.get("k_exp", allow_stale=True) == (
        "payload_exp",
        "hash_exp",
        "text/html",
    )

    # Clear cache
    cache.clear()
    assert not cache.has("k1")
    assert cache.get("k1") is None
    assert cache.get("k_exp", allow_stale=True) is None


def test_instagram_crawler_initialization() -> None:
    """Verify default and customized InstagramCrawler attributes."""
    crawler = InstagramCrawler()
    assert crawler.username == DEFAULT_INSTAGRAM_USERNAME
    assert crawler.instagram_url == DEFAULT_INSTAGRAM_URL
    assert crawler.graph_api_url == DEFAULT_GRAPH_API_URL
    assert crawler.web_profile_url == DEFAULT_WEB_PROFILE_URL
    assert crawler.access_token is None
    assert crawler.rate_limiter.min_interval == DEFAULT_RATE_LIMIT_INTERVAL
    assert crawler.cache.default_ttl == DEFAULT_CACHE_TTL_SECONDS

    custom_client = ResilientHttpClient()
    custom_cache = SessionCache(default_ttl=60.0)
    custom_limiter = RateLimiter(min_interval=0.5)
    custom = InstagramCrawler(
        http_client=custom_client,
        username="ecuicehockey",
        instagram_url="https://custom.instagram.com/",
        graph_api_url="https://custom.graph.api/",
        web_profile_url="https://custom.web.api/",
        access_token="test_token_123",
        session_cache=custom_cache,
        rate_limiter=custom_limiter,
    )
    assert custom.client is custom_client
    assert custom.access_token == "test_token_123"
    assert custom.cache is custom_cache
    assert custom.rate_limiter is custom_limiter


@pytest.mark.anyio
async def test_fetch_graph_api_posts_success() -> None:
    """Verify fetching posts via official Graph API."""
    mock_client = AsyncMock(spec=ResilientHttpClient)
    mock_client.fetch_json.return_value = (SAMPLE_GRAPH_API_RESPONSE, "graph_hash")

    crawler = InstagramCrawler(
        http_client=mock_client,
        access_token="valid_token",
        rate_limiter=RateLimiter(min_interval=0),
    )
    posts, payload, c_hash = await crawler.fetch_graph_api_posts()

    assert len(posts) == 1
    assert posts[0].post_id == "18012345678"
    assert posts[0].opponent_name == "NC State University"
    assert c_hash == "graph_hash"
    assert "18012345678" in payload
    mock_client.fetch_json.assert_awaited_once()


@pytest.mark.anyio
async def test_fetch_graph_api_posts_missing_token() -> None:
    """Verify ValueError when Graph API is called without access token."""
    crawler = InstagramCrawler(access_token=None)
    with pytest.raises(
        ValueError,
        match="Instagram Graph API access token is required",
    ):
        await crawler.fetch_graph_api_posts()


@pytest.mark.anyio
async def test_fetch_web_api_posts_success() -> None:
    """Verify fetching posts via web profile JSON endpoint."""
    mock_client = AsyncMock(spec=ResilientHttpClient)
    mock_client.fetch_json.return_value = (SAMPLE_WEB_PROFILE_RESPONSE, "web_hash")

    crawler = InstagramCrawler(
        http_client=mock_client,
        rate_limiter=RateLimiter(min_interval=0),
    )
    posts, payload, c_hash = await crawler.fetch_web_api_posts()

    assert len(posts) == 1
    assert posts[0].post_id == "18098765432"
    assert posts[0].opponent_name == "Duke University"
    assert c_hash == "web_hash"
    assert "18098765432" in payload
    mock_client.fetch_json.assert_awaited_once()


@pytest.mark.anyio
async def test_fetch_web_api_posts_rate_limited_or_login() -> None:
    """Verify ValueError when web profile requires login or reports fail."""
    mock_client = AsyncMock(spec=ResilientHttpClient)
    mock_client.fetch_json.return_value = ({"status": "fail"}, "hash_fail")

    crawler = InstagramCrawler(
        http_client=mock_client,
        rate_limiter=RateLimiter(min_interval=0),
    )
    with pytest.raises(
        ValueError,
        match="Instagram web profile requires login or is rate-limited",
    ):
        await crawler.fetch_web_api_posts()

    # require_login flag
    mock_client.fetch_json.return_value = ({"require_login": True}, "hash_login")
    with pytest.raises(
        ValueError,
        match="Instagram web profile requires login or is rate-limited",
    ):
        await crawler.fetch_web_api_posts()


@pytest.mark.anyio
async def test_fetch_html_posts_success() -> None:
    """Verify fetching posts via public HTML profile scraping."""
    mock_client = AsyncMock(spec=ResilientHttpClient)
    mock_client.fetch_text.return_value = (SAMPLE_HTML_RESPONSE, "html_hash")

    crawler = InstagramCrawler(
        http_client=mock_client,
        rate_limiter=RateLimiter(min_interval=0),
    )
    posts, payload, c_hash = await crawler.fetch_html_posts()

    assert len(posts) == 2
    assert c_hash == "html_hash"
    assert payload == SAMPLE_HTML_RESPONSE
    mock_client.fetch_text.assert_awaited_once()


def test_try_parse_cached_payload() -> None:
    """Verify parsing cached payloads for both JSON and HTML types."""
    crawler = InstagramCrawler()

    # 1. Valid JSON payload matching web profile
    web_json = '{"data": {"user": {"edge_owner_to_timeline_media": {"edges": []}}}}'
    assert crawler._try_parse_cached_payload(web_json, "application/json") == []

    # 2. Valid JSON payload matching Graph API
    graph_json = '{"data": [{"id": "1", "caption": "vs Duke", "permalink": "p"}]}'
    parsed_graph = crawler._try_parse_cached_payload(graph_json, "application/json")
    assert len(parsed_graph) == 1

    # 3. Malformed JSON payload
    assert crawler._try_parse_cached_payload("{malformed", "application/json") == []

    # 4. HTML payload
    parsed_html = crawler._try_parse_cached_payload(SAMPLE_HTML_RESPONSE, "text/html")
    assert len(parsed_html) == 2


@pytest.mark.anyio
async def test_fetch_posts_multi_tier_fallback() -> None:
    """Verify complete multi-tier fallback sequence in fetch_posts."""
    mock_client = AsyncMock(spec=ResilientHttpClient)
    crawler = InstagramCrawler(
        http_client=mock_client,
        access_token="test_token",
        rate_limiter=RateLimiter(min_interval=0),
    )

    # Tier 1: Graph API succeeds
    mock_client.fetch_json.return_value = (SAMPLE_GRAPH_API_RESPONSE, "hash_graph")
    posts, _, c_hash, c_type = await crawler.fetch_posts(prefer_graph_api=True)
    assert len(posts) == 1
    assert c_hash == "hash_graph"
    assert c_type == "application/json"

    # Tier 0: Cache hit (subsequent call returns cached data without client fetch)
    mock_client.fetch_json.reset_mock()
    posts_cache, _, _, _ = await crawler.fetch_posts(use_cache=True)
    assert len(posts_cache) == 1
    mock_client.fetch_json.assert_not_called()

    # Tier 2: Cache cleared, Graph API fails -> Web API succeeds
    crawler.cache.clear()
    mock_client.fetch_json.side_effect = [
        httpx.ConnectError("Graph down"),
        (SAMPLE_WEB_PROFILE_RESPONSE, "hash_web"),
    ]
    posts_web, _, c_hash_web, c_type_web = await crawler.fetch_posts(
        prefer_graph_api=True,
    )
    assert len(posts_web) == 1
    assert c_hash_web == "hash_web"
    assert c_type_web == "application/json"

    # Tier 3: Graph API and Web API fail -> HTML scrape succeeds
    crawler.cache.clear()
    mock_client.fetch_json.side_effect = httpx.HTTPError("APIs down")
    mock_client.fetch_text.return_value = (SAMPLE_HTML_RESPONSE, "hash_html")
    posts_html, _, c_hash_html, c_type_html = await crawler.fetch_posts(
        prefer_graph_api=True,
    )
    assert len(posts_html) == 2
    assert c_hash_html == "hash_html"
    assert c_type_html == "text/html"

    # Tier 4: Everything fails on network -> returns stale cache
    crawler.cache.clear()
    crawler.cache.set(
        "posts",
        SAMPLE_HTML_RESPONSE,
        "stale_hash",
        "text/html",
        ttl=-1.0,
    )
    mock_client.fetch_json.side_effect = httpx.HTTPError("APIs down")
    mock_client.fetch_text.side_effect = httpx.HTTPError("Scrape down")
    posts_stale, _, c_hash_stale, _ = await crawler.fetch_posts(
        prefer_graph_api=True,
        use_cache=True,
    )
    assert len(posts_stale) == 2
    assert c_hash_stale == "stale_hash"

    # Tier 5: Everything fails and cache is empty -> returns empty list
    crawler.cache.clear()
    posts_none, payload_none, hash_none, type_none = await crawler.fetch_posts(
        prefer_graph_api=True,
        use_cache=True,
    )
    assert posts_none == []
    assert payload_none == ""
    assert hash_none == ""
    assert type_none == "none"


@pytest.mark.anyio
async def test_fetch_posts_empty_responses_trigger_fallback() -> None:
    """Verify that returning empty post lists properly cascades down tiers."""
    mock_client = AsyncMock(spec=ResilientHttpClient)
    # Graph API returns empty data list
    mock_client.fetch_json.side_effect = [
        ({"data": []}, "empty_graph"),
        (SAMPLE_WEB_PROFILE_RESPONSE, "hash_web"),
    ]
    crawler = InstagramCrawler(
        http_client=mock_client,
        access_token="tok",
        rate_limiter=RateLimiter(min_interval=0),
    )

    posts, _, _, _ = await crawler.fetch_posts(prefer_graph_api=True)
    assert len(posts) == 1
    assert posts[0].opponent_name == "Duke University"


@pytest.mark.anyio
async def test_sync_success_creates_games_and_snapshot(
    sync_session: Session,
) -> None:
    """Verify full sync creating source, snapshot, audit, and games."""
    mock_client = AsyncMock(spec=ResilientHttpClient)
    mock_client.fetch_json.return_value = (SAMPLE_GRAPH_API_RESPONSE, "hash_sync_1")

    crawler = InstagramCrawler(
        http_client=mock_client,
        access_token="token_sync",
        rate_limiter=RateLimiter(min_interval=0),
    )

    created, updated, audit = await crawler.sync(
        sync_session,
        season="2026-2027",
    )

    assert created == 1
    assert updated == 0
    assert audit.status == SyncStatus.SUCCESS.value
    assert audit.error_message is None

    # Verify DataSourceModel created
    source = sync_session.scalar(
        select(DataSourceModel).where(DataSourceModel.source_code == "instagram"),
    )
    assert source is not None
    assert source.source_type == DataSourceType.SOCIAL.value

    # Verify RawSnapshotModel created
    snapshot = sync_session.scalar(
        select(RawSnapshotModel).where(RawSnapshotModel.source_id == source.id),
    )
    assert snapshot is not None
    assert snapshot.content_hash == "hash_sync_1"

    # Verify GameModel persisted
    game = sync_session.scalar(select(GameModel))
    assert game is not None
    assert game.venue == "Carolina Ice Palace"
    assert game.status == GameStatus.SCHEDULED.value

    # Verify second sync does not duplicate game
    mock_client.fetch_json.return_value = (SAMPLE_GRAPH_API_RESPONSE, "hash_sync_2")
    created2, updated2, audit2 = await crawler.sync(
        sync_session,
        use_cache=False,
    )
    assert created2 == 0
    assert updated2 == 0
    assert audit2.status == SyncStatus.SUCCESS.value


@pytest.mark.anyio
async def test_sync_updates_existing_game_time_and_status(
    sync_session: Session,
) -> None:
    """Verify sync cross-references and updates existing games."""
    # Pre-seed existing game
    ecu = TeamModel(name="East Carolina University", city="Greenville", state="NC")
    duke = TeamModel(name="Duke University", city="Durham", state="NC")
    sync_session.add_all([ecu, duke])
    sync_session.flush()

    tz = ZoneInfo("America/New_York")
    orig_start = datetime(2026, 10, 25, 19, 0, tzinfo=tz).astimezone(UTC)
    game = GameModel(
        game_id="20261025-duke",
        home_team_id=ecu.id,
        away_team_id=duke.id,
        start_time=orig_start,
        venue="The Ice Center",
        status=GameStatus.SCHEDULED.value,
        season="2026-2027",
    )
    sync_session.add(game)
    sync_session.commit()

    # Time change announcement for Oct 25 vs Duke
    mock_client = AsyncMock(spec=ResilientHttpClient)
    mock_client.fetch_json.return_value = (
        SAMPLE_WEB_PROFILE_RESPONSE,
        "hash_web_update",
    )

    crawler = InstagramCrawler(
        http_client=mock_client,
        rate_limiter=RateLimiter(min_interval=0),
    )
    created, updated, audit = await crawler.sync(
        sync_session,
        season="2026-2027",
    )

    assert created == 0
    assert updated == 1
    assert audit.status == SyncStatus.SUCCESS.value

    sync_session.refresh(game)
    expected_new_start = datetime(2026, 10, 25, 20, 0, tzinfo=tz).astimezone(UTC)
    assert game.start_time.replace(tzinfo=UTC) == expected_new_start


@pytest.mark.anyio
async def test_sync_partial_when_no_posts_found(sync_session: Session) -> None:
    """Verify that sync records PARTIAL audit status when no posts are fetched."""
    mock_client = AsyncMock(spec=ResilientHttpClient)
    mock_client.fetch_json.side_effect = httpx.HTTPError("down")
    mock_client.fetch_text.side_effect = httpx.HTTPError("down")

    crawler = InstagramCrawler(
        http_client=mock_client,
        rate_limiter=RateLimiter(min_interval=0),
    )
    created, updated, audit = await crawler.sync(sync_session)

    assert created == 0
    assert updated == 0
    assert audit.status == SyncStatus.PARTIAL.value
    assert "No posts retrieved" in (audit.error_message or "")


@pytest.mark.anyio
async def test_sync_exception_rolls_back_and_records_failure(
    sync_session: Session,
) -> None:
    """Verify that sync records FAILURE status and rolls back on exception."""
    crawler = InstagramCrawler(rate_limiter=RateLimiter(min_interval=0))

    with (
        patch.object(
            crawler,
            "_execute_sync_fetch",
            side_effect=RuntimeError("Fatal sync error"),
        ),
        pytest.raises(RuntimeError, match="Fatal sync error"),
    ):
        await crawler.sync(sync_session)

    audit = sync_session.scalar(select(SyncAuditModel))
    assert audit is not None
    assert audit.status == SyncStatus.FAILURE.value
    assert "Fatal sync error" in (audit.error_message or "")


def test_persist_new_game_edge_cases(sync_session: Session) -> None:
    """Verify _persist_new_game_from_post conditions returning False."""
    crawler = InstagramCrawler()
    ecu_id = crawler._get_ecu_team_id(sync_session)

    # 1. Post missing date or time (to_parsed_game_record returns None)
    post_no_date = ParsedInstagramPost(
        post_id="p1",
        shortcode="s1",
        caption="Game vs Duke",
        url="u1",
        opponent_name="Duke University",
    )
    assert not crawler._persist_new_game_from_post(
        sync_session,
        post_no_date,
        ecu_id,
        "2026-2027",
    )

    # 2. Away game team resolution
    dt = datetime(2026, 11, 15, 20, 0, tzinfo=UTC)
    post_away = ParsedInstagramPost(
        post_id="p_away",
        shortcode="s_away",
        caption="ECU at Richmond on Nov 15 at 8pm",
        url="u_away",
        opponent_name="Richmond",
        is_home_game=False,
        game_datetime=dt,
        game_date=dt.date(),
        game_time=time(20, 0),
    )
    assert crawler._persist_new_game_from_post(
        sync_session,
        post_away,
        ecu_id,
        "2026-2027",
    )
    # Opponent is home_team_id, ECU is away_team_id
    game = sync_session.scalar(
        select(GameModel).where(GameModel.game_id == "instagram-s_away"),
    )
    assert game is not None
    assert game.away_team_id == ecu_id
    assert game.home_team_id != ecu_id

    # 3. Snapshot with empty payload returns None
    source = crawler._get_or_create_source(sync_session)
    assert crawler._record_snapshot(sync_session, source, "", "", "text/plain") is None


@pytest.mark.anyio
async def test_instagram_crawler_coverage_edges(sync_session: Session) -> None:
    """Test remaining branches and edge cases for 100% coverage."""
    crawler = InstagramCrawler(rate_limiter=RateLimiter(min_interval=0))

    # 1. _try_parse_cached_payload with non-empty public feed JSON
    web_json_str = json.dumps(SAMPLE_WEB_PROFILE_RESPONSE)
    parsed_web = crawler._try_parse_cached_payload(web_json_str, "application/json")
    assert len(parsed_web) == 1

    # 2. _try_web_api with empty posts returned
    with patch.object(
        crawler,
        "fetch_web_api_posts",
        return_value=([], "{}", "empty_h"),
    ):
        assert await crawler._try_web_api() is None

    # 3. _try_html_scrape with empty posts returned
    with patch.object(
        crawler,
        "fetch_html_posts",
        return_value=([], "<html></html>", "empty_h"),
    ):
        assert await crawler._try_html_scrape() is None

    # 4. _fetch_from_network with prefer_graph_api=False
    mock_client = AsyncMock(spec=ResilientHttpClient)
    mock_client.fetch_json.return_value = (
        SAMPLE_WEB_PROFILE_RESPONSE,
        "hash_web_no_graph",
    )
    crawler_no_graph = InstagramCrawler(
        http_client=mock_client,
        rate_limiter=RateLimiter(min_interval=0),
    )
    posts, _, _, _ = await crawler_no_graph.fetch_posts(
        prefer_graph_api=False,
        use_cache=False,
    )
    assert len(posts) == 1

    # 5. _get_or_create_opponent when opponent already exists
    team1 = crawler._get_or_create_opponent(sync_session, "Virginia Tech")
    team2 = crawler._get_or_create_opponent(sync_session, "Virginia Tech")
    assert team1.id == team2.id

    # 6. _matches_existing_game loop continuation across multiple games
    ecu_id = crawler._get_ecu_team_id(sync_session)
    dt1 = datetime(2026, 11, 20, 19, 0, tzinfo=UTC)
    dt2 = datetime(2026, 11, 21, 19, 0, tzinfo=UTC)
    g1 = GameModel(
        game_id="g_vt",
        home_team_id=ecu_id,
        away_team_id=team1.id,
        start_time=dt1,
        venue="Ice Center",
        status=GameStatus.SCHEDULED.value,
        season="2026-2027",
    )
    unc_team = crawler._get_or_create_opponent(sync_session, "UNC Chapel Hill")
    g2 = GameModel(
        game_id="g_unc",
        home_team_id=ecu_id,
        away_team_id=unc_team.id,
        start_time=dt2,
        venue="Ice Center",
        status=GameStatus.SCHEDULED.value,
        season="2026-2027",
    )
    sync_session.add_all([g1, g2])
    sync_session.flush()

    post_matching_g2 = ParsedInstagramPost(
        post_id="p_unc_match",
        shortcode="s_unc_match",
        caption="ECU vs UNC Chapel Hill on Nov 21 at 7pm",
        url="u",
        opponent_name="UNC Chapel Hill",
        game_datetime=dt2,
        game_date=dt2.date(),
        game_time=time(19, 0),
    )
    # Checks g1 (False, continues loop) then g2 (True, returns True)
    assert crawler._matches_existing_game(sync_session, post_matching_g2)
