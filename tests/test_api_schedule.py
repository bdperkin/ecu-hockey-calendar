"""Comprehensive tests for public master schedule JSON and CSV data feeds."""

# pylint: disable=too-many-lines

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
    resolve_past_and_future_filters,
)
from ecu_hockey_calendar.api.schedule_service import (
    ScheduleDataService,
    _annotate_now_divider,
    _build_render_context,
    _find_first_future_index,
    _format_coordinates,
    _is_game_past,
    filter_games,
    resolve_game_season,
    resolve_latest_season,
    resolve_pdf_filename,
)
from ecu_hockey_calendar.models import Game, GameResult, Team
from ecu_hockey_calendar.storage.engine import (
    create_sync_engine,
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
    """Test root endpoint advertises canonical schedule.* and legacy endpoints."""
    app = create_app()
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    endpoints = response.json()["endpoints"]
    assert endpoints["schedule_json"] == "/schedule.json"
    assert endpoints["schedule_csv"] == "/schedule.csv"
    assert endpoints["schedule_ics"] == "/schedule.ics"
    assert endpoints["schedule_rss"] == "/schedule.rss"
    assert endpoints["schedule_atom"] == "/schedule.atom"
    assert endpoints["calendar_ics"] == "/calendar.ics"
    assert endpoints["feed_rss"] == "/feed.rss"
    assert endpoints["feed_atom"] == "/feed.atom"


def test_get_schedule_json_endpoint(sample_games: list[Game]) -> None:
    """Test GET /schedule.json and /api/schedule.json route responses."""
    app = create_app()
    app.state.games_override = sample_games
    client = TestClient(app)

    # 1. Base canonical GET request
    resp = client.get("/schedule.json")
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

    # 2. Legacy alias parity
    alias_resp = client.get("/api/schedule.json")
    assert alias_resp.status_code == 200
    assert alias_resp.json() == data

    # 3. Query filters
    resp_filtered = client.get(
        "/schedule.json?season=2026-2027&opponent=UNC&home_only=true&status=W",
    )
    assert resp_filtered.status_code == 200
    filtered_data = resp_filtered.json()
    assert filtered_data["total_games"] == 1
    assert filtered_data["games"][0]["game_id"] == "ECU-2026-04"

    # 4. include_past and future_only parameter normalization
    resp_future = client.get("/schedule.json?future_only=true")
    assert resp_future.status_code == 200
    assert resp_future.json()["filters"]["future_only"] is True
    assert resp_future.json()["filters"]["include_past"] is False

    resp_past = client.get("/schedule.json?include_past=false")
    assert resp_past.status_code == 200
    assert resp_past.json()["filters"]["future_only"] is True
    assert resp_past.json()["filters"]["include_past"] is False


def test_head_schedule_json_endpoint(sample_games: list[Game]) -> None:
    """Test HEAD on /schedule.json and /api/schedule.json return empty body."""
    app = create_app()
    app.state.games_override = sample_games
    client = TestClient(app)

    get_resp = client.get("/schedule.json")
    head_resp = client.head("/schedule.json")
    alias_head = client.head("/api/schedule.json")

    assert head_resp.status_code == 200
    assert head_resp.content == b""
    assert head_resp.headers["etag"] == get_resp.headers["etag"]
    assert head_resp.headers["last-modified"] == get_resp.headers["last-modified"]
    assert alias_head.status_code == 200
    assert alias_head.headers["etag"] == get_resp.headers["etag"]


def test_get_schedule_csv_endpoint(sample_games: list[Game]) -> None:
    """Test GET /schedule.csv and /api/schedule.csv download headers and content."""
    app = create_app()
    app.state.games_override = sample_games
    client = TestClient(app)

    # 1. Base CSV GET request
    resp = client.get("/schedule.csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert resp.headers["content-disposition"] == (
        'attachment; filename="ecu-hockey-schedule.csv"'
    )
    assert "ETag" in resp.headers
    assert "Last-Modified" in resp.headers

    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert len(rows) == len(sample_games)

    # 2. Legacy alias parity
    alias_resp = client.get("/api/schedule.csv")
    assert alias_resp.status_code == 200
    assert alias_resp.text == resp.text

    # 3. Filtered CSV request
    resp_filtered = client.get("/schedule.csv?season=2026-2027&home_only=true")
    assert resp_filtered.status_code == 200
    filtered_rows = list(csv.DictReader(io.StringIO(resp_filtered.text)))
    assert len(filtered_rows) == 5
    for r in filtered_rows:
        assert r["designation"] == "Home"

    # 4. include_past / future_only filtering
    resp_fut = client.get("/schedule.csv?future_only=true")
    assert resp_fut.status_code == 200
    resp_inc_past = client.get("/schedule.csv?include_past=false")
    assert resp_inc_past.status_code == 200
    assert resp_fut.text == resp_inc_past.text


def test_head_schedule_csv_endpoint(sample_games: list[Game]) -> None:
    """Test HEAD /schedule.csv and /api/schedule.csv return empty body with headers."""
    app = create_app()
    app.state.games_override = sample_games
    client = TestClient(app)

    get_resp = client.get("/schedule.csv")
    head_resp = client.head("/schedule.csv")
    alias_head = client.head("/api/schedule.csv")

    assert head_resp.status_code == 200
    assert head_resp.content == b""
    assert head_resp.headers["etag"] == get_resp.headers["etag"]
    assert head_resp.headers["last-modified"] == get_resp.headers["last-modified"]

    assert alias_head.status_code == 200
    assert alias_head.content == b""
    assert alias_head.headers["etag"] == get_resp.headers["etag"]


def test_resolve_past_and_future_filters_unit() -> None:
    """Verify resolve_past_and_future_filters handles all permutations and defaults."""
    # Defaults
    assert resolve_past_and_future_filters(default_include_past=True) == (
        True,
        False,
    )
    assert resolve_past_and_future_filters(default_include_past=False) == (
        False,
        True,
    )

    # include_past provided alone
    assert resolve_past_and_future_filters(include_past=True) == (True, False)
    assert resolve_past_and_future_filters(include_past=False) == (False, True)

    # future_only provided alone
    assert resolve_past_and_future_filters(future_only=True) == (False, True)
    assert resolve_past_and_future_filters(future_only=False) == (True, False)

    # Both provided: include_past takes precedence
    assert resolve_past_and_future_filters(
        include_past=True,
        future_only=True,
    ) == (True, False)
    assert resolve_past_and_future_filters(
        include_past=False,
        future_only=False,
    ) == (False, True)
    assert resolve_past_and_future_filters(
        include_past=True,
        future_only=False,
    ) == (True, False)
    assert resolve_past_and_future_filters(
        include_past=False,
        future_only=True,
    ) == (False, True)


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
    res_strong = client.get("/api/schedule.json", headers={"If-None-Match": etag})
    assert res_strong.status_code == 304
    assert res_strong.content == b""

    # Match weak ETag
    assert (
        client.get(
            "/api/schedule.json",
            headers={"If-None-Match": f"W/{etag}"},
        ).status_code
        == 304
    )

    # Mismatch ETag
    assert (
        client.get(
            "/api/schedule.json",
            headers={"If-None-Match": '"mismatch"'},
        ).status_code
        == 200
    )

    # Match If-Modified-Since
    assert (
        client.get(
            "/api/schedule.json",
            headers={"If-Modified-Since": last_mod},
        ).status_code
        == 304
    )

    # Canonical /schedule.json conditional requests
    can_json = client.get("/schedule.json", headers={"If-None-Match": etag})
    assert can_json.status_code == 304
    assert can_json.content == b""

    assert (
        client.get(
            "/schedule.json",
            headers={"If-Modified-Since": last_mod},
        ).status_code
        == 304
    )

    # 2. CSV conditional requests
    csv_resp = client.get("/api/schedule.csv")
    csv_etag = csv_resp.headers["etag"]
    csv_304 = client.get("/api/schedule.csv", headers={"If-None-Match": csv_etag})
    assert csv_304.status_code == 304
    assert csv_304.content == b""

    # Canonical /schedule.csv conditional requests
    can_csv = client.get("/schedule.csv", headers={"If-None-Match": csv_etag})
    assert can_csv.status_code == 304
    assert can_csv.content == b""


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

    # Verify JSON feed loaded from DB (canonical and alias)
    json_resp = client.get("/api/schedule.json")
    assert json_resp.status_code == 200
    json_data = json_resp.json()
    assert json_data["total_games"] == 1
    assert json_data["games"][0]["game_id"] == "DB-2026-01"

    can_json_resp = client.get("/schedule.json")
    assert can_json_resp.status_code == 200
    assert can_json_resp.json() == json_data

    # Verify CSV feed loaded from DB (canonical and alias)
    csv_resp = client.get("/api/schedule.csv")
    assert csv_resp.status_code == 200
    rows = list(csv.DictReader(io.StringIO(csv_resp.text)))
    assert len(rows) == 1
    assert rows[0]["game_id"] == "DB-2026-01"

    can_csv_resp = client.get("/schedule.csv")
    assert can_csv_resp.status_code == 200
    assert can_csv_resp.text == csv_resp.text


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


def test_resolve_latest_season_variations(
    sample_games: list[Game],
    ecu_team: Team,
    unc_team: Team,
) -> None:
    """Test resolve_latest_season with game collections and reference dates."""
    older_game = Game(
        game_id="ECU-2025-01",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2025, 10, 16, 23, 30, tzinfo=UTC),
        venue="The Factory Ice House",
    )
    all_games = [*sample_games, older_game]
    assert resolve_latest_season(all_games) == "2026-2027"
    assert resolve_latest_season([older_game]) == "2025-2026"

    # With empty list / None, fall season (month >= 8)
    fall_dt = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    assert resolve_latest_season(None, now_utc=fall_dt) == "2026-2027"
    assert resolve_latest_season([], now_utc=fall_dt) == "2026-2027"

    # Spring season (month < 8)
    spring_dt = datetime(2027, 3, 1, 12, 0, tzinfo=UTC)
    assert resolve_latest_season([], now_utc=spring_dt) == "2026-2027"

    # Summer before cutoff (July)
    summer_dt = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
    assert resolve_latest_season([], now_utc=summer_dt) == "2025-2026"

    # Naive datetime
    naive_dt = datetime(2026, 11, 5, 14, 0)  # noqa: DTZ001
    assert resolve_latest_season([], now_utc=naive_dt) == "2026-2027"

    # Default (no arguments)
    latest_default = resolve_latest_season()
    assert len(latest_default) == 9
    assert "-" in latest_default


def test_filter_games_season_aliases(
    sample_games: list[Game],
    ecu_team: Team,
    unc_team: Team,
) -> None:
    """Test filter_games with season aliases: latest, current, all, and empty string."""
    older_game = Game(
        game_id="ECU-2025-01",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2025, 10, 16, 23, 30, tzinfo=UTC),
        venue="The Factory Ice House",
    )
    mixed_games = [*sample_games, older_game]

    # 'latest' and 'current' should filter to the latest season only
    latest_games = filter_games(mixed_games, season="latest")
    assert len(latest_games) == len(sample_games)
    assert older_game not in latest_games

    current_games = filter_games(mixed_games, season="CURRENT")
    assert current_games == latest_games

    # 'all' and '' should include all games across seasons
    all_games = filter_games(mixed_games, season="all")
    assert len(all_games) == len(mixed_games)
    assert older_game in all_games

    empty_season_games = filter_games(mixed_games, season="")
    assert len(empty_season_games) == len(mixed_games)

    none_season_games = filter_games(mixed_games, season=None)
    assert len(none_season_games) == len(mixed_games)

    # Specific historical season
    season_2025 = filter_games(mixed_games, season="2025-2026")
    assert len(season_2025) == 1
    assert season_2025[0].game_id == "ECU-2025-01"


def test_resolve_pdf_filename_aliases(sample_games: list[Game]) -> None:
    """Test resolve_pdf_filename with season aliases."""
    assert (
        resolve_pdf_filename("latest", sample_games)
        == "ecu_hockey_schedule_2026-2027.pdf"
    )
    assert (
        resolve_pdf_filename("CURRENT", sample_games)
        == "ecu_hockey_schedule_2026-2027.pdf"
    )
    assert resolve_pdf_filename("all", sample_games) == "ecu_hockey_schedule.pdf"
    assert resolve_pdf_filename("ALL", sample_games) == "ecu_hockey_schedule.pdf"


@pytest.fixture
def season_aliases_client(
    tmp_path: Path,
    sample_games: list[Game],
    ecu_team: Team,
    unc_team: Team,
) -> TestClient:
    """Fixture providing TestClient with games in 2025-2026 and 2026-2027."""
    db_url = f"sqlite:///{tmp_path / 'aliases_test.db'}"
    engine = create_sync_engine(db_url)
    init_db(engine)

    older_game = Game(
        game_id="ECU-2025-01",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2025, 10, 16, 23, 30, tzinfo=UTC),
        venue="The Factory Ice House",
    )

    with get_sync_session(engine) as session:
        t1 = TeamModel(name=ecu_team.name, city=ecu_team.city, state=ecu_team.state)
        t2 = TeamModel(name=unc_team.name, city=unc_team.city, state=unc_team.state)
        session.add_all([t1, t2])
        session.flush()

        for g in sample_games:
            session.add(
                GameModel.from_domain(
                    g,
                    home_team_id=t1.id,
                    away_team_id=t2.id,
                    season="2026-2027",
                ),
            )

        session.add(
            GameModel.from_domain(
                older_game,
                home_team_id=t1.id,
                away_team_id=t2.id,
                season="2025-2026",
            ),
        )
        session.commit()

    return TestClient(create_app(database_url=db_url))


def test_extract_games_from_database_season_aliases(
    season_aliases_client: TestClient,
    sample_games: list[Game],
) -> None:
    """Test extract_games_from_database query filtering with season aliases."""
    client = season_aliases_client

    # Verify JSON feed with aliases
    res_latest = client.get("/schedule.json?season=latest")
    assert res_latest.status_code == 200
    assert res_latest.json()["total_games"] == len(sample_games)

    res_all = client.get("/schedule.json?season=all")
    assert res_all.status_code == 200
    assert res_all.json()["total_games"] == len(sample_games) + 1

    res_historical = client.get("/schedule.json?season=2025-2026")
    assert res_historical.status_code == 200
    assert res_historical.json()["total_games"] == 1
    assert res_historical.json()["games"][0]["game_id"] == "ECU-2025-01"

    # Verify default JSON feed without season query defaults to latest season
    res_default_json = client.get("/schedule.json")
    assert res_default_json.status_code == 200
    assert res_default_json.json()["total_games"] == len(sample_games)
    assert res_default_json.json()["season"] == "2026-2027"

    # Verify CSV feed with aliases
    res_csv_latest = client.get("/schedule.csv?season=latest")
    assert res_csv_latest.status_code == 200
    assert "ECU-2025-01" not in res_csv_latest.text

    res_csv_all = client.get("/schedule.csv?season=all")
    assert res_csv_all.status_code == 200
    assert "ECU-2025-01" in res_csv_all.text

    # Verify default CSV feed without season query defaults to latest season
    res_default_csv = client.get("/schedule.csv")
    assert res_default_csv.status_code == 200
    assert "ECU-2025-01" not in res_default_csv.text

    # Verify PDF route with aliases
    res_pdf_latest = client.get("/schedule.pdf?season=latest")
    assert res_pdf_latest.status_code == 200
    assert (
        'filename="ecu_hockey_schedule_2026-2027.pdf"'
        in res_pdf_latest.headers["content-disposition"]
    )

    res_pdf_all = client.get("/schedule.pdf?season=all")
    assert res_pdf_all.status_code == 200
    assert (
        'filename="ecu_hockey_schedule.pdf"'
        in res_pdf_all.headers["content-disposition"]
    )

    # Verify default PDF feeds without season query default to latest season
    res_default_pdf = client.get("/schedule.pdf")
    assert res_default_pdf.status_code == 200
    assert (
        'filename="ecu_hockey_schedule_2026-2027.pdf"'
        in res_default_pdf.headers["content-disposition"]
    )

    res_default_api_pdf = client.get("/api/schedule.pdf")
    assert res_default_api_pdf.status_code == 200
    assert (
        'filename="ecu_hockey_schedule_2026-2027.pdf"'
        in res_default_api_pdf.headers["content-disposition"]
    )


def test_build_render_context_season_variations(sample_games: list[Game]) -> None:
    """Test _build_render_context with different season filter inputs."""
    ctx_none = _build_render_context(sample_games, [], "http://test", {"season": None})
    assert ctx_none["selected_season"] == "latest"
    assert ctx_none["is_all_seasons"] is False

    ctx_empty = _build_render_context(sample_games, [], "http://test", {})
    assert ctx_empty["selected_season"] == "latest"

    ctx_all = _build_render_context(sample_games, [], "http://test", {"season": "all"})
    assert ctx_all["selected_season"] == "all"
    assert ctx_all["is_all_seasons"] is True

    ctx_spec = _build_render_context(
        sample_games,
        [],
        "http://test",
        {"season": "2025-2026"},
    )
    assert ctx_spec["selected_season"] == "2025-2026"
    assert ctx_spec["resolved_season"] == "2025-2026"


def test_extract_games_from_database_empty_db_latest(tmp_path: Path) -> None:
    """Test extract_games_from_database with latest season on empty database."""
    db_url = f"sqlite:///{tmp_path / 'empty_latest.db'}"
    engine = create_sync_engine(db_url)
    init_db(engine)
    client = TestClient(create_app(database_url=db_url))
    res = client.get("/schedule.json?season=latest")
    assert res.status_code == 200
    assert res.json()["total_games"] == 0


def test_is_game_past(ecu_team: Team, unc_team: Team) -> None:
    """Test _is_game_past evaluates chronologically based on game start time."""
    ref_time = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)

    past_game = Game(
        game_id="PAST-1",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2026, 9, 20, 20, 0, tzinfo=UTC),
        venue="The Factory Ice House",
        result=GameResult.SCHEDULED,
    )
    assert _is_game_past(past_game, ref_time) is True

    # Future game with a tie/win result (e.g. scraped unplayed game) is not past
    future_game_with_result = Game(
        game_id="FUTURE-TIE-1",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2026, 10, 15, 20, 0, tzinfo=UTC),
        venue="The Factory Ice House",
        result=GameResult.TIE,
        home_score=0,
        away_score=0,
    )
    assert _is_game_past(future_game_with_result, ref_time) is False

    future_scheduled_game = Game(
        game_id="FUTURE-1",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2026, 10, 15, 20, 0, tzinfo=UTC),
        venue="The Factory Ice House",
        result=GameResult.SCHEDULED,
    )
    assert _is_game_past(future_scheduled_game, ref_time) is False

    # Naive ref_time handling
    naive_ref = datetime(2026, 10, 1, 0, 0)  # noqa: DTZ001
    assert _is_game_past(past_game, naive_ref) is True
    assert _is_game_past(future_scheduled_game, naive_ref) is False


def test_find_first_future_index(ecu_team: Team, unc_team: Team) -> None:
    """Test _find_first_future_index identifies first upcoming fixture."""
    ref_time = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)

    assert _find_first_future_index([], ref_time) is None

    past_g = Game(
        game_id="P1",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2026, 9, 10, 20, 0, tzinfo=UTC),
        venue="Rink",
        result=GameResult.WIN,
    )
    future_g = Game(
        game_id="F1",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2026, 10, 10, 20, 0, tzinfo=UTC),
        venue="Rink",
        result=GameResult.SCHEDULED,
    )

    assert _find_first_future_index([past_g], ref_time) is None
    assert _find_first_future_index([future_g], ref_time) == 0
    assert _find_first_future_index([past_g, future_g], ref_time) == 1


def test_annotate_now_divider(ecu_team: Team, unc_team: Team) -> None:
    """Test _annotate_now_divider sets show_now_divider_before correctly."""
    ref_time = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)

    past_g = Game(
        game_id="P1",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2026, 9, 10, 20, 0, tzinfo=UTC),
        venue="Rink",
        result=GameResult.WIN,
    )
    future_g = Game(
        game_id="F1",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2026, 10, 10, 20, 0, tzinfo=UTC),
        venue="Rink",
        result=GameResult.SCHEDULED,
    )

    fmt_games = [{"id": "P1"}, {"id": "F1"}]
    has_div = _annotate_now_divider(fmt_games, [past_g, future_g], ref_time)
    assert has_div is True
    assert fmt_games[0]["show_now_divider_before"] is False
    assert fmt_games[1]["show_now_divider_before"] is True

    fmt_future = [{"id": "F1"}]
    has_div_future = _annotate_now_divider(fmt_future, [future_g], ref_time)
    assert has_div_future is False
    assert fmt_future[0]["show_now_divider_before"] is False

    fmt_past = [{"id": "P1"}]
    has_div_past = _annotate_now_divider(fmt_past, [past_g], ref_time)
    assert has_div_past is False
    assert fmt_past[0]["show_now_divider_before"] is False


def test_generate_html_schedule_now_divider(sample_games: list[Game]) -> None:
    """Test generate_html_schedule renders NOW divider and scroll centering script."""
    service = ScheduleDataService()
    ref_now = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)

    html_with_divider = service.generate_html_schedule(
        sample_games,
        season="all",
        now_utc=ref_now,
    )
    assert 'id="now-divider"' in html_with_divider
    assert 'id="now-divider-mobile"' in html_with_divider
    assert "--- NOW ---" in html_with_divider
    assert "scrollToNowDivider()" in html_with_divider
    assert "scrollIntoView" in html_with_divider

    html_embed = service.generate_html_schedule(
        sample_games,
        season="all",
        embed=True,
        now_utc=ref_now,
    )
    assert 'id="now-divider"' in html_embed
    assert 'id="now-divider-mobile"' in html_embed
    assert "--- NOW ---" in html_embed
    assert "scrollToNowDivider()" in html_embed
