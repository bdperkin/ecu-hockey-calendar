"""Comprehensive tests for responsive HTML schedule views and embed widget routes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from ecu_hockey_calendar.api.app import create_app
from ecu_hockey_calendar.api.schedule_service import (
    DEFAULT_TEMPLATES_DIR,
    ScheduleDataService,
    _format_html_game,
)
from ecu_hockey_calendar.api.service import DEFAULT_TICKETS_URL
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
            game_id="ECU-2026-05",
            home_team=duke,
            away_team=ecu_team,
            start_time=datetime(2026, 9, 27, 20, 0, tzinfo=UTC),
            venue="Orange County Sportsplex",
            result=GameResult.LOSS,
            home_score=4,
            away_score=1,
        ),
        Game(
            game_id="ECU-2026-06",
            home_team=ecu_team,
            away_team=vt,
            start_time=datetime(2026, 10, 3, 23, 30, tzinfo=UTC),
            venue="The Factory Ice House",
            result=GameResult.OVERTIME_LOSS,
            home_score=3,
            away_score=4,
        ),
        Game(
            game_id="ECU-2026-07",
            home_team=nc_state,
            away_team=ecu_team,
            start_time=datetime(2026, 10, 10, 23, 0, tzinfo=UTC),
            venue="Invisalign Arena",
            result=GameResult.TIE,
            home_score=2,
            away_score=2,
        ),
        Game(
            game_id="ECU-2026-08",
            home_team=ecu_team,
            away_team=duke,
            start_time=datetime(2026, 12, 4, 23, 0, tzinfo=UTC),
            venue="Unknown Local Arena",
            result=GameResult.POSTPONED,
        ),
    ]


@pytest.fixture
def populated_db_url(tmp_path: Path, diverse_games: list[Game]) -> str:
    """Fixture initializing database with diverse game fixtures."""
    db_file = tmp_path / "web_test.db"
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

    return db_url


def test_get_schedule_html_empty() -> None:
    """Verify /schedule responds with 200 and empty state when no games exist."""
    app = create_app()
    client = TestClient(app)
    response = client.get("/schedule")

    assert response.status_code == 200
    assert "text/html" in response.headers["Content-Type"]
    assert (
        'filename="ecu-hockey-schedule.html"' in response.headers["Content-Disposition"]
    )
    assert "ETag" in response.headers
    assert "Last-Modified" in response.headers
    assert "No Games Found" in response.text
    assert "East Carolina University Men's Ice Hockey" in response.text


def test_head_schedule_html() -> None:
    """Verify HEAD /schedule returns headers with empty body."""
    app = create_app()
    client = TestClient(app)
    response = client.head("/schedule")

    assert response.status_code == 200
    assert response.text == ""
    assert "text/html" in response.headers["Content-Type"]
    assert "ETag" in response.headers
    assert "Last-Modified" in response.headers


def test_get_schedule_embed_empty() -> None:
    """Verify /schedule/embed responds with lightweight widget layout."""
    app = create_app()
    client = TestClient(app)
    response = client.get("/schedule/embed")

    assert response.status_code == 200
    assert "text/html" in response.headers["Content-Type"]
    assert (
        'filename="ecu-hockey-schedule-embed.html"'
        in response.headers["Content-Disposition"]
    )
    assert "embed-mode" in response.text
    assert '<header class="site-header">' not in response.text
    assert '<nav class="site-nav">' not in response.text
    assert '<footer class="site-footer">' not in response.text
    assert "copyEmbedCode" in response.text


def test_head_schedule_embed() -> None:
    """Verify HEAD /schedule/embed returns headers with empty body."""
    app = create_app()
    client = TestClient(app)
    response = client.head("/schedule/embed")

    assert response.status_code == 200
    assert response.text == ""
    assert "text/html" in response.headers["Content-Type"]
    assert "ETag" in response.headers


def test_schedule_conditional_headers_304(populated_db_url: str) -> None:
    """Verify conditional revalidation returns 304 for ETag or Last-Modified."""
    app = create_app(database_url=populated_db_url)
    client = TestClient(app)

    res = client.get("/schedule")
    assert res.status_code == 200
    etag = res.headers["ETag"]
    last_mod = res.headers["Last-Modified"]

    # Matching If-None-Match
    res_inm = client.get("/schedule", headers={"If-None-Match": etag})
    assert res_inm.status_code == 304
    assert res_inm.text == ""

    # Matching If-Modified-Since
    res_ims = client.get("/schedule", headers={"If-Modified-Since": last_mod})
    assert res_ims.status_code == 304
    assert res_ims.text == ""

    # Non-matching ETag
    res_stale = client.get("/schedule", headers={"If-None-Match": '"stale-etag"'})
    assert res_stale.status_code == 200


def test_schedule_filtering(populated_db_url: str) -> None:
    """Verify query filtering on /schedule route."""
    app = create_app(database_url=populated_db_url)
    client = TestClient(app)

    # Season filter
    res_season = client.get("/schedule?season=2026-2027")
    assert res_season.status_code == 200
    assert "<strong>8</strong> games listed" in res_season.text

    # Home only filter
    res_home = client.get("/schedule?home_only=true")
    assert res_home.status_code == 200
    assert "Home Matches Only" in res_home.text
    assert "Home" in res_home.text

    # Opponent substring filter
    res_opp = client.get("/schedule?opponent=unc")
    assert res_opp.status_code == 200
    assert "UNC Chapel Hill" in res_opp.text
    assert "Duke University" not in res_opp.text

    # Status filter - Scheduled
    res_sched = client.get("/schedule?status=scheduled")
    assert res_sched.status_code == 200
    assert "Scheduled" in res_sched.text

    # Status filter - Final
    res_final = client.get("/schedule?status=final")
    assert res_final.status_code == 200
    assert "W 5-2" in res_final.text
    assert "L 1-4" in res_final.text

    # Empty result filter
    res_empty = client.get("/schedule?opponent=NonExistentTeamXYZ")
    assert res_empty.status_code == 200
    assert "No Games Found" in res_empty.text


def test_schedule_embed_filtering(populated_db_url: str) -> None:
    """Verify query filtering on /schedule/embed route."""
    app = create_app(database_url=populated_db_url)
    client = TestClient(app)

    res = client.get("/schedule/embed?home_only=true&season=2026-2027")
    assert res.status_code == 200
    assert "Home Only" in res.text
    assert "The Factory Ice House" in res.text


def test_schedule_html_game_details_rendering(populated_db_url: str) -> None:
    """Verify detailed elements: venues, map links, tickets button, scores, badges."""
    app = create_app(database_url=populated_db_url)
    client = TestClient(app)

    res = client.get("/schedule")
    assert res.status_code == 200
    content = res.text

    # Venue & Map link
    assert "The Factory Ice House" in content
    assert "1839 S Main St, Wake Forest, NC 27587" in content
    assert "https://www.google.com/maps/search/?api=1&amp;query=" in content

    # Tickets button (present for home games, absent/dash for away games)
    assert DEFAULT_TICKETS_URL in content
    assert "btn-ticket" in content

    # Game statuses and badges
    assert "status-win" in content
    assert "W 5-2" in content
    assert "status-loss" in content
    assert "L 1-4" in content
    assert "status-otl" in content
    assert "OTL 3-4" in content
    assert "status-tie" in content
    assert "T 2-2" in content
    assert "status-cancelled" in content
    assert "Cancelled" in content
    assert "status-postponed" in content
    assert "Postponed" in content


def test_format_html_game_helper_variations(ecu_team: Team, unc_team: Team) -> None:
    """Verify _format_html_game with various outcomes and edge cases."""
    now = datetime(2026, 10, 16, 23, 30, tzinfo=UTC)

    # Win with no scores specified
    win_game = Game("W1", ecu_team, unc_team, now, "Rink", GameResult.WIN)
    w_view = _format_html_game(win_game, ecu_team.name)
    assert w_view["score_text"] == "W"
    assert w_view["status_badge_class"] == "status-win"
    assert w_view["is_home"] is True
    assert w_view["tickets_url"] == DEFAULT_TICKETS_URL

    # Loss with no scores specified
    loss_game = Game("L1", ecu_team, unc_team, now, "Rink", GameResult.LOSS)
    l_view = _format_html_game(loss_game, ecu_team.name)
    assert l_view["score_text"] == "L"
    assert l_view["status_badge_class"] == "status-loss"

    # OT Loss with no scores specified
    otl_game = Game("O1", ecu_team, unc_team, now, "Rink", GameResult.OVERTIME_LOSS)
    o_view = _format_html_game(otl_game, ecu_team.name)
    assert o_view["score_text"] == "OTL"
    assert o_view["status_badge_class"] == "status-otl"

    # Tie with no scores specified
    tie_game = Game("T1", ecu_team, unc_team, now, "Rink", GameResult.TIE)
    t_view = _format_html_game(tie_game, ecu_team.name)
    assert t_view["score_text"] == "T"
    assert t_view["status_badge_class"] == "status-tie"

    # Away game: no tickets URL
    away_game = Game("A1", unc_team, ecu_team, now, "Rink", GameResult.SCHEDULED)
    a_view = _format_html_game(away_game, ecu_team.name)
    assert a_view["is_home"] is False
    assert a_view["designation"] == "Away"
    assert a_view["tickets_url"] is None


def test_schedule_data_service_html_unit(diverse_games: list[Game]) -> None:
    """Unit test ScheduleDataService HTML generation methods."""
    service = ScheduleDataService()

    # Verify Jinja environment property
    assert service.jinja_env is not None

    # Custom template directory
    custom_service = ScheduleDataService(templates_dir=DEFAULT_TEMPLATES_DIR)
    html_custom = custom_service.generate_html_schedule(diverse_games)
    assert "East Carolina University Men's Ice Hockey" in html_custom

    # Custom base_url
    html_base = service.generate_html_schedule(
        diverse_games,
        base_url="https://hockey.ecu.edu",
    )
    assert "https://hockey.ecu.edu/schedule" in html_base
    assert "https://hockey.ecu.edu/calendar.ics" in html_base
    assert "https://hockey.ecu.edu/api/schedule.csv" in html_base
    assert "https://hockey.ecu.edu/api/schedule.json" in html_base

    # Embed HTML generation
    html_embed = service.generate_html_schedule(
        diverse_games,
        embed=True,
        base_url="https://hockey.ecu.edu",
    )
    assert "embed-mode" in html_embed
    assert "https://hockey.ecu.edu/schedule/embed" in html_embed
