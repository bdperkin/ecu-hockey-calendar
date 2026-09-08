"""Comprehensive tests for public master schedule JSON and CSV data feeds."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from ecu_hockey_calendar.api.app import create_app
from ecu_hockey_calendar.api.routes.common import (
    check_conditional_headers,
    extract_games_from_database,
    is_etag_fresh,
    is_modified_since_fresh,
)
from ecu_hockey_calendar.api.schedule_service import (
    ScheduleDataService,
    _format_coordinates,
    filter_games,
    resolve_game_season,
)
from ecu_hockey_calendar.models import Game, GameResult, Team
from ecu_hockey_calendar.storage.engine import (
    get_sync_session,
    init_db,
)
from ecu_hockey_calendar.storage.models import GameModel, GameStatus, TeamModel

if TYPE_CHECKING:
    from pathlib import Path


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
    """Fixture providing diverse set of sample games."""
    nc_state = Team(name="NC State University", city="Raleigh", state="NC")
    vt = Team(name="Virginia Tech", city="Blacksburg", state="VA")
    duke = Team(name="Duke University", city="Durham", state="NC")

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
        Game(
            game_id="ECU-2027-01",
            home_team=duke,
            away_team=ecu_team,
            start_time=datetime(2027, 1, 15, 19, 0, tzinfo=UTC),
            venue="Orange County Sportsplex",
            result=GameResult.LOSS,
            home_score=4,
            away_score=1,
        ),
        Game(
            game_id="ECU-2027-02",
            home_team=ecu_team,
            away_team=nc_state,
            start_time=datetime(2027, 2, 20, 20, 0, tzinfo=UTC),
            venue="The Factory Ice House",
            result=GameResult.TIE,
            home_score=3,
            away_score=3,
        ),
        Game(
            game_id="ECU-2027-03",
            home_team=ecu_team,
            away_team=vt,
            start_time=datetime(2027, 3, 5, 20, 0, tzinfo=UTC),
            venue="The Factory Ice House",
            result=GameResult.OVERTIME_LOSS,
            home_score=2,
            away_score=3,
        ),
    ]


def test_resolve_game_season(ecu_team: Team, unc_team: Team) -> None:
    """Test collegiate season string computation based on month cutoff."""
    fall_game = Game(
        game_id="G1",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        venue="The Factory Ice House",
    )
    spring_game = Game(
        game_id="G2",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2027, 7, 31, 12, 0, tzinfo=UTC),
        venue="The Factory Ice House",
    )

    assert resolve_game_season(fall_game) == "2026-2027"
    assert resolve_game_season(spring_game) == "2026-2027"


def test_format_coordinates() -> None:
    """Test venue coordinates parser for valid, empty, and invalid geo values."""
    assert _format_coordinates(None) is None
    assert _format_coordinates("") is None
    assert _format_coordinates("invalid-no-semicolon") is None

    parsed = _format_coordinates("35.9389;-78.5367")
    assert parsed == {"latitude": 35.9389, "longitude": -78.5367}


def test_filter_games_options(sample_games: list[Game]) -> None:
    """Test filter_games function across all filter dimensions."""
    # 1. Season filter
    season_games = filter_games(sample_games, season="2026-2027")
    assert len(season_games) == len(sample_games)
    assert filter_games(sample_games, season="2025-2026") == []

    # 2. Opponent filter (case insensitive substring)
    unc_games = filter_games(sample_games, opponent="unc chapel")
    assert len(unc_games) == 2
    for g in unc_games:
        assert "unc" in g.away_team.name.lower() or "unc" in g.home_team.name.lower()

    # 3. Home only filter
    home_games = filter_games(sample_games, home_only=True)
    assert len(home_games) == 5
    for g in home_games:
        assert g.home_team.name == "East Carolina University"

    # 4. Status filter variants
    w_games = filter_games(sample_games, status="W")
    assert len(w_games) == 1
    assert filter_games(sample_games, status="win") == w_games
    assert filter_games(sample_games, status="WINS") == w_games

    l_games = filter_games(sample_games, status="L")
    assert len(l_games) == 1
    assert filter_games(sample_games, status="loss") == l_games
    assert filter_games(sample_games, status="LOSSES") == l_games

    t_games = filter_games(sample_games, status="T")
    assert len(t_games) == 1
    assert filter_games(sample_games, status="tie") == t_games
    assert filter_games(sample_games, status="TIES") == t_games

    otl_games = filter_games(sample_games, status="OTL")
    assert len(otl_games) == 1
    assert filter_games(sample_games, status="overtime_loss") == otl_games
    assert filter_games(sample_games, status="OT_LOSS") == otl_games

    canc_games = filter_games(sample_games, status="CANCELLED")
    assert len(canc_games) == 1
    assert filter_games(sample_games, status="CANCELED") == canc_games

    sched_games = filter_games(sample_games, status="SCHEDULED")
    assert len(sched_games) == 2

    # Non-matching status
    assert filter_games(sample_games, status="NON_EXISTENT") == []

    # Combined filters
    combined = filter_games(
        sample_games,
        season="2026-2027",
        opponent="UNC",
        home_only=True,
        status="W",
    )
    assert len(combined) == 1
    assert combined[0].game_id == "ECU-2026-04"


def test_schedule_data_service_json(sample_games: list[Game]) -> None:
    """Test ScheduleDataService JSON generation methods."""
    service = ScheduleDataService()

    feed = service.generate_json_feed(sample_games)
    assert feed["primary_team"] == "East Carolina University"
    assert feed["total_games"] == len(sample_games)
    assert len(feed["games"]) == len(sample_games)

    first_game = feed["games"][0]
    assert first_game["game_id"] == "ECU-2026-04"  # earliest start time in sample
    assert first_game["designation"] == "Home"
    assert first_game["is_home"] is True
    assert first_game["tickets_url"] is not None
    assert first_game["coordinates"] is not None
    assert first_game["status"] == "W"
    assert first_game["home_score"] == 5
    assert first_game["away_score"] == 2

    json_str = service.generate_json_string(sample_games, indent=2)
    assert isinstance(json_str, str)
    assert '"total_games": 7' in json_str


def test_schedule_data_service_csv(sample_games: list[Game]) -> None:
    """Test ScheduleDataService CSV generation format and columns."""
    service = ScheduleDataService()
    csv_text = service.generate_csv_feed(sample_games)

    reader = csv.DictReader(io.StringIO(csv_text))
    rows = list(reader)
    assert len(rows) == len(sample_games)

    expected_cols = [
        "game_id",
        "season",
        "date",
        "time_utc",
        "start_time_iso",
        "home_team",
        "away_team",
        "opponent",
        "designation",
        "venue",
        "location",
        "status",
        "home_score",
        "away_score",
        "tickets_url",
    ]
    assert reader.fieldnames == expected_cols

    # Check score formatting: integer score vs empty string
    first_row = rows[0]  # ECU-2026-04
    assert first_row["home_score"] == "5"
    assert first_row["away_score"] == "2"
    assert first_row["tickets_url"] != ""

    scheduled_row = rows[1]  # ECU-2026-01
    assert scheduled_row["home_score"] == ""
    assert scheduled_row["away_score"] == ""


def test_root_endpoint_schedule_urls() -> None:
    """Test root endpoint advertises schedule.json and schedule.csv endpoints."""
    app = create_app()
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    endpoints = response.json()["endpoints"]
    assert endpoints["schedule_json"] == "/api/schedule.json"
    assert endpoints["schedule_csv"] == "/api/schedule.csv"


def test_get_schedule_json_endpoint(sample_games: list[Game]) -> None:
    """Test GET /api/schedule.json endpoint responses and query filters."""
    app = create_app()
    app.state.games_override = sample_games
    client = TestClient(app)

    # 1. Base GET request
    resp = client.get("/api/schedule.json")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/json"
    assert resp.headers["content-disposition"] == (
        'inline; filename="ecu-hockey-schedule.json"'
    )
    assert "ETag" in resp.headers
    assert "Last-Modified" in resp.headers
    assert "max-age=" in resp.headers["cache-control"]

    data = resp.json()
    assert data["total_games"] == len(sample_games)
    assert len(data["games"]) == len(sample_games)

    # 2. Query filters
    resp_filtered = client.get(
        "/api/schedule.json?season=2026-2027&opponent=UNC&home_only=true&status=W",
    )
    assert resp_filtered.status_code == 200
    filtered_data = resp_filtered.json()
    assert filtered_data["total_games"] == 1
    assert filtered_data["games"][0]["game_id"] == "ECU-2026-04"


def test_head_schedule_json_endpoint(sample_games: list[Game]) -> None:
    """Test HEAD /api/schedule.json returns identical headers and empty body."""
    app = create_app()
    app.state.games_override = sample_games
    client = TestClient(app)

    get_resp = client.get("/api/schedule.json")
    head_resp = client.head("/api/schedule.json")

    assert head_resp.status_code == 200
    assert head_resp.content == b""
    assert head_resp.headers["etag"] == get_resp.headers["etag"]
    assert head_resp.headers["last-modified"] == get_resp.headers["last-modified"]


def test_get_schedule_csv_endpoint(sample_games: list[Game]) -> None:
    """Test GET /api/schedule.csv endpoint download headers and content."""
    app = create_app()
    app.state.games_override = sample_games
    client = TestClient(app)

    # 1. Base CSV GET request
    resp = client.get("/api/schedule.csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert resp.headers["content-disposition"] == (
        'attachment; filename="ecu-hockey-schedule.csv"'
    )
    assert "ETag" in resp.headers
    assert "Last-Modified" in resp.headers

    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert len(rows) == len(sample_games)

    # 2. Filtered CSV request
    resp_filtered = client.get("/api/schedule.csv?season=2026-2027&home_only=true")
    assert resp_filtered.status_code == 200
    filtered_rows = list(csv.DictReader(io.StringIO(resp_filtered.text)))
    assert len(filtered_rows) == 5
    for r in filtered_rows:
        assert r["designation"] == "Home"


def test_head_schedule_csv_endpoint(sample_games: list[Game]) -> None:
    """Test HEAD /api/schedule.csv returns empty body with headers."""
    app = create_app()
    app.state.games_override = sample_games
    client = TestClient(app)

    get_resp = client.get("/api/schedule.csv")
    head_resp = client.head("/api/schedule.csv")

    assert head_resp.status_code == 200
    assert head_resp.content == b""
    assert head_resp.headers["etag"] == get_resp.headers["etag"]
    assert head_resp.headers["last-modified"] == get_resp.headers["last-modified"]


def test_schedule_conditional_caching(sample_games: list[Game]) -> None:
    """Test HTTP conditional caching (304 Not Modified) for JSON and CSV feeds."""
    app = create_app()
    app.state.games_override = sample_games
    client = TestClient(app)

    # 1. JSON conditional requests
    json_resp = client.get("/api/schedule.json")
    etag = json_resp.headers["etag"]
    last_mod = json_resp.headers["last-modified"]

    # Match strong ETag
    r304_strong = client.get("/api/schedule.json", headers={"If-None-Match": etag})
    assert r304_strong.status_code == 304
    assert r304_strong.content == b""

    # Match weak ETag
    r304_weak = client.get("/api/schedule.json", headers={"If-None-Match": f"W/{etag}"})
    assert r304_weak.status_code == 304

    # Mismatch ETag
    r200_etag = client.get(
        "/api/schedule.json",
        headers={"If-None-Match": '"mismatch"'},
    )
    assert r200_etag.status_code == 200

    # Match If-Modified-Since
    r304_mod = client.get("/api/schedule.json", headers={"If-Modified-Since": last_mod})
    assert r304_mod.status_code == 304

    # 2. CSV conditional requests
    csv_resp = client.get("/api/schedule.csv")
    csv_etag = csv_resp.headers["etag"]
    csv_304 = client.get("/api/schedule.csv", headers={"If-None-Match": csv_etag})
    assert csv_304.status_code == 304
    assert csv_304.content == b""


def test_schedule_database_integration(tmp_path: Path) -> None:
    """Test schedule endpoints loading from seeded SQLite database."""
    db_file = tmp_path / "test_schedule.db"
    db_url = f"sqlite:///{db_file}"

    app = create_app(database_url=db_url)
    init_db(app.state.db_engine)

    with get_sync_session(app.state.db_engine) as session:
        ecu_orm = TeamModel(
            name="East Carolina University",
            city="Greenville",
            state="NC",
            division="ACHA M2",
            conference="ACCHL",
        )
        unc_orm = TeamModel(
            name="UNC Chapel Hill",
            city="Chapel Hill",
            state="NC",
            division="ACHA M2",
            conference="ACCHL",
        )
        session.add_all([ecu_orm, unc_orm])
        session.flush()

        game_orm = GameModel(
            game_id="DB-2026-01",
            home_team_id=ecu_orm.id,
            away_team_id=unc_orm.id,
            start_time=datetime(2026, 11, 20, 23, 0, tzinfo=UTC),
            venue="The Factory Ice House",
            season="2026-2027",
            status=GameStatus.SCHEDULED,
        )
        session.add(game_orm)
        session.commit()

    client = TestClient(app)

    # Verify JSON feed loaded from DB
    json_resp = client.get("/api/schedule.json")
    assert json_resp.status_code == 200
    json_data = json_resp.json()
    assert json_data["total_games"] == 1
    assert json_data["games"][0]["game_id"] == "DB-2026-01"

    # Verify CSV feed loaded from DB
    csv_resp = client.get("/api/schedule.csv")
    assert csv_resp.status_code == 200
    rows = list(csv.DictReader(io.StringIO(csv_resp.text)))
    assert len(rows) == 1
    assert rows[0]["game_id"] == "DB-2026-01"


def test_common_helpers_edge_cases() -> None:
    """Test edge cases for shared route caching and extraction helpers."""
    # 1. is_etag_fresh with empty client etag
    assert is_etag_fresh(None, '"abc"') is False
    assert is_etag_fresh("", '"abc"') is False

    # 2. is_modified_since_fresh with empty or invalid date
    assert is_modified_since_fresh(None, "Tue, 08 Sep 2026 12:00:00 GMT") is False
    assert (
        is_modified_since_fresh("invalid date", "Tue, 08 Sep 2026 12:00:00 GMT")
        is False
    )

    # 3. extract_games_from_database when db_engine is None
    dummy_request = cast(
        Request,
        type(
            "Req",
            (),
            {
                "app": type(
                    "App",
                    (),
                    {"state": type("State", (), {"db_engine": None})()},
                )(),
            },
        )(),
    )
    assert extract_games_from_database(dummy_request) == []

    # 4. check_conditional_headers with no matching headers
    headers_req = cast(
        Request,
        type(
            "Req",
            (),
            {
                "headers": {
                    "if-none-match": '"other"',
                    "if-modified-since": "Mon, 01 Jan 2000 00:00:00 GMT",
                },
            },
        )(),
    )
    assert (
        check_conditional_headers(
            headers_req,
            '"my-etag"',
            "Tue, 08 Sep 2026 12:00:00 GMT",
        )
        is False
    )
