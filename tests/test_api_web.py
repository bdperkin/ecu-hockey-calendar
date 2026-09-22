"""Comprehensive tests for responsive HTML schedule views and embed widget routes."""
# pylint: disable=too-many-lines

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
            start_time=datetime(2026, 9, 5, 23, 0, tzinfo=UTC),
            venue="The Factory Ice House",
            result=GameResult.WIN,
            home_score=5,
            away_score=2,
        ),
        Game(
            game_id="ECU-2026-05",
            home_team=duke,
            away_team=ecu_team,
            start_time=datetime(2026, 9, 12, 20, 0, tzinfo=UTC),
            venue="Orange County Sportsplex",
            result=GameResult.LOSS,
            home_score=4,
            away_score=1,
        ),
        Game(
            game_id="ECU-2026-06",
            home_team=ecu_team,
            away_team=vt,
            start_time=datetime(2026, 9, 13, 23, 30, tzinfo=UTC),
            venue="The Factory Ice House",
            result=GameResult.OVERTIME_LOSS,
            home_score=3,
            away_score=4,
        ),
        Game(
            game_id="ECU-2026-07",
            home_team=nc_state,
            away_team=ecu_team,
            start_time=datetime(2026, 9, 14, 23, 0, tzinfo=UTC),
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

    # Future only and include_past normalization
    res_fut = client.get("/schedule?future_only=true")
    assert res_fut.status_code == 200
    res_past = client.get("/schedule?include_past=false")
    assert res_past.status_code == 200
    assert res_fut.text == res_past.text


def test_schedule_embed_filtering(populated_db_url: str) -> None:
    """Verify query filtering on /schedule/embed route."""
    app = create_app(database_url=populated_db_url)
    client = TestClient(app)

    res = client.get("/schedule/embed?home_only=true&season=2026-2027")
    assert res.status_code == 200
    assert "Home Only" in res.text
    assert "The Factory Ice House" in res.text

    # Future only and include_past in embed mode
    res_fut_embed = client.get("/schedule/embed?future_only=true")
    assert res_fut_embed.status_code == 200
    res_past_embed = client.get("/schedule/embed?include_past=false")
    assert res_past_embed.status_code == 200
    assert res_fut_embed.text == res_past_embed.text


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
    assert "https://hockey.ecu.edu/schedule.ics" in html_base
    assert "https://hockey.ecu.edu/schedule.csv" in html_base
    assert "https://hockey.ecu.edu/schedule.json" in html_base

    # Embed HTML generation
    html_embed = service.generate_html_schedule(
        diverse_games,
        embed=True,
        base_url="https://hockey.ecu.edu",
    )
    assert "embed-mode" in html_embed
    assert "https://hockey.ecu.edu/schedule/embed" in html_embed


def test_favicon_and_static_branding_assets() -> None:
    """Verify favicon endpoint, webmanifest, and static branding assets are served."""
    app = create_app()
    client = TestClient(app)

    # GET /favicon.ico
    fav_res = client.get("/favicon.ico")
    assert fav_res.status_code == 200
    assert "image/x-icon" in fav_res.headers["Content-Type"]
    assert "public, max-age=86400" in fav_res.headers["Cache-Control"]
    assert len(fav_res.content) > 0

    # HEAD /favicon.ico
    head_fav = client.head("/favicon.ico")
    assert head_fav.status_code == 200
    assert "image/x-icon" in head_fav.headers["Content-Type"]
    assert head_fav.text == ""

    # GET /site.webmanifest
    manifest_res = client.get("/site.webmanifest")
    assert manifest_res.status_code == 200
    assert "application/manifest+json" in manifest_res.headers["Content-Type"]
    assert "public, max-age=86400" in manifest_res.headers["Cache-Control"]
    manifest_data = manifest_res.json()
    assert manifest_data["name"] == "East Carolina University Men's Ice Hockey Calendar"
    assert manifest_data["short_name"] == "ECU Hockey"
    assert manifest_data["theme_color"] == "#592a8a"
    assert len(manifest_data["icons"]) >= 2

    # HEAD /site.webmanifest
    head_manifest = client.head("/site.webmanifest")
    assert head_manifest.status_code == 200
    assert "application/manifest+json" in head_manifest.headers["Content-Type"]
    assert head_manifest.text == ""

    # GET /static/favicon.svg
    svg_fav = client.get("/static/favicon.svg")
    assert svg_fav.status_code == 200
    assert "image/svg+xml" in svg_fav.headers["Content-Type"]
    assert "<svg" in svg_fav.text

    # GET /static/ecu_hockey_logo.svg
    svg_res = client.get("/static/ecu_hockey_logo.svg")
    assert svg_res.status_code == 200
    assert "image/svg+xml" in svg_res.headers["Content-Type"]
    assert "<svg" in svg_res.text

    # GET /static/ecu_hockey_logo.png
    png_res = client.get("/static/ecu_hockey_logo.png")
    assert png_res.status_code == 200
    assert "image/png" in png_res.headers["Content-Type"]
    assert png_res.content[:8] == b"\x89PNG\r\n\x1a\n"

    # Multi-resolution icon PNGs
    for icon_name in [
        "favicon-16x16.png",
        "favicon-32x32.png",
        "apple-touch-icon.png",
        "android-chrome-192x192.png",
        "android-chrome-512x512.png",
    ]:
        res = client.get(f"/static/{icon_name}")
        assert res.status_code == 200
        assert "image/png" in res.headers["Content-Type"]
        assert res.content[:8] == b"\x89PNG\r\n\x1a\n"

    # GET /static/favicon.ico
    static_fav_res = client.get("/static/favicon.ico")
    assert static_fav_res.status_code == 200
    content_type = static_fav_res.headers["Content-Type"]
    assert "image/x-icon" in content_type or "image/vnd.microsoft.icon" in content_type


def test_schedule_html_includes_branding(diverse_games: list[Game]) -> None:
    """Verify rendered HTML schedule includes brand logo and favicon tags."""
    service = ScheduleDataService()
    html = service.generate_html_schedule(diverse_games)

    assert '<link rel="icon" type="image/x-icon" href="/favicon.ico">' in html
    assert '<link rel="icon" type="image/svg+xml" href="/static/favicon.svg">' in html
    assert 'sizes="32x32"' in html
    assert 'href="/static/favicon-32x32.png"' in html
    assert 'sizes="16x16"' in html
    assert 'href="/static/favicon-16x16.png"' in html
    assert 'sizes="180x180"' in html
    assert 'href="/static/apple-touch-icon.png"' in html
    assert '<link rel="manifest" href="/site.webmanifest">' in html
    assert '<meta name="theme-color" content="#592a8a">' in html
    assert '<img src="/static/ecu_hockey_logo.svg"' in html
    assert 'alt="East Carolina University Men\'s Ice Hockey Logo"' in html
    assert 'class="header-logo"' in html


def test_schedule_html_includes_formats_dropdown(
    diverse_games: list[Game],
) -> None:
    """Verify rendered HTML schedule includes top navigation formats dropdown."""
    service = ScheduleDataService()
    html = service.generate_html_schedule(
        diverse_games,
        base_url="https://hockey.ecu.edu",
    )

    # Formats dropdown trigger and ARIA attributes
    assert 'id="formats-menu-button"' in html
    assert 'aria-haspopup="true"' in html
    assert 'aria-expanded="false"' in html
    assert "Formats" in html

    # All 6 endpoints in formats dropdown
    assert 'href="https://hockey.ecu.edu/schedule.atom"' in html
    assert 'href="https://hockey.ecu.edu/schedule.csv"' in html
    assert 'href="https://hockey.ecu.edu/schedule.ics"' in html
    assert 'href="https://hockey.ecu.edu/schedule.json"' in html
    assert 'href="https://hockey.ecu.edu/schedule.pdf"' in html
    assert 'href="https://hockey.ecu.edu/schedule.rss"' in html
    assert "/schedule.atom" in html
    assert "/schedule.csv" in html
    assert "/schedule.ics" in html
    assert "/schedule.json" in html
    assert "/schedule.pdf" in html
    assert "/schedule.rss" in html


def test_schedule_html_includes_docs_dropdown(
    diverse_games: list[Game],
) -> None:
    """Verify rendered HTML schedule includes top navigation docs dropdown."""
    service = ScheduleDataService()
    html = service.generate_html_schedule(
        diverse_games,
        base_url="https://hockey.ecu.edu",
    )

    # Docs dropdown trigger and ARIA attributes
    assert 'id="docs-menu-button"' in html
    assert 'aria-haspopup="true"' in html
    assert 'aria-expanded="false"' in html
    assert "Docs" in html

    # All documentation targets in docs dropdown
    assert 'href="https://bdperkin.github.io/ecu-hockey-calendar/"' in html
    assert 'href="https://github.com/bdperkin/ecu-hockey-calendar"' in html
    assert 'href="/docs"' in html
    assert 'href="/redoc"' in html
    assert "Project Docs" in html
    assert "GitHub Repo" in html
    assert "Swagger UI" in html
    assert "ReDoc" in html


def test_schedule_html_includes_embed_widget_nav_link(
    diverse_games: list[Game],
) -> None:
    """Verify rendered HTML schedule includes Embed Widget top navigation link."""
    service = ScheduleDataService()
    html = service.generate_html_schedule(
        diverse_games,
        base_url="https://hockey.ecu.edu",
    )

    assert 'href="https://hockey.ecu.edu/schedule/embed"' in html
    assert "Embed Widget" in html
    assert '<div class="nav-actions">' not in html


def test_html_footer_includes_external_entity_links(
    diverse_games: list[Game],
) -> None:
    """Verify rendered HTML footer contains external entity links."""
    service = ScheduleDataService()
    html = service.generate_html_schedule(diverse_games)

    # Base footer organization and institutional links
    assert (
        '<a href="https://www.ecu.edu/"\n'
        '   target="_blank"\n'
        '   rel="noopener noreferrer">East Carolina University</a>'
    ) in html or 'href="https://www.ecu.edu/"' in html
    assert 'href="https://www.ecu.edu/"' in html
    assert 'href="https://www.acchockey.com/"' in html
    assert 'href="https://www.greenvillenc.gov/"' in html
    assert 'href="https://www.nc.gov/"' in html
    assert 'href="https://www.ecuhockey.com/"' in html
    assert 'href="https://github.com/bdperkin/ecu-hockey-calendar"' in html
    assert 'href="https://github.com/bdperkin/ecu-hockey-calendar/issues"' in html
    assert "Atlantic Coast Conference Hockey League (ACCHL)" in html
    assert "Official ECU Hockey Website" in html
    assert "GitHub Repository" in html
    assert "Issue Tracker" in html


def test_root_html_includes_hero_external_links() -> None:
    """Verify GET / hero section includes external entity links."""
    app = create_app()
    client = TestClient(app)
    resp = client.get(
        "/",
        headers={"Accept": "text/html,application/xhtml+xml"},
    )
    assert resp.status_code == 200
    html = resp.text

    assert 'href="https://www.ecuhockey.com/"' in html
    assert 'href="https://achahockey.org/"' in html
    assert 'href="https://www.acchockey.com/"' in html
    assert (
        "East Carolina University Men&#39;s Ice Hockey</a>" in html
        or "East Carolina University Men's Ice Hockey</a>" in html
    )
    assert ">ACHA</a>" in html
    assert ">ACCHL</a>" in html


def test_root_html_includes_grouped_feature_directory() -> None:
    """Verify GET / renders grouped feature directory with titles and summaries."""
    app = create_app()
    client = TestClient(app)
    resp = client.get(
        "/",
        headers={"Accept": "text/html,application/xhtml+xml"},
    )
    assert resp.status_code == 200
    html = resp.text

    # Section heading
    assert "Navigation &amp; Feature Directory" in html

    # Four logical category headers
    assert "Schedule &amp; Subscriptions</h4>" in html
    assert "Tools &amp; Widgets</h4>" in html
    assert "Documentation &amp; APIs</h4>" in html
    assert "System &amp; Diagnostics</h4>" in html

    # Category 1: Schedule & Subscriptions
    assert 'href="/schedule"' in html
    assert "Interactive schedule table and mobile cards" in html
    assert 'href="/schedule.ics"' in html
    assert "Live iCal calendar feed syncing game dates" in html
    assert 'href="/schedule.atom"' in html
    assert 'href="/schedule.csv"' in html
    assert 'href="/schedule.json"' in html
    assert 'href="/schedule.pdf"' in html
    assert 'href="/schedule.rss"' in html

    # Category 2: Tools & Widgets
    assert 'href="/schedule/embed"' in html
    assert "Responsive iframe schedule widget designed" in html
    assert 'id="hero-view-as-json-btn"' in html
    assert "Live REST service discovery document" in html

    # Category 3: Documentation & APIs
    assert 'href="https://bdperkin.github.io/ecu-hockey-calendar/"' in html
    assert 'href="https://github.com/bdperkin/ecu-hockey-calendar"' in html
    assert "Comprehensive architecture guides" in html
    assert "Source code repository, issue tracker" in html
    assert 'href="/docs"' in html
    assert "Interactive OpenAPI console to test endpoints" in html
    assert 'href="/redoc"' in html
    assert "Comprehensive visual OpenAPI reference documentation" in html

    # Category 4: System & Diagnostics
    assert 'href="/health"' in html
    assert "Real-time service health check, component diagnostics" in html
    assert 'href="/sync"' in html
    assert "Ingestion pipeline telemetry, upstream source freshness" in html
    assert 'href="/conflicts"' in html
    assert "Multi-source schedule dispute detection and automated" in html

    # Calendar subscription showcase URI consistency and sync guide
    assert "http://testserver/schedule.ics" in html
    assert "webcal://testserver/schedule.ics" in html
    assert (
        'href="https://bdperkin.github.io/ecu-hockey-calendar/calendar_sync.html"'
        in html
    )


@pytest.fixture
def multi_season_client(
    tmp_path: Path,
    ecu_team: Team,
    unc_team: Team,
) -> TestClient:
    """Fixture providing TestClient with games spanning 2025-2026 and 2026-2027."""
    db_file = tmp_path / "web_multi_season.db"
    db_url = f"sqlite:///{db_file}"
    engine = create_sync_engine(db_url)
    init_db(engine)

    g_current = Game(
        game_id="ECU-2026-01",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2026, 10, 16, 23, 30, tzinfo=UTC),
        venue="The Factory Ice House",
        result=GameResult.SCHEDULED,
    )
    vt_team = Team(name="Virginia Tech", city="Blacksburg", state="VA")
    g_historical = Game(
        game_id="ECU-2025-01",
        home_team=ecu_team,
        away_team=vt_team,
        start_time=datetime(2025, 10, 10, 20, 0, tzinfo=UTC),
        venue="The Factory Ice House",
        result=GameResult.WIN,
        home_score=4,
        away_score=2,
    )

    with get_sync_session(engine) as session:
        t1 = TeamModel(name=ecu_team.name, city=ecu_team.city, state=ecu_team.state)
        t2 = TeamModel(name=unc_team.name, city=unc_team.city, state=unc_team.state)
        t3 = TeamModel(name=vt_team.name, city=vt_team.city, state=vt_team.state)
        session.add_all([t1, t2, t3])
        session.flush()

        session.add_all(
            [
                GameModel.from_domain(
                    g_current,
                    home_team_id=t1.id,
                    away_team_id=t2.id,
                    season="2026-2027",
                ),
                GameModel.from_domain(
                    g_historical,
                    home_team_id=t1.id,
                    away_team_id=t3.id,
                    season="2025-2026",
                ),
            ],
        )
        session.commit()

    return TestClient(create_app(database_url=db_url))


def test_schedule_html_multi_season_defaults_and_aliases(
    multi_season_client: TestClient,
) -> None:
    """Verify /schedule HTML defaults to latest season and supports aliases."""
    client = multi_season_client

    # 1. Default visit to /schedule -> defaults to latest season (2026-2027)
    res_default = client.get("/schedule")
    assert res_default.status_code == 200
    assert "<strong>1</strong> game listed" in res_default.text
    assert "• Season 2026-2027" in res_default.text
    assert "Latest Season (2026-2027)" in res_default.text
    assert "UNC Chapel Hill" in res_default.text
    assert "Virginia Tech" not in res_default.text

    # 2. Explicit ?season=latest
    res_latest = client.get("/schedule?season=latest")
    assert res_latest.status_code == 200
    assert "<strong>1</strong> game listed" in res_latest.text
    assert "• Season 2026-2027" in res_latest.text
    assert "UNC Chapel Hill" in res_latest.text
    assert "Virginia Tech" not in res_latest.text

    # 3. Explicit ?season=all -> shows all games across seasons
    res_all = client.get("/schedule?season=all")
    assert res_all.status_code == 200
    assert "<strong>2</strong> games listed" in res_all.text
    assert "• All Seasons" in res_all.text
    assert "UNC Chapel Hill" in res_all.text
    assert "Virginia Tech" in res_all.text

    # 4. Explicit empty ?season= -> shows all games
    res_empty = client.get("/schedule?season=")
    assert res_empty.status_code == 200
    assert "<strong>2</strong> games listed" in res_empty.text
    assert "• All Seasons" in res_empty.text

    # 5. Explicit historical season ?season=2025-2026
    res_hist = client.get("/schedule?season=2025-2026")
    assert res_hist.status_code == 200
    assert "<strong>1</strong> game listed" in res_hist.text
    assert "• Season 2025-2026" in res_hist.text
    assert "Virginia Tech" in res_hist.text
    assert "UNC Chapel Hill" not in res_hist.text


def test_schedule_embed_multi_season_defaults_and_aliases(
    multi_season_client: TestClient,
) -> None:
    """Verify /schedule/embed and HEAD requests with season defaults and aliases."""
    client = multi_season_client

    # 1. /schedule/embed default -> latest season
    res_def = client.get("/schedule/embed")
    assert res_def.status_code == 200
    assert "<strong>1</strong> game listed" in res_def.text
    assert "• Season 2026-2027" in res_def.text

    # 2. /schedule/embed ?season=all -> all seasons
    res_all = client.get("/schedule/embed?season=all")
    assert res_all.status_code == 200
    assert "<strong>2</strong> games listed" in res_all.text
    assert "• All Seasons" in res_all.text

    # 3. /schedule/embed ?season=latest
    res_latest = client.get("/schedule/embed?season=latest")
    assert res_latest.status_code == 200
    assert "<strong>1</strong> game listed" in res_latest.text

    # 4. HEAD requests for /schedule and /schedule/embed
    assert client.head("/schedule?season=latest").status_code == 200
    assert client.head("/schedule?season=all").status_code == 200
    assert client.head("/schedule/embed?season=latest").status_code == 200
    assert client.head("/schedule/embed?season=all").status_code == 200


def test_schedule_now_divider_rendered_and_script_included(
    populated_db_url: str,
) -> None:
    """Verify NOW divider row, mobile card, and auto-scroll script in /schedule."""
    app = create_app(database_url=populated_db_url)
    client = TestClient(app)

    res = client.get("/schedule")
    assert res.status_code == 200
    assert 'id="now-divider"' in res.text
    assert 'class="now-divider-row"' in res.text
    assert 'id="now-divider-mobile"' in res.text
    assert 'class="now-divider-card"' in res.text
    assert "--- NOW ---" in res.text
    assert "scrollToNowDivider()" in res.text
    assert "scrollIntoView" in res.text


def test_schedule_embed_now_divider_rendered(populated_db_url: str) -> None:
    """Verify NOW divider and auto-scroll script in /schedule/embed."""
    app = create_app(database_url=populated_db_url)
    client = TestClient(app)

    res = client.get("/schedule/embed")
    assert res.status_code == 200
    assert 'id="now-divider"' in res.text
    assert 'id="now-divider-mobile"' in res.text
    assert "--- NOW ---" in res.text
    assert "scrollToNowDivider()" in res.text


def test_schedule_now_divider_omitted_when_only_past_or_future(
    populated_db_url: str,
) -> None:
    """Verify NOW divider is omitted when filtered to only past or scheduled games."""
    app = create_app(database_url=populated_db_url)
    client = TestClient(app)

    # Filter to final / completed games only (all games in past)
    res_past = client.get("/schedule?status=final")
    assert res_past.status_code == 200
    assert 'id="now-divider"' not in res_past.text
    assert "--- NOW ---" not in res_past.text
    assert "scrollToNowDivider" not in res_past.text

    # Filter to scheduled games only (all games in future)
    res_future = client.get("/schedule?status=scheduled")
    assert res_future.status_code == 200
    assert 'id="now-divider"' not in res_future.text
    assert "--- NOW ---" not in res_future.text
    assert "scrollToNowDivider" not in res_future.text


def test_schedule_now_divider_with_future_tie_games(  # pylint: disable=too-many-locals
    ecu_team: Team,
    unc_team: Team,
    tmp_path: Path,
) -> None:
    """Verify NOW divider renders when future games have tie results.

    Tests edge case where unplayed future games were crawled with 0-0 ties.
    """
    now = datetime.now(UTC)
    past_game = Game(
        game_id="PAST-TIE",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=now - timedelta(days=5),
        venue="The Factory Ice House",
        result=GameResult.TIE,
        home_score=2,
        away_score=2,
    )
    future_game = Game(
        game_id="FUTURE-TIE",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=now + timedelta(days=5),
        venue="The Factory Ice House",
        result=GameResult.TIE,
        home_score=0,
        away_score=0,
    )
    db_url = f"sqlite:///{tmp_path / 'tie_test.db'}"
    engine = create_sync_engine(db_url)
    init_db(engine)

    with get_sync_session(engine) as session:
        t1 = session.merge(TeamModel.from_domain(ecu_team))
        t2 = session.merge(TeamModel.from_domain(unc_team))
        session.flush()
        session.add(
            GameModel.from_domain(past_game, home_team_id=t1.id, away_team_id=t2.id),
        )
        session.add(
            GameModel.from_domain(future_game, home_team_id=t1.id, away_team_id=t2.id),
        )
        session.commit()

    app = create_app(database_url=db_url)
    client = TestClient(app)

    res = client.get("/schedule")
    assert res.status_code == 200
    assert 'id="now-divider"' in res.text
    assert "--- NOW ---" in res.text
    assert "scrollToNowDivider()" in res.text

    res_embed = client.get("/schedule/embed")
    assert res_embed.status_code == 200
    assert 'id="now-divider"' in res_embed.text
    assert "--- NOW ---" in res_embed.text
    assert "scrollToNowDivider()" in res_embed.text


def test_web_and_embed_team_logos_and_fallbacks(  # pylint: disable=too-many-locals
    tmp_path: Path,
    ecu_team: Team,
    unc_team: Team,
) -> None:
    """Verify team logos and fallback initials render in schedule and embed views."""
    team_with_logo = Team(
        name="Appalachian State University",
        city="Boone",
        state="NC",
        logo_url="https://example.com/asu_logo.png",
    )
    game_with_logo = Game(
        game_id="WEB-LOGO-01",
        home_team=ecu_team,
        away_team=team_with_logo,
        start_time=datetime(2026, 11, 14, 19, 30, tzinfo=UTC),
        venue="The Factory Ice House",
    )
    game_without_logo = Game(
        game_id="WEB-LOGO-02",
        home_team=unc_team,
        away_team=ecu_team,
        start_time=datetime(2026, 11, 21, 19, 0, tzinfo=UTC),
        venue="Orange County Sportsplex",
    )

    db_url = f"sqlite:///{tmp_path / 'logos_test.db'}"
    engine = create_sync_engine(db_url)
    init_db(engine)

    with get_sync_session(engine) as session:
        t_ecu = session.merge(TeamModel.from_domain(ecu_team))
        t_asu = session.merge(TeamModel.from_domain(team_with_logo))
        t_unc = session.merge(TeamModel.from_domain(unc_team))
        session.flush()
        session.add(
            GameModel.from_domain(
                game_with_logo,
                home_team_id=t_ecu.id,
                away_team_id=t_asu.id,
            ),
        )
        session.add(
            GameModel.from_domain(
                game_without_logo,
                home_team_id=t_unc.id,
                away_team_id=t_ecu.id,
            ),
        )
        session.commit()

    app = create_app(database_url=db_url)
    client = TestClient(app)

    # Schedule view
    res = client.get("/schedule")
    assert res.status_code == 200
    assert 'class="team-logo"' in res.text
    assert 'src="https://example.com/asu_logo.png"' in res.text
    assert 'alt="Appalachian State University logo"' in res.text
    assert 'class="team-logo-fallback"' in res.text
    assert 'aria-label="UNC Chapel Hill initials">UNC</span>' in res.text

    # Embed view
    res_embed = client.get("/schedule/embed")
    assert res_embed.status_code == 200
    assert 'class="team-logo"' in res_embed.text
    assert 'src="https://example.com/asu_logo.png"' in res_embed.text
    assert 'class="team-logo-fallback"' in res_embed.text
    assert 'aria-label="UNC Chapel Hill initials">UNC</span>' in res_embed.text
