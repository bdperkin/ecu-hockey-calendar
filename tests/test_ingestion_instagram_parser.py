"""Unit tests for the ECU Hockey Instagram feed and announcement parser."""

# pylint: disable=protected-access

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from ecu_hockey_calendar.ingestion.instagram_parser import (
    DEFAULT_GRAPH_API_URL,
    DEFAULT_INSTAGRAM_URL,
    DEFAULT_INSTAGRAM_USERNAME,
    DEFAULT_WEB_PROFILE_URL,
    IG_APP_ID,
    MONTH_MAP,
    AnnouncementType,
    ParsedInstagramPost,
    _adjust_12h_period,
    _apply_announcement_to_game,
    _clean_caption_text,
    _clean_extracted_team,
    _contains_ecu,
    _extract_at_opponent,
    _extract_edge_caption,
    _extract_edge_timestamp,
    _extract_edges_list,
    _extract_first_node_text,
    _extract_og_meta_item,
    _extract_other_opponent,
    _extract_user_dict,
    _extract_web_edges,
    _is_cancellation,
    _is_game_day,
    _is_opponent_match,
    _is_postponement,
    _is_same_calendar_day,
    _is_score_update,
    _is_time_change,
    _matches_post_opponent,
    _matches_post_timing,
    _matches_post_to_game,
    _parse_12h_time,
    _parse_graph_timestamp,
    _parse_month_name_date,
    _parse_numeric_date,
    _parse_single_ld_script,
    _post_to_game_record,
    _resolve_post_date,
    _resolve_post_status,
    _resolve_post_teams,
    _resolve_post_venue,
    _update_game_status_from_post,
    _update_game_time_from_post,
    build_game_datetime,
    classify_announcement,
    cross_reference_announcements_with_games,
    extract_date_from_caption,
    extract_opponent_from_caption,
    extract_time_from_caption,
    extract_venue_from_caption,
    parse_graph_api_media_item,
    parse_graph_api_response,
    parse_html_instagram_feed,
    parse_public_feed_json,
    parse_web_profile_post_node,
    resolve_game_status_from_announcement,
)
from ecu_hockey_calendar.storage.models import GameModel, GameStatus, TeamModel


def test_constants_and_enums() -> None:
    """Verify default module constants and enum definitions."""
    assert DEFAULT_INSTAGRAM_USERNAME == "ecuicehockey"
    assert "instagram.com" in DEFAULT_INSTAGRAM_URL
    assert "graph.instagram.com" in DEFAULT_GRAPH_API_URL
    assert "api/v1/users/web_profile_info" in DEFAULT_WEB_PROFILE_URL
    assert IG_APP_ID == "936619743392459"
    assert MONTH_MAP["oct"] == 10
    assert MONTH_MAP["february"] == 2
    assert AnnouncementType.GAME_DAY == "game_day"
    assert AnnouncementType.TIME_CHANGE == "time_change"
    assert AnnouncementType.CANCELLATION == "cancellation"
    assert AnnouncementType.POSTPONEMENT == "postponement"
    assert AnnouncementType.SCORE_UPDATE == "score_update"
    assert AnnouncementType.GENERAL == "general"


def test_text_classification_helpers() -> None:
    """Verify boolean text classification helpers."""
    assert _is_cancellation("Tonight's game is cancelled due to weather")
    assert _is_cancellation("Game has been called off")
    assert not _is_cancellation("Regular gameday post")

    assert _is_postponement("Tonight's game is postponed to Sunday")
    assert _is_postponement("Matchup rescheduled for next week")
    assert not _is_postponement("Puck drop at 7")

    assert _is_time_change("Time change: puck drop moved to 8:30 PM")
    assert _is_time_change("Start time updated for tonight")
    assert not _is_time_change("Tickets on sale now")

    assert _is_score_update("Final: ECU 5, NC State 3")
    assert _is_score_update("Final Score: Pirates 4, UNC 2")
    assert _is_score_update("Won 6-2 against Duke")
    assert not _is_score_update("Great practice today")

    assert _is_game_day("GAMEDAY! ECU takes on UNC tonight")
    assert _is_game_day("Puck drop tonight at 7:00 PM")
    assert not _is_game_day("Check out our team merch")

    assert _clean_caption_text("   Lots   of   spaces \n and newlines \t ") == (
        "Lots of spaces and newlines"
    )


def test_classify_announcement() -> None:
    """Verify primary announcement classification."""
    assert (
        classify_announcement("GAME CANCELLED: Rink mechanical issues")
        == AnnouncementType.CANCELLATION
    )
    assert (
        classify_announcement("Tonight's matchup has been postponed to Saturday")
        == AnnouncementType.POSTPONEMENT
    )
    assert (
        classify_announcement("TIME CHANGE: Puck drop moved to 8:30pm tonight")
        == AnnouncementType.TIME_CHANGE
    )
    assert (
        classify_announcement("FINAL: Pirates 4, Richmond 1!")
        == AnnouncementType.SCORE_UPDATE
    )
    assert (
        classify_announcement("GAMEDAY: Pirates hosting Wake Forest tonight at 7:30 PM")
        == AnnouncementType.GAME_DAY
    )
    assert (
        classify_announcement("Happy Thanksgiving from ECU Hockey!")
        == AnnouncementType.GENERAL
    )


def test_resolve_game_status_from_announcement() -> None:
    """Verify status resolution mapping."""
    assert (
        resolve_game_status_from_announcement(AnnouncementType.CANCELLATION)
        == GameStatus.CANCELLED
    )
    assert (
        resolve_game_status_from_announcement(AnnouncementType.POSTPONEMENT)
        == GameStatus.POSTPONED
    )
    assert (
        resolve_game_status_from_announcement(AnnouncementType.SCORE_UPDATE)
        == GameStatus.FINAL
    )
    assert (
        resolve_game_status_from_announcement(AnnouncementType.GAME_DAY)
        == GameStatus.SCHEDULED
    )
    assert (
        resolve_game_status_from_announcement(AnnouncementType.TIME_CHANGE)
        == GameStatus.SCHEDULED
    )
    assert resolve_game_status_from_announcement(AnnouncementType.GENERAL) is None


def test_clean_extracted_team_and_contains_ecu() -> None:
    """Verify team cleaning and ECU pattern matching."""
    assert _contains_ecu("ECU")
    assert _contains_ecu("East Carolina University")
    assert _contains_ecu("Pirates")
    assert not _contains_ecu("NC State")

    assert _clean_extracted_team("NC State") == "NC State University"
    assert _clean_extracted_team("   ") is None
    assert _clean_extracted_team("ECU") is None
    assert _clean_extracted_team("a") is None


def test_extract_opponent_from_caption() -> None:
    """Verify extracting opponent and home/away status from captions."""
    opp, is_home = extract_opponent_from_caption(
        "GAMEDAY: ECU vs NC State tonight at 7pm!",
    )
    assert opp == "NC State University"
    assert is_home is True

    opp, is_home = extract_opponent_from_caption("Pirates @ Wake Forest tonight")
    assert opp == "Wake Forest University"
    assert is_home is False

    opp, is_home = extract_opponent_from_caption(
        "ECU hosting Duke University at The Factory",
    )
    assert opp == "Duke University"
    assert is_home is True

    opp, is_home = extract_opponent_from_caption("ECU takes on Virginia Tech tonight")
    assert opp == "Virginia Tech"
    assert is_home is None

    opp, is_home = extract_opponent_from_caption("Happy holidays to all our fans!")
    assert opp is None
    assert is_home is None

    # Coverage for helper fallback branches
    assert _extract_at_opponent("no at symbol") is None
    assert _extract_other_opponent("regular social media announcement") is None


def test_time_extraction() -> None:
    """Verify extracting 12-hour game start times."""
    assert extract_time_from_caption("Puck drop at 7:30 PM tonight") == time(19, 30)
    assert extract_time_from_caption("Game starts at 8pm") == time(20, 0)
    assert extract_time_from_caption("Morning practice at 10:15 am") == time(10, 15)
    assert extract_time_from_caption("High noon at 12:00 pm") == time(12, 0)
    assert extract_time_from_caption("Midnight matchup at 12:00 am") == time(0, 0)
    assert extract_time_from_caption("No time in this caption") is None

    assert _adjust_12h_period(1, "am") == 1
    assert _adjust_12h_period(12, "pm") == 12
    m_inv_time = re.search(r"(\d+):(\d+)\s*(am|pm)", "25:00 pm")
    assert m_inv_time is not None
    assert _parse_12h_time(m_inv_time) is None


def test_date_extraction() -> None:
    """Verify calendar date extraction from captions."""
    assert extract_date_from_caption("Game on Oct 18, 2026") == date(2026, 10, 18)
    assert extract_date_from_caption("Catch the Pirates on October 4th") == date(
        2026,
        10,
        4,
    )
    assert extract_date_from_caption("Friday, 10/24/2026 at 7pm") == date(2026, 10, 24)
    assert extract_date_from_caption("Matchup on 11/15/26") == date(2026, 11, 15)
    assert extract_date_from_caption("Game on 12/5") == date(2026, 12, 5)
    assert extract_date_from_caption("No date mentioned") is None

    # Invalid regex matches
    m_inv_month = re.search(r"(\w+)\s+(\d+)", "FakeMonth 15")
    assert m_inv_month is not None
    assert _parse_month_name_date(m_inv_month, 2026) is None

    m_inv_day = re.search(r"(\w+)\s+(\d+)", "Feb 31")
    assert m_inv_day is not None
    assert _parse_month_name_date(m_inv_day, 2026) is None

    m_inv_num = re.search(r"(\d+)/(\d+)", "13/45")
    assert m_inv_num is not None
    assert _parse_numeric_date(m_inv_num, 2026) is None


def test_build_game_datetime() -> None:
    """Verify build_game_datetime combines date, time, and timezone."""
    d = date(2026, 10, 18)
    t = time(19, 30)
    dt_utc = build_game_datetime(d, t)
    assert dt_utc is not None
    assert dt_utc.tzinfo == UTC
    assert dt_utc.year == 2026
    assert dt_utc.month == 10

    # Default time when time is omitted
    dt_default_time = build_game_datetime(d, None)
    assert dt_default_time is not None

    # None when date is omitted
    assert build_game_datetime(None, t) is None

    # Custom timezone
    dt_custom = build_game_datetime(d, t, tz=ZoneInfo("America/Chicago"))
    assert dt_custom is not None


def test_venue_extraction() -> None:
    """Verify extracting venue names from caption text."""
    assert (
        extract_venue_from_caption("Playing tonight at the Carolina Ice Palace!")
        == "Carolina Ice Palace"
    )
    assert (
        extract_venue_from_caption("Matchup at Richmond Ice Zone in VA")
        == "Richmond Ice Zone"
    )
    assert (
        extract_venue_from_caption("Join us at the Greensboro Coliseum Complex")
        == "Greensboro Coliseum Complex"
    )
    assert extract_venue_from_caption("No location given") is None


def test_parsed_instagram_post_domain_conversion() -> None:
    """Verify conversion of ParsedInstagramPost to ParsedGameRecord."""
    dt = datetime(2026, 10, 18, 23, 30, tzinfo=UTC)
    post_home = ParsedInstagramPost(
        post_id="12345",
        shortcode="Cxyz123",
        caption="GAMEDAY vs NC State tonight at 7:30 PM!",
        url="https://www.instagram.com/p/Cxyz123/",
        published_at=datetime.now(UTC),
        announcement_type=AnnouncementType.GAME_DAY,
        opponent_name="NC State University",
        is_home_game=True,
        game_datetime=dt,
        venue="Carolina Ice Palace",
        status_override=GameStatus.SCHEDULED,
    )
    rec_home = post_home.to_parsed_game_record(season="2026-2027")
    assert rec_home is not None
    assert rec_home.game_id == "instagram-Cxyz123"
    assert rec_home.opponent_name == "NC State University"
    assert rec_home.is_home is True
    assert rec_home.venue == "Carolina Ice Palace"
    assert rec_home.status == GameStatus.SCHEDULED

    post_away = ParsedInstagramPost(
        post_id="67890",
        shortcode="",
        caption="Pirates @ Wake Forest tonight!",
        url="https://www.instagram.com/p/67890/",
        published_at=datetime.now(UTC),
        announcement_type=AnnouncementType.GAME_DAY,
        opponent_name="Wake Forest University",
        is_home_game=False,
        game_datetime=dt,
    )
    rec_away = post_away.to_parsed_game_record(season="2026-2027")
    assert rec_away is not None
    assert rec_away.game_id == "instagram-67890"
    assert rec_away.is_home is False
    assert rec_away.venue == "TBD"

    # Helpers coverage
    assert _resolve_post_teams(post_away) == (
        "Wake Forest University",
        "East Carolina University",
    )
    assert _resolve_post_venue(post_away, is_home=False) == "TBD"
    assert _resolve_post_status(post_away) == GameStatus.SCHEDULED
    assert (
        _post_to_game_record(
            ParsedInstagramPost(
                post_id="1",
                shortcode="1",
                caption="test",
                url="test",
            ),
            "2026-2027",
        )
        is None
    )


def test_parse_graph_api_response() -> None:
    """Verify parsing Graph API JSON responses."""
    payload = {
        "data": [
            {
                "id": "18012345678",
                "caption": (
                    "GAMEDAY: ECU vs NC State tonight at 7:30 PM "
                    "at Carolina Ice Palace!"
                ),
                "media_type": "IMAGE",
                "timestamp": "2026-10-18T16:00:00+0000",
                "permalink": "https://www.instagram.com/p/Cxyz789/",
            },
            {
                "id": "18098765432",
                "caption": (
                    "TIME CHANGE: Puck drop against Duke moved to 8:00 PM on Oct 25"
                ),
                "media_type": "VIDEO",
                "timestamp": "2026-10-25T14:00:00Z",
                "permalink": "https://www.instagram.com/p/Cabc123/",
            },
        ],
    }
    posts = parse_graph_api_response(payload)
    assert len(posts) == 2
    assert posts[0].post_id == "18012345678"
    assert posts[0].shortcode == "Cxyz789"
    assert posts[0].announcement_type == AnnouncementType.GAME_DAY
    assert posts[0].opponent_name == "NC State University"
    assert posts[0].is_home_game is True
    assert posts[0].venue == "Carolina Ice Palace"

    assert posts[1].announcement_type == AnnouncementType.TIME_CHANGE
    assert posts[1].opponent_name == "Duke University"

    # Empty or invalid payloads
    assert not parse_graph_api_response({})
    assert not parse_graph_api_response({"data": "not-a-list"})
    assert not parse_graph_api_response("not-a-dict")
    assert parse_graph_api_media_item({}) is None
    assert _parse_graph_timestamp(12345) is None
    assert _parse_graph_timestamp("invalid-date") is None


def test_parse_public_feed_json() -> None:
    """Verify parsing Instagram web profile GraphQL responses."""
    payload = {
        "data": {
            "user": {
                "edge_owner_to_timeline_media": {
                    "edges": [
                        {
                            "node": {
                                "id": "999888777",
                                "shortcode": "Dxyz001",
                                "taken_at_timestamp": 1792345678,
                                "edge_media_to_caption": {
                                    "edges": [
                                        {
                                            "node": {
                                                "text": (
                                                    "GAME CANCELLED: Due to weather, "
                                                    "tonight vs Richmond is called off."
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
    posts = parse_public_feed_json(payload)
    assert len(posts) == 1
    assert posts[0].post_id == "999888777"
    assert posts[0].shortcode == "Dxyz001"
    assert posts[0].announcement_type == AnnouncementType.CANCELLATION
    assert posts[0].status_override == GameStatus.CANCELLED

    # GraphQL legacy wrapper structure
    legacy_payload = {
        "graphql": {
            "user": {
                "edge_owner_to_timeline_media": {
                    "edges": [
                        {
                            "node": {
                                "id": "111222",
                                "shortcode": "Legacy1",
                                "taken_at_timestamp": 1792345600,
                                "edge_media_to_caption": {
                                    "edges": [
                                        {
                                            "node": {
                                                "text": "FINAL: ECU 5, Duke 2",
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
    legacy_posts = parse_public_feed_json(legacy_payload)
    assert len(legacy_posts) == 1
    assert legacy_posts[0].shortcode == "Legacy1"

    # Edge cases and missing nodes
    assert not parse_public_feed_json({})
    assert not parse_public_feed_json("invalid")
    assert parse_web_profile_post_node({}) is None
    assert _extract_user_dict({}) is None
    assert _extract_edge_caption({}) == ""
    assert _extract_first_node_text([]) == ""
    assert _extract_edge_timestamp({}) is None
    assert _extract_web_edges({"data": "invalid"}) == []


def test_parse_html_instagram_feed() -> None:
    """Verify parsing HTML profile pages via JSON-LD and OpenGraph tags."""
    html_ld = """
    <html>
        <head>
            <script type="application/ld+json">
            {
                "identifier": "post-ld-101",
                "articleBody": "Puck drop tonight vs Wake Forest at 7:30 PM!",
                "url": "https://www.instagram.com/p/post-ld-101/"
            }
            </script>
            <script type="application/ld+json">invalid json</script>
        </head>
    </html>
    """
    ld_posts = parse_html_instagram_feed(html_ld)
    assert len(ld_posts) == 1
    assert ld_posts[0].post_id == "post-ld-101"
    assert ld_posts[0].announcement_type == AnnouncementType.GAME_DAY

    html_og = """
    <html>
        <head>
            <meta property="og:description"
                content="GAMEDAY: ECU hosting Duke tonight at 7:00 PM!" />
            <meta property="og:url" content="https://www.instagram.com/ecuicehockey/" />
        </head>
    </html>
    """
    og_posts = parse_html_instagram_feed(html_og)
    assert len(og_posts) == 1
    assert og_posts[0].announcement_type == AnnouncementType.GAME_DAY

    # Empty HTML returns empty list
    assert parse_html_instagram_feed("<html><body>No metadata</body></html>") == []
    assert _extract_og_meta_item(None) is None  # type: ignore[arg-type]
    assert _parse_single_ld_script("not json") is None


def test_cross_reference_announcements_with_games() -> None:
    """Verify matching announcements to games and applying modifications."""
    ecu = TeamModel(
        id=1,
        name="East Carolina University",
        city="Greenville",
        state="NC",
    )
    ncstate = TeamModel(
        id=2,
        name="NC State University",
        city="Raleigh",
        state="NC",
    )
    duke = TeamModel(
        id=3,
        name="Duke University",
        city="Durham",
        state="NC",
    )

    tz = ZoneInfo("America/New_York")
    game1_start = datetime(2026, 10, 18, 19, 0, tzinfo=tz).astimezone(UTC)
    game1 = GameModel(
        id=10,
        game_id="game-1",
        home_team_id=1,
        away_team_id=2,
        home_team=ecu,
        away_team=ncstate,
        start_time=game1_start,
        end_time=game1_start + timedelta(hours=2.5),
        venue="TBD",
        status=GameStatus.SCHEDULED.value,
    )

    game2_start = datetime(2026, 10, 25, 20, 0, tzinfo=tz).astimezone(UTC)
    game2 = GameModel(
        id=20,
        game_id="game-2",
        home_team_id=1,
        away_team_id=3,
        home_team=ecu,
        away_team=duke,
        start_time=game2_start,
        end_time=game2_start + timedelta(hours=2.5),
        venue="The Factory",
        status=GameStatus.SCHEDULED.value,
    )

    announcement_cancel = ParsedInstagramPost(
        post_id="post-cancel",
        shortcode="cancel1",
        caption="Tonight's game vs NC State is cancelled!",
        url="https://instagram.com/p/cancel1",
        published_at=datetime(2026, 10, 18, 14, 0, tzinfo=UTC),
        announcement_type=AnnouncementType.CANCELLATION,
        opponent_name="NC State University",
        is_home_game=True,
        game_date=date(2026, 10, 18),
        status_override=GameStatus.CANCELLED,
    )

    announcement_time = ParsedInstagramPost(
        post_id="post-time",
        shortcode="time1",
        caption="TIME CHANGE vs Duke: puck drop moved to 8:30 PM",
        url="https://instagram.com/p/time1",
        announcement_type=AnnouncementType.TIME_CHANGE,
        opponent_name="Duke University",
        is_home_game=True,
        game_date=date(2026, 10, 25),
        game_time=time(20, 30),
    )

    updated = cross_reference_announcements_with_games(
        [game1, game2],
        [announcement_cancel, announcement_time],
    )
    assert len(updated) == 2
    assert game1.status == GameStatus.CANCELLED.value
    expected_new_start = datetime(2026, 10, 25, 20, 30, tzinfo=tz).astimezone(UTC)
    assert game2.start_time == expected_new_start


def test_cross_reference_helpers_edge_cases() -> None:
    """Verify timing and opponent matching helpers in edge cases."""
    ecu = TeamModel(
        id=1,
        name="East Carolina University",
        city="Greenville",
        state="NC",
    )
    unc = TeamModel(id=2, name="UNC Chapel Hill", city="Chapel Hill", state="NC")
    game = GameModel(
        id=1,
        game_id="g1",
        home_team_id=1,
        away_team_id=2,
        home_team=ecu,
        away_team=unc,
        start_time=datetime(2026, 11, 1, 19, 0, tzinfo=UTC),
        venue="Carolina Ice Palace",
        status=GameStatus.SCHEDULED.value,
    )

    # Opponent mismatch
    post_diff_opp = ParsedInstagramPost(
        post_id="p1",
        shortcode="s1",
        caption="vs Duke",
        url="u1",
        opponent_name="Duke University",
    )
    assert not _matches_post_to_game(game, post_diff_opp)

    # Same day match via published_at
    post_pub = ParsedInstagramPost(
        post_id="p2",
        shortcode="s2",
        caption="Gameday vs UNC tonight!",
        url="u2",
        announcement_type=AnnouncementType.GAME_DAY,
        published_at=datetime(2026, 11, 1, 14, 0, tzinfo=UTC),
        opponent_name="UNC Chapel Hill",
    )
    assert _matches_post_to_game(game, post_pub)

    # Timing helpers
    assert _is_same_calendar_day(
        datetime(2026, 11, 1, 12, 0, tzinfo=UTC),
        datetime(2026, 11, 1, 18, 0, tzinfo=UTC),
    )
    assert _is_opponent_match("NC State", "NC State University")
    assert not _matches_post_timing(game, ParsedInstagramPost("1", "1", "test", "u"))
    assert not _update_game_time_from_post(game, post_pub)
    assert not _update_game_status_from_post(game, post_pub)


def test_instagram_parser_coverage_edges() -> None:
    """Test remaining branch paths and edge cases for instagram_parser."""
    # 1. _resolve_post_teams with home game
    post_home = ParsedInstagramPost(
        post_id="p_home",
        shortcode="s_home",
        caption="vs Duke",
        url="u",
        opponent_name="Duke Blue Devils",
        is_home_game=True,
    )
    assert _resolve_post_teams(post_home) == (
        "East Carolina University",
        "Duke Blue Devils",
    )

    # 2. _extract_at_opponent edge
    assert _extract_at_opponent("playing at nothing") is None

    # 3. _extract_other_opponent facing
    assert _extract_other_opponent("ECU facing UNC Wilmington") == (
        "UNC Wilmington",
        None,
    )
    assert _extract_other_opponent("nothing to see here") is None

    # 4. extract_date_from_caption fallback
    # month regex matches invalid date, then falls through to numeric regex
    assert extract_date_from_caption("Invalid Month 99") is None

    # 5. _extract_first_node_text edges
    assert _extract_first_node_text([]) == ""
    assert _extract_first_node_text(["not_a_dict"]) == ""
    assert _extract_first_node_text([{"node": "not_a_dict"}]) == ""

    # 6. _resolve_post_date game day with pub_at
    pub = datetime(2026, 10, 31, 15, 0, tzinfo=UTC)
    assert _resolve_post_date("GAMEDAY", pub, AnnouncementType.GAME_DAY) == date(
        2026,
        10,
        31,
    )

    # 7. _extract_edges_list edge
    assert (
        _extract_edges_list({"edge_owner_to_timeline_media": {"edges": "invalid"}})
        == []
    )
    assert _extract_edges_list({"edge_owner_to_timeline_media": "invalid"}) == []

    # 8. _parse_single_ld_script without articleBody
    assert _parse_single_ld_script('{"@context": "https://schema.org"}') is None

    # 9. parse_graph_api_response with empty ID
    res = parse_graph_api_response({"data": [{"id": ""}, {"no_id": True}]})
    assert len(res) == 0

    # 10. _matches_post_opponent without opponent_name
    ecu = TeamModel(
        id=1,
        name="East Carolina University",
        city="Greenville",
        state="NC",
    )
    unc = TeamModel(id=2, name="UNC Chapel Hill", city="Chapel Hill", state="NC")
    game = GameModel(
        id=1,
        game_id="g1",
        home_team_id=1,
        away_team_id=2,
        home_team=ecu,
        away_team=unc,
        start_time=datetime(2026, 11, 1, 19, 0, tzinfo=UTC),
        venue="TBD",
        status=GameStatus.SCHEDULED.value,
    )
    post_no_opp = ParsedInstagramPost(
        post_id="p_no_opp",
        shortcode="s_no_opp",
        caption="Puck drops tonight!",
        url="u",
        opponent_name=None,
        game_datetime=datetime(2026, 11, 1, 19, 0, tzinfo=UTC),
        venue="Carolina Ice Palace",
    )
    assert _matches_post_opponent(game, post_no_opp)
    assert _matches_post_to_game(game, post_no_opp)

    # 11. _apply_announcement_to_game updates venue when venue was TBD
    assert _apply_announcement_to_game(game, post_no_opp)
    assert game.venue == "Carolina Ice Palace"

    # 12. _update_game_time_from_post when time already matches
    post_time = ParsedInstagramPost(
        post_id="p_time",
        shortcode="s_time",
        caption="Time change",
        url="u",
        announcement_type=AnnouncementType.TIME_CHANGE,
        game_time=time(14, 0),
    )
    tz = ZoneInfo("America/New_York")
    game.start_time = datetime(2026, 11, 1, 14, 0, tzinfo=tz).astimezone(UTC)
    assert not _update_game_time_from_post(game, post_time)

    # 13. _update_game_status_from_post when status already matches
    post_stat = ParsedInstagramPost(
        post_id="p_stat",
        shortcode="s_stat",
        caption="Canceled",
        url="u",
        status_override=GameStatus.CANCELLED,
    )
    game.status = GameStatus.CANCELLED.value
    assert not _update_game_status_from_post(game, post_stat)

    # 14. extract_venue_from_caption via regex pattern fallback (not in known_venues)
    assert extract_venue_from_caption("Playing at Metroplex Arena") == "Metroplex Arena"

    # 15. extract_time_from_caption with invalid time preceding valid time
    assert extract_time_from_caption("Game at 25:00 PM or 7:30 PM") == time(19, 30)

    # 16. extract_date_from_caption with invalid month preceding valid numeric date
    assert extract_date_from_caption("Feb 30 or 10/24") == date(2026, 10, 24)

    # 17. Opponent cleaning returning empty
    assert _extract_at_opponent("ECU @ East Carolina tonight") is None
    assert _extract_other_opponent("ECU vs Pirates tonight") is None

    # 18. Edge caption when edges is not a list/tuple
    assert _extract_edge_caption({"edge_media_to_caption": {"edges": "invalid"}}) == ""

    # 19. Public feed parsing with non-node edges and empty-id nodes
    raw_web_edges = {
        "data": {
            "user": {
                "edge_owner_to_timeline_media": {
                    "edges": [
                        {"not_node": 1},
                        "not_a_dict",
                        {"node": {"id": ""}},
                    ],
                },
            },
        },
    }
    assert not parse_public_feed_json(raw_web_edges)

    # 20. Graph API response with non-dict item
    graph_res = parse_graph_api_response({"data": ["not_dict"]})
    assert not graph_res

    # 21. cross_reference_announcements_with_games when game does not match post
    post_unmatched = ParsedInstagramPost(
        post_id="p_unmatched",
        shortcode="s_unmatched",
        caption="vs Virginia Tech",
        url="u",
        opponent_name="Virginia Tech Hokies",
    )
    assert not cross_reference_announcements_with_games([game], [post_unmatched])
