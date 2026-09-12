"""Unit and functional tests for the RSS and Atom syndication feed engine."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from ecu_hockey_calendar.api.service import DEFAULT_ECU_TEAM_NAME
from ecu_hockey_calendar.models import Game, GameResult, Team
from ecu_hockey_calendar.syndication import (
    RSS_MEDIA_TYPE,
    SyndicationConfig,
    SyndicationFeedService,
    _build_description_details,
    _build_division_conference_line,
    _format_abnormal_status_title,
    _format_completed_title,
    _resolve_match_scores,
    build_syndication_caching_headers,
    format_match_description,
    format_match_title,
)

EASTERN_TZ = ZoneInfo("America/New_York")


def test_syndication_config_defaults() -> None:
    """Verify default values in SyndicationConfig dataclass."""
    config = SyndicationConfig()
    assert config.title == "ECU Men's Ice Hockey Schedule"
    assert "Official schedule" in config.description
    assert config.base_url == "https://ecuhockey.com"
    assert config.language == "en-US"
    assert config.primary_team_name == DEFAULT_ECU_TEAM_NAME


def test_syndication_config_custom() -> None:
    """Verify custom values in SyndicationConfig dataclass."""
    config = SyndicationConfig(
        title="Custom Title",
        description="Custom Description",
        base_url="https://custom.com",
        language="en-GB",
        primary_team_name="Custom Team",
    )
    assert config.title == "Custom Title"
    assert config.description == "Custom Description"
    assert config.base_url == "https://custom.com"
    assert config.language == "en-GB"
    assert config.primary_team_name == "Custom Team"


def test_resolve_match_scores(ecu_team: Team, unc_team: Team) -> None:
    """Test extracting scores from perspective of primary team."""
    game = Game(
        game_id="G1",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2026, 11, 6, 19, 30, tzinfo=UTC),
        venue="The Factory Ice House",
        home_score=5,
        away_score=2,
        result=GameResult.WIN,
    )
    # Home perspective
    p_score, o_score = _resolve_match_scores(game, is_home=True)
    assert p_score == 5
    assert o_score == 2

    # Away perspective
    p_score_away, o_score_away = _resolve_match_scores(game, is_home=False)
    assert p_score_away == 2
    assert o_score_away == 5


def test_format_completed_title_outcomes(ecu_team: Team, unc_team: Team) -> None:
    """Test title formatting for all completed game results."""
    # Win
    win_game = Game(
        game_id="G1",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2026, 11, 6, 19, 30, tzinfo=UTC),
        venue="Arena",
        home_score=6,
        away_score=3,
        result=GameResult.WIN,
    )
    assert (
        _format_completed_title(win_game, is_home=True, opponent_name="UNC Chapel Hill")
        == "Final: ECU 6, UNC Chapel Hill 3"
    )

    # Loss
    loss_game = Game(
        game_id="G2",
        home_team=unc_team,
        away_team=ecu_team,
        start_time=datetime(2026, 11, 7, 19, 30, tzinfo=UTC),
        venue="Arena",
        home_score=4,
        away_score=1,
        result=GameResult.LOSS,
    )
    assert (
        _format_completed_title(
            loss_game,
            is_home=False,
            opponent_name="UNC Chapel Hill",
        )
        == "Final: ECU 1, UNC Chapel Hill 4"
    )

    # Overtime loss
    otl_game = Game(
        game_id="G3",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2026, 11, 8, 19, 30, tzinfo=UTC),
        venue="Arena",
        home_score=2,
        away_score=3,
        result=GameResult.OVERTIME_LOSS,
    )
    assert (
        _format_completed_title(otl_game, is_home=True, opponent_name="UNC Chapel Hill")
        == "Final (OT): ECU 2, UNC Chapel Hill 3"
    )

    # Tie
    tie_game = Game(
        game_id="G4",
        home_team=unc_team,
        away_team=ecu_team,
        start_time=datetime(2026, 11, 9, 19, 30, tzinfo=UTC),
        venue="Arena",
        home_score=2,
        away_score=2,
        result=GameResult.TIE,
    )
    assert (
        _format_completed_title(
            tie_game,
            is_home=False,
            opponent_name="UNC Chapel Hill",
        )
        == "Final: ECU 2, UNC Chapel Hill 2"
    )


def test_format_completed_title_missing_scores_or_uncompleted(
    ecu_team: Team,
    unc_team: Team,
) -> None:
    """Test that completed title returns None when scores are missing or uncompleted."""
    sched_game = Game(
        game_id="G1",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2026, 11, 6, 19, 30, tzinfo=UTC),
        venue="Arena",
        result=GameResult.SCHEDULED,
    )
    assert (
        _format_completed_title(sched_game, is_home=True, opponent_name="UNC") is None
    )

    missing_score_game = Game(
        game_id="G2",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2026, 11, 6, 19, 30, tzinfo=UTC),
        venue="Arena",
        home_score=None,
        away_score=3,
        result=GameResult.WIN,
    )
    assert (
        _format_completed_title(missing_score_game, is_home=True, opponent_name="UNC")
        is None
    )


def test_format_abnormal_status_title(ecu_team: Team, unc_team: Team) -> None:
    """Test title formatting for cancelled, postponed, and regular games."""
    cancelled = Game(
        game_id="G1",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2026, 11, 6, 19, 30, tzinfo=UTC),
        venue="Arena",
        result=GameResult.CANCELLED,
    )
    assert (
        _format_abnormal_status_title(
            cancelled,
            "ECU Hockey vs UNC Chapel Hill",
            "Home Match",
        )
        == "Cancelled: ECU Hockey vs UNC Chapel Hill (Home Match)"
    )

    postponed = Game(
        game_id="G2",
        home_team=unc_team,
        away_team=ecu_team,
        start_time=datetime(2026, 11, 7, 19, 30, tzinfo=UTC),
        venue="Arena",
        result=GameResult.POSTPONED,
    )
    assert (
        _format_abnormal_status_title(
            postponed,
            "ECU Hockey at UNC Chapel Hill",
            "Away Match",
        )
        == "Postponed: ECU Hockey at UNC Chapel Hill (Away Match)"
    )

    scheduled = Game(
        game_id="G3",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2026, 11, 8, 19, 30, tzinfo=UTC),
        venue="Arena",
        result=GameResult.SCHEDULED,
    )
    assert (
        _format_abnormal_status_title(
            scheduled,
            "ECU Hockey vs UNC Chapel Hill",
            "Home Match",
        )
        is None
    )


def test_format_match_title_all_cases(ecu_team: Team, unc_team: Team) -> None:
    """Verify format_match_title for home, away, scheduled, and abnormal games."""
    home_sched = Game(
        game_id="G1",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2026, 11, 6, 19, 30, tzinfo=UTC),
        venue="Arena",
        result=GameResult.SCHEDULED,
    )
    assert (
        format_match_title(home_sched, DEFAULT_ECU_TEAM_NAME)
        == "ECU Hockey vs UNC Chapel Hill (Home Match)"
    )

    away_sched = Game(
        game_id="G2",
        home_team=unc_team,
        away_team=ecu_team,
        start_time=datetime(2026, 11, 7, 19, 30, tzinfo=UTC),
        venue="Arena",
        result=GameResult.SCHEDULED,
    )
    assert (
        format_match_title(away_sched, DEFAULT_ECU_TEAM_NAME)
        == "ECU Hockey at UNC Chapel Hill (Away Match)"
    )

    cancelled_game = Game(
        game_id="G3",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2026, 11, 8, 19, 30, tzinfo=UTC),
        venue="Arena",
        result=GameResult.CANCELLED,
    )
    assert (
        format_match_title(cancelled_game, DEFAULT_ECU_TEAM_NAME)
        == "Cancelled: ECU Hockey vs UNC Chapel Hill (Home Match)"
    )

    postponed_game = Game(
        game_id="G4",
        home_team=unc_team,
        away_team=ecu_team,
        start_time=datetime(2026, 11, 9, 19, 30, tzinfo=UTC),
        venue="Arena",
        result=GameResult.POSTPONED,
    )
    assert (
        format_match_title(postponed_game, DEFAULT_ECU_TEAM_NAME)
        == "Postponed: ECU Hockey at UNC Chapel Hill (Away Match)"
    )

    completed_game = Game(
        game_id="G5",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2026, 11, 10, 19, 30, tzinfo=UTC),
        venue="Arena",
        result=GameResult.WIN,
        home_score=5,
        away_score=2,
    )
    assert (
        format_match_title(completed_game, DEFAULT_ECU_TEAM_NAME)
        == "Final: ECU 5, UNC Chapel Hill 2"
    )


def test_build_division_conference_line() -> None:
    """Test building opponent division and conference descriptor line."""
    full_team = Team(
        name="NC State",
        city="Raleigh",
        state="NC",
        division="ACHA M2",
        conference="ACCHL",
    )
    assert (
        _build_division_conference_line(full_team)
        == "Division: ACHA M2 | Conference: ACCHL"
    )

    div_only_team = Team(
        name="Club Team",
        city="Charlotte",
        state="NC",
        division="ACHA M2",
        conference="",
    )
    assert _build_division_conference_line(div_only_team) == "Division: ACHA M2"

    no_div_team = Team(
        name="Open Team",
        city="Greenville",
        state="NC",
        division="",
        conference="",
    )
    assert _build_division_conference_line(no_div_team) is None


def test_build_description_details(ecu_team: Team, unc_team: Team) -> None:
    """Test description details lines with scores, notes, and ticket link."""
    # Completed home game
    completed_home = Game(
        game_id="G1",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2026, 11, 6, 19, 30, tzinfo=UTC),
        venue="The Factory Ice House",
        home_score=5,
        away_score=2,
        result=GameResult.WIN,
    )
    lines = _build_description_details(
        completed_home,
        is_home=True,
        opponent_name="UNC Chapel Hill",
    )
    assert "Score: ECU 5, UNC Chapel Hill 2" in lines
    assert "Tickets: https://ecuhockey.com/tickets" in lines

    # Away scheduled game
    away_sched = Game(
        game_id="G2",
        home_team=unc_team,
        away_team=ecu_team,
        start_time=datetime(2026, 11, 7, 19, 30, tzinfo=UTC),
        venue="Orange County Sportsplex",
        result=GameResult.SCHEDULED,
    )
    away_lines = _build_description_details(
        away_sched,
        is_home=False,
        opponent_name="UNC Chapel Hill",
    )
    assert not any("Score:" in line for line in away_lines)
    assert not any("Tickets:" in line for line in away_lines)


def test_format_match_description_full(ecu_team: Team, unc_team: Team) -> None:
    """Test full format_match_description output."""
    game = Game(
        game_id="G1",
        home_team=ecu_team,
        away_team=unc_team,
        start_time=datetime(2026, 11, 6, 19, 30, tzinfo=UTC),
        venue="The Factory Ice House",
        home_score=4,
        away_score=1,
        result=GameResult.WIN,
    )
    desc = format_match_description(game, DEFAULT_ECU_TEAM_NAME)
    assert "ECU Men's Ice Hockey match against UNC Chapel Hill." in desc
    assert "Date:" in desc
    assert "Puck Drop:" in desc
    assert "Venue: The Factory Ice House, 1839 S Main St, Wake Forest, NC 27587" in desc
    assert "Designation: Home" in desc
    assert "Status: W" in desc
    assert "Score: ECU 4, UNC Chapel Hill 1" in desc
    assert "Tickets: https://ecuhockey.com/tickets" in desc
    assert "Division: ACHA M2 | Conference: ACCHL" in desc


def test_format_match_description_no_division_or_conference(ecu_team: Team) -> None:
    """Test format_match_description when opponent lacks division/conference."""
    independent_team = Team(
        name="Club Independent",
        city="Charlotte",
        state="NC",
        division="",
        conference="",
    )
    game = Game(
        game_id="G2",
        home_team=ecu_team,
        away_team=independent_team,
        start_time=datetime(2026, 11, 6, 19, 30, tzinfo=UTC),
        venue="The Factory Ice House",
        result=GameResult.SCHEDULED,
    )
    desc = format_match_description(game, DEFAULT_ECU_TEAM_NAME)
    assert "Division:" not in desc
    assert "Conference:" not in desc
    assert "Designation: Home" in desc


def test_build_syndication_caching_headers(ecu_team: Team, unc_team: Team) -> None:
    """Test syndication caching headers construction."""
    games = [
        Game(
            game_id="G1",
            home_team=ecu_team,
            away_team=unc_team,
            start_time=datetime(2026, 11, 6, 19, 30, tzinfo=UTC),
            venue="Arena",
        ),
    ]
    headers = build_syndication_caching_headers(
        content="<rss></rss>",
        games=games,
        media_type=RSS_MEDIA_TYPE,
        max_age=300,
    )
    assert headers["Content-Type"] == RSS_MEDIA_TYPE
    assert "max-age=300" in headers["Cache-Control"]
    assert "stale-while-revalidate=600" in headers["Cache-Control"]
    assert headers["ETag"].startswith('"')
    assert "Last-Modified" in headers


def test_syndication_feed_service_generate_rss(ecu_team: Team, unc_team: Team) -> None:
    """Test generating standard RSS 2.0 XML with SyndicationFeedService."""
    service = SyndicationFeedService()
    games = [
        Game(
            game_id="G1",
            home_team=ecu_team,
            away_team=unc_team,
            start_time=datetime(2026, 11, 6, 19, 30, tzinfo=UTC),
            venue="The Factory Ice House",
            result=GameResult.WIN,
            home_score=4,
            away_score=2,
        ),
        Game(
            game_id="G2",
            home_team=unc_team,
            away_team=ecu_team,
            start_time=datetime(2026, 11, 13, 20, 0, tzinfo=UTC),
            venue="Orange County Sportsplex",
            result=GameResult.SCHEDULED,
        ),
    ]

    rss_xml = service.generate_rss_feed(
        games,
        season="2026-2027",
        feed_url="https://ecuhockey.com/feed.rss",
        now_utc=datetime(2026, 11, 1, 12, 0, tzinfo=UTC),
    )
    assert "<rss" in rss_xml
    assert 'version="2.0"' in rss_xml
    assert "<title>ECU Men's Ice Hockey Schedule</title>" in rss_xml
    assert "<link>https://ecuhockey.com/feed.rss</link>" in rss_xml
    assert '<guid isPermaLink="false">urn:ecu-hockey:game:G1</guid>' in rss_xml
    assert '<guid isPermaLink="false">urn:ecu-hockey:game:G2</guid>' in rss_xml
    assert "<category>ACCHL</category>" in rss_xml
    assert "<category>ACHA M2</category>" in rss_xml
    assert "<category>Hockey</category>" in rss_xml
    assert "<category>ECU</category>" in rss_xml
    assert "Final: ECU 4, UNC Chapel Hill 2" in rss_xml
    assert "ECU Hockey at UNC Chapel Hill (Away Match)" in rss_xml


def test_syndication_feed_service_generate_atom(ecu_team: Team, unc_team: Team) -> None:
    """Test generating standard Atom 1.0 XML with SyndicationFeedService."""
    service = SyndicationFeedService()
    games = [
        Game(
            game_id="G1",
            home_team=ecu_team,
            away_team=unc_team,
            start_time=datetime(2026, 11, 6, 19, 30, tzinfo=UTC),
            venue="The Factory Ice House",
            result=GameResult.WIN,
            home_score=4,
            away_score=2,
        ),
    ]

    atom_xml = service.generate_atom_feed(
        games,
        season="2026-2027",
        feed_url="https://ecuhockey.com/feed.atom",
        now_utc=datetime(2026, 11, 1, 12, 0, tzinfo=UTC),
    )
    assert "<feed" in atom_xml
    assert "http://www.w3.org/2005/Atom" in atom_xml
    assert "<title>ECU Men's Ice Hockey Schedule</title>" in atom_xml
    assert "urn:ecu-hockey:game:G1" in atom_xml
    assert "Final: ECU 4, UNC Chapel Hill 2" in atom_xml


def test_syndication_feed_service_filters(ecu_team: Team, unc_team: Team) -> None:
    """Test filtering syndication feeds by season, opponent, home_only, future_only."""
    service = SyndicationFeedService()
    games = [
        Game(
            game_id="G1",
            home_team=ecu_team,
            away_team=unc_team,
            start_time=datetime(2026, 11, 6, 19, 30, tzinfo=UTC),
            venue="The Factory Ice House",
            result=GameResult.WIN,
            home_score=5,
            away_score=1,
        ),
        Game(
            game_id="G2",
            home_team=unc_team,
            away_team=ecu_team,
            start_time=datetime(2026, 11, 13, 20, 0, tzinfo=UTC),
            venue="Orange County Sportsplex",
            result=GameResult.SCHEDULED,
        ),
    ]

    # Home only filter
    home_rss = service.generate_rss_feed(games, home_only=True)
    assert "urn:ecu-hockey:game:G1" in home_rss
    assert "urn:ecu-hockey:game:G2" not in home_rss

    # Future only filter relative to reference time
    future_rss = service.generate_rss_feed(
        games,
        future_only=True,
        now_utc=datetime(2026, 11, 10, 0, 0, tzinfo=UTC),
    )
    assert "urn:ecu-hockey:game:G1" not in future_rss
    assert "urn:ecu-hockey:game:G2" in future_rss

    # Opponent filter
    opp_rss = service.generate_rss_feed(games, opponent="Nonexistent Team")
    assert "urn:ecu-hockey:game:G1" not in opp_rss
    assert "urn:ecu-hockey:game:G2" not in opp_rss


def test_syndication_empty_games_feed() -> None:
    """Test feed generation when games list is completely empty."""
    service = SyndicationFeedService()
    now = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    rss_xml = service.generate_rss_feed(
        [],
        feed_url="https://ecuhockey.com/feed.rss",
        now_utc=now,
    )
    assert "<rss" in rss_xml
    assert "<title>ECU Men's Ice Hockey Schedule</title>" in rss_xml
    assert "<item>" not in rss_xml

    atom_xml = service.generate_atom_feed(
        [],
        feed_url="https://ecuhockey.com/feed.atom",
        now_utc=now,
    )
    assert "<feed" in atom_xml
    assert "<entry>" not in atom_xml
