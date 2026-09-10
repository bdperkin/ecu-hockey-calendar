"""Comprehensive tests for FastAPI calendar feed and RFC 5545 subscription service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from ecu_hockey_calendar.api.app import create_app
from ecu_hockey_calendar.api.server import run_server
from ecu_hockey_calendar.api.service import (
    CalendarFeedConfig,
    CalendarFeedService,
    VenueDetails,
    escape_text,
    fold_line,
    generate_game_uid,
    resolve_venue_details,
)
from ecu_hockey_calendar.calendar import ECUHockeyCalendar
from ecu_hockey_calendar.models import Game, GameResult, Team
from ecu_hockey_calendar.storage.engine import (
    create_sync_engine,
    get_sync_session,
    init_db,
)
from ecu_hockey_calendar.storage.models import GameModel, GameStatus, TeamModel


@pytest.fixture
def ecu_team() -> Team:
    """Fixture providing standard ECU team entity."""
    return Team(
        name="East Carolina University",
        city="Greenville",
        state="NC",
        division="ACHA M2",
        conference="ACCHL",
    )


@pytest.fixture
def unc_team() -> Team:
    """Fixture providing standard UNC opponent team."""
    return Team(
        name="UNC Chapel Hill",
        city="Chapel Hill",
        state="NC",
        division="ACHA M2",
        conference="ACCHL",
    )


@pytest.fixture
def sample_games(ecu_team: Team, unc_team: Team) -> list[Game]:
    """Fixture providing sample home, away, cancelled, and completed games."""
    nc_state = Team(name="NC State University", city="Raleigh", state="NC")
    vt = Team(name="Virginia Tech", city="Blacksburg", state="VA")

    return [
        Game(
            game_id="ECU-2026-01",
            home_team=ecu_team,
            away_team=unc_team,
            start_time=datetime(2026, 10, 16, 23, 30, tzinfo=UTC),
            venue="The Factory Ice House",
            result=GameResult.SCHEDULED,
        ),
        Game(
            game_id="ECU-2026-02",
            home_team=nc_state,
            away_team=ecu_team,
            start_time=datetime(2026, 10, 24, 0, 0, tzinfo=UTC),
            venue="Invisalign Arena",
            result=GameResult.SCHEDULED,
        ),
        Game(
            game_id="ECU-2026-03",
            home_team=ecu_team,
            away_team=vt,
            start_time=datetime(2026, 11, 6, 23, 0, tzinfo=UTC),
            venue="The Factory Ice House",
            result=GameResult.CANCELLED,
        ),
        Game(
            game_id="ECU-2026-04",
            home_team=ecu_team,
            away_team=unc_team,
            start_time=datetime(2026, 9, 20, 23, 0, tzinfo=UTC),
            venue="The Factory Ice House",
            result=GameResult.WIN,
            home_score=5,
            away_score=2,
        ),
    ]


def test_root_endpoint() -> None:
    """Test GET / returns API service status and route metadata."""
    app = create_app()
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "/calendar.ics" in data["endpoints"]["calendar_ics"]
    assert "/docs" in data["endpoints"]["docs"]


def test_calendar_feed_empty_schedule() -> None:
    """Test /calendar.ics with empty schedule returns valid RFC 5545 container."""
    app = create_app()
    app.state.games_override = []
    client = TestClient(app)

    response = client.get("/calendar.ics")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/calendar; charset=utf-8"
    assert "inline; filename=" in response.headers["content-disposition"]

    content = response.text
    assert content.startswith("BEGIN:VCALENDAR\r\n")
    assert "VERSION:2.0\r\n" in content
    assert "METHOD:PUBLISH\r\n" in content
    assert "X-WR-CALNAME:" in content
    assert content.endswith("END:VCALENDAR\r\n")
    assert "BEGIN:VEVENT" not in content


def test_calendar_feed_with_games(sample_games: list[Game]) -> None:
    """Test /calendar.ics renders games with full RFC 5545 attributes."""
    app = create_app()
    app.state.games_override = sample_games
    client = TestClient(app)

    response = client.get("/calendar.ics")
    assert response.status_code == 200

    content = response.text
    assert content.startswith("BEGIN:VCALENDAR\r\n")

    unfolded = content.replace("\r\n ", "")

    # Verify home game vs UNC
    assert "SUMMARY:ECU Hockey vs UNC Chapel Hill" in unfolded
    assert (
        "LOCATION:The Factory Ice House\\, 1839 S Main St\\, Wake Forest\\, NC 27587"
        in unfolded
    )
    assert "GEO:35.955400;-78.532300" in unfolded
    assert "STATUS:CONFIRMED" in unfolded
    assert "UID:game-ecu-2026-01@ecuhockey.com" in unfolded

    # Verify away game at NC State
    assert "SUMMARY:ECU Hockey at NC State University" in unfolded
    assert (
        "LOCATION:Invisalign Arena\\, 1001 Competition Dr\\, Morrisville\\, NC 27560"
        in unfolded
    )

    # Verify cancelled game
    assert "SUMMARY:[CANCELLED] ECU Hockey vs Virginia Tech" in unfolded
    assert "STATUS:CANCELLED" in unfolded

    # Verify score in description for completed game
    assert "Score: East Carolina University 5\\, UNC Chapel Hill 2" in unfolded


def test_calendar_feed_alarm_configuration(sample_games: list[Game]) -> None:
    """Test VALARM generation with default, custom, and disabled alarms."""
    app = create_app()
    app.state.games_override = sample_games
    client = TestClient(app)

    # 1. Default alarm (120 minutes = 2 hours)
    res_default = client.get("/calendar.ics")
    assert "BEGIN:VALARM" in res_default.text
    assert "TRIGGER:-PT2H" in res_default.text
    assert "starts in 2 hours!" in res_default.text

    # 2. Custom alarm (30 minutes)
    res_30m = client.get("/calendar.ics?alarm_minutes=30")
    assert "BEGIN:VALARM" in res_30m.text
    assert "TRIGGER:-PT30M" in res_30m.text
    assert "starts in 30 minutes!" in res_30m.text

    # 3. Disabled alarm (0 minutes)
    res_disabled = client.get("/calendar.ics?alarm_minutes=0")
    assert "BEGIN:VALARM" not in res_disabled.text


def test_calendar_feed_webcal_headers_and_redirect(sample_games: list[Game]) -> None:
    """Test webcal:// subscription headers and query param redirect."""
    app = create_app()
    app.state.games_override = sample_games
    client = TestClient(app)

    # Check response headers contain webcal scheme
    res = client.get("/calendar.ics")
    assert "x-webcal-location" in res.headers
    assert res.headers["x-webcal-location"].startswith("webcal://")
    assert "link" in res.headers
    assert 'rel="alternate"' in res.headers["link"]

    # Check webcal=true redirects with 307
    res_redirect = client.get("/calendar.ics?webcal=true", follow_redirects=False)
    assert res_redirect.status_code == 307
    assert res_redirect.headers["location"].startswith("webcal://")


def test_calendar_feed_caching_and_conditional_get(sample_games: list[Game]) -> None:
    """Test ETag, Last-Modified, and 304 Not Modified conditional responses."""
    app = create_app()
    app.state.games_override = sample_games
    client = TestClient(app)

    # Initial fetch
    res1 = client.get("/calendar.ics")
    assert res1.status_code == 200
    etag = res1.headers.get("etag")
    last_mod = res1.headers.get("last-modified")
    assert etag is not None
    assert last_mod is not None

    # Conditional GET with If-None-Match exact match -> 304
    res_304 = client.get("/calendar.ics", headers={"If-None-Match": etag})
    assert res_304.status_code == 304
    assert res_304.text == ""

    # Conditional GET with weak validator -> 304
    res_weak = client.get("/calendar.ics", headers={"If-None-Match": f"W/{etag}"})
    assert res_weak.status_code == 304

    # Conditional GET with mismatched ETag -> 200
    res_mismatch = client.get(
        "/calendar.ics",
        headers={"If-None-Match": '"different-hash"'},
    )
    assert res_mismatch.status_code == 200

    # Conditional GET with If-Modified-Since matching -> 304
    res_since = client.get("/calendar.ics", headers={"If-Modified-Since": last_mod})
    assert res_since.status_code == 304

    # Conditional GET with future If-Modified-Since -> 304
    future_date = "Thu, 01 Jan 2099 00:00:00 GMT"
    res_future = client.get("/calendar.ics", headers={"If-Modified-Since": future_date})
    assert res_future.status_code == 304

    # Conditional GET with past date -> 200
    past_date = "Mon, 01 Jan 2000 00:00:00 GMT"
    res_past = client.get("/calendar.ics", headers={"If-Modified-Since": past_date})
    assert res_past.status_code == 200

    # Conditional GET with malformed date -> 200
    res_malformed = client.get(
        "/calendar.ics",
        headers={"If-Modified-Since": "invalid-http-date"},
    )
    assert res_malformed.status_code == 200


def test_calendar_feed_head_request(sample_games: list[Game]) -> None:
    """Test HEAD /calendar.ics returns identical headers with no body."""
    app = create_app()
    app.state.games_override = sample_games
    client = TestClient(app)

    res_get = client.get("/calendar.ics")
    res_head = client.head("/calendar.ics")

    assert res_head.status_code == 200
    assert res_head.text == ""
    assert res_head.headers["content-type"] == res_get.headers["content-type"]
    assert res_head.headers["etag"] == res_get.headers["etag"]
    assert res_head.headers["x-webcal-location"] == res_get.headers["x-webcal-location"]


def test_calendar_feed_include_past_filter() -> None:
    """Test include_past query parameter filtering."""
    now = datetime.now(UTC)
    ecu = Team(name="East Carolina University", city="Greenville", state="NC")
    unc = Team(name="UNC Chapel Hill", city="Chapel Hill", state="NC")

    past_game = Game(
        game_id="PAST-01",
        home_team=ecu,
        away_team=unc,
        start_time=now - timedelta(days=30),
        venue="The Factory Ice House",
        result=GameResult.WIN,
    )
    future_game = Game(
        game_id="FUTURE-01",
        home_team=ecu,
        away_team=unc,
        start_time=now + timedelta(days=30),
        venue="The Factory Ice House",
        result=GameResult.SCHEDULED,
    )

    app = create_app()
    app.state.games_override = [past_game, future_game]
    client = TestClient(app)

    # 1. include_past=true (default) includes both
    res_all = client.get("/calendar.ics")
    assert "game-past-01@ecuhockey.com" in res_all.text
    assert "game-future-01@ecuhockey.com" in res_all.text

    # 2. include_past=false excludes past games
    res_future_only = client.get("/calendar.ics?include_past=false")
    assert "game-past-01@ecuhockey.com" not in res_future_only.text
    assert "game-future-01@ecuhockey.com" in res_future_only.text


def test_calendar_feed_database_integration() -> None:
    """Test calendar feed querying directly from a populated database."""
    engine = create_sync_engine("sqlite:///:memory:")
    init_db(engine)

    # Insert teams and games
    with get_sync_session(engine) as session:
        ecu_orm = TeamModel(
            name="East Carolina University",
            city="Greenville",
            state="NC",
        )
        unc_orm = TeamModel(name="UNC Chapel Hill", city="Chapel Hill", state="NC")
        session.add_all([ecu_orm, unc_orm])
        session.flush()

        game1 = GameModel(
            game_id="DB-GAME-01",
            home_team_id=ecu_orm.id,
            away_team_id=unc_orm.id,
            start_time=datetime(2026, 11, 14, 23, 0, tzinfo=UTC),
            venue="The Factory Ice House",
            status=GameStatus.SCHEDULED.value,
            season="2026-2027",
        )
        game2 = GameModel(
            game_id="DB-GAME-OTHER-SEASON",
            home_team_id=ecu_orm.id,
            away_team_id=unc_orm.id,
            start_time=datetime(2025, 11, 14, 23, 0, tzinfo=UTC),
            venue="The Factory Ice House",
            status=GameStatus.SCHEDULED.value,
            season="2025-2026",
        )
        session.add_all([game1, game2])

    app = create_app()
    app.state.db_engine = engine
    client = TestClient(app)

    # Query all games
    res_all = client.get("/calendar.ics")
    assert res_all.status_code == 200
    assert "game-db-game-01@ecuhockey.com" in res_all.text
    assert "game-db-game-other-season@ecuhockey.com" in res_all.text

    # Query specific season filter
    res_season = client.get("/calendar.ics?season=2026-2027")
    assert res_season.status_code == 200
    assert "game-db-game-01@ecuhockey.com" in res_season.text
    assert "game-db-game-other-season@ecuhockey.com" not in res_season.text


def test_line_folding_and_escaping() -> None:
    """Test RFC 5545 line folding at 75 octets and character escaping."""
    # Test escaping
    raw_str = "Text with , comma ; semi \\ backslash and \n newline"
    escaped = escape_text(raw_str)
    assert "\\," in escaped
    assert "\\;" in escaped
    assert "\\\\" in escaped
    assert "\\n" in escaped

    # Test folding short line (no fold)
    short_line = "SUMMARY:Short line"
    assert fold_line(short_line) == short_line

    # Test folding line > 75 octets
    long_line = "DESCRIPTION:" + "A" * 120
    folded = fold_line(long_line)
    lines = folded.split("\r\n")
    assert len(lines) == 2
    assert len(lines[0].encode("utf-8")) <= 75
    assert lines[1].startswith(" ")
    assert len(lines[1].encode("utf-8")) <= 75


def test_venue_resolution_and_uid_generation(ecu_team: Team, unc_team: Team) -> None:
    """Test venue resolution and deterministic UID formatting."""
    # Test known venue
    loc, geo = resolve_venue_details("The Factory Ice House")
    assert "1839 S Main St" in loc
    assert geo == "35.955400;-78.532300"

    # Test unknown venue
    unknown_loc, unknown_geo = resolve_venue_details("Random Rink Arena")
    assert unknown_loc == "Random Rink Arena"
    assert unknown_geo is None

    # Test UID generation with custom game_id
    game = Game(
        game_id="ECU-TEST-01",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2026, 10, 15, 23, 0, tzinfo=UTC),
        venue="The Factory Ice House",
    )
    uid = generate_game_uid(game)
    assert uid == "game-ecu-test-01@ecuhockey.com"

    # Test UID generation with existing @ domain
    game_at = Game(
        game_id="custom-uid-123@ecuhockey.com",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2026, 10, 15, 23, 0, tzinfo=UTC),
        venue="The Factory Ice House",
    )
    assert generate_game_uid(game_at) == "custom-uid-123@ecuhockey.com"

    # Test UID generation with non-alphanumeric fallback
    game_fallback = Game(
        game_id="***",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2026, 10, 15, 23, 0, tzinfo=UTC),
        venue="The Factory Ice House",
    )
    uid_fallback = generate_game_uid(game_fallback)
    assert uid_fallback.startswith("game-20261015-")
    assert uid_fallback.endswith("@ecuhockey.com")


def test_openapi_schema_and_docs_endpoints() -> None:
    """Test Swagger UI, ReDoc, and OpenAPI schema endpoints load properly."""
    app = create_app()
    client = TestClient(app)

    # OpenAPI JSON
    res_json = client.get("/openapi.json")
    assert res_json.status_code == 200
    schema = res_json.json()
    assert "/calendar.ics" in schema["paths"]

    # Swagger docs
    res_docs = client.get("/docs")
    assert res_docs.status_code == 200
    assert "swagger-ui" in res_docs.text

    # ReDoc
    res_redoc = client.get("/redoc")
    assert res_redoc.status_code == 200
    assert "redoc" in res_redoc.text


def test_run_server_invocation() -> None:
    """Test run_server calls uvicorn.run with specified parameters."""
    with patch("uvicorn.run") as mock_run:
        run_server(host="127.0.0.1", port=9000, reload=False)
        mock_run.assert_called_once_with(
            "ecu_hockey_calendar.api.app:create_app",
            host="127.0.0.1",
            port=9000,
            reload=False,
            factory=True,
        )


def test_resolve_package_version_fallback() -> None:
    """Test package version fallback when get_version returns fallback."""
    with patch(
        "ecu_hockey_calendar.api.app.get_version",
        return_value="0.0.0+unknown",
    ):
        app = create_app()
        assert app.version == "0.0.0+unknown"


def test_app_lifespan_engine_disposal(tmp_path: Path) -> None:
    """Test app lifespan context manager disposes db engine if configured."""
    db_file = tmp_path / "lifespan.db"
    app = create_app(database_url=f"sqlite:///{db_file}")
    with TestClient(app) as client:
        res = client.get("/")
        assert res.status_code == 200

    # Also verify lifespan when db_engine is None
    app_no_db = create_app()
    with TestClient(app_no_db) as client_no_db:
        res = client_no_db.get("/")
        assert res.status_code == 200


def test_create_app_cors_disabled() -> None:
    """Test create_app with enable_cors=False."""
    app = create_app(enable_cors=False)
    client = TestClient(app)
    res = client.get("/")
    assert res.status_code == 200


def test_default_calendar_fallback(ecu_team: Team, unc_team: Team) -> None:
    """Test _get_active_games falls back to default_calendar when no override or DB."""
    app = create_app()
    default_cal = ECUHockeyCalendar()
    test_game = Game(
        game_id="DEFAULT-CAL-01",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2026, 11, 20, 23, 0, tzinfo=UTC),
        venue="The Factory Ice House",
    )
    default_cal.schedule.add_game(test_game)
    app.state.default_calendar = default_cal
    client = TestClient(app)

    res = client.get("/calendar.ics")
    assert res.status_code == 200
    assert "game-default-cal-01@ecuhockey.com" in res.text

    # Also test when default_calendar is None
    app.state.default_calendar = None
    res_empty = client.get("/calendar.ics")
    assert res_empty.status_code == 200
    assert "BEGIN:VEVENT" not in res_empty.text


def test_calendar_feed_postponed_game(ecu_team: Team, unc_team: Team) -> None:
    """Test calendar feed correctly formats postponed games with [POSTPONED] prefix."""
    game = Game(
        game_id="ECU-POSTPONED-01",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2026, 12, 1, 23, 0, tzinfo=UTC),
        venue="The Factory Ice House",
        result=GameResult.POSTPONED,
    )
    app = create_app()
    app.state.games_override = [game]
    client = TestClient(app)
    res = client.get("/calendar.ics")
    assert res.status_code == 200
    assert "SUMMARY:[POSTPONED] ECU Hockey vs UNC Chapel Hill" in res.text
    assert "STATUS:CANCELLED" in res.text


def test_calendar_feed_service_season_in_cal_name(sample_games: list[Game]) -> None:
    """Test season string is appended to X-WR-CALNAME."""
    svc = CalendarFeedService()
    feed = svc.generate_ics_feed(sample_games, season="2026-2027")
    assert "X-WR-CALNAME:ECU Men's Ice Hockey Schedule (2026-2027)" in feed


def test_calendar_feed_custom_config(sample_games: list[Game]) -> None:
    """Test custom configuration for CalendarFeedService."""
    config = CalendarFeedConfig(
        prod_id="-//Custom Org//Custom Calendar//EN",
        calendar_name="Custom Team Schedule",
        calendar_desc="Custom Description",
        timezone_name="UTC",
        refresh_interval_hours=2,
        alarm_minutes=45,
        duration_hours=3.0,
        primary_team_name="East Carolina University",
        domain="custom.org",
    )
    svc = CalendarFeedService(config=config)
    feed = svc.generate_ics_feed(sample_games)
    assert "PRODID:-//Custom Org//Custom Calendar//EN" in feed
    assert "X-WR-CALNAME:Custom Team Schedule" in feed
    assert "TRIGGER:-PT45M" in feed


def test_venue_details_missing_coordinates() -> None:
    """Test VenueDetails.geo_string returns None when coordinates are missing."""
    venue = VenueDetails(
        name="Mystery Rink",
        address="100 Secret Way",
        city="Raleigh",
        state="NC",
        postal_code="27601",
        latitude=None,
        longitude=None,
    )
    assert venue.geo_string is None
    assert "Mystery Rink, 100 Secret Way" in venue.full_location


def test_game_unknown_venue_no_geo(ecu_team: Team, unc_team: Team) -> None:
    """Test game at unknown venue omits GEO property line."""
    game = Game(
        game_id="UNKNOWN-VENUE-01",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2026, 12, 15, 23, 0, tzinfo=UTC),
        venue="Some Random Pond",
    )
    svc = CalendarFeedService()
    feed = svc.generate_ics_feed([game])
    assert "LOCATION:Some Random Pond" in feed
    assert "GEO:" not in feed


def test_get_last_modified_empty() -> None:
    """Test get_last_modified with empty list and default_dt."""
    fallback_dt = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    res = CalendarFeedService.get_last_modified([], default_dt=fallback_dt)
    assert res == fallback_dt

    now_res = CalendarFeedService.get_last_modified([])
    assert isinstance(now_res, datetime)


def test_line_folding_multibyte_and_chunks() -> None:
    """Test line folding for multi-byte UTF-8 and multiple fold splits."""
    very_long = "X" * 200
    folded = fold_line(very_long, max_octets=75)
    lines = folded.split("\r\n")
    assert len(lines) == 3
    assert lines[0] == "X" * 75
    assert lines[1] == " " + "X" * 74
    assert lines[2] == " " + "X" * 51

    # Multi-byte UTF-8 character that cannot fit in chunk boundary
    emoji_only = "🏒"
    folded_forced = fold_line(emoji_only, max_octets=2)
    assert folded_forced == "🏒"
