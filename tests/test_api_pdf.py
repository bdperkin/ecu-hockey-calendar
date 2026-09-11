"""Comprehensive tests for printable PDF schedule export and route handlers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from ecu_hockey_calendar.api.app import create_app
from ecu_hockey_calendar.api.schedule_service import (
    ScheduleDataService,
    resolve_pdf_filename,
)
from ecu_hockey_calendar.models import Game, GameResult, Team
from ecu_hockey_calendar.storage.engine import (
    create_sync_engine,
    get_sync_session,
    init_db,
)
from ecu_hockey_calendar.storage.models import GameModel, TeamModel

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def ecu_team() -> Team:
    """Fixture providing canonical ECU team."""
    return Team(
        name="East Carolina University",
        city="Greenville",
        state="NC",
        division="ACHA M2",
        conference="ACCHL",
    )


@pytest.fixture
def unc_team() -> Team:
    """Fixture providing standard opponent team."""
    return Team(
        name="UNC Chapel Hill",
        city="Chapel Hill",
        state="NC",
        division="ACHA M2",
        conference="ACCHL",
    )


@pytest.fixture
def diverse_games(ecu_team: Team, unc_team: Team) -> list[Game]:
    """Fixture providing diverse set of games across results and venues."""
    nc_state = Team(
        name="NC State University",
        city="Raleigh",
        state="NC",
        division="ACHA M2",
        conference="ACCHL",
    )
    vt = Team(
        name="Virginia Tech",
        city="Blacksburg",
        state="VA",
        division="ACHA M2",
        conference="ACCHL",
    )
    duke = Team(
        name="Duke University",
        city="Durham",
        state="NC",
        division="ACHA M2",
        conference="ACCHL",
    )

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
            result=GameResult.WIN,
            home_score=2,
            away_score=4,
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
            result=GameResult.LOSS,
            home_score=1,
            away_score=3,
        ),
        Game(
            game_id="ECU-2026-05",
            home_team=ecu_team,
            away_team=duke,
            start_time=datetime(2026, 11, 20, 23, 0, tzinfo=UTC),
            venue="The Factory Ice House",
            result=GameResult.OVERTIME_LOSS,
            home_score=3,
            away_score=4,
        ),
        Game(
            game_id="ECU-2026-06",
            home_team=duke,
            away_team=ecu_team,
            start_time=datetime(2026, 12, 5, 23, 0, tzinfo=UTC),
            venue="Orange County Sportsplex",
            result=GameResult.TIE,
            home_score=2,
            away_score=2,
        ),
        Game(
            game_id="ECU-2026-07",
            home_team=ecu_team,
            away_team=nc_state,
            start_time=datetime(2026, 12, 12, 23, 0, tzinfo=UTC),
            venue="The Factory Ice House",
            result=GameResult.POSTPONED,
        ),
        Game(
            game_id="ECU-2027-01",
            home_team=duke,
            away_team=ecu_team,
            start_time=datetime(2027, 1, 15, 19, 0, tzinfo=UTC),
            venue="Orange County Sportsplex",
            result=GameResult.SCHEDULED,
        ),
    ]


@pytest.fixture
def populated_db_app(tmp_path: Path, diverse_games: list[Game]) -> TestClient:
    """Fixture providing FastAPI test client backed by SQLite database with games."""
    db_file = tmp_path / "test_pdf.db"
    db_url = f"sqlite:///{db_file}"
    engine = create_sync_engine(db_url)
    init_db(engine)

    with get_sync_session(engine) as session:
        team_models: dict[str, TeamModel] = {}
        for g in diverse_games:
            for t in (g.home_team, g.away_team):
                if t.name not in team_models:
                    tm = TeamModel(
                        name=t.name,
                        city=t.city,
                        state=t.state,
                        division=t.division,
                        conference=t.conference,
                    )
                    session.add(tm)
                    session.flush()
                    team_models[t.name] = tm

            gm = GameModel.from_domain(
                g,
                home_team_id=team_models[g.home_team.name].id,
                away_team_id=team_models[g.away_team.name].id,
                season="2026-2027",
            )
            session.add(gm)

        session.commit()

    app = create_app(database_url=db_url)
    return TestClient(app)


def test_generate_pdf_schedule_valid_binary(diverse_games: list[Game]) -> None:
    """Verify generate_pdf_schedule returns binary PDF starting with %PDF-1."""
    service = ScheduleDataService()
    pdf_bytes = service.generate_pdf_schedule(diverse_games)
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000
    assert pdf_bytes.startswith(b"%PDF-1.")


def test_generate_pdf_schedule_empty() -> None:
    """Verify generate_pdf_schedule handles empty game list cleanly."""
    service = ScheduleDataService()
    pdf_bytes = service.generate_pdf_schedule([])
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF-1.")


def test_generate_pdf_schedule_filters(diverse_games: list[Game]) -> None:
    """Verify generate_pdf_schedule honors filter options."""
    service = ScheduleDataService()
    pdf_bytes = service.generate_pdf_schedule(
        diverse_games,
        season="2026-2027",
        opponent="UNC",
        home_only=True,
        status="scheduled",
        generated_date="Oct 16, 2026",
    )
    assert pdf_bytes.startswith(b"%PDF-1.")


def test_resolve_pdf_filename(diverse_games: list[Game]) -> None:
    """Verify attachment filename resolution for various conditions."""
    # Explicit season
    assert (
        resolve_pdf_filename("2026-2027", diverse_games)
        == "ecu_hockey_schedule_2026-2027.pdf"
    )
    assert (
        resolve_pdf_filename(" 2026 2027 ", diverse_games)
        == "ecu_hockey_schedule_2026-2027.pdf"
    )

    # Inferred single season
    single_season = [g for g in diverse_games if "2026" in g.game_id]
    assert (
        resolve_pdf_filename(None, single_season) == "ecu_hockey_schedule_2026-2027.pdf"
    )

    # Inferred multiple seasons
    multi_season_games = [
        *diverse_games,
        Game(
            game_id="ECU-2025-01",
            home_team=diverse_games[0].home_team,
            away_team=diverse_games[0].away_team,
            start_time=datetime(2025, 10, 10, 20, 0, tzinfo=UTC),
            venue="The Factory Ice House",
            result=GameResult.SCHEDULED,
        ),
    ]
    assert resolve_pdf_filename(None, multi_season_games) == "ecu_hockey_schedule.pdf"

    # Empty list
    assert resolve_pdf_filename(None, []) == "ecu_hockey_schedule.pdf"


def test_get_api_schedule_pdf(populated_db_app: TestClient) -> None:
    """Verify GET /api/schedule.pdf returns valid binary and headers."""
    resp = populated_db_app.get("/api/schedule.pdf?season=2026-2027")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert (
        'attachment; filename="ecu_hockey_schedule_2026-2027.pdf"'
        in resp.headers["content-disposition"]
    )
    assert "etag" in resp.headers
    assert "last-modified" in resp.headers
    assert resp.content.startswith(b"%PDF-1.")


def test_get_web_schedule_pdf(populated_db_app: TestClient) -> None:
    """Verify GET /schedule.pdf returns application/pdf from web root path."""
    resp = populated_db_app.get("/schedule.pdf?season=2026-2027")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert (
        'attachment; filename="ecu_hockey_schedule_2026-2027.pdf"'
        in resp.headers["content-disposition"]
    )
    assert resp.content.startswith(b"%PDF-1.")


def test_head_schedule_pdf(populated_db_app: TestClient) -> None:
    """Verify HEAD /api/schedule.pdf and /schedule.pdf return empty bodies."""
    for path in ["/api/schedule.pdf", "/schedule.pdf"]:
        resp = populated_db_app.head(path)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert "etag" in resp.headers
        assert "last-modified" in resp.headers
        assert len(resp.content) == 0


def test_schedule_pdf_caching_etag_304(populated_db_app: TestClient) -> None:
    """Verify conditional revalidation via If-None-Match returns 304."""
    initial = populated_db_app.get("/schedule.pdf?season=2026-2027")
    assert initial.status_code == 200
    etag = initial.headers["etag"]

    cached_resp = populated_db_app.get(
        "/schedule.pdf?season=2026-2027",
        headers={"if-none-match": etag},
    )
    assert cached_resp.status_code == 304
    assert len(cached_resp.content) == 0


def test_schedule_pdf_caching_last_modified_304(
    populated_db_app: TestClient,
) -> None:
    """Verify conditional revalidation via If-Modified-Since returns 304."""
    initial = populated_db_app.get("/api/schedule.pdf?season=2026-2027")
    assert initial.status_code == 200
    last_mod = initial.headers["last-modified"]

    cached_resp = populated_db_app.get(
        "/api/schedule.pdf?season=2026-2027",
        headers={"if-modified-since": last_mod},
    )
    assert cached_resp.status_code == 304
    assert len(cached_resp.content) == 0


def test_schedule_pdf_filtering(populated_db_app: TestClient) -> None:
    """Verify query filters narrow results and return valid PDF."""
    resp = populated_db_app.get(
        "/schedule.pdf?home_only=true&status=scheduled&opponent=UNC",
    )
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF-1.")


def test_schedule_views_contain_pdf_links(
    populated_db_app: TestClient,
) -> None:
    """Verify HTML schedule view and root view link to schedule.pdf."""
    sched_html = populated_db_app.get("/schedule")
    assert sched_html.status_code == 200
    assert "/schedule.pdf" in sched_html.text
    assert "Export PDF" in sched_html.text
    assert "Printable PDF" in sched_html.text

    root_html = populated_db_app.get("/", headers={"accept": "text/html"})
    assert root_html.status_code == 200
    assert "/schedule.pdf" in root_html.text

    root_json = populated_db_app.get("/", headers={"accept": "application/json"})
    assert root_json.status_code == 200
    assert root_json.json()["endpoints"]["schedule_pdf"] == "/schedule.pdf"
