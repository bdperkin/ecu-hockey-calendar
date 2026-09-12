"""Comprehensive tests for RSS 2.0 and Atom 1.0 schedule syndication endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from ecu_hockey_calendar.api.app import create_app
from ecu_hockey_calendar.models import Game, GameResult, Team
from ecu_hockey_calendar.storage.engine import (
    create_sync_engine,
    get_sync_session,
    init_db,
)
from ecu_hockey_calendar.storage.models import GameModel, GameStatus, TeamModel
from ecu_hockey_calendar.syndication import ATOM_MEDIA_TYPE, RSS_MEDIA_TYPE

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def sample_syndication_games(ecu_team: Team, unc_team: Team) -> list[Game]:
    """Provide diverse game fixtures for testing syndication feeds."""
    nc_state = Team(
        name="NC State University",
        city="Raleigh",
        state="NC",
        division="ACHA M2",
        conference="ACCHL",
    )
    return [
        Game(
            game_id="ECU-2026-2027-01",
            home_team=ecu_team,
            away_team=unc_team,
            start_time=datetime(2026, 10, 2, 20, 0, tzinfo=UTC),
            venue="The Factory Ice House",
            result=GameResult.WIN,
            home_score=5,
            away_score=2,
        ),
        Game(
            game_id="ECU-2026-2027-02",
            home_team=nc_state,
            away_team=ecu_team,
            start_time=datetime(2026, 11, 14, 19, 30, tzinfo=UTC),
            venue="PNC Arena",
            result=GameResult.SCHEDULED,
        ),
        Game(
            game_id="ECU-2026-2027-03",
            home_team=ecu_team,
            away_team=unc_team,
            start_time=datetime(2026, 12, 5, 18, 0, tzinfo=UTC),
            venue="The Factory Ice House",
            result=GameResult.POSTPONED,
        ),
    ]


@pytest.fixture
def test_client(sample_syndication_games: list[Game]) -> TestClient:
    """Provide TestClient with in-memory sample games attached to app state."""
    app = create_app()
    app.state.games_override = sample_syndication_games
    return TestClient(app)


def test_get_feed_rss(test_client: TestClient) -> None:
    """Test GET /feed.rss returns valid RSS 2.0 XML with headers."""
    response = test_client.get("/feed.rss")
    assert response.status_code == 200
    assert response.headers["content-type"] == RSS_MEDIA_TYPE
    assert "public, max-age=300" in response.headers["cache-control"]
    assert "etag" in response.headers
    assert "last-modified" in response.headers
    assert (
        response.headers["content-disposition"]
        == 'inline; filename="ecu-hockey-schedule.rss"'
    )

    body = response.text
    assert "<rss" in body
    assert 'version="2.0"' in body
    assert "<title>ECU Men's Ice Hockey Schedule</title>" in body
    assert "Final: ECU 5, UNC Chapel Hill 2" in body
    assert "ECU Hockey at NC State University (Away Match)" in body
    assert "Postponed: ECU Hockey vs UNC Chapel Hill (Home Match)" in body


def test_head_feed_rss(test_client: TestClient) -> None:
    """Test HEAD /feed.rss returns caching headers with empty body."""
    response = test_client.head("/feed.rss")
    assert response.status_code == 200
    assert response.headers["content-type"] == RSS_MEDIA_TYPE
    assert "etag" in response.headers
    assert "last-modified" in response.headers
    assert response.text == ""


def test_get_api_schedule_rss(test_client: TestClient) -> None:
    """Test GET /api/schedule.rss alias behaves identically to /feed.rss."""
    response = test_client.get("/api/schedule.rss")
    assert response.status_code == 200
    assert response.headers["content-type"] == RSS_MEDIA_TYPE
    assert "<rss" in response.text
    assert "Final: ECU 5, UNC Chapel Hill 2" in response.text


def test_head_api_schedule_rss(test_client: TestClient) -> None:
    """Test HEAD /api/schedule.rss alias returns headers without body."""
    response = test_client.head("/api/schedule.rss")
    assert response.status_code == 200
    assert response.headers["content-type"] == RSS_MEDIA_TYPE
    assert response.text == ""


def test_get_feed_atom(test_client: TestClient) -> None:
    """Test GET /feed.atom returns valid Atom 1.0 XML with headers."""
    response = test_client.get("/feed.atom")
    assert response.status_code == 200
    assert response.headers["content-type"] == ATOM_MEDIA_TYPE
    assert "public, max-age=300" in response.headers["cache-control"]
    assert "etag" in response.headers
    assert "last-modified" in response.headers
    assert (
        response.headers["content-disposition"]
        == 'inline; filename="ecu-hockey-schedule.atom"'
    )

    body = response.text
    assert "<feed" in body
    assert "http://www.w3.org/2005/Atom" in body
    assert "<title>ECU Men's Ice Hockey Schedule</title>" in body
    assert "Final: ECU 5, UNC Chapel Hill 2" in body


def test_head_feed_atom(test_client: TestClient) -> None:
    """Test HEAD /feed.atom returns headers without body."""
    response = test_client.head("/feed.atom")
    assert response.status_code == 200
    assert response.headers["content-type"] == ATOM_MEDIA_TYPE
    assert "etag" in response.headers
    assert response.text == ""


def test_get_api_schedule_atom(test_client: TestClient) -> None:
    """Test GET /api/schedule.atom alias endpoint."""
    response = test_client.get("/api/schedule.atom")
    assert response.status_code == 200
    assert response.headers["content-type"] == ATOM_MEDIA_TYPE
    assert "<feed" in response.text


def test_head_api_schedule_atom(test_client: TestClient) -> None:
    """Test HEAD /api/schedule.atom alias endpoint."""
    response = test_client.head("/api/schedule.atom")
    assert response.status_code == 200
    assert response.headers["content-type"] == ATOM_MEDIA_TYPE
    assert response.text == ""


def test_feed_conditional_etag_caching(test_client: TestClient) -> None:
    """Test 304 Not Modified when client sends matching If-None-Match header."""
    res1 = test_client.get("/feed.rss")
    assert res1.status_code == 200
    etag = res1.headers["etag"]

    res2 = test_client.get("/feed.rss", headers={"If-None-Match": etag})
    assert res2.status_code == 304
    assert res2.text == ""


def test_feed_conditional_last_modified_caching(test_client: TestClient) -> None:
    """Test 304 Not Modified when client sends fresh If-Modified-Since header."""
    res1 = test_client.get("/feed.atom")
    assert res1.status_code == 200
    last_mod = res1.headers["last-modified"]

    res2 = test_client.get("/feed.atom", headers={"If-Modified-Since": last_mod})
    assert res2.status_code == 304
    assert res2.text == ""


def test_feed_filtering_parameters(test_client: TestClient) -> None:
    """Test syndication query parameter filters."""
    # Filter home_only
    home_res = test_client.get("/feed.rss?home_only=true")
    assert home_res.status_code == 200
    assert "Final: ECU 5, UNC Chapel Hill 2" in home_res.text
    assert "PNC Arena" not in home_res.text

    # Filter opponent
    opp_res = test_client.get("/feed.rss?opponent=NC+State")
    assert opp_res.status_code == 200
    assert "ECU Hockey at NC State University (Away Match)" in opp_res.text
    assert "The Factory Ice House" not in opp_res.text

    # Filter status
    status_res = test_client.get("/feed.rss?status=postponed")
    assert status_res.status_code == 200
    assert "Postponed: ECU Hockey vs UNC Chapel Hill (Home Match)" in status_res.text
    assert "ECU Hockey at NC State University" not in status_res.text


def test_feed_database_storage_integration(tmp_path: Path) -> None:
    """Test syndication feed with active database persistence storage."""
    db_path = tmp_path / "syndication_test.db"
    db_url = f"sqlite:///{db_path}"
    engine = create_sync_engine(db_url)
    init_db(engine)

    with get_sync_session(engine) as session:
        home_t = TeamModel(
            name="East Carolina University",
            city="Greenville",
            state="NC",
        )
        away_t = TeamModel(name="Duke University", city="Durham", state="NC")
        session.add_all([home_t, away_t])
        session.flush()

        game_m = GameModel(
            game_id="ECU-DUKE-01",
            season="2026-2027",
            home_team_id=home_t.id,
            away_team_id=away_t.id,
            start_time=datetime(2026, 12, 10, 20, 0, tzinfo=UTC),
            venue="The Factory Ice House",
            status=GameStatus.SCHEDULED,
        )
        session.add(game_m)
        session.commit()

    app = create_app(database_url=db_url)
    client = TestClient(app)

    res = client.get("/feed.rss")
    assert res.status_code == 200
    assert "ECU Hockey vs Duke University (Home Match)" in res.text
